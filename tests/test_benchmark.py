import copy
import hashlib
from pathlib import Path

import pytest

from resolvelab.benchmark import cases, digest, load_manifest, validate_training_rows
from resolvelab.curation import collect, read_rows
from resolvelab.hf_policy import initial_messages
from resolvelab.runner import Runner
from resolvelab.store import Store, dumps
from resolvelab.training import encode_example

MANIFEST = Path(__file__).parents[1] / "benchmarks/composition-v1.json"


def test_frozen_composition_splits_are_disjoint_and_all_reference_cases_work(tmp_path):
    manifest = load_manifest(MANIFEST)
    store = Store(tmp_path / "suite.sqlite")
    runner = Runner(store)
    for split, count in [("train", 72), ("dev", 8), ("test", 24)]:
        episodes = list(cases(manifest, split))
        assert len(episodes) == count
        for spec, seed in episodes:
            run = runner.execute(store.create(spec.id, seed, spec=spec))
            assert run["verdict"]["passed"], (split, spec.id, seed)


def test_leakage_check_rejects_equivalent_composition_and_seed(tmp_path):
    manifest = load_manifest(MANIFEST)
    changed = copy.deepcopy(manifest)
    changed["splits"]["test"]["templates"][0]["faults"] = ["rate", "mapping"]
    path = tmp_path / "bad.json"
    path.write_text(dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="Overlapping"):
        load_manifest(path)
    changed = copy.deepcopy(manifest)
    changed["splits"]["test"]["seeds"][0] = manifest["splits"]["train"]["seeds"][0]
    path.write_text(dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="seeds"):
        load_manifest(path)


def test_curator_never_exports_test_and_validator_rejects_relabeled_test(tmp_path):
    manifest = load_manifest(MANIFEST)
    for split in ("train", "dev", "test"):
        manifest["splits"][split]["seeds"] = manifest["splits"][split]["seeds"][:1]
    result = collect(manifest, tmp_path, tmp_path)
    assert result["splits"]["train"]["episodes"] == 9
    assert not (tmp_path / "test.jsonl").exists()
    rows = read_rows(tmp_path / "train.jsonl")
    assert (
        hashlib.sha256((tmp_path / "train.jsonl").read_bytes()).hexdigest()
        == result["splits"]["train"]["sha256"]
    )
    assert all(
        "faults" not in dumps(r["messages"]) and "verdict" not in dumps(r["messages"]) for r in rows
    )
    assert rows[0]["messages"] == initial_messages()
    row = copy.deepcopy(rows[0])
    row["template"], row["seed"] = "test_mapping_partial", 3301
    with pytest.raises(ValueError, match="outside"):
        validate_training_rows([row], manifest)
    row = copy.deepcopy(rows[0])
    row["manifest_sha256"] = digest({"different": True})
    with pytest.raises(ValueError, match="fingerprint"):
        validate_training_rows([row], manifest)
    with pytest.raises(ValueError, match="Test episodes"):
        validate_training_rows(rows, manifest, "test")


def test_action_encoding_masks_prefix_by_length_and_rejects_truncation():
    class Tokenizer:
        eos_token = "!"

        def apply_chat_template(self, messages, **kwargs):
            assert kwargs["enable_thinking"] is False
            return [10, 11, 12]

        def encode(self, text, **kwargs):
            assert text.endswith("!")
            return [20, 21]

    row = {"messages": [], "target": {"name": "inspect_job", "arguments": {}}}
    ids, supervised = encode_example(Tokenizer(), row, 5)
    assert ids == [10, 11, 12, 20, 21] and supervised == 2
    with pytest.raises(ValueError, match="truncation"):
        encode_example(Tokenizer(), row, 4)
