"""Render the README figure of the dialect study (light and dark SVG) from artifacts/v0.5 only.

Left: pass rate per arm in held-out dialects (one dot per training seed, a tick at the mean)
against the original contract. Right: failed episodes by cause, from the exploratory table.
"""

import json
from pathlib import Path

from make_readme_figure import THEMES, bar, text

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "artifacts/v0.5"
OUT = ROOT / "docs/assets"

GROUPS = (("base-1.7b",), ("bc", "bc-volume", "dagger"), ("bc-multi", "bc-volume-multi", "dagger-multi"))
LABELS = {"base-1.7b": "Qwen3-1.7B base"}
FOCUS = "dagger-multi"
# The v0.4 figure's categories and colours; each cause of the failure table folds into one.
CAUSES = {
    "Token copy error": ("token runs to output cap", "malformed-token loop"),
    "Wrong write": ("wrong-record write", "wrong-value write"),
    "False success": ("claims success, no write attempted", "claims success after a refused write"),
    "Other": (
        "other invalid output",
        "repeated-write loop",
        "other budget loop",
        "escalation error",
        "other",
    ),
}
PANELS = (
    ("Held-out dialects", "test"),
    ("Original contract", "study-contract"),
)
BAR_ARMS = ("bc-volume-multi", "dagger-multi")


def data():
    analysis = json.loads((BUNDLE / "analysis-test.json").read_text(encoding="utf-8"))
    failures = json.loads((BUNDLE / "diagnostics/failure-causes.json").read_text(encoding="utf-8"))
    rates = {}
    for arm, summary in analysis["arms"].items():
        if arm in analysis["transfer"]:
            original = analysis["transfer"][arm]["study_contract_rate"]
        else:
            original = analysis["cost_of_diversity"][arm]["study_contract_rate"]
        success = summary["success"]
        rates[arm] = {"mean": success["mean"], "per_seed": success["per_seed"], "original": original}
    causes = {
        key: {name: sum(run["causes"][c] for c in members) for name, members in CAUSES.items()}
        for key, run in failures.items()
    }
    return rates, causes


