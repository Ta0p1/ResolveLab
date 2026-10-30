"""Analysis for the dialect transfer study (docs/dialect-transfer-protocol.md), fixed before test.

Q1 pairs each adapter's held-out-dialect episodes with its own published v0.4 episodes on the
study contract: the same adapter and seed, so seeds are resampled jointly for both conditions
(``paired_seed_bootstrap``). Q2 and Q3 compare different adapters on the same dialect episodes
with the v0.4 machinery unchanged: arms' seeds resampled independently, episodes within
composition strata, plus the composition-cluster bootstrap and exact McNemar per seed pair.
"""

import random

from ..casedesk.analysis import arm_summary, compare, load_arms, matrix, slices
from ..casedesk.stats import mcnemar, percentile, seed_mean_rate
from .assignment import dialect_named

ZERO_SHOT = ("bc", "bc-volume", "dagger", "base-1.7b")
MULTI = {"bc-multi": "bc", "bc-volume-multi": "bc-volume", "dagger-multi": "dagger"}
# (left, right, question, minimum effect, ceiling rule applies)
DECISIONS = {
    "Q2": ("bc", "bc-multi", "contract diversity on the same states and actions", 0.10, False),
    "Q3": ("bc-volume-multi", "dagger-multi", "DAgger vs size-matched BC in train dialects", 0.05, True),
}
SECONDARY = [
    ("bc-volume", "dagger", "Q1: the v0.4 DAgger advantage, in held-out dialects"),
    ("bc-volume", "bc-volume-multi", "diversity with the extra expert rows"),
    ("dagger", "dagger-multi", "diversity with DAgger rows"),
    ("base-1.7b", "bc-multi", "size control vs multi-dialect BC"),
]


def paired_seed_bootstrap(left, right, strata, draws=10000, seed=2026):
    """CI for mean(right) - mean(left) when row k of both is the same adapter (seed k).

    Each draw resamples seed indices once for both conditions, then episodes within strata.
    """
    if len(left) != len(right):
        raise ValueError("Conditions must hold the same seeds")
    rng = random.Random(seed)
    by_stratum = {}
    for index, stratum in enumerate(strata):
        by_stratum.setdefault(stratum, []).append(index)
    n, k = len(strata), len(left)
    estimates = []
    for _ in range(draws):
        seeds = [rng.randrange(k) for _ in range(k)]
        picks = [rng.choice(members) for members in by_stratum.values() for _ in members]
        total = sum(right[s][i] - left[s][i] for s in seeds for i in picks)
        estimates.append(total / (n * k))
    point = sum(sum(b) - sum(a) for a, b in zip(left, right)) / (n * k)
    return {"estimate": point, "ci95": [percentile(estimates, 0.025), percentile(estimates, 0.975)]}


def transfer(canonical, dialect, strata, draws=10000):
    """Q1 for one adapter: dialect minus study contract, and the registered classification."""
    if sorted(canonical, key=str) != sorted(dialect, key=str):
        raise ValueError("Q1 needs the same seeds in both conditions")
    left, right = matrix(canonical), matrix(dialect)
    shift = paired_seed_bootstrap(left, right, strata, draws)
    rate = seed_mean_rate(right)["mean"]
    if rate < 0.5:
        verdict = "does not transfer"
    elif shift["estimate"] >= -0.05 and shift["ci95"][0] >= -0.10:
        verdict = "transfers"
    else:
        verdict = "partial"
    return {
        "study_contract_rate": seed_mean_rate(left)["mean"],
        "dialect_rate": rate,
        "dialect_minus_study": shift,
        "mcnemar_by_seed": [mcnemar(a, b) for a, b in zip(left, right)],
        "classification": verdict,
    }


def decide(comparison, left, right, minimum, ceiling):
    est = comparison["hierarchical"]["estimate"]
    low, high = comparison["hierarchical"]["ci95"]
    rates = [r for arm in (left, right) for r in arm["success"]["per_seed"]]
    if ceiling and min(rates) >= 0.95:
        return "uninformative (ceiling)"
    if est >= minimum and low > 0:
        verdict = "supported"
    elif high < 0:
        verdict = "harmful"
    else:
        verdict = "inconclusive at this size"
    if verdict == "supported" and comparison["safety_difference_per_120"] > 2:
        verdict += " but fails safety non-inferiority"
    return verdict


