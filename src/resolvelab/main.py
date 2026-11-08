"""Console entry point: ``resolvelab casedesk ...`` for the benchmark, ``resolvelab durable ...``
for the durable-recovery environment, ``resolvelab proxy ...`` for the fault proxy, all else to
the original CLI.

The original ``cli.py`` is part of the locked v0.3/v0.4 source, so new commands are added
here instead of editing it.
"""

import sys


def main():
    argv = sys.argv[1:]
    if argv[:1] == ["casedesk"]:
        from .casedesk.cli import main as casedesk

        sys.exit(casedesk(argv[1:]))
    if argv[:1] == ["durable"]:
        from .durable.cli import main as durable

        sys.exit(durable(argv[1:]))
    if argv[:1] == ["proxy"]:
        from .proxy.cli import main as proxy

        sys.exit(proxy(argv[1:]))
    if argv[:1] in ([], ["-h"], ["--help"]):
        print("CaseDesk benchmark commands: resolvelab casedesk --help")
        print("Durable recovery (crashes, restarts, races): resolvelab durable --help")
        print("Fault proxy for any HTTP service: resolvelab proxy --help\n")
    from .cli import main as legacy

    legacy()
