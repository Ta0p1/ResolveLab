"""Publish completed reports and their exact raw traces; derive UI evidence from them."""

import json
import shutil
from pathlib import Path

from resolvelab.evaluation import write_report
from resolvelab.httpdesk.experiment import compare
from resolvelab.training import file_hash

root = Path(__file__).resolve().parents[1]
bundle = root / "artifacts/v0.3"
local = root / ".local"
config = json.loads((root / "benchmarks/httpdesk-sft-v1.json").read_text(encoding="utf-8"))
lock = json.loads((bundle / "test-lock.json").read_text(encoding="utf-8"))
names = ["base-test", "large-test", *[f"sft-{s}-test" for s in config["training_seeds"]]]
reports, previews, training = {}, {}, {}
for name in names:
    source = local / f"http-{name}.json"
    report = json.loads(source.read_text(encoding="utf-8"))
    assert report["status"] == "completed" and len(report["rows"]) == 30
    assert report["source_sha256"] == lock["source_sha256"]
    shutil.copyfile(source, bundle / f"{name}.json")
    (bundle / name).mkdir(exist_ok=True)
    for row in report["rows"]:
        trace = source.with_suffix("") / row["trace"]
        assert file_hash(trace) == row["trace_sha256"]
        shutil.copyfile(trace, bundle / name / row["trace"])
    reports[name] = report
    # Every test episode is inspectable locally, with duplicate raw token text omitted in UI only.
    previews[name] = {}
    for row in report["rows"]:
        trace = json.loads((bundle / name / row["trace"]).read_text(encoding="utf-8"))
        previews[name][row["trace"]] = {
            k: trace[k]
            for k in ("task", "verdict", "observations", "http_client", "initial_state", "final_state")
        }
for seed in config["training_seeds"]:
    source = local / f"http-sft-{seed}/training.json"
    assert file_hash(source) == lock["selected_adapters"][str(seed)]["training_report_sha256"]
    shutil.copyfile(source, bundle / f"training-{seed}.json")
    training[str(seed)] = json.loads(source.read_text(encoding="utf-8"))
    write_report(
        bundle / f"comparison-{seed}.json", compare(reports["base-test"], reports[f"sft-{seed}-test"])
    )
(bundle / "data").mkdir(exist_ok=True)
for name in ("train.jsonl", "dev.jsonl", "provenance.json"):
    shutil.copyfile(local / "http-data-ordered" / name, bundle / "data" / name)
evidence = {
    "reports": reports,
    "lock": lock,
    "training": training,
    "previews": previews,
    "manifest": json.loads((root / "benchmarks/httpdesk-v1.json").read_text(encoding="utf-8")),
}
write_report(root / "src/resolvelab/static/http-experiment.json", evidence)
print(
    f"Published {sum(len(r['rows']) for r in reports.values())} model episodes and three training runs."
)