def convention_factors(specs, assignment):
    conventions = {s["id"]: dialect_named(assignment["episodes"][s["id"]]) for s in specs}
    factors = {}
    for style in ("etag", "revision", "weak_etag", "version_tag"):
        factors[f"token_{style}"] = lambda s, v=style: conventions[s["id"]].token == v
    for style in ("page", "opaque", "offset", "page_number"):
        factors[f"cursor_{style}"] = lambda s, v=style: conventions[s["id"]].cursor == v
    for unit in ("seconds", "milliseconds"):
        factors[f"unit_{unit}"] = lambda s, v=unit: conventions[s["id"]].unit == v
    factors["conflict_is_409"] = lambda s: conventions[s["id"]].codes[412] == 409
    factors["phrasing_seen"] = lambda s: s["phrasing_group"] == "seen"
    factors["phrasing_held_out"] = lambda s: s["phrasing_group"] == "unseen"
    factors |= {
        c: (lambda s, c=c: s["composition"] == c) for c in dict.fromkeys(x["composition"] for x in specs)
    }
    return factors


def analyze(
    dialect_dir, study_dir, manifest, assignment, multi_study_dir=None, pool="test", draws=10000
):
    """``dialect_dir``: reports in held-out dialects. ``study_dir``: the published v0.4 reports on
    the study contract. ``multi_study_dir``: the multi arms on the study contract (cost of
    diversity), if run."""
    dialect, order = load_arms(dialect_dir, manifest, pool)
    study, _ = load_arms(study_dir, manifest, pool)
    specs = manifest["episodes"][pool]
    strata = [s["composition"] for s in specs]
    factors = convention_factors(specs, assignment)
    report = {
        "pool": pool,
        "episodes": len(order),
        "arms": {
            name: arm_summary(arm) | {"slices": slices(arm, specs, factors)}
            for name, arm in dialect.items()
        },
        "transfer": {
            name: transfer(study[name], dialect[name], strata, draws)
            for name in ZERO_SHOT
            if name in dialect and name in study
        },
        "comparisons": {},
        "decisions": {},
    }
    for key, (left, right, question, minimum, ceiling) in DECISIONS.items():
        if left in dialect and right in dialect:
            name = f"{right} - {left}"
            comparison = {"question": f"{key}: {question}"} | compare(
                dialect[left], dialect[right], strata
            )
            report["comparisons"][name] = comparison
            report["decisions"][key] = decide(
                comparison, report["arms"][left], report["arms"][right], minimum, ceiling
            )
    for left, right, question in SECONDARY:
        if left in dialect and right in dialect:
            report["comparisons"][f"{right} - {left}"] = {"question": question} | compare(
                dialect[left], dialect[right], strata
            )
    if multi_study_dir is not None:
        multi, _ = load_arms(multi_study_dir, manifest, pool)
        report["cost_of_diversity"] = {}
        for arm, counterpart in MULTI.items():
            if arm in multi and counterpart in study:
                own = seed_mean_rate(matrix(multi[arm]))["mean"]
                reference = seed_mean_rate(matrix(study[counterpart]))["mean"]
                report["cost_of_diversity"][arm] = {
                    "study_contract_rate": own,
                    "v04_counterpart_rate": reference,
                    "stated_as_cost": own < reference - 0.05,
                }
    trained = [report["arms"][a]["success"]["mean"] for a in dialect if a != "base-1.7b"]
    if "base-1.7b" in dialect and trained:
        report["baseline_is_headline"] = report["arms"]["base-1.7b"]["success"]["mean"] >= max(trained)
    return report


def markdown(report):
    from ..casedesk.analysis import markdown as study_markdown

    pct = lambda x: f"{100 * x:.1f}"  # noqa: E731
    lines = [
        study_markdown(report).rstrip(),
        "",
        "| Q1 adapter | Study contract | Held-out dialects | Δ (pp) | 95% CI | Classification |",
    ]
    lines.append("|---|---:|---:|---:|---|---|")
    for name, t in report["transfer"].items():
        shift = t["dialect_minus_study"]
        lines.append(
            f"| {name} | {pct(t['study_contract_rate'])}% | {pct(t['dialect_rate'])}% | {pct(shift['estimate'])} | "
            f"[{pct(shift['ci95'][0])}, {pct(shift['ci95'][1])}] | {t['classification']} |"
        )
    lines.append("")
    lines += [f"{key} (registered rule): **{verdict}**." for key, verdict in report["decisions"].items()]
    if report.get("baseline_is_headline"):
        lines.append("`base-1.7b` matches or beats every trained arm: that is the headline.")
    return "\n".join(lines) + "\n"
