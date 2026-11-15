"""Offline tests of chronological holdout and label/feature discipline."""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from open_data_intelligence.ml_benchmark import (
    FEATURE_COLUMNS, _features, run_benchmark,
)
from open_data_intelligence.sf311 import clean_sf311


def example_csv(tmp_path: Path, *, test_period=True, has_late=True) -> Path:
    rows = []
    dates = [
        "2024-01-07", "2024-01-21", "2024-03-07",
        "2024-04-21", "2024-05-07", "2024-08-21",
    ]
    if test_period:
        dates += ["2024-10-07", "2024-10-21", "2024-11-07", "2024-12-21"]
    for day in dates:
        for n in range(24):
            timestamp = datetime.fromisoformat(f"{day}T{n % 12:02d}:00:00")
            closed = timestamp + timedelta(hours=240 if n % 4 == 0 and has_late else 24)
            rows.append({
                "service_request_id": f"{day}-{n}",
                "requested_datetime": timestamp.isoformat(),
                "closed_date": closed.isoformat(),
                "service_name": "Parking Enforcement" if n % 2 else "Streetlights",
                "service_subtype": "Level 1" if n % 3 else "Level 2",
                "supervisor_district": str(n % 5 + 1),
            })
    rows.append({
        "service_request_id": "MISSING-1",
        "requested_datetime": "2024-09-07T12:00:00",
        "closed_date": "",
        "service_name": "Parks",
        "service_subtype": "Unknown",
        "supervisor_district": "1",
    })
    target = tmp_path / "cases.csv"
    pd.DataFrame(rows).to_csv(target, index=False)
    return target


def test_report_chart_and_repeated_run(tmp_path: Path):
    source = example_csv(tmp_path)
    report_file, image_file = tmp_path / "out.json", tmp_path / "out.png"
    first = run_benchmark(source, report_file, image_file)
    assert run_benchmark(source, report_file, image_file) == first
    assert first["missing_closure_outcomes_excluded"] == 1
    assert first["training"]["rows"] == 144
    assert first["holdout"]["rows"] == 96
    assert first["training"]["classes"]["over_7d"] == 36
    assert first["holdout"]["classes"]["over_7d"] == 24
    assert first["holdout"]["unique_days"] == 4
    assert 0 <= first["logistic_regression_balanced"]["late_f1"] <= 1
    assert json.loads(report_file.read_text()) == first
    assert image_file.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_no_holdout_fails(tmp_path: Path):
    source = example_csv(tmp_path, test_period=False)
    with pytest.raises(ValueError, match="Insufficient holdout support"):
        run_benchmark(source, tmp_path / "out.json", tmp_path / "out.png")


def test_single_class_fails(tmp_path: Path):
    source = example_csv(tmp_path, has_late=False)
    with pytest.raises(ValueError, match="Insufficient training support"):
        run_benchmark(source, tmp_path / "out.json", tmp_path / "out.png")


def test_features_do_not_include_labels_or_identifiers(tmp_path: Path):
    cleaned, _ = clean_sf311(pd.read_csv(example_csv(tmp_path), dtype=str))
    features = _features(cleaned)
    assert set(features.columns) == set(FEATURE_COLUMNS)
    assert not {"closed_date", "resolution_hours", "service_request_id"} & set(features.columns)
