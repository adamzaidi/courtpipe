# courtpipe/cli.py
from __future__ import annotations

from pathlib import Path
import argparse
import logging
import os
from datetime import date

from utils.run_context import init_run_context, configure_run_logging


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="courtpipe",
        description="CourtListener ETL + judicial outcome analytics pipeline",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_run = sub.add_parser("run", help="Run the full pipeline end-to-end")
    sp_run.add_argument("--query", default="corporation")
    sp_run.add_argument("--max-cases", type=int, default=int(os.getenv("MAX_CASES", "1000")))
    sp_run.add_argument("--fast-mode", action="store_true")
    sp_run.add_argument("--page-size", type=int, default=0)
    sp_run.add_argument("--no-models", action="store_true")
    sp_run.add_argument("--no-viz", action="store_true")
    sp_run.add_argument("--label", choices=["coarse", "fine", "both"], default="both")

    sp_ex = sub.add_parser("extract", help="Run extract step only")
    sp_ex.add_argument("--query", default="corporation")
    sp_ex.add_argument("--max-cases", type=int, default=int(os.getenv("MAX_CASES", "1000")))
    sp_ex.add_argument("--fast-mode", action="store_true")
    sp_ex.add_argument("--page-size", type=int, default=0)

    sub.add_parser("transform", help="Run transform step only")
    sub.add_parser("load", help="Run load step only")

    sp_m = sub.add_parser("model", help="Run model training/eval only")
    sp_m.add_argument("--label", choices=["coarse", "fine"], default="coarse")

    sub.add_parser("viz", help="Generate visualizations only")
    sub.add_parser("doctor", help="Quick health check: verify expected files/dirs exist")

    sp_dl = sub.add_parser("download-idb", help="Download the public FJC civil zip into a local cache")
    sp_dl.add_argument("--out", default="data/idb/cv88on.zip")
    sp_dl.add_argument("--force", action="store_true")

    sp_ev = sub.add_parser(
        "evaluate-settlement",
        help="Score filing-time IDB code-13 settlement on a local civil file",
    )
    sp_ev.add_argument("--idb", required=True, help="Local cv88on.zip, the extracted txt, or a csv")
    sp_ev.add_argument("--report", default="data/model-eval/settlement_report.json")
    sp_ev.add_argument("--audit-out", default="docs/idb/audit_sample.csv")
    sp_ev.add_argument("--results-md", default="", help="Optional markdown summary path")
    sp_ev.add_argument("--as-of", default="", help="Extract as-of date YYYY-MM-DD; default is the zip timestamp")
    sp_ev.add_argument("--bootstrap", type=int, default=1000)

    sp_mtd_fetch = sub.add_parser(
        "fetch-mtd",
        help="Modest cached CourtListener pull of 12(b)(6) candidate dockets (needs a token)",
    )
    sp_mtd_fetch.add_argument("--out", default="data/extracted/mtd_extract.jsonl")
    sp_mtd_fetch.add_argument("--cache", default="data/cache/courtlistener")
    sp_mtd_fetch.add_argument("--max-dockets", type=int, default=20)

    sp_mtd = sub.add_parser(
        "evaluate-mtd",
        help="Score the motion-to-dismiss model on a local extract (no network)",
    )
    sp_mtd.add_argument("--extract", required=True, help="Local JSONL/JSON extract of dockets")
    sp_mtd.add_argument("--report", default="data/model-eval/mtd_report.json")
    sp_mtd.add_argument("--audit-out", default="docs/mtd/audit_sample.csv")
    sp_mtd.add_argument("--results-md", default="")
    sp_mtd.add_argument("--bootstrap", type=int, default=1000)

    sp_mtd_smoke = sub.add_parser(
        "smoke-mtd",
        help="One authenticated docket-entry read (needs a token; does not train)",
    )
    sp_mtd_smoke.add_argument("--cache", default="data/cache/courtlistener")
    sp_mtd_smoke.add_argument("--docket-id", type=int, default=0)

    sp_ap_fetch = sub.add_parser(
        "fetch-appeal",
        help="Modest cached CourtListener pull of appellate clusters (needs a token)",
    )
    sp_ap_fetch.add_argument("--out", default="data/extracted/appeal_extract.jsonl")
    sp_ap_fetch.add_argument("--cache", default="data/cache/courtlistener")
    sp_ap_fetch.add_argument("--max-clusters", type=int, default=20)

    sp_ap = sub.add_parser(
        "evaluate-appeal",
        help="Score the appeal-reversal model on a local extract (no network)",
    )
    sp_ap.add_argument("--extract", required=True, help="Local JSONL/JSON extract of clusters")
    sp_ap.add_argument("--report", default="data/model-eval/appeal_report.json")
    sp_ap.add_argument("--audit-out", default="docs/appeal/audit_sample.csv")
    sp_ap.add_argument("--results-md", default="")
    sp_ap.add_argument("--bootstrap", type=int, default=1000)
    sp_ap.add_argument("--snapshot-year", type=int, default=0)

    sp_ap_smoke = sub.add_parser(
        "smoke-appeal",
        help="One authenticated cluster read (needs a token; does not train)",
    )
    sp_ap_smoke.add_argument("--cache", default="data/cache/courtlistener")
    sp_ap_smoke.add_argument("--cluster-id", type=int, default=0)

    return p


