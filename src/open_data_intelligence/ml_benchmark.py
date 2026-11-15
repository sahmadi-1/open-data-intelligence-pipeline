"""Retrospective seven-day closure benchmark for a bounded DataSF sample.

Offline portfolio demonstration only: no deployment, model artifact, or API calls.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, confusion_matrix,
    f1_score, precision_score, recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from .sf311 import DATASET_PAGE, clean_sf311

HOLDOUT_START = pd.Timestamp("2024-10-01")
FEATURE_COLUMNS = (
    "service_name", "service_subtype", "supervisor_district",
    "request_hour", "request_weekday",
)
LATE_THRESHOLD_HOURS = 168


def _features(clean: pd.DataFrame) -> pd.DataFrame:
    """Never use ID, closure datetime or actual duration as predictors."""
    timestamp = pd.to_datetime(clean["requested_datetime"], errors="raise")
    return pd.DataFrame({
        "service_name": clean["service_name"].fillna("Unknown").astype(str),
        "service_subtype": clean["service_subtype"].fillna("Unknown").astype(str),
        "supervisor_district": clean["supervisor_district"].fillna("Unknown").astype(str),
        "request_hour": timestamp.dt.hour.astype(str),
        "request_weekday": timestamp.dt.dayofweek.astype(str),
    }, index=clean.index)


def _metrics(actual, predicted) -> dict:
    tn, fp, fn, tp = (
        int(x) for x in confusion_matrix(actual, predicted, labels=[0, 1]).ravel()
    )
    return {
        "accuracy": round(float(accuracy_score(actual, predicted)), 4),
        "balanced_accuracy": round(float(balanced_accuracy_score(actual, predicted)), 4),
        "late_precision": round(float(precision_score(
            actual, predicted, pos_label=1, zero_division=0)), 4),
        "late_recall": round(float(recall_score(
            actual, predicted, pos_label=1, zero_division=0)), 4),
        "late_f1": round(float(f1_score(
            actual, predicted, pos_label=1, zero_division=0)), 4),
        "confusion_matrix": {
            "on_time_correct": tn,
            "on_time_falsely_late": fp,
            "late_missed": fn,
            "late_correct": tp,
        },
    }


def _class_counts(y) -> dict:
    return {
        "within_7d": int((y == 0).sum()),
        "over_7d": int((y == 1).sum()),
    }


def run_benchmark(source: Path, report_file: Path, chart_file: Path) -> dict:
    """Fit once with a predefined Oct-Dec 2024 holdout; report test metrics."""
    source, report_file, chart_file = (
        Path(source), Path(report_file), Path(chart_file)
    )
    cleaned, quality = clean_sf311(pd.read_csv(source, dtype=str))
    duration = pd.to_numeric(cleaned["resolution_hours"], errors="coerce")
    known = cleaned.loc[duration.notna()].copy()
    if known.empty:
        raise ValueError("No known closure durations available")

    timestamps = pd.to_datetime(known["requested_datetime"], errors="raise")
    label = duration.loc[duration.notna()].gt(LATE_THRESHOLD_HOURS).astype(int)
    is_training = timestamps < HOLDOUT_START
    is_test = ~is_training

    def verify_support(mask, name: str, min_days: int) -> None:
        values = label.loc[mask]
        day_count = int(timestamps.loc[mask].dt.date.nunique())
        if (
            len(values) < 40
            or day_count < min_days
            or values.nunique() < 2
            or values.value_counts().min() < 10
        ):
            raise ValueError(
                f"Insufficient {name} support: rows={len(values)}, "
                f"unique_days={day_count}, classes={_class_counts(values)}; "
                f"need >=40 rows, >={min_days} distinct days, "
                "and >=10 observations for each class"
            )

    verify_support(is_training, "training", 6)
    verify_support(is_test, "holdout", 4)

    feature_frame = _features(known)
    x_train, x_test = feature_frame.loc[is_training], feature_frame.loc[is_test]
    y_train, y_test = label.loc[is_training], label.loc[is_test]

    baseline = DummyClassifier(strategy="most_frequent")
    baseline.fit(x_train, y_train)
    baseline_metrics = _metrics(y_test, baseline.predict(x_test))

    logistic = Pipeline([
        ("encode", ColumnTransformer([
            ("categorical", OneHotEncoder(handle_unknown="ignore"),
             list(FEATURE_COLUMNS)),
        ])),
        ("classifier", LogisticRegression(
            max_iter=2000, class_weight="balanced", random_state=42)),
    ])
    logistic.fit(x_train, y_train)
    logistic_metrics = _metrics(y_test, logistic.predict(x_test))

    report = {
        "source": DATASET_PAGE,
        "objective": "Exploratory: closure after 7 days (1) vs within 7 days (0)",
        "sampling": "First 250 requests on two fixed days/month in 2024; nonrepresentative",
        "data_quality": quality,
        "missing_closure_outcomes_excluded": int(duration.isna().sum()),
        "submission_features_only": list(FEATURE_COLUMNS),
        "point_in_time_caveat": (
            "The public export may reflect later edits to service categories "
            "or district; historical as-at-submission feature values are not verified"
        ),
        "training": {
            "before": str(HOLDOUT_START.date()),
            "rows": int(is_training.sum()),
            "unique_days": int(timestamps.loc[is_training].dt.date.nunique()),
            "classes": _class_counts(y_train),
        },
        "holdout": {
            "on_or_after": str(HOLDOUT_START.date()),
            "rows": int(is_test.sum()),
            "unique_days": int(timestamps.loc[is_test].dt.date.nunique()),
            "classes": _class_counts(y_test),
        },
        "majority_baseline": baseline_metrics,
        "logistic_regression_balanced": logistic_metrics,
        "limitations": (
            "Retrospective benchmark; not representative, not production ML, "
            "and not proof of performance outside these selected 2024 days"
        ),
    }
    report_file.parent.mkdir(parents=True, exist_ok=True)
    chart_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    names = ["Balanced accuracy", "Late recall", "Late F1"]
    keys = ["balanced_accuracy", "late_recall", "late_f1"]
    baseline_bars = [baseline_metrics[key] for key in keys]
    logistic_bars = [logistic_metrics[key] for key in keys]
    fig, ax = plt.subplots(figsize=(10.4, 5.4))
    fig.subplots_adjust(left=.10, right=.97, top=.85, bottom=.23)
    xx = list(range(len(names)))
    a = ax.bar([x - .19 for x in xx], baseline_bars, .36,
               label="Majority baseline")
    b = ax.bar([x + .19 for x in xx], logistic_bars, .36,
               label="Logistic regression")
    ax.bar_label(a, fmt="%.2f", padding=3)
    ax.bar_label(b, fmt="%.2f", padding=3)
    ax.set_xticks(xx, names)
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("Score (0–1)")
    ax.set_title("Retrospective holdout: seven-day closure classification")
    ax.grid(axis="y", alpha=.18)
    ax.set_axisbelow(True)
    ax.legend(loc="upper right")
    fig.text(.05, .07, "Fixed Oct–Dec 2024 holdout | Nonrepresentative sample | Unknown closure outcomes excluded", fontsize=9)
    fig.text(.05, .035, "Late = closed after 7 days; illustrative threshold, not official SLA. Public export may contain later edits.", fontsize=8.6)
    fig.savefig(chart_file, dpi=150, facecolor="white")
    plt.close(fig)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline SF311 logistic regression benchmark")
    parser.add_argument("--input", type=Path, default=Path("data/sf311_multimonth.csv"))
    parser.add_argument("--report", type=Path, default=Path("output/ml/benchmark.json"))
    parser.add_argument("--chart", type=Path, default=Path("output/ml/benchmark_comparison.png"))
    args = parser.parse_args()
    print(json.dumps(run_benchmark(args.input, args.report, args.chart), indent=2))


if __name__ == "__main__":
    main()