def render(theme, rates, causes):
    t = THEMES[theme]
    width, height = 1020, 376
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="system-ui, -apple-system, Segoe UI, sans-serif">',
        f'<rect width="{width}" height="{height}" rx="10" fill="{t["surface"]}"/>',
    ]
    # Left panel: pass rate per arm, both contracts.
    left, label_w, plot_w, top, row_h, group_gap = 24, 118, 280, 112, 32, 9
    x0 = left + label_w
    held_x, original_x = x0 + plot_w + 62, x0 + plot_w + 118
    parts.append(text(left, 32, "Pass rate, 120 test episodes", t["ink"], 15, weight=600))
    parts.append(
        text(
            left,
            52,
            "Each episode in a generated API dialect, or on the original contract.",
            t["ink2"],
            12,
        )
    )
    # Legend: the marks themselves, in the neutral colour.
    parts.append(f'<circle cx="{left + 5}" cy="75" r="5" fill="{t["rest"]}"/>')
    parts.append(text(left + 15, 79.5, "Held-out, per seed", t["ink2"], 12))
    parts.append(
        f'<line x1="{left + 139}" y1="68" x2="{left + 139}" y2="82" stroke="{t["rest"]}" '
        f'stroke-width="2" stroke-linecap="round"/>'
    )
    parts.append(text(left + 148, 79.5, "Held-out mean", t["ink2"], 12))
    parts.append(
        f'<circle cx="{left + 251}" cy="75" r="5" fill="{t["surface"]}" stroke="{t["ink2"]}" stroke-width="2"/>'
    )
    parts.append(text(left + 261, 79.5, "Original contract", t["ink2"], 12))
    parts.append(text(held_x, 95, "Held-out", t["muted"], 11, "end"))
    parts.append(text(original_x, 95, "Original", t["muted"], 11, "end"))
    rows = len([a for g in GROUPS for a in g])
    bottom = top + row_h * (rows - 1) + group_gap * (len(GROUPS) - 1)
    for pct in (0, 25, 50, 75, 100):
        gx = x0 + plot_w * pct / 100
        parts.append(
            f'<line x1="{gx:.1f}" y1="{top - 12}" x2="{gx:.1f}" y2="{bottom + 14}" '
            f'stroke="{t["grid"]}" stroke-width="1"/>'
        )
        parts.append(text(gx, bottom + 30, f"{pct}%", t["muted"], 11, "middle"))
    cy = top
    for group in GROUPS:
        for arm in group:
            focus = arm == FOCUS
            colour = t["focus"] if focus else t["rest"]
            ink = t["ink"] if focus else t["ink2"]
            weight = 600 if focus else 400
            rate = rates[arm]
            mx, ox = x0 + plot_w * rate["mean"], x0 + plot_w * rate["original"]
            parts.append(text(left, cy + 4, LABELS.get(arm, arm), ink, 13, weight=weight))
            parts.append(
                f'<line x1="{mx:.1f}" y1="{cy}" x2="{ox:.1f}" y2="{cy}" stroke="{t["axis"]}" '
                f'stroke-width="2"/>'
            )
            parts.append(
                f'<circle cx="{ox:.1f}" cy="{cy}" r="5" fill="{t["surface"]}" stroke="{t["ink2"]}" '
                f'stroke-width="2"/>'
            )
            parts.append(
                f'<line x1="{mx:.1f}" y1="{cy - 9}" x2="{mx:.1f}" y2="{cy + 9}" stroke="{colour}" '
                f'stroke-width="2" stroke-linecap="round"/>'
            )
            for seed_rate in rate["per_seed"]:
                px = x0 + plot_w * seed_rate
                parts.append(
                    f'<circle cx="{px:.1f}" cy="{cy}" r="5" fill="{colour}" stroke="{t["surface"]}" '
                    f'stroke-width="2"/>'
                )
            parts.append(text(held_x, cy + 4, f"{100 * rate['mean']:.1f}%", ink, 13, "end", weight))
            parts.append(
                text(original_x, cy + 4, f"{100 * rate['original']:.1f}%", t["ink2"], 13, "end")
            )
            cy += row_h
        cy += group_gap
    # Right panel: failed episodes by cause.
    rx, rlabel_w, rplot_w = 584, 112, 214
    bx = rx + rlabel_w
    keys = [f"{pool}/{arm}" for _, pool in PANELS for arm in BAR_ARMS]
    scale = rplot_w / max(sum(causes[k].values()) for k in keys)
    parts.append(text(rx, 32, "Failed episodes by cause", t["ink"], 15, weight=600))
    parts.append(text(rx, 52, "Three training seeds pooled (360 episodes per arm).", t["ink2"], 12))
    lx = rx
    for i, name in enumerate(CAUSES):
        parts.append(f'<rect x="{lx}" y="70" width="10" height="10" rx="2" fill="{t["series"][i]}"/>')
        parts.append(text(lx + 15, 79.5, name, t["ink2"], 12))
        lx += 15 + 6.4 * len(name) + 14
    y = 102
    for panel, pool in PANELS:
        parts.append(text(rx, y, panel, t["ink2"], 12, weight=600))
        first = y + 10
        for arm in BAR_ARMS:
            y += 10
            focus = arm == FOCUS
            ink = t["ink"] if focus else t["ink2"]
            weight = 600 if focus else 400
            parts.append(text(rx, y + 16.5, arm, ink, 13, weight=weight))
            counts = causes[f"{pool}/{arm}"]
            present = [c for c in CAUSES if counts[c]]
            x = bx
            for k, name in enumerate(present):
                w = counts[name] * scale
                seg = w - (2 if k < len(present) - 1 else 0)
                index = list(CAUSES).index(name)
                parts.append(bar(x, y, seg, 24, t["series"][index], k == len(present) - 1))
                if seg >= 22:
                    number = "#0b0b0b" if index in (2, 3) else "#ffffff"
                    parts.append(text(x + seg / 2, y + 16.5, counts[name], number, 12, "middle", 600))
                x += w
            parts.append(text(x + 8, y + 16.5, f"{sum(counts.values())} failed", ink, 13, weight=weight))
            small = [f"{c.lower()} {counts[c]}" for c in present if counts[c] * scale - 2 < 22]
            note = ", ".join(small)
            if not counts["Token copy error"]:
                note = f"no token copy errors; {note}" if note else "no token copy errors"
            elif note:
                note = f"incl. {note}"
            if note:
                parts.append(text(bx, y + 38, note, t["muted"], 11))
            y += 40
        parts.append(
            f'<line x1="{bx}" y1="{first - 4}" x2="{bx}" y2="{y - 12}" stroke="{t["axis"]}" stroke-width="1"/>'
        )
        y += 24
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main():
    rates, causes = data()
    OUT.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        path = OUT / f"dialect-transfer-results-{theme}.svg"
        path.write_text(render(theme, rates, causes), encoding="utf-8", newline="\n")
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
