"""Offline Matplotlib charts for the bounded DataSF 311 sample.

Reads a local CSV; never contacts the network. All plots are descriptive,
not representative population estimates or predictive ML results.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # Reliable non-interactive PNG output on CI and Windows.
import matplotlib.pyplot as plt
import pandas as pd

from .sf311 import clean_sf311


def _save(fig, destination: Path, caption: str) -> None:
    fig.text(0.03, 0.035, caption, fontsize=8.5, color="dimgray")
    fig.savefig(destination, dpi=150, facecolor="white")
    plt.close(fig)


def render_charts(cleaned: pd.DataFrame, destination: Path) -> dict:
    """Generate three bounded aggregate plots from already-validated records."""
    if cleaned.empty:
        raise ValueError("No validated records available for charting")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    created = pd.to_datetime(cleaned["requested_datetime"])
    first = str(created.min().date())
    last = str(created.max().date())
    days = int(created.dt.date.nunique())
    note = f"DataSF 311 | {len(cleaned):,} accepted cases | {first} to {last} ({days} day(s)) | Nonrepresentative sample"
    paths = []

    # 1. Top categories by service-request volume.
    top = cleaned["service_name"].value_counts().head(10).sort_values()
    fig, ax = plt.subplots(figsize=(10, 6.0))
    fig.subplots_adjust(left=0.34, right=0.94, top=0.89, bottom=0.15)
    bars = ax.barh(top.index, top.to_numpy())
    ax.bar_label(bars, fmt="%d", padding=4)
    ax.set_xlim(0, max(1, float(top.max()) * 1.17))
    ax.set_xlabel("Number of requests")
    ax.set_title("Most frequent service categories in sampled cases", pad=15)
    ax.grid(axis="x", alpha=0.2)
    ax.set_axisbelow(True)
    path = destination / "service_volume.png"
    _save(fig, path, note)
    paths.append(path)

    # 2. Duration buckets for records with known closure dates.
    duration = pd.to_numeric(cleaned["resolution_hours"], errors="coerce")
    resolved = duration.dropna()
    labels = ["0–1 h", "1–24 h", "1–7 d", "7–30 d", "30–90 d", ">90 d"]
    bins = pd.cut(
        resolved, bins=[-0.001, 1, 24, 168, 720, 2160, float("inf")],
        labels=labels, include_lowest=True,
    )
    bucket_counts = bins.value_counts().reindex(labels, fill_value=0)
    fig, ax = plt.subplots(figsize=(10, 6.0))
    fig.subplots_adjust(left=0.11, right=0.95, top=0.86, bottom=0.20)
    bars = ax.bar(labels, bucket_counts.to_numpy())
    ax.bar_label(bars, fmt="%d", padding=4)
    ax.set_ylim(0, max(1, float(bucket_counts.max()) * 1.18))
    ax.set_ylabel("Closed requests")
    ax.set_title("Observed time to closure", pad=15)
    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)
    missing = int(duration.isna().sum())
    path = destination / "closure_duration.png"
    _save(fig, path, f"{note}\n{len(resolved):,} cases with valid closure duration; {missing:,} missing closure outcomes excluded")
    paths.append(path)

    # 3. Share closed within seven days, excluding unknown closure outcomes.
    closed = cleaned.loc[duration.notna(), ["service_name"]].copy()
    closed["within_7d"] = duration.loc[duration.notna()].le(168).astype(int)
    rates = (
        closed.groupby("service_name")["within_7d"]
        .agg(["size", "mean"])
        .rename(columns={"size": "closed_cases", "mean": "within_7d_rate"})
    )
    rates = rates.loc[rates["closed_cases"] >= 10]
    rates = rates.sort_values("closed_cases", ascending=False).head(10)
    rates = rates.sort_values("within_7d_rate")
    fig, ax = plt.subplots(figsize=(10, 6.0))
    fig.subplots_adjust(left=0.34, right=0.92, top=0.86, bottom=0.16)
    if rates.empty:
        ax.text(0.5, 0.5, "No categories with at least 10 closed cases", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
    else:
        values = rates["within_7d_rate"].to_numpy() * 100
        bars = ax.barh(rates.index, values)
        for bar, (pct, n) in zip(bars, zip(values, rates["closed_cases"].to_numpy())):
            ax.text(min(pct + 1, 97), bar.get_y() + bar.get_height() / 2,
                    f"{pct:.0f}% (n={n})", va="center", fontsize=8.5)
        ax.set_xlim(0, 115)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.set_xlabel("Closed within 7 days (%)")
        ax.grid(axis="x", alpha=0.2)
        ax.set_axisbelow(True)
    ax.set_title("Observed 7-day closure rate by category", pad=15)
    path = destination / "seven_day_closure_rate.png"
    _save(fig, path, f"{note}\nOnly categories with ≥10 closed cases; missing outcomes excluded; 7-day threshold is illustrative, not an SLA")
    paths.append(path)
    return {"accepted_rows": int(len(cleaned)), "first_request_date": first,
            "last_request_date": last, "distinct_request_days": days,
            "known_closure_rows": int(len(resolved)),
            "missing_closure_rows": missing,
            "charts": [str(p) for p in paths]}


def create_charts(source: Path, destination: Path) -> dict:
    """Read local CSV, reuse the existing validation contract, create PNGs."""
    data = pd.read_csv(source, dtype=str)
    cleaned, quality = clean_sf311(data)
    result = render_charts(cleaned, destination)
    result["quality"] = quality
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Make offline DataSF 311 summary charts")
    parser.add_argument("--input", type=Path, default=Path("data/sf311.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/charts"))
    args = parser.parse_args()
    print(json.dumps(create_charts(args.input, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
