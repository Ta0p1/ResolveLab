import threading
import time

from .policies import OllamaPolicy, PolicyResponseError, naive_next, reference_next
from .store import Store
from .tools import Toolbox
from .verification import grade

MAX_STEPS = 18


class Runner:
    def __init__(self, store: Store, provider=None):
        self.store = store
        self.provider = provider
        self._guard = threading.Lock()
        self._active: set[str] = set()
        self._model_lock = threading.Lock()

    def start(self, run_id: str):
        with self._guard:
            if run_id in self._active:
                return False
            run = self.store.get(run_id)
            if run["status"] in {"completed", "error"}:
                return False
            self._active.add(run_id)
        threading.Thread(target=self._background, args=(run_id,), daemon=True).start()
        return True

    def _background(self, run_id):
        try:
            self.execute(run_id)
        finally:
            with self._guard:
                self._active.discard(run_id)

    def execute(self, run_id: str) -> dict:
        run = self.store.get(run_id)
        if run["status"] in {"completed", "error"}:
            return run
        started = time.perf_counter()
        self.store.update(run_id, status="running", error=None)
        tools = Toolbox(self.store, run_id)
        observations = [
            {
                "name": e["name"],
                "arguments": e["arguments"],
                "result": {k: v for k, v in e["result"].items() if k != "mutated"},
            }
            for e in run["events"]
            if e["kind"] == "tool"
        ]
        provider = self.provider
        if run["policy"] == "ollama" and provider is None:
            provider = OllamaPolicy(run["model"] or "qwen3:4b")
        if run["policy"] not in {"naive", "reference", "ollama"} and provider is None:
            raise ValueError("A model provider must be supplied for this policy")
        # Reconstruct from committed tool events: a crash between an action and a message update is recoverable.
        messages = provider.initial_messages() if provider else []
        for observation in observations:
            if provider:
                provider.append_observation(messages, **observation)
        input_tokens, output_tokens = run["input_tokens"], run["output_tokens"]
        claim, summary = "failed", "Tool budget exhausted before verified completion."
        try:
            if (
                observations
                and observations[-1]["name"] == "finish"
                and observations[-1]["result"].get("ok")
            ):
                claim = observations[-1]["arguments"]["claim"]
                summary = observations[-1]["arguments"]["summary"]
            else:
                for _ in range(len(observations), MAX_STEPS):
                    if provider:
                        with self._model_lock:
                            action, usage, seconds = provider.next(messages)
                        input_tokens += usage["input_tokens"]
                        output_tokens += usage["output_tokens"]
                        self.store.event(
                            run_id, "model", "decision", action.model_dump(), usage, seconds * 1000
                        )
                        self.store.update(run_id, input_tokens=input_tokens, output_tokens=output_tokens)
                    else:
                        action = (reference_next if run["policy"] == "reference" else naive_next)(
                            observations
                        )
                    result = tools.call(action.name, action.arguments)
                    observations.append(
                        {"name": action.name, "arguments": action.arguments, "result": result}
                    )
                    if provider:
                        provider.append_observation(messages, action.name, action.arguments, result)
                        self.store.update(run_id, messages=messages)
                    if action.name == "finish" and result.get("ok"):
                        claim, summary = action.arguments["claim"], action.arguments["summary"]
                        break
            with self.store.connect() as c:
                verdict = grade(c, run_id, claim)
            self.store.update(
                run_id,
                status="completed",
                verdict=verdict,
                claim=claim,
                summary=summary,
                wall_seconds=run["wall_seconds"] + time.perf_counter() - started,
            )
            self.store.event(run_id, "verification", "outcome", {"claim": claim}, verdict)
        except Exception as exc:
            if isinstance(exc, PolicyResponseError):
                input_tokens += exc.usage["input_tokens"]
                output_tokens += exc.usage["output_tokens"]
                self.store.event(
                    run_id,
                    "model",
                    "invalid_response",
                    {},
                    {**exc.usage, "error": str(exc)},
                    exc.seconds * 1000,
                )
            with self.store.connect() as c:
                verdict = grade(c, run_id, "failed")
            self.store.update(
                run_id,
                status="error",
                verdict=verdict,
                claim="failed",
                error=f"{type(exc).__name__}: {str(exc)[:500]}",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                wall_seconds=run["wall_seconds"] + time.perf_counter() - started,
            )
        return self.store.get(run_id)
