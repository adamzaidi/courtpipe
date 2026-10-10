"""Offline results for the bundled synthetic opinions.

Reads tests/fixtures/sample_opinions.csv, labels it with the transform
stage, trains the baseline models, and writes charts plus metrics.
No CourtListener calls and no API key.

    python scripts/fixture_results.py --out docs/examples/fixture-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "sample_opinions.csv"


def _needs_review(fine: str, confidence: float) -> int:
    needs = 0
    if fine in {"other", "mixed"}:
        needs = 1
    if confidence < 0.60:
        needs = 1
    return needs


def run(out_dir: Path | None) -> dict:
    os.chdir(ROOT)

    import etl.transform as transform
    import analysis.model as model
    import vis.visualizations as viz

    with tempfile.TemporaryDirectory(prefix="courtpipe-fixture-") as tmp:
        tmp_path = Path(tmp)
        processed = tmp_path / "processed.csv"
        review = tmp_path / "review_queue.csv"
        eval_dir = tmp_path / "model-eval"
        chart_dir = tmp_path / "charts"
        eval_dir.mkdir()
        chart_dir.mkdir()

        def _refuse_fetch(url: str) -> str:
            raise RuntimeError(f"fixture run tried to fetch {url}")

        transform._fetch_plain_text_slice = _refuse_fetch
        transform.REVIEW_PATH = str(review)
        df = transform.transform_data(raw_path=str(FIXTURE), out_path=str(processed))

        for _, row in df.iterrows():
            expected = _needs_review(str(row["outcome_label_fine"]), float(row["outcome_confidence"]))
            if int(row["needs_review"]) != expected:
                raise RuntimeError("needs_review drifted from the transform rule")

        model.EVAL_DIR = str(eval_dir)
        model.EVAL_SUMMARY = str(eval_dir / "evaluation_summary.json")
        model.run_models(df, label="coarse")
        model.run_models(df, label="fine")

        viz.OUTDIR = str(chart_dir)
        viz.EVAL_DIR = str(eval_dir)
        viz.generate_visualizations(df)

        summary_path = eval_dir / "evaluation_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))

        label_counts = {
            str(k): int(v) for k, v in df["outcome_label_fine"].value_counts().sort_index().items()
        }
        coarse_counts = {
            str(int(k)): int(v) for k, v in df["outcome_code"].value_counts().sort_index().items()
        }
        conf = df["outcome_confidence"].astype(float)
        payload = {
            "n_rows": int(len(df)),
            "fixture": str(FIXTURE.relative_to(ROOT)),
            "label_counts": label_counts,
            "coarse_counts": coarse_counts,
            "needs_review": int((df["needs_review"] == 1).sum()),
            "auto_pass": int((df["needs_review"] == 0).sum()),
            "confidence_min": float(conf.min()),
            "confidence_p50": float(conf.quantile(0.50)),
            "confidence_p90": float(conf.quantile(0.90)),
            "confidence_max": float(conf.max()),
            "evaluation_summary": summary,
        }

        if out_dir is not None:
            dest = out_dir if out_dir.is_absolute() else ROOT / out_dir
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            (dest / "summary.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            shutil.copy(summary_path, dest / "evaluation_summary.json")
            for name in (
                "outcome_distribution.png",
                "review_queue_overview.png",
                "model_comparison_f1_macro_coarse.png",
            ):
                shutil.copy(chart_dir / name, dest / name)

        return payload


def _print(payload: dict) -> None:
    print(f"rows: {payload['n_rows']}")
    print("fine labels:", json.dumps(payload["label_counts"], sort_keys=True))
    print("coarse codes:", json.dumps(payload["coarse_counts"], sort_keys=True))
    print(
        "review: {needs} needs_review / {auto} auto_pass".format(
            needs=payload["needs_review"], auto=payload["auto_pass"]
        )
    )
    print(
        "confidence min/p50/p90/max: {min:.2f} / {p50:.2f} / {p90:.2f} / {max:.2f}".format(
            min=payload["confidence_min"],
            p50=payload["confidence_p50"],
            p90=payload["confidence_p90"],
            max=payload["confidence_max"],
        )
    )
    for key in sorted(payload["evaluation_summary"]):
        entry = payload["evaluation_summary"][key]
        if entry.get("status") != "ok":
            print(key, entry.get("status"), entry.get("reason"))
            continue
        print(
            "{key}: acc={acc:.4f} f1_macro={macro:.4f} f1_weighted={weighted:.4f} n_test={n}".format(
                key=key,
                acc=float(entry["accuracy"]),
                macro=float(entry["f1_macro"]),
                weighted=float(entry["f1_weighted"]),
                n=entry.get("n_test"),
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Label the synthetic fixture and write real metrics.")
    parser.add_argument("--out", type=Path, default=None, help="Directory for charts and JSON")
    args = parser.parse_args()
    payload = run(args.out)
    _print(payload)


if __name__ == "__main__":
    main()
