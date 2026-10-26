"""Exploratory counterfactual for the published v0.3 failure (not a holdout, not for selection).

Every model except LoRA seed 42 failed v0.3 record 6303, the only test record whose target
sits in list slot 0; training targets never sat there and the shared one-shot demo's target
sits in slot 3. Position was confounded with everything else about that record. Here the
records' contents are held fixed and only the target's slot moves (IDs keep their original,
now uninformative, suffixes), crossed with the original demo and the same demo episode with
its target moved to slot 0. Outputs are new files; v0.3 evidence is untouched.
"""

import argparse
import json
from pathlib import Path

from resolvelab.benchmark import digest
from resolvelab.casedesk.prompts import build_demo, load_v03_demo, prompt_with_demo
from resolvelab.casedesk.runner import run_episode
from resolvelab.casedesk.world import move_target
from resolvelab.evaluation import write_report
from resolvelab.httpdesk.schema import initial_messages
from resolvelab.httpdesk.service import DeskState
from resolvelab.store import utcnow
from resolvelab.training import file_hash

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = [("plain", []), ("conflict_lost", ["conflict", "lost_ack"])]
RECORDS = [6301, 6302, 6303]


def arms(adapter_root):
    lock = json.loads((ROOT / "artifacts/v0.3/test-lock.json").read_text(encoding="utf-8"))
    config = json.loads((ROOT / "benchmarks/httpdesk-sft-v1.json").read_text(encoding="utf-8"))
    small = {k: config[k] for k in ("base", "revision", "max_output", "context", "max_tools")}
    large = {**small, **config["larger_baseline"]}
    yield "base-0.6b", small, None
    yield "base-1.7b", large, None
    for seed, selected in lock["selected_adapters"].items():
        path = Path(adapter_root) / f"http-sft-{seed}" / selected["checkpoint"]
        if file_hash(path / "adapter_model.safetensors") != selected["sha256"]:
            raise ValueError(f"Adapter {seed} does not match the v0.3 test lock")
        yield f"lora-{seed}", small, path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapters", type=Path, required=True, help="v0.3 .local directory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    from resolvelab.httpdesk.policy import StructuredPolicy

    original = prompt_with_demo(load_v03_demo())
    assert digest(original("T")) == digest(initial_messages("T")), "Demo reconstruction drifted"
    moved = prompt_with_demo(build_demo(move_target(DeskState([], 4101), 0)))
    prompts = {"demo_slot3": original, "demo_slot0": moved}
    for name, config, adapter in arms(args.adapters):
        if args.only and name not in args.only:
            continue
        output = args.output / f"{name}.json"
        if output.exists():
            print("skip", output)
            continue
        policy = StructuredPolicy(config, adapter)
        report = {
            "arm": name,
            "config": config,
            "adapter": str(adapter) if adapter else None,
            "model": policy.metadata,
            "started_at": utcnow(),
            "rows": [],
        }
        for prompt_name, prompt in prompts.items():
            for template, faults in TEMPLATES:
                for seed in RECORDS:
                    for slot in range(len(DeskState(faults, seed).tickets)):
                        state = move_target(DeskState(faults, seed), slot)
                        spec = {
                            "id": f"{prompt_name}-{template}-{seed}-slot{slot}",
                            "composition": template,
                            "faults": faults,
                        }
                        trace = run_episode(
                            spec, policy, max_tools=config["max_tools"], state=state, prompt=prompt
                        )
                        trace.pop("steps")
                        write_report(args.output / name / f"{spec['id']}.json", trace)
                        row = {
                            "prompt": prompt_name,
                            "template": template,
                            "seed": seed,
                            "slot": slot,
                            "original_slot": list(DeskState(faults, seed).tickets).index(state.target),
                            "passed": trace["verdict"]["passed"],
                            "failure": trace["verdict"]["failure_category"],
                            "located": trace["diagnostics"]["located_target"],
                            "wrong_read": trace["diagnostics"]["first_wrong_read_step"] is not None,
                            "tools": len(trace["observations"]),
                        }
                        report["rows"].append(row)
                        print(json.dumps({"arm": name, **row}), flush=True)
        report["finished_at"] = utcnow()
        write_report(output, report)
        del policy
        __import__("torch").cuda.empty_cache()


if __name__ == "__main__":
    main()
