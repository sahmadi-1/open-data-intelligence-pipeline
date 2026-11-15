from pathlib import Path

import pandas as pd
import pytest

from open_data_intelligence.core import make_demo_csv, run_pipeline, validate_and_clean


def test_demo_quality_counts(tmp_path: Path) -> None:
    source = make_demo_csv(tmp_path / "input.csv")
    clean, counts = validate_and_clean(pd.read_csv(source))
    assert counts == {
        "input_rows": 85,
        "duplicates_removed": 1,
        "invalid_rows_removed": 4,
        "valid_rows": 80,
    }
    assert clean["ticket_id"].is_unique


def test_pipeline_report_and_idempotent_reload(tmp_path: Path) -> None:
    source = make_demo_csv(tmp_path / "input.csv")
    database = tmp_path / "data.sqlite"
    output = tmp_path / "report.json"
    first = run_pipeline(source, database, output)
    second = run_pipeline(source, database, output)
    assert first == second
    assert second["source_type"] == "synthetic_demo"
    assert second["quality"]["database_rows"] == 80
    assert sum(item["requests"] for item in second["district_summary"]) == 80
    assert output.exists()


def test_missing_column_fails_closed() -> None:
    with pytest.raises(ValueError, match="Missing required columns"):
        validate_and_clean(pd.DataFrame({"ticket_id": ["T-1"]}))


def test_empty_identifier_and_invalid_values_rejected(tmp_path: Path) -> None:
    source = make_demo_csv(tmp_path / "input.csv", count=1)
    frame = pd.read_csv(source, dtype=str).iloc[:1].copy()
    frame.loc[0, "ticket_id"] = ""
    frame.loc[0, "resolution_hours"] = "unparseable"
    _, counts = validate_and_clean(frame)
    assert counts["valid_rows"] == 0