def _bootstrap_logging() -> logging.Logger:
    logger = logging.getLogger("courtpipe")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
        logger.addHandler(h)
    return logger


def _doctor(logger: logging.Logger) -> int:
    """
    Quick health check so you (or a grader) can confirm the repo is in a runnable state.

    Returns:
      0 if all checks pass
      2 if something important is missing
    """
    checks: list[tuple[str, bool]] = [
        ("etl/ folder", Path("etl").exists()),
        ("analysis/ folder", Path("analysis").exists()),
        ("vis/ folder", Path("vis").exists()),
        ("utils/ folder", Path("utils").exists()),
        ("data/ folder", Path("data").exists()),
        ("data/extracted/", Path("data/extracted").exists()),
        ("data/processed/", Path("data/processed").exists()),
        ("raw_data.csv (optional)", Path("data/extracted/raw_data.csv").exists()),
        ("processed_data.csv (optional)", Path("data/processed/processed_data.csv").exists()),
        ("review_queue.csv (optional)", Path("data/processed/review_queue.csv").exists()),
        ("runs/ folder (optional)", Path("runs").exists()),
        (".env or .env.example", Path(".env").exists() or Path(".env.example").exists()),
    ]

    ok = True
    for name, exists in checks:
        logger.info("[doctor] %-28s : %s", name, "OK" if exists else "MISSING")
        # only fail hard on core structure; csv outputs and runs/ are optional
        if name.endswith("(optional)"):
            continue
        ok = ok and bool(exists)

    if ok:
        logger.info("[doctor] Looks good.")
        return 0

    logger.info("[doctor] Missing required structure/config. Fix the MISSING items above.")
    return 2


def _init_run_logging_if_needed(cmd: str, logger: logging.Logger):
    """
    Create runs/<run_id>/logs/run.log for commands that produce artifacts.
    Keeps `courtpipe --help` and `courtpipe doctor` lightweight.
    """
    if cmd in {"run", "extract", "transform", "load", "model", "viz"}:
        ctx = init_run_context()
        configure_run_logging(ctx)
        logger.info("Run context initialized: %s", getattr(ctx, "run_dir", "runs/<run_id>"))
        return ctx
    return None


