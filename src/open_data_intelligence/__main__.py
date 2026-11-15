"""Usage: python -m open_data_intelligence demo|run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import make_demo_csv, run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic city-service data pipeline")
    commands = parser.add_subparsers(dest="command", required=True)

    demo = commands.add_parser("demo", help="Generate a deterministic synthetic CSV")
    demo.add_argument("--output", type=Path, default=Path("data/demo.csv"))

    run = commands.add_parser("run", help="Validate, load to SQLite, and report")
    run.add_argument("--input", type=Path, default=Path("data/demo.csv"))
    run.add_argument("--db", type=Path, default=Path("output/services.sqlite"))
    run.add_argument("--report", type=Path, default=Path("output/report.json"))

    args = parser.parse_args()
    if args.command == "demo":
        print(f"Created synthetic input: {make_demo_csv(args.output)}")
    else:
        print(json.dumps(run_pipeline(args.input, args.db, args.report), indent=2))


if __name__ == "__main__":
    main()
