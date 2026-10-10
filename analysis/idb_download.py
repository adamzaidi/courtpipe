"""Download the public FJC civil Integrated Database zip.

The file is cached on disk. It is not committed. This module does not
read or write a CourtListener API key.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

FJC_CIVIL_ZIP_URL = "https://www.fjc.gov/sites/default/files/idb/textfiles/cv88on.zip"
USER_AGENT = "courtpipe-idb-download (local research cache)"


def download_idb(dest: Path, force: bool = False) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0 and not force:
        return dest
    request = urllib.request.Request(FJC_CIVIL_ZIP_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, dest.open("wb") as handle:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            handle.write(block)
    return dest
