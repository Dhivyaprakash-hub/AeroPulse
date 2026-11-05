"""Reproducible first-pass audit for BTS monthly On-Time Performance ZIPs.

Reads the original ZIPs in place and writes summaries only. It does not copy,
modify, or redistribute the source data.
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.util import hash_pandas_object


USECOLS = [
    "Year", "Quarter", "Month", "FlightDate", "Reporting_Airline",
    "DOT_ID_Reporting_Airline", "Tail_Number", "Flight_Number_Reporting_Airline",
    "OriginAirportID", "Origin", "DestAirportID", "Dest", "CRSDepTime",
    "DepTime", "DepDelay", "DepDelayMinutes", "CRSArrTime", "ArrTime",
    "ArrDelay", "ArrDel15", "Cancelled", "Diverted", "CRSElapsedTime",
    "ActualElapsedTime", "Distance",
]
STRING_COLS = [
    "FlightDate", "Reporting_Airline", "Tail_Number",
    "Flight_Number_Reporting_Airline", "Origin", "Dest",
]
NUMERIC_COLS = [c for c in USECOLS if c not in STRING_COLS]
PERIOD_RE = re.compile(r"_(20\d{2})_(\d{1,2})\.zip$", re.IGNORECASE)


def hhmm_minutes(series: pd.Series) -> pd.Series:
    """Convert BTS HHMM values to minutes after midnight; invalids -> NA."""
    x = pd.to_numeric(series, errors="coerce")
    hour = np.floor(x / 100)
    minute = x % 100
    midnight_2400 = x.eq(2400)
    valid = x.notna() & (((hour >= 0) & (hour < 24) & (minute >= 0) & (minute < 60)) | midnight_2400)
    return (hour * 60 + minute).where(valid).mask(midnight_2400, 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("zips", nargs="+", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    frames = []
    inventory = []
    exact_hash_chunks = []
    period_mismatch_rows = 0
    for path in args.zips:
        with zipfile.ZipFile(path) as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if len(csv_names) != 1:
                raise ValueError(f"Expected one CSV in {path.name}; found {csv_names}")
            member = csv_names[0]
            info = zf.getinfo(member)
            with zf.open(member) as header_stream:
                full_column_count = len(pd.read_csv(header_stream, nrows=0).columns)
            with zf.open(member) as stream:
                df = pd.read_csv(
                    stream, usecols=USECOLS, dtype={c: "string" for c in STRING_COLS},
                    low_memory=False,
                )
            # Hash the complete 110-column source rows in chunks for an exact
            # duplicate-record diagnostic without retaining the raw table.
            with zf.open(member) as full_stream:
                for full_chunk in pd.read_csv(full_stream, dtype="string", low_memory=False, chunksize=150_000):
                    exact_hash_chunks.append(hash_pandas_object(full_chunk, index=False).to_numpy(dtype=np.uint64))
        for col in NUMERIC_COLS:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["FlightDate"] = pd.to_datetime(df["FlightDate"], format="%Y-%m-%d", errors="coerce")
        for col in ("Reporting_Airline", "Tail_Number", "Flight_Number_Reporting_Airline", "Origin", "Dest"):
            df[col] = df[col].str.strip().str.upper()
        df["Tail_Number"] = df["Tail_Number"].replace({"": pd.NA, "NAN": pd.NA})
        period_match = PERIOD_RE.search(path.name)
        expected_period = None
        mismatch_rows = None
        if period_match:
            expected_period = f"{int(period_match.group(1)):04d}-{int(period_match.group(2)):02d}"
            mismatch_rows = int((df["FlightDate"].dt.to_period("M").astype("string") != expected_period).sum())
            period_mismatch_rows += mismatch_rows
        inventory.append({
            "file": path.name,
            "zip_bytes": path.stat().st_size,
            "csv_member": member,
            "csv_uncompressed_bytes": info.file_size,
            "rows": int(len(df)),
            "columns_in_csv": full_column_count,
            "expected_month": expected_period,
            "rows_outside_expected_month": mismatch_rows,
        })
        frames.append(df)

    data = pd.concat(frames, ignore_index=True)
    data["tail_present"] = data["Tail_Number"].notna()
    data["operated"] = (data["Cancelled"].fillna(0) == 0) & (data["Diverted"].fillna(0) == 0)

    # Flight key is a duplicate diagnostic, not asserted as a guaranteed BTS PK.
    key_cols = ["FlightDate", "DOT_ID_Reporting_Airline", "Flight_Number_Reporting_Airline", "OriginAirportID", "CRSDepTime"]
    duplicate_key_rows = int(data.duplicated(key_cols, keep=False).sum())
    duplicate_key_groups = int(data.loc[data.duplicated(key_cols, keep=False), key_cols].drop_duplicates().shape[0])
    full_hashes = np.concatenate(exact_hash_chunks) if exact_hash_chunks else np.array([], dtype=np.uint64)
    _, full_hash_counts = np.unique(full_hashes, return_counts=True)
    exact_duplicate_rows = int(np.maximum(full_hash_counts - 1, 0).sum())
    exact_duplicate_groups = int((full_hash_counts > 1).sum())

    core_fields = [
        "FlightDate", "Reporting_Airline", "Tail_Number", "Flight_Number_Reporting_Airline",
        "OriginAirportID", "DestAirportID", "CRSDepTime", "DepTime", "DepDelay",
        "CRSArrTime", "ArrTime", "ArrDelay", "Cancelled", "Diverted",
        "CRSElapsedTime", "ActualElapsedTime",
    ]
    missing = []
    for col in core_fields:
        miss = int(data[col].isna().sum())
        missing.append({
            "field": col, "missing_rows": miss,
            "missing_pct": round(100 * miss / len(data), 5) if len(data) else None,
        })

    operated = data[data["operated"]]
    operated_tail = operated[operated["Tail_Number"].notna()]
    tail_counts = operated_tail.groupby("Tail_Number", observed=True).size()
    tail_by_airline = (
        operated.assign(tail_present=operated["Tail_Number"].notna())
        .groupby("Reporting_Airline", observed=True)
        .agg(flights=("FlightDate", "size"), with_tail=("tail_present", "sum"))
        .reset_index()
    )
    tail_by_airline["tail_coverage_pct"] = (100 * tail_by_airline["with_tail"] / tail_by_airline["flights"]).round(4)
    tail_by_airline.to_csv(args.output / "tail_coverage_by_carrier.csv", index=False)

    # This algebraic audit checks whether scheduled HHMM + scheduled elapsed time
    # imply a stable integral-hour UTC-offset difference by route. It is a
    # feasibility diagnostic; it does not yet assert a fully reconstructed chain.
    dep_min = hhmm_minutes(data["CRSDepTime"])
    arr_min = hhmm_minutes(data["CRSArrTime"])
    elapsed = data["CRSElapsedTime"]
    raw = arr_min - dep_min - elapsed
    delta = ((raw + 720) % 1440) - 720
    nearest_hour = (delta / 60).round() * 60
    offset_residual = (delta - nearest_hour).abs()
    data["route_offset_delta_hours"] = (nearest_hour / 60).where(offset_residual <= 2)
    data["offset_residual_minutes"] = offset_residual
    valid_offset = data["route_offset_delta_hours"].notna() & data["operated"]
    route_offset_counts = (
        data.loc[valid_offset]
        .groupby(["OriginAirportID", "DestAirportID", "route_offset_delta_hours"], observed=True)
        .size().rename("flights").reset_index()
    )
    route_totals = route_offset_counts.groupby(["OriginAirportID", "DestAirportID"], observed=True)["flights"].sum().rename("route_flights")
    route_offset_counts = route_offset_counts.join(route_totals, on=["OriginAirportID", "DestAirportID"])
    route_offset_counts["share_of_route"] = route_offset_counts["flights"] / route_offset_counts["route_flights"]
    route_offset_counts.to_csv(args.output / "route_offset_diagnostic.csv", index=False)

    monthly = (
        data.groupby(data["FlightDate"].dt.to_period("M").astype("string"), dropna=False)
        .agg(
            flights=("FlightDate", "size"),
            carriers=("Reporting_Airline", "nunique"),
            origin_airports=("OriginAirportID", "nunique"),
            destination_airports=("DestAirportID", "nunique"),
            tails=("Tail_Number", "nunique"),
            tail_present=("Tail_Number", "count"),
            cancelled=("Cancelled", "sum"),
            diverted=("Diverted", "sum"),
        ).reset_index(names="month")
    )
    monthly["tail_coverage_pct"] = (100 * monthly["tail_present"] / monthly["flights"]).round(4)
    monthly.to_csv(args.output / "monthly_summary.csv", index=False)

    # Event-quality checks: cancellations/diversions can legitimately lack
    # arrival fields; negative delay values are valid (early arrivals).
    operated_labelled = data[data["operated"] & data["ArrDelay"].notna()]
    validation = {
        "flight_date_invalid_rows": int(data["FlightDate"].isna().sum()),
        "rows_outside_zip_expected_month": period_mismatch_rows,
        "invalid_crs_departure_hhmm_rows": int((data["CRSDepTime"].notna() & dep_min.isna()).sum()),
        "invalid_crs_arrival_hhmm_rows": int((data["CRSArrTime"].notna() & arr_min.isna()).sum()),
        "operated_rows": int(data["operated"].sum()),
        "cancelled_rows": int((data["Cancelled"] == 1).sum()),
        "diverted_rows": int((data["Diverted"] == 1).sum()),
        "operated_rows_with_arrdelay": int(data["operated"].sum() and data.loc[data["operated"], "ArrDelay"].notna().sum()),
        "operated_rows_with_tail": int(data.loc[data["operated"], "Tail_Number"].notna().sum()),
        "operated_tail_rows_with_arrdelay": int(operated_labelled["Tail_Number"].notna().sum()),
        "operated_unique_tails": int(operated_tail["Tail_Number"].nunique()),
        "tail_numbers_with_2plus_operated_flights": int((tail_counts >= 2).sum()),
        "tail_numbers_with_10plus_operated_flights": int((tail_counts >= 10).sum()),
        "flight_key_duplicate_rows": duplicate_key_rows,
        "flight_key_duplicate_groups": duplicate_key_groups,
        "route_offset_rows_operated": int(valid_offset.sum()),
        "route_offset_rows_operated_pct": round(100 * valid_offset.sum() / max(int(data["operated"].sum()), 1), 4),
        "route_offset_residual_le_2min_pct": round(100 * (offset_residual[data["operated"]].le(2).sum() / max(int(data["operated"].sum()), 1)), 4),
        "route_offset_non_integral_hour_rows": int((data["operated"] & offset_residual.gt(2)).sum()),
        "exact_full_row_duplicate_rows_by_64bit_hash": exact_duplicate_rows,
        "exact_full_row_duplicate_groups_by_64bit_hash": exact_duplicate_groups,
        "full_row_hashes_compared": int(len(full_hashes)),
    }

    dep_actual_min = hhmm_minutes(data["DepTime"])
    arr_actual_min = hhmm_minutes(data["ArrTime"])
    dep_clock_residual = ((dep_actual_min - dep_min - data["DepDelay"] + 720) % 1440) - 720
    arr_clock_residual = ((arr_actual_min - arr_min - data["ArrDelay"] + 720) % 1440) - 720
    operated_mask = data["operated"]
    time_consistency = {
        "operated_with_valid_actual_departure_clock": int((operated_mask & dep_actual_min.notna()).sum()),
        "operated_departure_delay_clock_match_within_2min": int((operated_mask & dep_actual_min.notna() & data["DepDelay"].notna() & dep_clock_residual.abs().le(2)).sum()),
        "operated_departure_delay_clock_mismatch_gt_2min": int((operated_mask & dep_actual_min.notna() & data["DepDelay"].notna() & dep_clock_residual.abs().gt(2)).sum()),
        "operated_with_valid_actual_arrival_clock": int((operated_mask & arr_actual_min.notna()).sum()),
        "operated_arrival_delay_clock_match_within_2min": int((operated_mask & arr_actual_min.notna() & data["ArrDelay"].notna() & arr_clock_residual.abs().le(2)).sum()),
        "operated_arrival_delay_clock_mismatch_gt_2min": int((operated_mask & arr_actual_min.notna() & data["ArrDelay"].notna() & arr_clock_residual.abs().gt(2)).sum()),
        "operated_arrdelay_median_minutes": float(data.loc[operated_mask, "ArrDelay"].median()),
        "operated_arrdelay_p90_minutes": float(data.loc[operated_mask, "ArrDelay"].quantile(0.9)),
        "operated_arrdelay_p95_minutes": float(data.loc[operated_mask, "ArrDelay"].quantile(0.95)),
        "operated_arrdelay_ge_15_pct": round(100 * float((data.loc[operated_mask, "ArrDelay"] >= 15).mean()), 4),
        "operated_arrdelay_negative_pct": round(100 * float((data.loc[operated_mask, "ArrDelay"] < 0).mean()), 4),
    }

    # Most common inferred offset difference by route, with modal agreement.
    route_modal = route_offset_counts.sort_values("flights", ascending=False).drop_duplicates(["OriginAirportID", "DestAirportID"])
    route_agreement = route_modal["share_of_route"]
    offset_summary = {
        "route_count_with_usable_offset": int(route_modal.shape[0]),
        "route_modal_agreement_median": round(float(route_agreement.median()), 6) if len(route_agreement) else None,
        "route_modal_agreement_p10": round(float(route_agreement.quantile(0.1)), 6) if len(route_agreement) else None,
        "routes_with_modal_agreement_ge_99pct": int((route_agreement >= 0.99).sum()),
        "routes_with_modal_agreement_lt_95pct": int((route_agreement < 0.95).sum()),
        "inferred_offset_difference_distribution": {
            str(int(k)): int(v) for k, v in data.loc[valid_offset, "route_offset_delta_hours"].value_counts().sort_index().items()
        },
    }

    summary = {
        "scope": "BTS Reporting Carrier On-Time Performance; Jan-Mar 2025",
        "source_zip_inventory": inventory,
        "row_count": int(len(data)),
        "column_count_full_csv": int(inventory[0]["columns_in_csv"]),
        "audited_columns": USECOLS,
        "date_min": str(data["FlightDate"].min().date()) if data["FlightDate"].notna().any() else None,
        "date_max": str(data["FlightDate"].max().date()) if data["FlightDate"].notna().any() else None,
        "distinct_reporting_airlines": int(data["Reporting_Airline"].nunique()),
        "distinct_origin_airports": int(data["OriginAirportID"].nunique()),
        "distinct_destination_airports": int(data["DestAirportID"].nunique()),
        "distinct_tail_numbers_all_rows": int(data["Tail_Number"].nunique()),
        "distinct_flight_numbers": int(data["Flight_Number_Reporting_Airline"].nunique()),
        "missingness_core_fields": missing,
        "validation_and_rotation_coverage": validation,
        "delay_clock_consistency_and_target_distribution": time_consistency,
        "route_offset_diagnostic": offset_summary,
        "delay_clock_consistency_and_target_distribution": time_consistency,
        "monthly_summary": monthly.to_dict(orient="records"),
        "important_caveat": "Repeated tail identifiers and route/time consistency are audit evidence, not yet proof that every aircraft rotation can be reconstructed without omitted ferry, non-reporting, or missing-tail legs.",
    }
    (args.output / "audit_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    pd.DataFrame(missing).to_csv(args.output / "core_missingness.csv", index=False)
    print(json.dumps({
        "row_count": summary["row_count"],
        "column_count_full_csv": summary["column_count_full_csv"],
        "date_min": summary["date_min"], "date_max": summary["date_max"],
        "carriers": summary["distinct_reporting_airlines"],
        "origins": summary["distinct_origin_airports"],
        "destinations": summary["distinct_destination_airports"],
        "validation_and_rotation_coverage": validation,
        "route_offset_diagnostic": offset_summary,
        "monthly_summary": summary["monthly_summary"],
        "missingness_core_fields": missing,
    }, indent=2))


if __name__ == "__main__":
    main()
