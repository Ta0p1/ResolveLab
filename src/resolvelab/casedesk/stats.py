"""Small-sample statistics without third-party dependencies.

The v0.3 template bootstrap collapsed to [66.7, 66.7] because every template reused the same
three records, so success was a deterministic function of the record. In v2 each episode has
its own record, and we separate two sources of uncertainty:

- record generalization for the fixed registered compositions: resample episodes within
  composition strata (paired across arms on the same episodes);
- training-seed variation: resample registered training seeds of each arm.

``hierarchical_bootstrap`` draws both. Cross-composition generalization (resampling the ten
compositions) is reported separately and is expected to be wide.
"""

import math
import random


def wilson(k, n, z=1.959964):
    if not n:
        return [0.0, 1.0]
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [max(0.0, centre - half), min(1.0, centre + half)]


def binomial_two_sided(k, n):
    """Exact two-sided p-value for k successes in n fair trials (McNemar's exact test)."""
    if not n:
        return 1.0
    probs = [math.comb(n, i) / 2**n for i in range(n + 1)]
    observed = probs[k]
    return min(1.0, sum(p for p in probs if p <= observed * (1 + 1e-9)))


def mcnemar(left, right):
    """Paired binary outcomes on the same episodes: right-only wins vs left-only wins."""
    if len(left) != len(right):
        raise ValueError("Unpaired outcomes")
    gains = sum(not a and b for a, b in zip(left, right))
    losses = sum(a and not b for a, b in zip(left, right))
    return {
        "right_only": gains,
        "left_only": losses,
        "p_exact": binomial_two_sided(gains, gains + losses),
    }


def percentile(values, q):
    values = sorted(values)
    position = (len(values) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def hierarchical_bootstrap(left, right, strata, draws=10000, seed=2026):
    """CI for mean(right) - mean(left) over paired episodes.

    ``left`` and ``right`` are lists of per-seed outcome vectors (seeds x episodes; a
    deterministic baseline has one row). Each draw resamples each arm's seeds independently,
    then episodes within strata (the same episode indices for both arms).
    """
    rng = random.Random(seed)
    by_stratum = {}
    for index, stratum in enumerate(strata):
        by_stratum.setdefault(stratum, []).append(index)
    n = len(strata)
    estimates = []
    for _ in range(draws):
        left_seeds = [rng.choice(left) for _ in left]
        right_seeds = [rng.choice(right) for _ in right]
        picks = [rng.choice(members) for members in by_stratum.values() for _ in members]
        total = 0.0
        for i in picks:
            total += sum(s[i] for s in right_seeds) / len(right_seeds)
            total -= sum(s[i] for s in left_seeds) / len(left_seeds)
        estimates.append(total / n)
    point = sum(sum(s) / n for s in right) / len(right) - sum(sum(s) / n for s in left) / len(left)
    return {"estimate": point, "ci95": [percentile(estimates, 0.025), percentile(estimates, 0.975)]}


def cluster_bootstrap(left, right, clusters, draws=10000, seed=2026):
    """Resample whole compositions: generalization to *other* compositions like these."""
    rng = random.Random(seed)
    groups = {}
    for index, cluster in enumerate(clusters):
        groups.setdefault(cluster, []).append(index)
    keys = list(groups)

    def mean(rows, indices):
        return sum(sum(s[i] for i in indices) / len(indices) for s in rows) / len(rows)

    estimates = []
    for _ in range(draws):
        chosen = [i for _ in keys for i in groups[rng.choice(keys)]]
        estimates.append(mean(right, chosen) - mean(left, chosen))
    return {"ci95": [percentile(estimates, 0.025), percentile(estimates, 0.975)]}


def seed_mean_rate(rows):
    """Mean and range of per-seed success rates."""
    rates = [sum(r) / len(r) for r in rows]
    return {"mean": sum(rates) / len(rates), "min": min(rates), "max": max(rates), "per_seed": rates}


def paired_power(p_left_only, p_right_only, n, alpha=0.05, sims=4000, seed=7):
    """Simulated power of the exact McNemar test for given discordance probabilities."""
    rng = random.Random(seed)
    hits = 0
    for _ in range(sims):
        gains = losses = 0
        for _ in range(n):
            u = rng.random()
            if u < p_right_only:
                gains += 1
            elif u < p_right_only + p_left_only:
                losses += 1
        hits += binomial_two_sided(gains, gains + losses) < alpha
    return hits / sims
