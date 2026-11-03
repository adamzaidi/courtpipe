"""Render README figures from docs/idb/settlement_report.json.

Reads only the recorded report. No data download, no API key.

    python scripts/idb_figures.py --report docs/idb/settlement_report.json --out docs/idb/figures
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INK = "#1f2933"
MUTED = "#8a94a3"
MODEL = "#2f6fdb"
BASE = "#b8c1cc"
BEST = "#5b6675"

BASELINE_NAMES = {
    "constant": "Constant rate",
    "nos_rate": "Case type rate",
    "court_rate": "District rate",
    "nos_court_rate": "Case type x district rate",
}


def _style(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(MUTED)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=INK, labelsize=9)


def auc_chart(report: dict, out: Path) -> None:
    p = report["primary"]
    best = p["best_baseline_auc"]
    rows = [(BASELINE_NAMES[k], v["roc_auc"], None, BEST if k == best else BASE) for k, v in p["baselines"].items()]
    lo, hi = p["bootstrap_vs_auc_baseline"]["model_auc_ci95"]
    rows.append(("Logistic regression (filing-time fields)", p["model_roc_auc"], (lo, hi), MODEL))

    fig, ax = plt.subplots(figsize=(7.2, 3.2), dpi=150)
    y = list(range(len(rows)))
    for i, (_, auc, ci, color) in enumerate(rows):
        ax.barh(i, auc - 0.5, left=0.5, color=color, height=0.6)
        if ci:
            ax.errorbar(auc, i, xerr=[[auc - ci[0]], [ci[1] - auc]], fmt="none", ecolor=INK, capsize=3, lw=1)
        ax.text(0.505, i, f"{auc:.3f}", va="center", ha="left", fontsize=8.5, color="white" if color in (MODEL, BEST) else INK)
    ax.set_yticks(y, [r[0] for r in rows])
    ax.set_xlim(0.5, 0.78)
    ax.set_xlabel("Test ROC-AUC (FY2018-2021 filings; bar starts at chance, 0.5)", fontsize=9, color=INK)
    ax.set_title("The model does not beat the case type x district baseline", fontsize=10.5, color=INK, loc="left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(out / "auc_vs_baselines.png")
    plt.close(fig)


def calibration_chart(report: dict, out: Path) -> None:
    bins = [b for b in report["calibration"] if b["n"]]
    fig, ax = plt.subplots(figsize=(4.6, 4.2), dpi=150)
    ax.plot([0, 1], [0, 1], color=MUTED, lw=1, ls="--", label="Perfect calibration")
    xs = [b["mean_predicted"] for b in bins]
    ys = [b["observed_rate"] for b in bins]
    sizes = [max(12, b["n"] / 2.5) for b in bins]
    ax.plot(xs, ys, color=MODEL, lw=1.2)
    ax.scatter(xs, ys, s=sizes, color=MODEL, zorder=3, label="Model (dot area = cases in bin)")
    ax.set_xlim(0, 0.9)
    ax.set_ylim(0, 0.9)
    ax.set_xlabel("Mean predicted settlement probability", fontsize=9, color=INK)
    ax.set_ylabel("Observed settlement rate", fontsize=9, color=INK)
    ax.set_title("Calibrated below 0.3, overconfident above", fontsize=10.5, color=INK, loc="left")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(out / "calibration.png")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="docs/idb/settlement_report.json")
    ap.add_argument("--out", default="docs/idb/figures")
    args = ap.parse_args()
    report = json.loads(Path(args.report).read_text())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    auc_chart(report, out)
    calibration_chart(report, out)
    print(f"wrote {out}/auc_vs_baselines.png and {out}/calibration.png")


if __name__ == "__main__":
    main()
