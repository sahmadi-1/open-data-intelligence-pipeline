"""Optional real-world DataSF 311 ingestion and quality audit.

Network access occurs only when the fetch command is called explicitly.
Only selected non-free-text fields are requested.

Source: https://data.sf.gov/d/vw6y-z8j6
License: Open Data Commons Public Domain Dedication and License 1.0 (PDDL)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

DATASET_PAGE = "https://data.sf.gov/d/vw6y-z8j6"
DATASET_ID = "vw6y-z8j6"
API_ENDPOINT = f"https://data.sf.gov/resource/{DATASET_ID}.csv"
SOURCE_FIELDS = (
    "service_request_id",
    "requested_datetime",
    "closed_date",
    "service_name",
    "service_subtype",
    "supervisor_district",
)
MAX_ROWS = 10_000
MAX_DOWNLOAD_BYTES = 12_000_000


def make_url(*, start: str = "2024-09-01", end: str = "2024-10-01", limit: int = 5_000) -> str:
    """Build a bounded and deterministic public Socrata SODA2 CSV query.

    The fixed date range avoids introducing sliding-window/recent-data changes.
    The query is intentionally not a representative random sample.
    """
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as exc:
        raise ValueError("start/end must be ISO dates (YYYY-MM-DD)") from exc
    if not first < last or (last - first).days > 366:
        raise ValueError("Require a positive date range of no more than 366 days")
    if isinstance(limit, bool) or not isinstance(limit, int) or not (1 <= limit <= MAX_ROWS):
        raise ValueError(f"limit must be an integer from 1 to {MAX_ROWS}")
    filters = {
        "$select": ",".join(SOURCE_FIELDS),
        "$where": (
            f"requested_datetime >= '{first.isoformat()}T00:00:00' "
            f"AND requested_datetime < '{last.isoformat()}T00:00:00'"
        ),
        "$order": "requested_datetime ASC, service_request_id ASC",
        "$limit": str(limit),
    }
    return f"{API_ENDPOINT}?{urllib.parse.urlencode(filters)}"


def download_csv(destination: Path, *, start: str = "2024-09-01", end: str = "2024-10-01", limit: int = 5_000) -> dict:
    """Explicit, bounded download. Never called automatically by CI or import."""
    url = make_url(start=start, end=end, limit=limit)
    request = urllib.request.Request(url, headers={"User-Agent": "open-data-intelligence-pipeline/0.2"})
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(payload) > MAX_DOWNLOAD_BYTES:
        raise ValueError("API response exceeded the 12 MB safety limit")
    try:
        content = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("API response was not UTF-8 CSV") from exc
    try:
        header = next(csv.reader(content.splitlines()))
    except StopIteration as exc:
        raise ValueError("API response was empty") from exc
    if not set(SOURCE_FIELDS).issubset(header):
        raise ValueError(f"Unexpected response columns: {header}; refusing to write")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".partial")
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, destination)
    finally:
        tmp.unlink(missing_ok=True)
    return {"source": DATASET_PAGE, "output": str(destination), "bytes": len(payload), "requested_limit": limit}


def clean_sf311(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Clean SF311 records without hiding missing closure outcomes.

    Missing closure dates remain in the database but are excluded from
    closure-time summaries, rather than being treated as quick resolutions.
    """
    missing = sorted(set(SOURCE_FIELDS) - set(frame.columns))
    if missing:
        raise ValueError(f"Missing required SF311 columns: {', '.join(missing)}")
    rows = frame.loc[:, list(SOURCE_FIELDS)].copy()
    for field in ("service_request_id", "service_name", "service_subtype", "supervisor_district"):
        rows[field] = rows[field].fillna("").astype(str).str.strip()
    duplicate = rows.duplicated("service_request_id", keep="first")
    duplicates_removed = int(duplicate.sum())
    rows = rows.loc[~duplicate].copy()

    created = pd.to_datetime(rows["requested_datetime"], errors="coerce", format="mixed")
    closed_text = rows["closed_date"].fillna("").astype(str).str.strip()
    closed = pd.to_datetime(closed_text, errors="coerce", format="mixed")
    invalid_closed_date = closed_text.ne("") & closed.isna()
    hours = (closed - created).dt.total_seconds() / 3600
    invalid = (
        rows["service_request_id"].eq("")
        | rows["service_name"].eq("")
        | created.isna()
        | invalid_closed_date
        | (hours < 0)
    )
    invalid_rows_removed = int(invalid.sum())
    valid = rows.loc[~invalid].copy()
    valid_created = created.loc[~invalid]
    valid_closed = closed.loc[~invalid]
    valid_hours = hours.loc[~invalid]
    valid["requested_datetime"] = valid_created.dt.strftime("%Y-%m-%dT%H:%M:%S")
    valid["closed_date"] = valid_closed.dt.strftime("%Y-%m-%dT%H:%M:%S")
    valid["closed_date"] = valid["closed_date"].where(valid_closed.notna(), None)
    valid["resolution_hours"] = valid_hours.where(valid_closed.notna(), None)
    valid["service_subtype"] = valid["service_subtype"].replace("", "Unknown")
    valid["supervisor_district"] = valid["supervisor_district"].replace("", "Unknown")
    valid["source_dataset"] = DATASET_ID

    return valid, {
        "input_rows": int(len(frame)),
        "duplicate_ids_removed": duplicates_removed,
        "invalid_rows_removed": invalid_rows_removed,
        "accepted_rows": int(len(valid)),
        "missing_or_unresolved_closure": int(valid_closed.isna().sum()),
        "closed_with_valid_duration": int(valid_closed.notna().sum()),
        "closed_over_90_days": int((valid_hours > 90 * 24).sum()),
    }


