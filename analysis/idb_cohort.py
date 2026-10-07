"""Filing-time cohort for the FJC civil Integrated Database settlement track.

Rules follow docs/idb/SPEC.md. Nothing in this module calls the network.
"""

from __future__ import annotations

import csv
import hashlib
import re
import zipfile
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

NOS_CODES = {"160", "410", "850"}
ALLOWED_ORIGINS = {"1", "2", "3", "5", "6", "13"}
CODEBOOK_DISP = set(range(0, 21)) | {-8}
JUDGMENT_DISPS = {4, 6, 7, 8, 9, 15, 17}
NOT_MERITS_DISPS = {0, 1, 10, 11, 16, 18, 19, 20}

TRAIN_START = date(2009, 10, 1)
TRAIN_END = date(2017, 10, 1)  # exclusive
TEST_END = date(2021, 9, 30)

HEADER_REQUIRED = [
    "CIRCUIT",
    "DISTRICT",
    "OFFICE",
    "DOCKET",
    "ORIGIN",
    "FILEDATE",
    "JURIS",
    "NOS",
    "RESIDENC",
    "JURY",
    "CLASSACT",
    "DEMANDED",
    "DEF",
    "PLT",
    "DISP",
    "JUDGMENT",
    "PROCPROG",
    "TERMDATE",
    "STATUSCD",
]

LOAD_COLUMNS = [
    "CIRCUIT",
    "DISTRICT",
    "OFFICE",
    "DOCKET",
    "ORIGIN",
    "FILEDATE",
    "JURIS",
    "NOS",
    "RESIDENC",
    "JURY",
    "CLASSACT",
    "DEMANDED",
    "COUNTY",
    "ARBIT",
    "MDLDOCK",
    "PLT",
    "DEF",
    "TERMDATE",
    "DISP",
    "JUDGMENT",
    "PROSE",
    "IFP",
    "STATUSCD",
]

# Raw fields that must never enter the feature matrix.
FORBIDDEN_FEATURE_FIELDS = [
    "DISP",
    "JUDGMENT",
    "PROCPROG",
    "TERMDATE",
    "NOJ",
    "AMTREC",
    "TRCLACT",
    "MDLDOCK",
    "STATUSCD",
    "DEF",
    "PLT",
    "DEMANDED",
]

CATEGORICAL_FEATURES = [
    "CIRCUIT",
    "DISTRICT",
    "OFFICE",
    "ORIGIN",
    "file_month",
    "JURIS",
    "NOS",
    "RESIDENC",
    "JURY",
    "CLASSACT",
    "demanded_bin",
    "COUNTY",
    "ARBIT",
    "PROSE",
    "IFP",
]
NUMERIC_FEATURES = ["demanded_missing", "file_year"]
FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERIC_FEATURES

SIX_WAY_LABELS = [
    "settled_out_of_court",
    "voluntary_dismissal",
    "consent_judgment",
    "judgment_for_plaintiff",
    "judgment_for_defendant",
    "other",
]

_GOV_PHRASES = (
    "UNITED STATES",
    "STATE OF",
    "COMMONWEALTH",
    "CITY OF",
    "COUNTY OF",
    "DEPARTMENT",
    "SECRETARY",
    "COMMISSION",
    "DISTRICT ATTORNEY",
)
_SUFFIX_TOKENS = {
    "INC",
    "INCORPORATED",
    "CORP",
    "CORPORATION",
    "LLC",
    "LLP",
    "LP",
    "LTD",
    "LIMITED",
    "PLC",
    "BANCORP",
    "HOLDINGS",
    "COMPANY",
}
_SUFFIX_SEQUENCES = (
    ("L", "L", "C"),
    ("L", "L", "P"),
    ("P", "L", "C"),
    ("NATIONAL", "ASSOCIATION"),
    ("L", "P"),
    ("N", "A"),
)
_PUNCT = re.compile(r"[^A-Z0-9]+")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def zip_member_date(path: Path, member: str = "cv88on.txt") -> date | None:
    if path.suffix.lower() != ".zip":
        return None
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(member)
    return datetime(*info.date_time).date()


