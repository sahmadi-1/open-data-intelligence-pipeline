"""Offline multi-month sampling tests: no network calls."""
import json
from pathlib import Path

import pandas as pd
import pytest

from open_data_intelligence import sampling
from open_data_intelligence.sf311 import SOURCE_FIELDS


def mock_download(path, *, start, end, limit):
    assert limit <= 500
    assert (pd.Timestamp(end) - pd.Timestamp(start)).days == 1
    row = {
        "service_request_id": [start.replace("-", "")],
        "requested_datetime": [f"{start}T00:15:00.000"],
        "closed_date": [f"{start}T05:15:00.000"],
        "service_name": ["Streetlight"],
        "service_subtype": ["Bulb"],
        "supervisor_district": ["2"],
    }
    pd.DataFrame(row, columns=SOURCE_FIELDS).to_csv(path, index=False)
    return {"bytes": Path(path).stat().st_size}


def test_fixed_windows_cover_year():
    windows = sampling.sampling_windows()
    assert len(windows) == 24
    assert windows[0] == ("2024-01-07", "2024-01-08")
    assert windows[1] == ("2024-01-21", "2024-01-22")
    assert windows[-1] == ("2024-12-21", "2024-12-22")
    assert len(set(windows)) == 24


def test_collect_and_manifest_offline(monkeypatch, tmp_path):
    monkeypatch.setattr(sampling, "download_csv", mock_download)
    data = tmp_path / "out.csv"
    manifest = tmp_path / "info.json"
    outcome = sampling.fetch_multimonth(data, manifest)
    frame = pd.read_csv(data, dtype=str)
    info = json.loads(manifest.read_text())
    assert outcome["rows"] == 24
    assert outcome["maximum_possible_rows"] == 6000
    assert len(frame) == 24
    assert frame["service_request_id"].nunique() == 24
    assert list(frame.columns) == list(SOURCE_FIELDS)
    assert info["windows_requested"] == 24
    assert len(info["windows"]) == 24
    assert info["retrieved_rows"] == 24
    assert "not representative" in info["limitations"]
    assert sampling.fetch_multimonth(data, manifest) == outcome


def test_failure_preserves_old_outputs(monkeypatch, tmp_path):
    data, manifest = tmp_path / "old.csv", tmp_path / "old.json"
    data.write_text("old CSV")
    manifest.write_text("old JSON")
    calls = 0
    def fail_on_third(path, *, start, end, limit):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("mock download interrupted")
        return mock_download(path, start=start, end=end, limit=limit)
    monkeypatch.setattr(sampling, "download_csv", fail_on_third)
    with pytest.raises(OSError, match="interrupted"):
        sampling.fetch_multimonth(data, manifest)
    assert data.read_text() == "old CSV"
    assert manifest.read_text() == "old JSON"


@pytest.mark.parametrize("limit", [0, -1, 501, True, 5.5])
def test_bad_limits_rejected(limit, tmp_path):
    with pytest.raises(ValueError, match="per_day_limit"):
        sampling.fetch_multimonth(tmp_path / "a.csv", tmp_path / "a.json", per_day_limit=limit)


def test_output_paths_must_differ(tmp_path):
    path = tmp_path / "same"
    with pytest.raises(ValueError, match="different"):
        sampling.fetch_multimonth(path, path)


def test_excess_rows_rejected(monkeypatch, tmp_path):
    def over_limit(path, *, start, end, limit):
        df = pd.DataFrame({field: ["X"] * (limit + 1) for field in SOURCE_FIELDS})
        df.to_csv(path, index=False)
        return {"bytes": Path(path).stat().st_size}
    monkeypatch.setattr(sampling, "download_csv", over_limit)
    with pytest.raises(ValueError, match="exceeds request limit"):
        sampling.fetch_multimonth(tmp_path / "a.csv", tmp_path / "a.json")
