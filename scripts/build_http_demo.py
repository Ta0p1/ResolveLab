"""Build a fixed in-context example from a verified TRAIN episode only."""

import json
from pathlib import Path

from resolvelab.httpdesk.experiment import episode
from resolvelab.httpdesk.schema import action_json
from resolvelab.store import dumps

trace = episode({"id": "train_plain", "faults": []}, 4101)
assert trace["verdict"]["passed"]
messages = [{"role": "user", "content": trace["task"]}]
for obs in trace["observations"]:
    messages.append(
        {
            "role": "assistant",
            "content": action_json({"name": obs["name"], "arguments": obs["arguments"]}),
        }
    )
    if obs["name"] != "finish":
        messages.append(
            {"role": "user", "content": dumps({"tool": obs["name"], "result": obs["result"]})}
        )
path = Path("src/resolvelab/httpdesk/demo.json")
path.write_text(
    json.dumps({"template": "train_plain", "seed": 4101, "messages": messages}, indent=2) + "\n",
    encoding="utf-8",
    newline="\n",
)
print(path)
