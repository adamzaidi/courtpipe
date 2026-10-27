#!/usr/bin/env python3
"""Download the public FJC civil file into a gitignored directory.

    python scripts/download_idb.py --out data/idb/cv88on.zip

The zip is not committed. courtpipe evaluate-settlement reads a local path
and does not download by itself.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from analysis.idb_download import FJC_CIVIL_ZIP_URL, download_idb


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download the public FJC civil IDB zip")
    parser.add_argument("--out", type=Path, default=Path("data/idb/cv88on.zip"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    path = download_idb(args.out, force=args.force)
    print(f"cached {path} ({path.stat().st_size} bytes)")
    print(f"source {FJC_CIVIL_ZIP_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
