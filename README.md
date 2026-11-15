# Open Data Intelligence Pipeline

[![Python tests](https://github.com/sahmadi-1/open-data-intelligence-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/sahmadi-1/open-data-intelligence-pipeline/actions/workflows/ci.yml)

A small, reproducible **Python, pandas and SQLite data-quality and reporting project**, created as a public engineering portfolio demonstration.

> The default demonstration uses **synthetic municipal service requests**. An optional, explicitly invoked real-data path uses selected public DataSF 311 records; CI never makes network calls. No proprietary source code, patient records, or trading information are used.

## What it demonstrates

- Deterministic synthetic CSV generation containing deliberate data defects
- Validation, data cleaning, duplicate handling and explicit quality counts
- Idempotent SQLite upserts and SQL aggregation
- Reproducible JSON reporting and a simple command-line interface
- Automated tests using pytest and GitHub Actions

## Run locally

Requires Python 3.11+.

```bash
python -m venv .venv
# Activate the venv, then:
python -m pip install -e '.[dev]'
python -m open_data_intelligence demo
python -m open_data_intelligence run
python -m pytest -q
```

On Windows PowerShell with Python 3.12:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m open_data_intelligence demo
.\.venv\Scripts\python.exe -m open_data_intelligence run
.\.venv\Scripts\python.exe -m pytest -q
```

Outputs, generated locally and excluded from Git:

- `data/demo.csv`: synthetic input dataset
- `output/services.sqlite`: validated stored records
- `output/report.json`: quality and district-summary report

The default demonstration produces **85 input rows**, including **1 duplicate** and **4 invalid rows**, leaving **80 validated rows**. Re-running the input does not add duplicates to SQLite.

## Project layout

- `src/open_data_intelligence/`: deterministic dataset generator, cleaning, SQLite and CLI
- `tests/`: data quality and idempotence tests
- `.github/workflows/ci.yml`: automated tests on pushes and pull requests

## Scope and limitations

Version 0.1 is a deliberate minimum viable engineering demonstration, **not a production service**. It has no cloud infrastructure, live dataset ingestion, deployed ML model or web UI. Validation rules target the described synthetic schema. Potential future improvements include a properly licensed external dataset and an explicitly evaluated forecasting baseline.

## Confidentiality

All code and demo records in this repository were created separately for this portfolio project and do not contain employer-owned code, customer details, or private datasets.


## Optional real-world data path (v0.2)

**Source:** [San Francisco 311 Cases](https://data.sf.gov/d/vw6y-z8j6) (dataset `vw6y-z8j6`)  
**Publisher:** San Francisco 311 / DataSF  
**License:** [ODC PDDL 1.0](https://opendatacommons.org/licenses/pddl/1-0/) (public domain)  
**Access:** Socrata SODA2 public CSV query. The live request has not yet been executed in this repository environment.

This is an independent optional workflow; it does not replace the synthetic demo.

~~~bash
# Explicit external API call (only when you run this command):
python -m open_data_intelligence.sf311 fetch --start 2024-09-01 --end 2024-10-01 --limit 5000

# Offline cleansing, idempotent SQLite load and JSON reporting:
python -m open_data_intelligence.sf311 analyze
~~~

- Requests only six structured fields: case ID, request date, closure date, category, subtype and supervisor district. **Does not request addresses, free-text details, notes, names or precise coordinates.**
- The download is bounded to at most 10,000 records / 12 MB, and defaults to a fixed historical date window for repeatability.
- Reports duplicate IDs, invalid or missing dates, negative durations, long-duration outliers and missing closure outcomes.
- Keeps records without closure outcomes but excludes them from observed resolution-time calculations.
- Reports a seven-day closure threshold as an **illustrative descriptive metric**, not an official agency service-level agreement.
- The slice is the *first* rows in date order within the requested window, **not a representative random sample**. Do not generalize its rates to the full population.
- Generated CSV, SQLite and JSON files are not committed. Data may change upstream between fetches. Treat API access, real-data distributions and performance as **unverified until a successful manual download**.
- This version does **not** train or claim a predictive ML model. Any future prediction must use only information available at request creation, with time-based validation and careful handling of censored/unresolved requests.
