"""Render the README result figure (light and dark SVG) from the published v0.4 bundle only.

Left: test success per arm, one dot per training seed and a tick at the mean.
Right: failed test episodes by cause, classified from the zipped traces.
"""

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "artifacts/v0.4"
OUT = ROOT / "docs/assets"

ARMS = [
    ("base-0.6b", "Qwen3-0.6B base"),
    ("base-0.6b-3demo", "0.6B base, 3 demos"),
    ("base-1.7b", "Qwen3-1.7B base"),
    ("base-1.7b-3demo", "1.7B base, 3 demos"),
    ("v03-lora", "v0.3 adapters"),
    ("bc", "BC"),
    ("bc-volume", "BC + expert rows"),
    ("dagger", "BC + DAgger rows"),
]
CAUSES = ["ETag copy error", "Unsafe write", "False success", "Other"]
THEMES = {
    "light": {
        "surface": "#fcfcfb",
        "ink": "#0b0b0b",
        "ink2": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "focus": "#2a78d6",
        "rest": "#898781",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
    },
    "dark": {
        "surface": "#1a1a19",
        "ink": "#f0efec",
        "ink2": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "focus": "#3987e5",
        "rest": "#898781",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500"],
    },
}


def malformed(etag):
    return not (etag.startswith('"v') and etag.endswith('"') and etag[2:-1].isdigit())


def cause(row, trace):
    """The same mutually exclusive taxonomy as artifacts/v0.4/RESULTS.md."""
    if row["error"] == "json_error":
        raw = [d for d in trace["decisions"] if "error" in d][-1]["usage"].get("raw_output", "")
        return "ETag copy error" if '"etag"' in raw else "Other"
    if row["error"] == "tool_budget":
        patches = [o for o in trace["observations"] if o["name"] == "patch_ticket"]
        return "ETag copy error" if any(malformed(o["arguments"]["etag"]) for o in patches) else "Other"
    return {"unsafe_mutation": "Unsafe write", "false_success": "False success"}.get(
        row["failure_category"], "Other"
    )


def data():
    analysis = json.loads((BUNDLE / "analysis-test.json").read_text(encoding="utf-8"))
    rates = {name: analysis["arms"][name]["success"] for name, _ in ARMS}
    causes = {}
    for arm in ("bc", "bc-volume", "dagger"):
        counts = dict.fromkeys(CAUSES, 0)
        # Exact per-seed names: a "bc-*" glob would also match the bc-volume reports.
        for seed in analysis["arms"][arm]["seeds"]:
            report_path = BUNDLE / "test" / f"{arm}-{seed}.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            traces = zipfile.ZipFile(BUNDLE / "traces/test" / f"{report_path.stem}.zip")
            for row in report["rows"]:
                if not row["passed"]:
                    counts[cause(row, json.loads(traces.read(row["trace"])))] += 1
        causes[arm] = counts
    return rates, causes


def text(x, y, value, fill, size=13, anchor="start", weight=400):
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-size="{size}" text-anchor="{anchor}" '
        f'font-weight="{weight}">{value}</text>'
    )


def bar(x, y, width, height, fill, round_end):
    """Square at the baseline, 4px rounded data-end."""
    if width <= 0:
        return ""
    r = min(4, width / 2) if round_end else 0
    return (
        f'<path d="M{x:.1f},{y:.1f} h{width - r:.1f} q{r},0 {r},{r} v{height - 2 * r:.1f} '
        f'q0,{r} {-r},{r} h{-(width - r):.1f} z" fill="{fill}"/>'
    )


