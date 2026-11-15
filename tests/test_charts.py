"""Offline chart smoke tests, including empty/unknown-outcome cases."""
from pathlib import Path

import pandas as pd
import pytest

from open_data_intelligence.charts import create_charts, render_charts
from open_data_intelligence.sf311 import clean_sf311


def sample_frame() -> pd.DataFrame:
    rows = []
    for i in range(25):
        rows.append({
            "service_request_id": f"R-{i}",
            "requested_datetime": "2024-09-01T09:00:00.000",
            "closed_date": (
                "" if i == 24 else
                "2024-09-15T09:00:00.000" if i >= 20 else
                "2024-09-02T09:00:00.000"
            ),
            "service_name": "Streetlights" if i < 20 else "Other",
            "service_subtype": "Repair",
            "supervisor_district": "1",
        })
    rows.append(dict(rows[0]))  # Known duplicate.
    rows.append({**rows[0], "service_request_id": "BAD", "requested_datetime": "invalid"})
    return pd.DataFrame(rows)


def test_png_generation_uses_validated_data(tmp_path: Path):
    source = tmp_path / "input.csv"
    sample_frame().to_csv(source, index=False)
    dest = tmp_path / "charts"
    report = create_charts(source, dest)
    assert report["accepted_rows"] == 25
    assert report["quality"]["duplicate_ids_removed"] == 1
    assert report["quality"]["invalid_rows_removed"] == 1
    assert report["missing_closure_rows"] == 1
    assert report["known_closure_rows"] == 24
    assert report["distinct_request_days"] == 1
    assert len(report["charts"]) == 3
    for path in report["charts"]:
        data = Path(path).read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(data) > 2500
    assert create_charts(source, dest) == report


def test_zero_valid_rows_do_not_create_pngs(tmp_path: Path):
    frame = sample_frame().iloc[:1].copy()
    frame.loc[frame.index[0], "requested_datetime"] = "invalid"
    cleaned, _ = clean_sf311(frame)
    folder = tmp_path / "charts"
    with pytest.raises(ValueError, match="No validated records"):
        render_charts(cleaned, folder)
    assert not folder.exists()


def test_missing_required_fields_fail_closed(tmp_path: Path):
    source = tmp_path / "input.csv"
    pd.DataFrame({"service_request_id": ["R-1"]}).to_csv(source, index=False)
    with pytest.raises(ValueError, match="Missing required"):
        create_charts(source, tmp_path / "charts")
