"""Run the synthetic CaseDesk service separately for manual HTTP contract inspection."""

import argparse

import uvicorn

from resolvelab.httpdesk.benchmark import FAULTS
from resolvelab.httpdesk.service import DeskState, create_app

parser = argparse.ArgumentParser()
parser.add_argument("--seed", type=int, default=4101)
parser.add_argument("--faults", nargs="*", choices=sorted(FAULTS), default=["conflict", "lost_ack"])
parser.add_argument("--port", type=int, default=8770)
args = parser.parse_args()
state = DeskState(args.faults, args.seed)
print("Synthetic sandbox; state and receipts last for this process only.", flush=True)
print(state.task, flush=True)
uvicorn.run(create_app(state), host="127.0.0.1", port=args.port)