def analyze_csv(source: Path, database: Path, report_file: Path) -> dict:
    """Import cleaned records into SQLite and report on observed closures."""
    source, database, report_file = map(Path, (source, database, report_file))
    data = pd.read_csv(source, dtype=str, keep_default_na=True)
    clean, quality = clean_sf311(data)
    database.parent.mkdir(parents=True, exist_ok=True)
    report_file.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS sf311_requests (
            service_request_id TEXT PRIMARY KEY,
            requested_datetime TEXT NOT NULL,
            closed_date TEXT,
            service_name TEXT NOT NULL,
            service_subtype TEXT NOT NULL,
            supervisor_district TEXT NOT NULL,
            resolution_hours REAL,
            source_dataset TEXT NOT NULL
        )""")
        columns = (
            "service_request_id", "requested_datetime", "closed_date",
            "service_name", "service_subtype", "supervisor_district",
            "resolution_hours", "source_dataset",
        )
        conn.executemany(
            """INSERT INTO sf311_requests (
              service_request_id, requested_datetime, closed_date, service_name,
              service_subtype, supervisor_district, resolution_hours, source_dataset
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(service_request_id) DO UPDATE SET
              requested_datetime=excluded.requested_datetime,
              closed_date=excluded.closed_date,
              service_name=excluded.service_name,
              service_subtype=excluded.service_subtype,
              supervisor_district=excluded.supervisor_district,
              resolution_hours=excluded.resolution_hours,
              source_dataset=excluded.source_dataset""",
            (
                tuple(None if pd.isna(v) else v for v in record)
                for record in clean.loc[:, list(columns)].itertuples(index=False, name=None)
            ),
        )
        stored = conn.execute("SELECT COUNT(*) FROM sf311_requests").fetchone()[0]
        summary = conn.execute("""SELECT service_name, COUNT(*),
            ROUND(AVG(resolution_hours), 2),
            SUM(CASE WHEN resolution_hours IS NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN resolution_hours IS NOT NULL AND resolution_hours <= 168 THEN 1 ELSE 0 END)
            FROM sf311_requests
            GROUP BY service_name ORDER BY COUNT(*) DESC, service_name ASC
            LIMIT 12""").fetchall()

    report = {
        "source": DATASET_PAGE,
        "license": "ODC PDDL 1.0",
        "data_scope": "bounded request-date slice, not a representative population sample",
        "seven_day_threshold": "illustrative only; not an official agency SLA",
        "quality": {**quality, "database_rows": int(stored)},
        "service_summary": [
            {
                "service_name": name,
                "requests": n,
                "mean_resolution_hours_closed_only": avg,
                "without_valid_closure": unknown,
                "closed_within_seven_days": within_week,
            }
            for name, n, avg, unknown, within_week in summary
        ],
    }
    report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicit DataSF 311 retrieval and data-quality audit")
    subs = parser.add_subparsers(dest="command", required=True)
    fetch = subs.add_parser("fetch", help="Download a bounded public CSV; requires network")
    fetch.add_argument("--start", default="2024-09-01")
    fetch.add_argument("--end", default="2024-10-01")
    fetch.add_argument("--limit", type=int, default=5_000)
    fetch.add_argument("--output", type=Path, default=Path("data/sf311.csv"))
    report = subs.add_parser("analyze", help="Offline quality checks, SQLite and report")
    report.add_argument("--input", type=Path, default=Path("data/sf311.csv"))
    report.add_argument("--db", type=Path, default=Path("output/sf311.sqlite"))
    report.add_argument("--report", type=Path, default=Path("output/sf311-report.json"))
    args = parser.parse_args()
    if args.command == "fetch":
        result = download_csv(args.output, start=args.start, end=args.end, limit=args.limit)
    else:
        result = analyze_csv(args.input, args.db, args.report)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