def normalize_party(value: object) -> str:
    text = "" if value is None else str(value)
    return " ".join(_PUNCT.sub(" ", text.upper()).split())


def _has_suffix(tokens: list[str]) -> bool:
    if any(token in _SUFFIX_TOKENS for token in tokens):
        return True
    for seq in _SUFFIX_SEQUENCES:
        width = len(seq)
        for start in range(0, len(tokens) - width + 1):
            if tuple(tokens[start : start + width]) == seq:
                return True
    return False


def _is_government(normalized: str, tokens: list[str]) -> bool:
    if any(phrase in normalized for phrase in _GOV_PHRASES):
        return True
    for index in range(len(tokens) - 1):
        if tokens[index] == "U" and tokens[index + 1] == "S":
            return True
    return False


def _residence_corporate(juris: object, residenc: object) -> bool:
    if _numeric_code(juris) != "4":
        return False
    code = "" if residenc is None else str(residenc).strip()
    return len(code) >= 2 and code[1] in {"4", "5"} and code[0].isdigit()


def classify_defendant(def_raw: object, juris: object, residenc: object) -> str:
    """Return name_suffix, corporate_via_residence, government, non_corporate, or corporate_unknown."""
    normalized = normalize_party(def_raw)
    tokens = normalized.split() if normalized else []
    if normalized and _is_government(normalized, tokens):
        return "government"
    if normalized and _has_suffix(tokens):
        return "name_suffix"
    if _residence_corporate(juris, residenc):
        return "corporate_via_residence"
    if not normalized:
        return "corporate_unknown"
    return "non_corporate"


def _numeric_code(value: object) -> str:
    text = "" if value is None else str(value).strip()
    if text == "" or text.lower() in {"nan", "none"}:
        return ""
    try:
        number = float(text)
    except ValueError:
        return text.upper()
    if not number.is_integer():
        return text
    return str(int(number))


def _disp_code(value: object) -> int | None:
    text = _numeric_code(value)
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _judgment_code(value: object) -> int | None:
    text = _numeric_code(value)
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def map_label(disp: int | None, judgment: int | None) -> str:
    """One label, first match in the spec table. Unknown codes are unmapped."""
    if disp is None or disp == -8 or disp in NOT_MERITS_DISPS:
        return "not_a_merits_ending"
    if disp == 13:
        return "settled_out_of_court"
    if disp == 12:
        return "voluntary_dismissal"
    if disp == 5:
        return "consent_judgment"
    if disp in JUDGMENT_DISPS:
        if judgment == 1:
            return "judgment_for_plaintiff"
        if judgment == 2:
            return "judgment_for_defendant"
        if judgment is None or judgment in {0, 3, 4, -8}:
            return "judgment_other"
        return "unmapped"
    if disp in {2, 3, 14}:
        return "other_dismissal"
    return "unmapped"


def six_way(label: str) -> str | None:
    if label in {"judgment_other", "other_dismissal"}:
        return "other"
    if label in SIX_WAY_LABELS:
        return label
    return None


def demanded_bin(raw: object) -> str:
    text = "" if raw is None else str(raw).strip()
    if text == "" or text == "-8":
        return "missing"
    try:
        value = int(float(text))
    except ValueError:
        return "missing"
    if value < 0:
        return "missing"
    if value == 0:
        return "zero"
    if value == 1:
        return "one"
    if value >= 9999:
        return "topcoded"
    if value < 50:
        return "under_50"
    if value < 500:
        return "50_to_499"
    if value < 5000:
        return "500_to_4999"
    return "5000_to_9998"


def _cat_level(value: object, *, keep_neg8: bool = False) -> str:
    text = "" if value is None else str(value).strip()
    if text.lower() in {"", "nan", "none"}:
        return "missing"
    if text == "-8" and not keep_neg8:
        return "missing"
    return text


def _district_code(value: object) -> str:
    text = "" if value is None else str(value).strip().upper()
    if text.isdigit():
        return text.zfill(2)
    return text


def fiscal_year(day: date) -> int:
    return day.year + 1 if day.month >= 10 else day.year


def file_year_feature(year: int) -> float:
    """Single numeric trend. Test years extrapolate; they are not unseen dummies."""
    return (float(year) - 2015.0) / 5.0


