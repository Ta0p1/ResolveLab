"""Console entry point: ``resolvelab casedesk ...`` for the benchmark, all else to the original CLI.

The original ``cli.py`` is part of the locked v0.3/v0.4 source, so new commands are added
here instead of editing it.
"""

import sys


def main():
    argv = sys.argv[1:]
    if argv[:1] == ["casedesk"]:
        from .casedesk.cli import main as casedesk

        sys.exit(casedesk(argv[1:]))
    if argv[:1] in ([], ["-h"], ["--help"]):
        print("CaseDesk benchmark commands: resolvelab casedesk --help\n")
    from .cli import main as legacy

    legacy()
