"""Small, reproducible ETL pipeline with explicit data-quality checks.

All demo records are synthetic. No external data sources are accessed.
"""

from __future__ import annotations

import csv
import json
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

COLUMNS = (
    "ticket_id",
    "created_date",
    "district",
    "service_type",
    "resolution_hours",
    "satisfaction_score",
)
DISTRICTS = ("North", "South", "East", "West")
SERVICES = ("Lighting", "Parks", "Road repair", "Waste collection")


def make_demo_csv(destination: Path, *, count: int = 80) -> Path:
    """Write deterministic, synthetic records with known quality problems."""
    if count < 1:
        raise ValueError("count must be positive")
    rng = random.Random(2026)
    start = date(2026, 1, 1)
    rows = []
    for index in range(1, count + 1):
        rows.append(
            {
                "ticket_id": f"T-{index:04d}",
                "created_date": str(start + timedelta(days=index - 1)),
                "district": rng.choice(DISTRICTS),
                "service_type": rng.choice(SERVICES),
                "resolution_hours": rng.randint(1, 96),
                "satisfaction_score": rng.randint(1, 5),
            }
        )

    # Deliberate defects to demonstrate deduplication and validation.
    rows.append(dict(rows[0]))
    for ticket_id, changes in (
        ("BAD-01", {"district": ""}),
        ("BAD-02", {"resolution_hours": -5}),
        ("BAD-03", {"created_date": "not-a-date"}),
        ("BAD-04", {"satisfaction_score": 7}),
    ):
        rows.append({**rows[0], "ticket_id": ticket_id, **changes})

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return destination


def validate_and_clean(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Return valid records and counts; duplicates keep their first occurrence."""
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    rows = frame.loc[:, list(COLUMNS)].copy()
    for column in ("ticket_id", "created_date", "district", "service_type"):
        rows[column] = rows[column].fillna("").astype(str).str.strip()

    duplicate_mask = rows.duplicated(subset="ticket_id", keep="first")
    duplicates = int(duplicate_mask.sum())
    rows = rows.loc[~duplicate_mask].copy()

    dates = pd.to_datetime(rows["created_date"], errors="coerce", format="%Y-%m-%d")
    hours = pd.to_numeric(rows["resolution_hours"], errors="coerce")
    scores = pd.to_numeric(rows["satisfaction_score"], errors="coerce")

    valid = (
        rows["ticket_id"].ne("")
        & rows["district"].isin(DISTRICTS)
        & rows["service_type"].isin(SERVICES)
        & dates.notna()
        & hours.between(0, 720, inclusive="both")
        & scores.isin([1, 2, 3, 4, 5])
    )
    invalid = int((~valid).sum())
    cleaned = rows.loc[valid].copy()
    cleaned["created_date"] = dates.loc[valid].dt.strftime("%Y-%m-%d")
    cleaned["resolution_hours"] = hours.loc[valid].astype(float)
    cleaned["satisfaction_score"] = scores.loc[valid].astype(int)
    counts = {
        "input_rows": len(frame),
        "duplicates_removed": duplicates,
        "invalid_rows_removed": invalid,
        "valid_rows": len(cleaned),
    }
    return cleaned, counts


def run_pipeline(source: Path, database: Path, report_file: Path) -> dict:
    """Validate, idempotently upsert into SQLite, and save an aggregate report."""
    source, database, report_file = map(Path, (source, database, report_file))
    cleaned, quality = validate_and_clean(pd.read_csv(source, dtype=str))
    database.parent.mkdir(parents=True, exist_ok=True)
    report_file.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS service_requests (
                ticket_id TEXT PRIMARY KEY,
                created_date TEXT NOT NULL,
                district TEXT NOT NULL,
                service_type TEXT NOT NULL,
                resolution_hours REAL NOT NULL,
                satisfaction_score INTEGER NOT NULL
            )"""
        )
        conn.executemany(
            """INSERT INTO service_requests (
                ticket_id, created_date, district, service_type,
                resolution_hours, satisfaction_score
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticket_id) DO UPDATE SET
                created_date=excluded.created_date,
                district=excluded.district,
                service_type=excluded.service_type,
                resolution_hours=excluded.resolution_hours,
                satisfaction_score=excluded.satisfaction_score""",
            cleaned.loc[:, list(COLUMNS)].itertuples(index=False, name=None),
        )
        stored = conn.execute("SELECT COUNT(*) FROM service_requests").fetchone()[0]
        grouped = conn.execute(
            """SELECT district, COUNT(*), ROUND(AVG(resolution_hours), 2),
                ROUND(AVG(satisfaction_score), 2)
            FROM service_requests
            GROUP BY district ORDER BY district"""
        ).fetchall()

    report = {
        "source_type": "synthetic_demo",
        "quality": {**quality, "database_rows": stored},
        "district_summary": [
            {
                "district": district,
                "requests": requests,
                "avg_resolution_hours": hours,
                "avg_satisfaction_score": score,
            }
            for district, requests, hours, score in grouped
        ],
    }
    report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