def resolve_table_path(idb_path: Path) -> tuple[Path, date | None]:
    """Return a delimited text path and, for a zip, the member timestamp."""
    idb_path = Path(idb_path)
    if not idb_path.exists():
        raise FileNotFoundError(f"IDB file not found: {idb_path}")
    if idb_path.suffix.lower() == ".zip":
        as_of = zip_member_date(idb_path)
        text_path = idb_path.with_name("cv88on.txt")
        if not text_path.exists() or text_path.stat().st_size < 1000:
            with zipfile.ZipFile(idb_path) as archive:
                archive.extract("cv88on.txt", idb_path.parent)
        return text_path, as_of
    return idb_path, None


def _separator(path: Path) -> str:
    with path.open("r", encoding="latin-1", newline="") as handle:
        header = handle.readline()
    if "\t" in header:
        return "\t"
    return ","


def read_header(path: Path) -> list[str]:
    sep = _separator(path)
    with path.open("r", encoding="latin-1", newline="") as handle:
        row = next(csv.reader(handle, delimiter=sep))
    return [cell.strip() for cell in row]


def load_candidate_rows(path: Path, log=None) -> pd.DataFrame:
    """Rows whose nature of suit is 160, 410, or 850. Other suits are not loaded."""
    header = read_header(path)
    missing = [name for name in HEADER_REQUIRED if name not in header]
    if missing:
        raise ValueError(f"IDB file is missing required columns: {', '.join(missing)}")
    usecols = [name for name in LOAD_COLUMNS if name in header]
    sep = _separator(path)
    frames: list[pd.DataFrame] = []
    seen = 0
    kept = 0
    outside_window = 0
    reader = pd.read_csv(
        path,
        sep=sep,
        dtype=str,
        usecols=usecols,
        chunksize=250_000,
        encoding="latin-1",
        quoting=csv.QUOTE_NONE,
        na_filter=False,
        keep_default_na=False,
        low_memory=False,
        on_bad_lines="warn",
    )
    for chunk in reader:
        seen += len(chunk)
        nos = chunk["NOS"].map(_numeric_code).str.zfill(3)
        chunk = chunk.loc[nos.isin(NOS_CODES)].copy()
        if not chunk.empty:
            chunk["NOS"] = nos.loc[chunk.index]
            filed = pd.to_datetime(chunk["FILEDATE"], format="%m/%d/%Y", errors="coerce")
            in_window = filed.between("2009-10-01", "2021-09-30")
            outside_window += int((~in_window).sum())
            chunk = chunk.loc[in_window]
            if not chunk.empty:
                frames.append(chunk)
                kept += len(chunk)
        if log and seen % 1_000_000 < 250_000:
            log(f"scanned {seen:,} rows, kept {kept:,} with NOS 160/410/850")
    if not frames:
        raise ValueError("No rows with nature of suit 160, 410, or 850.")
    out = pd.concat(frames, ignore_index=True)
    if log:
        log(
            f"loaded {len(out):,} NOS 160/410/850 rows inside FY2010-2021 "
            f"from {seen:,} scanned; {outside_window:,} of those suits were outside the window"
        )
    out.attrs["rows_scanned"] = seen
    out.attrs["nos_outside_window"] = outside_window
    return out


