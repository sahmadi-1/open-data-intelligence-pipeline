"""Offline tests: never reach the public open-data API."""
import json
import urllib.parse
from pathlib import Path

import pandas as pd
import pytest

from open_data_intelligence.sf311 import (
    SOURCE_FIELDS, analyze_csv, clean_sf311, download_csv, make_url,
)


def records():
    return pd.DataFrame([
        {"service_request_id": "101", "requested_datetime": "2024-09-02T00:00:00.000", "closed_date": "2024-09-03T00:00:00.000", "service_name": "Streetlights", "service_subtype": "Repair", "supervisor_district": "1"},
        {"service_request_id": "101", "requested_datetime": "2024-09-02T00:00:00.000", "closed_date": "2024-09-03T00:00:00.000", "service_name": "Streetlights", "service_subtype": "Repair", "supervisor_district": "1"},
        {"service_request_id": "102", "requested_datetime": "2024-09-02T00:00:00.000", "closed_date": "", "service_name": "Streetlights", "service_subtype": "", "supervisor_district": ""},
        {"service_request_id": "103", "requested_datetime": "BAD", "closed_date": "2024-09-03T00:00:00.000", "service_name": "Streetlights", "service_subtype": "Repair", "supervisor_district": "1"},
        {"service_request_id": "104", "requested_datetime": "2024-09-03T00:00:00.000", "closed_date": "2024-09-02T00:00:00.000", "service_name": "Streetlights", "service_subtype": "Repair", "supervisor_district": "1"},
    ])


def test_query_is_limited_and_whitelisted():
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(make_url(limit=5000)).query)
    assert query["$limit"] == ["5000"]
    assert set(query["$select"][0].split(",")) == set(SOURCE_FIELDS)
    assert "address" not in query["$select"][0]
    assert "status_notes" not in query["$select"][0]
    with pytest.raises(ValueError):
        make_url(limit=10001)
    with pytest.raises(ValueError):
        make_url(start="2024-10-01", end="2024-09-01")
    with pytest.raises(ValueError):
        make_url(start="' OR 1=1--")


def test_quality_counts_and_missing_closure_kept():
    clean, counts = clean_sf311(records())
    assert counts == {
        "input_rows": 5,
        "duplicate_ids_removed": 1,
        "invalid_rows_removed": 2,
        "accepted_rows": 2,
        "missing_or_unresolved_closure": 1,
        "closed_with_valid_duration": 1,
        "closed_over_90_days": 0,
    }
    assert set(clean["service_request_id"]) == {"101", "102"}
    assert clean.loc[clean["service_request_id"] == "102", "closed_date"].iloc[0] is None


def test_idempotent_sqlite_and_reporting(tmp_path: Path):
    source = tmp_path / "cases.csv"
    records().to_csv(source, index=False)
    db, dest = tmp_path / "cases.sqlite", tmp_path / "report.json"
    one = analyze_csv(source, db, dest)
    two = analyze_csv(source, db, dest)
    assert one == two
    assert one["quality"]["database_rows"] == 2
    assert one["service_summary"][0]["closed_within_seven_days"] == 1
    assert one["service_summary"][0]["without_valid_closure"] == 1
    assert json.loads(dest.read_text()) == one


def test_missing_schema_rejected():
    with pytest.raises(ValueError, match="Missing required"):
        clean_sf311(pd.DataFrame({"service_request_id": ["101"]}))


def test_network_fetch_mocked_and_bounded(monkeypatch, tmp_path: Path):
    csv_body = records().to_csv(index=False).encode()
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def read(self, n):
            assert n == 12_000_001
            return csv_body
    def fake_urlopen(req, timeout):
        assert timeout == 25
        assert req.full_url.startswith("https://data.sf.gov/")
        return FakeResponse()
    monkeypatch.setattr("open_data_intelligence.sf311.urllib.request.urlopen", fake_urlopen)
    dest = tmp_path / "download.csv"
    result = download_csv(dest, limit=5)
    assert result["bytes"] == len(csv_body)
    assert pd.read_csv(dest).shape[0] == 5


def test_malformed_closure_date_rejected_not_marked_unresolved():
    frame = records().iloc[:1].copy()
    frame.loc[0, "closed_date"] = "not-a-date"
    cleaned, stats = clean_sf311(frame)
    assert len(cleaned) == 0
    assert stats["invalid_rows_removed"] == 1
    assert stats["missing_or_unresolved_closure"] == 0