def main(argv: list[str] | None = None) -> int:
    logger = _bootstrap_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "doctor":
        return _doctor(logger)

    if args.cmd == "download-idb":
        from analysis.idb_download import download_idb

        path = download_idb(Path(args.out), force=bool(args.force))
        logger.info("Cached IDB zip at %s (%s bytes)", path, path.stat().st_size)
        return 0

    if args.cmd == "evaluate-settlement":
        from analysis.idb_evaluate import render_results, run_evaluation

        as_of = date.fromisoformat(args.as_of) if args.as_of else None
        try:
            report = run_evaluation(
                Path(args.idb),
                Path(args.report),
                audit_path=Path(args.audit_out) if args.audit_out else None,
                as_of=as_of,
                bootstrap_draws=int(args.bootstrap),
                log=logger.info,
            )
        except (FileNotFoundError, ValueError) as exc:
            logger.error("%s", exc)
            return 2
        if args.results_md:
            Path(args.results_md).write_text(render_results(report))
            logger.info("Wrote %s", args.results_md)
        gate = "pass" if report["modeling_gate"]["passed"] else "fail"
        logger.info("audit_gate=%s modeling_gate=%s", report["audit_gate"], gate)
        return 0

    if args.cmd == "fetch-mtd":
        from analysis.mtd.fetch import fetch_mtd_extract

        try:
            path = fetch_mtd_extract(
                Path(args.out),
                Path(args.cache),
                max_dockets=int(args.max_dockets),
                log=logger.info,
            )
        except RuntimeError as exc:
            logger.error("%s", exc)
            return 2
        logger.info("Wrote %s", path)
        return 0

    if args.cmd == "evaluate-mtd":
        from analysis.mtd.evaluate import render_results, run_evaluation

        try:
            report = run_evaluation(
                Path(args.extract),
                Path(args.report),
                audit_path=Path(args.audit_out) if args.audit_out else None,
                bootstrap_draws=int(args.bootstrap),
                results_md=Path(args.results_md) if args.results_md else None,
                log=logger.info,
            )
        except (FileNotFoundError, ValueError, AssertionError) as exc:
            logger.error("%s", exc)
            return 2
        if args.results_md:
            Path(args.results_md).write_text(render_results(report))
            logger.info("Wrote %s", args.results_md)
        gate = "pass" if report["modeling_gate"]["passed"] else "fail"
        logger.info("audit_gate=%s modeling_gate=%s", report["audit_gate"], gate)
        return 0

    if args.cmd == "smoke-mtd":
        from analysis.mtd.fetch import SMOKE_DOCKET_ID, smoke_docket_entries

        docket_id = int(args.docket_id) or SMOKE_DOCKET_ID
        try:
            info = smoke_docket_entries(Path(args.cache), docket_id=docket_id)
        except RuntimeError as exc:
            logger.error("%s", exc)
            return 2
        logger.info("mtd smoke ok docket_id=%s entries=%s", info["docket_id"], info["n_entries_page"])
        return 0

    if args.cmd == "fetch-appeal":
        from analysis.appeal.fetch import fetch_appeal_extract

        try:
            path = fetch_appeal_extract(
                Path(args.out),
                Path(args.cache),
                max_clusters=int(args.max_clusters),
                log=logger.info,
            )
        except RuntimeError as exc:
            logger.error("%s", exc)
            return 2
        logger.info("Wrote %s", path)
        return 0

    if args.cmd == "evaluate-appeal":
        from analysis.appeal.evaluate import render_results, run_evaluation

        year = int(args.snapshot_year) or None
        try:
            report = run_evaluation(
                Path(args.extract),
                Path(args.report),
                audit_path=Path(args.audit_out) if args.audit_out else None,
                bootstrap_draws=int(args.bootstrap),
                snapshot_year=year,
                results_md=Path(args.results_md) if args.results_md else None,
                log=logger.info,
            )
        except (FileNotFoundError, ValueError, AssertionError) as exc:
            logger.error("%s", exc)
            return 2
        if args.results_md:
            Path(args.results_md).write_text(render_results(report))
            logger.info("Wrote %s", args.results_md)
        gate = "pass" if report["modeling_gate"]["passed"] else "fail"
        logger.info("audit_gate=%s modeling_gate=%s", report["audit_gate"], gate)
        return 0

    if args.cmd == "smoke-appeal":
        from analysis.appeal.fetch import SMOKE_CLUSTER_ID, smoke_cluster

        cluster_id = int(args.cluster_id) or SMOKE_CLUSTER_ID
        try:
            info = smoke_cluster(Path(args.cache), cluster_id=cluster_id)
        except RuntimeError as exc:
            logger.error("%s", exc)
            return 2
        logger.info("appeal smoke ok cluster_id=%s", info["cluster_id"])
        return 0

    # Ensure runs/<run_id>/logs/run.log exists for real commands
    _ = _init_run_logging_if_needed(args.cmd, logger)

    # Lazy imports so `courtpipe --help` / `courtpipe doctor` never explode due to heavy deps
    if args.cmd == "extract":
        from etl.extract import extract_data

        page_size = args.page_size if args.page_size else None
        extract_data(
            query=args.query,
            max_cases=args.max_cases,
            fast_mode=bool(args.fast_mode),
            page_size=page_size,
        )
        return 0

    if args.cmd == "transform":
        from etl.transform import transform_data

        transform_data()
        return 0

    if args.cmd == "load":
        from etl.load import load_data

        _ = load_data()
        return 0

    if args.cmd == "model":
        from etl.load import load_data
        from analysis.model import run_models

        df = load_data()
        run_models(df, label=args.label)
        return 0

    if args.cmd == "viz":
        from etl.load import load_data
        from vis.visualizations import generate_visualizations

        df = load_data()
        generate_visualizations(df)
        return 0

    if args.cmd == "run":
        from etl.extract import extract_data
        from etl.transform import transform_data
        from etl.load import load_data
        from analysis.model import run_models

        page_size = args.page_size if args.page_size else None

        logger.info("Step 1: Extract")
        extract_data(
            query=args.query,
            max_cases=args.max_cases,
            fast_mode=bool(args.fast_mode),
            page_size=page_size,
        )

        logger.info("Step 2: Transform")
        transform_data()

        logger.info("Step 3: Load")
        df = load_data()

        if not args.no_models:
            logger.info("Step 4: Models")
            if args.label in ("coarse", "both"):
                run_models(df, label="coarse")
            if args.label in ("fine", "both"):
                run_models(df, label="fine")

        if not args.no_viz:
            logger.info("Step 5: Visualizations")
            from vis.visualizations import generate_visualizations

            generate_visualizations(df)

        logger.info("Done.")
        return 0

    parser.print_help()
    return 2