def prepare_rows(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Type the candidate rows and attach labels. Does not yet apply the cohort filters."""
    frame = raw.copy()
    counts: dict[str, int] = {"nos_rows": int(len(frame))}

    frame["disp"] = frame["DISP"].map(_disp_code)
    unexpected = sorted({int(v) for v in frame["disp"].dropna().unique() if int(v) not in CODEBOOK_DISP})
    counts["unexpected_disp_rows"] = int(frame["disp"].isin(unexpected).sum()) if unexpected else 0
    counts["unexpected_disp_codes"] = unexpected

    frame["judgment"] = frame["JUDGMENT"].map(_judgment_code)
    frame["label"] = [
        map_label(None if pd.isna(disp) else int(disp), None if pd.isna(judg) else int(judg))
        for disp, judg in zip(frame["disp"], frame["judgment"])
    ]
    frame["y_settle"] = (frame["label"] == "settled_out_of_court").astype(int)
    frame["y_broad"] = frame["disp"].isin([5, 12, 13]).astype(int)
    frame["label6"] = frame["label"].map(lambda value: six_way(value) or "")

    frame["file_date"] = pd.to_datetime(frame["FILEDATE"], format="%m/%d/%Y", errors="coerce")
    frame["term_date"] = pd.to_datetime(frame["TERMDATE"], format="%m/%d/%Y", errors="coerce")
    frame["DISTRICT"] = frame["DISTRICT"].map(_district_code)
    frame["OFFICE"] = frame["OFFICE"].map(lambda value: str(value).strip())
    frame["DOCKET"] = frame["DOCKET"].map(lambda value: str(value).strip())
    frame["ORIGIN"] = frame["ORIGIN"].map(_numeric_code)
    frame["JURIS"] = frame["JURIS"].map(_numeric_code)
    frame["CIRCUIT"] = frame["CIRCUIT"].map(_numeric_code)
    frame["NOS"] = frame["NOS"].map(lambda value: _numeric_code(value).zfill(3) if _numeric_code(value).isdigit() else _numeric_code(value))
    frame["case_key"] = frame["DISTRICT"] + "|" + frame["OFFICE"] + "|" + frame["DOCKET"]
    frame["def_norm"] = frame["DEF"].map(normalize_party)
    frame["corporate_rule"] = [
        classify_defendant(defn, juris, resid)
        for defn, juris, resid in zip(frame["DEF"], frame["JURIS"], frame["RESIDENC"])
    ]
    frame["STATUSCD"] = frame["STATUSCD"].map(lambda value: str(value).strip().upper())
    frame["MDLDOCK"] = frame["MDLDOCK"].map(lambda value: str(value).strip()) if "MDLDOCK" in frame.columns else ""
    return frame, counts


def build_cohort(frame: pd.DataFrame, counts: dict) -> tuple[pd.DataFrame, dict]:
    """Apply the approved cohort filters and drop duplicate case keys."""
    work = frame
    dated = work["file_date"].notna()
    counts["bad_filedate"] = int((~dated).sum())
    work = work.loc[dated]

    in_window = (work["file_date"].dt.date >= TRAIN_START) & (work["file_date"].dt.date <= TEST_END)
    counts["outside_fy2010_2021"] = int((~in_window).sum())
    work = work.loc[in_window]

    terminated = work["STATUSCD"].eq("L")
    counts["not_terminated"] = int((~terminated).sum())
    counts["pending_status_s"] = int(work["STATUSCD"].eq("S").sum())
    work = work.loc[terminated]

    origin_ok = work["ORIGIN"].isin(ALLOWED_ORIGINS)
    counts["origin_excluded"] = int((~origin_ok).sum())
    work = work.loc[origin_ok]

    corporate = work["corporate_rule"].isin(["name_suffix", "corporate_via_residence"])
    counts["not_corporate"] = int((~corporate).sum())
    for rule, size in work["corporate_rule"].value_counts().items():
        counts[f"party_{rule}"] = int(size)
    work = work.loc[corporate]

    in_cohort = ~work["label"].isin(["not_a_merits_ending", "unmapped"])
    counts["not_a_merits_ending"] = int(work["label"].eq("not_a_merits_ending").sum())
    counts["unmapped_label"] = int(work["label"].eq("unmapped").sum())
    work = work.loc[in_cohort].copy()

    work = work.sort_values(["case_key", "file_date", "term_date"], na_position="last")
    duplicate = work["case_key"].duplicated(keep="first")
    counts["duplicate_rows_dropped"] = int(duplicate.sum())
    work = work.loc[~duplicate].copy()
    counts["cohort_rows"] = int(len(work))

    work["fiscal_year"] = work["file_date"].dt.date.map(fiscal_year)
    work["file_month"] = work["file_date"].dt.month.map(lambda month: f"{int(month):02d}")
    work["file_year"] = work["file_date"].dt.year.map(file_year_feature)
    work["demanded_bin"] = work["DEMANDED"].map(demanded_bin)
    work["demanded_missing"] = (work["demanded_bin"] == "missing").astype(int)
    for column in ("RESIDENC", "JURY", "CLASSACT", "COUNTY", "ARBIT", "PROSE"):
        if column not in work.columns:
            work[column] = "missing"
        work[column] = work[column].map(_cat_level)
    if "IFP" not in work.columns:
        work["IFP"] = "missing"
    work["IFP"] = work["IFP"].map(lambda value: _cat_level(value, keep_neg8=True))
    work["CIRCUIT"] = work["CIRCUIT"].map(lambda value: value if value else "missing")
    work["OFFICE"] = work["OFFICE"].map(lambda value: value if value else "missing")
    return work, counts


def feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Filing-time columns only. Forbidden raw fields are dropped if present."""
    out = pd.DataFrame(index=frame.index)
    for column in CATEGORICAL_FEATURES:
        if column in {"file_month", "demanded_bin"}:
            out[column] = frame[column].astype(str)
        elif column in frame.columns:
            out[column] = frame[column].astype(str)
        else:
            out[column] = "missing"
    for column in NUMERIC_FEATURES:
        out[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    leaked = [name for name in FORBIDDEN_FEATURE_FIELDS if name in out.columns]
    if leaked:
        raise AssertionError(f"forbidden fields reached the feature matrix: {leaked}")
    if list(out.columns) != FEATURE_COLUMNS:
        raise AssertionError(f"feature columns {list(out.columns)} != {FEATURE_COLUMNS}")
    return out


def assign_splits(cohort: pd.DataFrame, as_of: date) -> tuple[pd.DataFrame, dict]:
    """Train FY2010–2017, test FY2018–2021, then censoring, MDL groups, and party names."""
    info: dict = {"as_of": as_of.isoformat()}
    work = cohort.copy()
    file_days = work["file_date"].dt.date
    work["split"] = np.where(file_days < TRAIN_END, "train", "test")
    info["train_before_rules"] = int((work["split"] == "train").sum())
    info["test_before_rules"] = int((work["split"] == "test").sum())
    if info["train_before_rules"] == 0 or info["test_before_rules"] == 0:
        raise ValueError("Training or test window is empty after cohort filters.")

    train = work["split"].eq("train")
    duration = (work.loc[train, "term_date"] - work.loc[train, "file_date"]).dt.days
    usable = duration[(duration.notna()) & (duration >= 0)]
    info["train_duration_rows"] = int(usable.shape[0])
    info["train_negative_or_missing_duration"] = int(train.sum() - usable.shape[0])
    if usable.empty:
        raise ValueError("Training rows have no usable filing-to-termination durations.")
    p95 = float(np.percentile(usable.to_numpy(), 95))
    info["train_duration_p95_days"] = p95

    test = work["split"].eq("test")
    horizon = work["file_date"] + pd.to_timedelta(p95, unit="D")
    censored = test & (horizon.dt.date > as_of)
    info["test_censored"] = int(censored.sum())
    work = work.loc[~censored].copy()

    mdl = work["MDLDOCK"].astype(str).str.strip()
    mdl_missing = mdl.isin(["", "-8", "nan", "None"])
    info["mdl_rows"] = int((~mdl_missing).sum())
    forced = 0
    spanning: list = []
    if (~mdl_missing).any():
        for key, part in work.loc[~mdl_missing].groupby(mdl.loc[~mdl_missing], sort=False):
            if set(part["split"]) == {"train", "test"}:
                spanning.append(key)
        if spanning:
            mask = mdl.isin(spanning) & work["split"].eq("test")
            forced = int(mask.sum())
            work.loc[mask, "split"] = "train"
    info["mdl_test_rows_moved_to_train"] = forced
    info["mdl_groups_spanning_split"] = len(spanning)

    train_names = set(work.loc[work["split"].eq("train") & work["def_norm"].ne(""), "def_norm"])
    leaked = work["split"].eq("test") & work["def_norm"].ne("") & work["def_norm"].isin(train_names)
    info["party_leakage_dropped"] = int(leaked.sum())
    info["party_leakage_dropped_settled"] = int(work.loc[leaked, "y_settle"].sum()) if leaked.any() else 0
    blank_test = work["split"].eq("test") & work["def_norm"].eq("")
    info["test_blank_def_kept"] = int(blank_test.sum())
    dropped = work.loc[leaked].copy()
    work = work.loc[~leaked].copy()

    info["train_rows"] = int(work["split"].eq("train").sum())
    info["test_rows"] = int(work["split"].eq("test").sum())
    if info["train_rows"] == 0 or info["test_rows"] == 0:
        raise ValueError("Training or test window is empty after censoring and party rules.")

    dup_train = int(work.loc[work["split"].eq("train"), "case_key"].duplicated().sum())
    dup_test = int(work.loc[work["split"].eq("test"), "case_key"].duplicated().sum())
    if dup_train or dup_test:
        raise ValueError(f"Duplicate case keys inside a split: train {dup_train}, test {dup_test}.")
    return work, info, dropped


def draw_audit_sample(cohort: pd.DataFrame, seed: int = 20261007) -> tuple[pd.DataFrame, dict]:
    """150-row hand-audit draw. Short strata are taken in full and the gap is recorded."""
    rng = np.random.default_rng(seed)
    ordered = cohort.sort_values(["DISTRICT", "OFFICE", "DOCKET", "FILEDATE"]).reset_index(drop=True)
    pieces: list[pd.DataFrame] = []
    shortfalls: dict[str, int] = {}

    def take(frame: pd.DataFrame, n: int) -> pd.DataFrame:
        if frame.empty or n <= 0:
            return frame.iloc[0:0]
        if len(frame) <= n:
            return frame
        chosen = np.sort(rng.choice(len(frame), size=n, replace=False))
        return frame.iloc[chosen]

    def stratified_disp13(frame: pd.DataFrame, n: int) -> pd.DataFrame:
        present = [nos for nos in ("160", "410", "850") if (frame["NOS"] == nos).any()]
        if not present:
            return frame.iloc[0:0]
        targets = {nos: 0 for nos in present}
        left = n
        while left > 0:
            moved = False
            for nos in present:
                spare = int((frame["NOS"] == nos).sum()) - targets[nos]
                if spare > 0 and left > 0:
                    targets[nos] += 1
                    left -= 1
                    moved = True
            if not moved:
                break
        parts = [take(frame.loc[frame["NOS"] == nos], targets[nos]) for nos in present]
        return pd.concat(parts, ignore_index=True) if parts else frame.iloc[0:0]

    plan = [
        ("disp_13", stratified_disp13(ordered.loc[ordered["disp"] == 13], 50), 50),
        ("disp_12", ordered.loc[ordered["disp"] == 12], 25),
        ("disp_5", ordered.loc[ordered["disp"] == 5], 25),
        (
            "judgment",
            ordered.loc[
                ordered["label"].isin(
                    ["judgment_for_plaintiff", "judgment_for_defendant", "judgment_other"]
                )
            ],
            25,
        ),
        ("other_dismissal", ordered.loc[ordered["label"].eq("other_dismissal")], 25),
    ]
    for name, pool, quota in plan:
        if name == "disp_13":
            drawn = pool
        else:
            drawn = take(pool, quota)
        shortfalls[name] = int(quota - len(drawn))
        if not drawn.empty:
            drawn = drawn.copy()
            drawn["stratum"] = name
            pieces.append(drawn)

    sample = pd.concat(pieces, ignore_index=True) if pieces else ordered.iloc[0:0]
    keep = [
        "stratum",
        "DISTRICT",
        "OFFICE",
        "DOCKET",
        "CIRCUIT",
        "FILEDATE",
        "TERMDATE",
        "NOS",
        "ORIGIN",
        "JURIS",
        "RESIDENC",
        "DEF",
        "PLT",
        "DISP",
        "JUDGMENT",
        "label",
        "y_settle",
        "corporate_rule",
        "case_key",
    ]
    sample = sample[keep].copy()
    sample.insert(0, "audit_id", np.arange(1, len(sample) + 1))
    sample["gold_label"] = ""
    sample["gold_notes"] = ""
    sample["auditor"] = ""
    meta = {
        "seed": seed,
        "rows": int(len(sample)),
        "shortfalls": shortfalls,
        "status": "pending",
    }
    return sample, meta
