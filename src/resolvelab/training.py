"""Action-only LoRA SFT. Heavy dependencies are optional and imported at execution."""

import hashlib
import importlib.metadata
import math
import random
import time
from pathlib import Path

from .benchmark import digest, validate_training_rows
from .curation import read_rows
from .evaluation import source_fingerprint, write_report
from .hf_policy import prompt_ids
from .store import dumps, utcnow


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encode_example(tokenizer, row, context):
    prefix = prompt_ids(tokenizer, row["messages"])
    target = tokenizer.encode(dumps(row["target"]) + tokenizer.eos_token, add_special_tokens=False)
    if not prefix or not target or len(prefix) + len(target) > context:
        raise ValueError("Empty or over-budget training example; truncation is forbidden")
    return prefix + target, len(target)


def action_loss(model, example):
    import torch
    import torch.nn.functional as F

    ids, count = example
    inputs = torch.tensor([ids], device=model.device)
    # Only action positions reach the large vocabulary head. Prefix tokens still condition
    # the transformer, but receive no direct language-model loss (including all tool data).
    logits = model(input_ids=inputs, use_cache=False, logits_to_keep=count + 1).logits
    return F.cross_entropy(logits[0, :-1].float(), inputs[0, -count:])


def train(config, manifest, data_dir: Path, output: Path):
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, get_cosine_schedule_with_warmup

    if output.exists():
        raise ValueError("Use a new experiment directory; completed experiments are immutable")
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("This configuration requires a CUDA GPU with bfloat16 support")
    random.seed(config["seed"])
    torch.manual_seed(config["seed"])
    torch.cuda.manual_seed_all(config["seed"])
    tokenizer = AutoTokenizer.from_pretrained(config["base"], revision=config["revision"])
    examples = {}
    for split in ("train", "dev"):
        rows = read_rows(data_dir / f"{split}.jsonl")
        validate_training_rows(rows, manifest, split)
        examples[split] = [encode_example(tokenizer, row, config["context"]) for row in rows]
    output.mkdir(parents=True)
    report = {
        "status": "running",
        "started_at": utcnow(),
        "config": config,
        "config_sha256": digest(config),
        "manifest_sha256": digest(manifest),
        "source_sha256": source_fingerprint(),
        "teacher": "scripted_runbook_v1",
        "data_sha256": {s: file_hash(data_dir / f"{s}.jsonl") for s in examples},
        "examples": {s: len(v) for s, v in examples.items()},
        "max_sequence_tokens": max(len(x[0]) for v in examples.values() for x in v),
        "supervised_tokens_per_epoch": sum(n for _, n in examples["train"]),
        "selection": "minimum dev action-token cross-entropy after each epoch; no test access",
        "hardware": torch.cuda.get_device_name(0),
        "dependencies": {
            p: importlib.metadata.version(p)
            for p in ("torch", "transformers", "peft", "accelerate", "numpy")
        },
        "epochs": [],
        "steps": [],
    }
    path = output / "training.json"
    write_report(path, report)
    started = time.perf_counter()
    try:
        model = AutoModelForCausalLM.from_pretrained(
            config["base"],
            revision=config["revision"],
            torch_dtype=torch.bfloat16,
            attn_implementation="sdpa",
        ).to("cuda")
        model = get_peft_model(
            model,
            LoraConfig(
                task_type="CAUSAL_LM",
                r=config["rank"],
                lora_alpha=config["alpha"],
                lora_dropout=config["dropout"],
                target_modules=config["target_modules"],
            ),
        )
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
        parameters = [p for p in model.parameters() if p.requires_grad]
        report["trainable_parameters"] = sum(p.numel() for p in parameters)
        report["total_parameters"] = sum(p.numel() for p in model.parameters())
        optimizer = torch.optim.AdamW(parameters, lr=config["learning_rate"], weight_decay=0.01)
        per_epoch = math.ceil(len(examples["train"]) / config["gradient_accumulation"])
        scheduler = get_cosine_schedule_with_warmup(
            optimizer,
            config["warmup_steps"],
            per_epoch * config["epochs"],
        )
        best, step = float("inf"), 0
        torch.cuda.reset_peak_memory_stats()
        for epoch in range(1, config["epochs"] + 1):
            model.train()
            order = list(range(len(examples["train"])))
            random.Random(config["seed"] + epoch).shuffle(order)
            epoch_losses = []
            for offset in range(0, len(order), config["gradient_accumulation"]):
                batch = order[offset : offset + config["gradient_accumulation"]]
                optimizer.zero_grad(set_to_none=True)
                losses = []
                for index in batch:
                    loss = action_loss(model, examples["train"][index])
                    if not torch.isfinite(loss):
                        raise ValueError("Non-finite training loss")
                    (loss / len(batch)).backward()
                    losses.append(loss.item())
                norm = torch.nn.utils.clip_grad_norm_(parameters, 1.0, error_if_nonfinite=True)
                optimizer.step()
                scheduler.step()
                step += 1
                epoch_losses.extend(losses)
                item = {
                    "step": step,
                    "epoch": epoch,
                    "loss": sum(losses) / len(losses),
                    "grad_norm": float(norm),
                    "lr": scheduler.get_last_lr()[0],
                    "elapsed_seconds": time.perf_counter() - started,
                }
                report["steps"].append(item)
                if step == 1 or step % 10 == 0:
                    write_report(path, report)
                    print(dumps(item), flush=True)
            model.eval()
            total, tokens = 0.0, 0
            with torch.inference_mode():
                for example in examples["dev"]:
                    total += action_loss(model, example).item() * example[1]
                    tokens += example[1]
            dev_loss = total / tokens
            checkpoint = output / f"epoch-{epoch}"
            model.save_pretrained(checkpoint, safe_serialization=True)
            tokenizer.save_pretrained(checkpoint)
            report["epochs"].append(
                {
                    "epoch": epoch,
                    "train_loss": sum(epoch_losses) / len(epoch_losses),
                    "dev_loss": dev_loss,
                    "checkpoint": checkpoint.name,
                    "adapter_sha256": file_hash(checkpoint / "adapter_model.safetensors"),
                }
            )
            if dev_loss < best:
                best = dev_loss
                report["selected_checkpoint"] = checkpoint.name
            write_report(path, report)
            print(dumps(report["epochs"][-1]), flush=True)
        report["status"] = "completed"
        report["peak_allocated_gib"] = torch.cuda.max_memory_allocated() / 1024**3
        report["peak_reserved_gib"] = torch.cuda.max_memory_reserved() / 1024**3
    except Exception as exc:
        report["status"] = "error"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["wall_seconds"] = time.perf_counter() - started
        report["finished_at"] = utcnow()
        write_report(path, report)
    return report
