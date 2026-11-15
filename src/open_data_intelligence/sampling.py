"""Bounded multi-month public DataSF 311 sampling; manual execution only."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .sf311 import DATASET_PAGE, SOURCE_FIELDS, download_csv

YEAR = 2024
DAYS_PER_MONTH = (7, 21)
DEFAULT_LIMIT = 250
MAX_LIMIT = 500


def sampling_windows() -> list[tuple[str, str]]:
    """Two one-day windows in each of the 12 months of 2024."""
    windows = []
    for month in range(1, 13):
        for day in DAYS_PER_MONTH:
            start = date(YEAR, month, day)
            windows.append((start.isoformat(), (start + timedelta(days=1)).isoformat()))
    return windows


def fetch_multimonth(
    destination: Path,
    manifest_path: Path,
    *,
    per_day_limit: int = DEFAULT_LIMIT,
) -> dict:
    """Collect bounded samples with no outputs changed on download failure."""
    if type(per_day_limit) is not int or not 1 <= per_day_limit <= MAX_LIMIT:
        raise ValueError(f"per_day_limit must be an integer from 1 to {MAX_LIMIT}")
    destination, manifest_path = Path(destination), Path(manifest_path)
    if destination.resolve() == manifest_path.resolve():
        raise ValueError("CSV and manifest output paths must be different")
    windows = sampling_windows()
    chunks: list[pd.DataFrame] = []
    receipts = []
    with tempfile.TemporaryDirectory(prefix="sf311-months-") as work:
        for index, (start, end) in enumerate(windows):
            local_file = Path(work) / f"window_{index:02d}.csv"
            download = download_csv(local_file, start=start, end=end, limit=per_day_limit)
            chunk = pd.read_csv(local_file, dtype=str)
            if not set(SOURCE_FIELDS).issubset(chunk.columns):
                raise ValueError(f"Unexpected schema for {start}; aborting batch")
            if len(chunk) > per_day_limit:
                raise ValueError(f"Window {start} exceeds request limit; aborting batch")
            chunks.append(chunk.loc[:, list(SOURCE_FIELDS)])
            receipts.append({
                "start_inclusive": start,
                "end_exclusive": end,
                "records": len(chunk),
                "bytes_downloaded": download["bytes"],
                "requested_limit": per_day_limit,
            })
            print(f"Window {index + 1}/{len(windows)}: {start}: {len(chunk)} rows", flush=True)
        combined = pd.concat(chunks, ignore_index=True)
        if combined.empty:
            raise ValueError("No records returned across all sample windows")
        manifest = {
            "source": DATASET_PAGE,
            "method": "first records by request-time within 24 fixed single-day windows",
            "year": YEAR,
            "day_of_month": list(DAYS_PER_MONTH),
            "windows_requested": len(windows),
            "per_window_limit": per_day_limit,
            "maximum_possible_rows": len(windows) * per_day_limit,
            "retrieved_rows": len(combined),
            "distinct_request_ids_in_raw_data": int(combined["service_request_id"].nunique()),
            "limitations": (
                "Purposive chronological sample, not representative. Dates cover only "
                "two selected days per month; each window returns its earliest "
                "requests. Use time-based assessment and account for missing "
                "closure outcomes before fitting any classifier."
            ),
            "windows": receipts,
        }
        csv_tmp = Path(work) / "combined.csv"
        json_tmp = Path(work) / "manifest.json"
        combined.to_csv(csv_tmp, index=False)
        json_tmp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(csv_tmp, destination)
        os.replace(json_tmp, manifest_path)
    return {
        "data_file": str(destination),
        "manifest_file": str(manifest_path),
        "windows": len(windows),
        "rows": len(combined),
        "distinct_request_ids": manifest["distinct_request_ids_in_raw_data"],
        "maximum_possible_rows": manifest["maximum_possible_rows"],
        "sampling_note": "Purposive, nonrepresentative fixed-date sampling",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manually fetch a bounded 2024 multi-month DataSF 311 sample"
    )
    parser.add_argument("--output", type=Path, default=Path("data/sf311_multimonth.csv"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("output/sf311_multimonth_manifest.json")
    )
    parser.add_argument("--per-day-limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()
    print(json.dumps(fetch_multimonth(args.output, args.manifest,
                                      per_day_limit=args.per_day_limit), indent=2))


if __name__ == "__main__":
    main()
