"""Supplementary 4B quantized control. Kept separate from the matched HF/LoRA experiment."""

import argparse
import copy
import json
import time
from pathlib import Path

import httpx

from resolvelab.benchmark import digest
from resolvelab.evaluation import write_report
from resolvelab.hf_policy import prompt_ids
from resolvelab.httpdesk.benchmark import cases, load_manifest, source_hash
from resolvelab.httpdesk.experiment import episode, summarize
from resolvelab.httpdesk.schema import action_schema, initial_messages, validate_action
from resolvelab.policies import PolicyResponseError
from resolvelab.store import dumps, utcnow
from resolvelab.training import file_hash


class OllamaSchemaPolicy:
    def __init__(self, config, client=None, tokenizer=None):
        self.config = config
        self.client = client or httpx.Client(
            base_url="http://127.0.0.1:11434", timeout=180, trust_env=False
        )
        if tokenizer is None:
            from transformers import AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(
                config["tokenizer"], revision=config["tokenizer_revision"]
            )
        self.tokenizer = tokenizer
        models = self.client.get("/api/tags").json()["models"]
        model = next(m for m in models if m["name"] == config["model"])
        if model["digest"] != config["digest"]:
            raise ValueError("Ollama model digest changed")
        details = self.client.post("/api/show", json={"model": config["model"]}).json()
        self.metadata = {
            "model": model["name"],
            "digest": model["digest"],
            "details": model["details"],
            "ollama_version": self.client.get("/api/version").json()["version"],
            "prompt_sha256": digest(initial_messages("TASK_PLACEHOLDER")),
            "schema_sha256": digest(action_schema()),
            "decoder": "Ollama JSON Schema",
            "force_json_field_order": "backend-defined",
            "state_dependent_constraints": False,
            "retries": 0,
            "thinking": False,
            "context_guard": "Pinned HF tokenizer preflight plus returned prompt count; backend chat templates can differ",
            "comparison_scope": config["role"],
            "backend_template_sha256": digest(details.get("template", "")),
            "model_parameters": details.get("parameters"),
            "capabilities": details.get("capabilities"),
            "execution_mode": "CPU integration smoke"
            if config.get("cpu_smoke")
            else "Ollama default offload",
        }
        self.metadata["base_prompt_sha256"] = self.metadata["prompt_sha256"]
        self.metadata["prompt_sha256"] = digest(
            {
                "base_prompt": initial_messages("TASK_PLACEHOLDER"),
                "system_addendum": config["system_addendum"],
                "observation_reminder": config["observation_reminder"],
            }
        )

    def next(self, messages):
        config = self.config
        messages = copy.deepcopy(messages)
        task = next(
            m["content"]
            for m in reversed(messages)
            if m["role"] == "user" and m["content"].startswith("New independent task:")
        )
        if config["system_addendum"]:
            messages[0]["content"] += "\n" + config["system_addendum"]
        if config["observation_reminder"] and messages[-1]["content"] != task:
            messages[-1]["content"] += "\n" + config["observation_reminder"] + task
        guard_tokens = len(prompt_ids(self.tokenizer, messages))
        if guard_tokens + config["max_output"] > config["context"]:
            raise PolicyResponseError(
                "Context budget exceeded", {"failure_category": "context_limit"}, 0
            )
        started = time.perf_counter()
        response = self.client.post(
            "/api/chat",
            json={
                "model": config["model"],
                "messages": messages,
                "stream": False,
                "think": False,
                "format": action_schema(),
                "keep_alive": "10m",
                "options": {
                    "temperature": config["temperature"],
                    "seed": config["seed"],
                    "num_ctx": config["context"],
                    "num_predict": config["max_output"],
                    **({"num_gpu": 0, "num_thread": 2} if config.get("cpu_smoke") else {}),
                },
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data.get("message", {}).get("content", "")
        seconds = time.perf_counter() - started
        usage = {
            "input_tokens": data.get("prompt_eval_count", 0),
            "output_tokens": data.get("eval_count", 0),
            "context_guard_tokens": guard_tokens,
            "done_reason": data.get("done_reason"),
            "raw_output": content,
            "json_valid": False,
            "schema_valid": False,
            "load_duration_ns": data.get("load_duration", 0),
            "prompt_eval_cached_count": data.get("prompt_eval_cached_count"),
        }
        if usage["input_tokens"] + config["max_output"] > config["context"]:
            usage["failure_category"] = "context_limit"
            raise PolicyResponseError("Backend prompt approached context limit", usage, seconds)
        try:
            value = json.loads(content)
            usage["json_valid"] = True
            result = validate_action(value)
            usage["schema_valid"] = True
        except (ValueError, TypeError) as exc:
            usage["failure_category"] = "schema_error" if usage["json_valid"] else "json_error"
            raise PolicyResponseError(str(exc)[:300], usage, seconds) from exc
        return result, usage, seconds


def evaluate(config, manifest, split, output):
    if output.exists():
        raise ValueError("Control report exists; never overwrite")
    if split == "test":
        lock = json.loads(Path("artifacts/v0.3/test-lock.json").read_text(encoding="utf-8"))
        assert lock["source_sha256"] == source_hash()
        assert lock["ollama_control_config_sha256"] == digest(config)
        assert lock["ollama_control_script_sha256"] == file_hash(__file__)
    if split == "test" and config.get("cpu_smoke"):
        raise ValueError("CPU smoke is development-only")
    selected_cases = list(cases(manifest, split))
    if config.get("cpu_smoke"):
        selected_cases = selected_cases[:2]
    policy = OllamaSchemaPolicy(config)
    report = {
        "status": "running",
        "policy": "ollama-4b-control",
        "split": split,
        "config": config,
        "config_sha256": digest(config),
        "source_sha256": source_hash(),
        "script_sha256": file_hash(__file__),
        "manifest_sha256": digest(manifest),
        "model": policy.metadata,
        "created_at": utcnow(),
        "total": len(selected_cases),
        "rows": [],
    }
    traces = output.with_suffix("")
    traces.mkdir(parents=True)
    write_report(output, report)
    try:
        for template, seed in selected_cases:
            trace = episode(template, seed, policy, config["max_tools"])
            trace.pop("training")
            trace["training_eligible"] = False
            path = traces / f"{template['id']}-{seed}.json"
            write_report(path, trace)
            calls = trace["decisions"]
            row = {
                "template": template["id"],
                "seed": seed,
                **trace["verdict"],
                "error": trace["error"],
                "tools": len(trace["observations"]),
                "decisions": len(calls),
                "json_valid": sum(c["usage"].get("json_valid", False) for c in calls),
                "schema_valid": sum(c["usage"].get("schema_valid", False) for c in calls),
                "output_tokens": sum(c["usage"].get("output_tokens", 0) for c in calls),
                "input_tokens": sum(c["usage"].get("input_tokens", 0) for c in calls),
                "seconds": trace["wall_seconds"],
                "trace": path.name,
                "trace_sha256": file_hash(path),
                "http_statuses": [
                    o["result"]["status"] for o in trace["observations"] if "status" in o["result"]
                ],
            }
            report["rows"].append(row)
            report["summary"] = summarize(report["rows"])
            write_report(output, report)
            print(
                dumps(
                    {
                        "template": template["id"],
                        "seed": seed,
                        "passed": row["passed"],
                        "tools": row["tools"],
                    }
                ),
                flush=True,
            )
        report["status"] = "completed"
        try:
            loaded = policy.client.get("/api/ps").json().get("models", [])
            current = next((m for m in loaded if m.get("name") == config["model"]), {})
            report["model"]["runtime_snapshot"] = {
                k: current.get(k) for k in ("name", "digest", "size", "size_vram", "context_length")
            }
        except (httpx.HTTPError, ValueError):
            report["model"]["runtime_snapshot"] = None
        report["finished_at"] = utcnow()
        write_report(output, report)
    finally:
        policy.client.close()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu-smoke", action="store_true", help="Two development episodes on CPU only")
    args = parser.parse_args()
    config = json.loads(Path("benchmarks/httpdesk-ollama-control.json").read_text(encoding="utf-8"))
    if args.cpu_smoke:
        if args.split != "dev":
            parser.error("CPU smoke cannot be used for test")
        config["cpu_smoke"] = True
    report = evaluate(config, load_manifest("benchmarks/httpdesk-v1.json"), args.split, args.output)
    print(json.dumps(report["summary"], indent=2))
