"""Find a registered benchmark file, in a checkout or inside an installed wheel."""

from pathlib import Path

PACKAGE = Path(__file__).resolve().parent


def benchmark_file(name):
    packaged = PACKAGE / "benchmarks" / name
    return packaged if packaged.exists() else PACKAGE.parents[1] / "benchmarks" / name