def render(theme, rates, causes):
    t = THEMES[theme]
    width, height = 1020, 380
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="system-ui, -apple-system, Segoe UI, sans-serif">',
        f'<rect width="{width}" height="{height}" rx="10" fill="{t["surface"]}"/>',
    ]
    # Left panel: success per arm.
    left, label_w, plot_w, top, row_h = 24, 150, 290, 78, 34
    x0 = left + label_w
    parts.append(text(left, 32, "Test success, 120 independent episodes", t["ink"], 15, weight=600))
    parts.append(text(left, 52, "Dots: training seeds. Tick: mean.", t["ink2"], 12))
    for pct in (0, 25, 50, 75, 100):
        gx = x0 + plot_w * pct / 100
        parts.append(
            f'<line x1="{gx:.1f}" y1="{top - 8}" x2="{gx:.1f}" y2="{top + row_h * len(ARMS) - 14}" '
            f'stroke="{t["grid"]}" stroke-width="1"/>'
        )
        parts.append(text(gx, top + row_h * len(ARMS) + 2, f"{pct}%", t["muted"], 11, "middle"))
    for i, (name, label) in enumerate(ARMS):
        cy = top + i * row_h + 4
        focus = name == "dagger"
        colour = t["focus"] if focus else t["rest"]
        parts.append(
            text(left, cy + 4, label, t["ink"] if focus else t["ink2"], 13, weight=600 if focus else 400)
        )
        mean = rates[name]["mean"]
        mx = x0 + plot_w * mean
        parts.append(
            f'<line x1="{mx:.1f}" y1="{cy - 9}" x2="{mx:.1f}" y2="{cy + 9}" stroke="{colour}" '
            f'stroke-width="2" stroke-linecap="round"/>'
        )
        for rate in rates[name]["per_seed"]:
            px = x0 + plot_w * rate
            parts.append(
                f'<circle cx="{px:.1f}" cy="{cy}" r="5" fill="{colour}" stroke="{t["surface"]}" '
                f'stroke-width="2"/>'
            )
        parts.append(
            text(
                x0 + plot_w + 20,
                cy + 4,
                f"{100 * mean:.1f}%",
                t["ink"] if focus else t["ink2"],
                13,
                weight=600 if focus else 400,
            )
        )
    # Right panel: failures by cause.
    rx, rlabel_w, rplot_w = 570, 146, 230
    bx = rx + rlabel_w
    scale = rplot_w / max(sum(c.values()) for c in causes.values())
    parts.append(text(rx, 32, "Failed test episodes by cause", t["ink"], 15, weight=600))
    parts.append(text(rx, 52, "Three training seeds pooled (360 episodes per arm).", t["ink2"], 12))
    lx = rx
    for i, name in enumerate(CAUSES):
        parts.append(f'<rect x="{lx}" y="70" width="10" height="10" rx="2" fill="{t["series"][i]}"/>')
        parts.append(text(lx + 15, 79.5, name, t["ink2"], 12))
        lx += 15 + 6.6 * len(name) + 16
    for j, (arm, label) in enumerate(
        (("bc", "BC"), ("bc-volume", "BC + expert rows"), ("dagger", "BC + DAgger rows"))
    ):
        y = 122 + j * 78
        focus = arm == "dagger"
        parts.append(
            text(rx, y + 16, label, t["ink"] if focus else t["ink2"], 13, weight=600 if focus else 400)
        )
        counts = causes[arm]
        present = [c for c in CAUSES if counts[c]]
        x = bx
        for k, c in enumerate(present):
            w = counts[c] * scale
            seg = w - (2 if k < len(present) - 1 else 0)
            fill = t["series"][CAUSES.index(c)]
            parts.append(bar(x, y, seg, 24, fill, k == len(present) - 1))
            if seg >= 22:
                ink = "#0b0b0b" if CAUSES.index(c) in (2, 3) else "#ffffff"
                parts.append(text(x + seg / 2, y + 16.5, counts[c], ink, 12, "middle", 600))
            x += w
        total = sum(counts.values())
        parts.append(
            text(
                x + 8,
                y + 16.5,
                f"{total} failed",
                t["ink"] if focus else t["ink2"],
                13,
                weight=600 if focus else 400,
            )
        )
        small = [f"{c.lower()} {counts[c]}" for c in present if counts[c] * scale - 2 < 22]
        if small:
            parts.append(text(bx, y + 42, "incl. " + ", ".join(small), t["muted"], 11))
    parts.append(
        f'<line x1="{bx}" y1="110" x2="{bx}" y2="{122 + 2 * 78 + 30}" stroke="{t["axis"]}" stroke-width="1"/>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main():
    rates, causes = data()
    OUT.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        path = OUT / f"casedesk-v2-results-{theme}.svg"
        path.write_text(render(theme, rates, causes), encoding="utf-8", newline="\n")
        print(path.relative_to(ROOT))
    print(json.dumps(causes))


if __name__ == "__main__":
    main()
