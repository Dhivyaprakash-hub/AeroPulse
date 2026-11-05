"""Chunked multi-month BTS audit. Reads each ZIP once and writes aggregates only."""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter, defaultdict
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
STR = ["FlightDate", "Reporting_Airline", "Tail_Number", "Flight_Number_Reporting_Airline", "Origin", "Dest"]
NUM = [c for c in USECOLS if c not in STR]
CORE = ["FlightDate", "Reporting_Airline", "Tail_Number", "Flight_Number_Reporting_Airline", "OriginAirportID", "DestAirportID", "CRSDepTime", "DepTime", "DepDelay", "CRSArrTime", "ArrTime", "ArrDelay", "Cancelled", "Diverted", "CRSElapsedTime", "ActualElapsedTime"]
PERIOD_RE = re.compile(r"_(20\d{2})_(\d{1,2})\.zip$", re.IGNORECASE)


def hhmm_minutes(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    h, m = np.floor(x / 100), x % 100
    midnight_2400 = x.eq(2400)
    ok = x.notna() & ((h.ge(0) & h.lt(24) & m.ge(0) & m.lt(60)) | midnight_2400)
    return (h * 60 + m).where(ok).mask(midnight_2400, 0)


def duplicate_counts(hashes: np.ndarray) -> tuple[int, int]:
    if not len(hashes):
        return 0, 0
    counts = np.unique(hashes, return_counts=True)[1]
    return int(np.maximum(counts - 1, 0).sum()), int((counts > 1).sum())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--chunksize", type=int, default=50_000)
    parser.add_argument("zips", nargs="+", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    inventory = []
    key_hashes = []
    missing_counts = Counter()
    unique_carriers, unique_tails, origins, destinations = set(), set(), set(), set()
    operated_tail_counts = Counter()
    carrier_flights, carrier_tail_present = Counter(), Counter()
    route_offsets = Counter()
    delay_arrays = []
    total_rows = operated_total = operated_arrdelay_count = cancelled_total = diverted_total = 0
    invalid_dates = invalid_dep_hhmm = invalid_arr_hhmm = period_mismatch_total = 0
    dep_valid = dep_match = dep_mismatch = arr_valid = arr_match = arr_mismatch = 0
    monthly = []

    for path in args.zips:
        period_match = PERIOD_RE.search(path.name)
        expected_period = f"{int(period_match.group(1)):04d}-{int(period_match.group(2)):02d}" if period_match else None
        file_rows = file_cancelled = file_diverted = file_operated = file_tail = 0
        file_carriers, file_origins, file_destinations, file_tails = set(), set(), set(), set()
        file_date_min = file_date_max = None
        file_period_mismatch = 0
        with zipfile.ZipFile(path) as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if len(csv_names) != 1:
                raise ValueError(f"Expected one CSV in {path.name}; found {csv_names}")
            member = csv_names[0]
            info = zf.getinfo(member)
            with zf.open(member) as hs:
                columns = len(pd.read_csv(hs, nrows=0).columns)
            with zf.open(member) as stream:
                reader = pd.read_csv(stream, usecols=USECOLS, dtype={c: "string" for c in STR}, low_memory=False, chunksize=args.chunksize)
                for chunk in reader:
                    df = chunk
                    key_hashes.append(hash_pandas_object(df[["FlightDate", "DOT_ID_Reporting_Airline", "Flight_Number_Reporting_Airline", "OriginAirportID", "CRSDepTime"]], index=False).to_numpy(dtype=np.uint64))
                    for c in NUM:
                        df[c] = pd.to_numeric(df[c], errors="coerce")
                    df["FlightDate"] = pd.to_datetime(df["FlightDate"], format="%Y-%m-%d", errors="coerce")
                    for c in ("Reporting_Airline", "Tail_Number", "Flight_Number_Reporting_Airline", "Origin", "Dest"):
                        df[c] = df[c].str.strip().str.upper()
                    df["Tail_Number"] = df["Tail_Number"].replace({"": pd.NA, "NAN": pd.NA})

                    file_rows += len(df)
                    total_rows += len(df)
                    for c in CORE:
                        missing_counts[c] += int(df[c].isna().sum())
                    invalid_dates += int(df["FlightDate"].isna().sum())
                    if expected_period:
                        mismatch = df["FlightDate"].dt.to_period("M").astype("string").ne(expected_period)
                        file_period_mismatch += int(mismatch.sum())
                    if df["FlightDate"].notna().any():
                        mn, mx = df["FlightDate"].min(), df["FlightDate"].max()
                        file_date_min = mn if file_date_min is None or mn < file_date_min else file_date_min
                        file_date_max = mx if file_date_max is None or mx > file_date_max else file_date_max

                    for c in ("Reporting_Airline", "Tail_Number", "OriginAirportID", "DestAirportID"):
                        vals = df[c].dropna().unique().tolist()
                        target = {"Reporting_Airline": file_carriers, "Tail_Number": file_tails, "OriginAirportID": file_origins, "DestAirportID": file_destinations}[c]
                        target.update(vals)
                    unique_carriers.update(df["Reporting_Airline"].dropna().unique().tolist())
                    unique_tails.update(df["Tail_Number"].dropna().unique().tolist())
                    origins.update(df["OriginAirportID"].dropna().unique().tolist())
                    destinations.update(df["DestAirportID"].dropna().unique().tolist())

                    operated = df["Cancelled"].fillna(0).eq(0) & df["Diverted"].fillna(0).eq(0)
                    cancelled = df["Cancelled"].eq(1)
                    diverted = df["Diverted"].eq(1)
                    op = df.loc[operated]
                    file_operated += int(operated.sum())
                    file_cancelled += int(cancelled.sum())
                    file_diverted += int(diverted.sum())
                    operated_total += int(operated.sum())
                    operated_arrdelay_count += int(op["ArrDelay"].notna().sum())
                    cancelled_total += int(cancelled.sum())
                    diverted_total += int(diverted.sum())
                    file_tail += int(op["Tail_Number"].notna().sum())
                    file_carriers_flights = op.groupby("Reporting_Airline", observed=True).size()
                    carrier_flights.update(file_carriers_flights.to_dict())
                    carrier_tail_present.update(op.groupby("Reporting_Airline", observed=True)["Tail_Number"].count().to_dict())
                    operated_tail_counts.update(op.loc[op["Tail_Number"].notna()].groupby("Tail_Number", observed=True).size().to_dict())
                    if op["ArrDelay"].notna().any():
                        delay_arrays.append(op.loc[op["ArrDelay"].notna(), "ArrDelay"].to_numpy(dtype=np.float32))

                    dep_min, arr_min = hhmm_minutes(df["CRSDepTime"]), hhmm_minutes(df["CRSArrTime"])
                    invalid_dep_hhmm += int((df["CRSDepTime"].notna() & dep_min.isna()).sum())
                    invalid_arr_hhmm += int((df["CRSArrTime"].notna() & arr_min.isna()).sum())
                    raw = arr_min - dep_min - df["CRSElapsedTime"]
                    delta = ((raw + 720) % 1440) - 720
                    nearest = (delta / 60).round() * 60
                    residual = (delta - nearest).abs()
                    route_ok = operated & residual.le(2)
                    route_frame = df.loc[route_ok, ["OriginAirportID", "DestAirportID"]].copy()
                    route_frame["hours"] = (nearest[route_ok] / 60).astype("int16")
                    route_offsets.update(route_frame.value_counts().to_dict())

                    dep_actual, arr_actual = hhmm_minutes(df["DepTime"]), hhmm_minutes(df["ArrTime"])
                    dr = ((dep_actual - dep_min - df["DepDelay"] + 720) % 1440) - 720
                    ar = ((arr_actual - arr_min - df["ArrDelay"] + 720) % 1440) - 720
                    valid = operated & dep_actual.notna() & df["DepDelay"].notna()
                    dep_valid += int(valid.sum())
                    dep_match += int((valid & dr.abs().le(2)).sum())
                    dep_mismatch += int((valid & dr.abs().gt(2)).sum())
                    valid = operated & arr_actual.notna() & df["ArrDelay"].notna()
                    arr_valid += int(valid.sum())
                    arr_match += int((valid & ar.abs().le(2)).sum())
                    arr_mismatch += int((valid & ar.abs().gt(2)).sum())

        period_mismatch_total += file_period_mismatch
        inventory.append({
            "file": path.name, "zip_bytes": path.stat().st_size, "csv_member": member,
            "csv_uncompressed_bytes": info.file_size, "rows": file_rows,
            "columns_in_csv": columns, "expected_month": expected_period,
            "rows_outside_expected_month": file_period_mismatch,
            "date_min": str(file_date_min.date()) if file_date_min is not None else None,
            "date_max": str(file_date_max.date()) if file_date_max is not None else None,
        })
        monthly.append({
            "month": expected_period, "flights": file_rows, "carriers": len(file_carriers),
            "origin_airports": len(file_origins), "destination_airports": len(file_destinations),
            "tails": len(file_tails), "tail_present": file_tail,
            "cancelled": file_cancelled, "diverted": file_diverted,
            "tail_coverage_pct": round(100 * file_tail / file_rows, 4) if file_rows else None,
        })
        print(f"Audited {path.name}: {file_rows:,} rows", flush=True)

    key_hashes = np.concatenate(key_hashes) if key_hashes else np.array([], dtype=np.uint64)
    key_duplicate_rows, key_duplicate_groups = duplicate_counts(key_hashes)
    delays = np.concatenate(delay_arrays) if delay_arrays else np.array([], dtype=np.float32)

    route_counts = pd.DataFrame([{"OriginAirportID": k[0], "DestAirportID": k[1], "route_offset_delta_hours": k[2], "flights": v} for k, v in route_offsets.items()])
    route_counts["route_flights"] = route_counts.groupby(["OriginAirportID", "DestAirportID"])["flights"].transform("sum")
    route_counts["share_of_route"] = route_counts["flights"] / route_counts["route_flights"]
    route_modal = route_counts.sort_values("flights", ascending=False).drop_duplicates(["OriginAirportID", "DestAirportID"])
    route_counts.to_csv(args.output / "route_offset_diagnostic.csv", index=False)
    route_agreement = route_modal["share_of_route"]
    route_offset_distribution = route_counts.groupby("route_offset_delta_hours")["flights"].sum().sort_index()

    missing = [{"field": c, "missing_rows": int(missing_counts[c]), "missing_pct": round(100 * missing_counts[c] / max(total_rows, 1), 5)} for c in CORE]
    tail_by_airline = pd.DataFrame([{"Reporting_Airline": k, "flights": v, "with_tail": carrier_tail_present[k], "tail_coverage_pct": round(100 * carrier_tail_present[k] / v, 4) if v else None} for k, v in carrier_flights.items()]).sort_values("Reporting_Airline")
    tail_by_airline.to_csv(args.output / "tail_coverage_by_carrier.csv", index=False)
    pd.DataFrame(missing).to_csv(args.output / "core_missingness.csv", index=False)
    pd.DataFrame(monthly).sort_values("month").to_csv(args.output / "monthly_summary.csv", index=False)

    summary = {
        "scope": f"BTS Reporting Carrier On-Time Performance; {len(args.zips)} monthly archives",
        "source_zip_inventory": inventory,
        "row_count": total_rows, "column_count_full_csv": int(inventory[0]["columns_in_csv"]) if inventory else 0,
        "audited_columns": USECOLS,
        "date_min": min((i["date_min"] for i in inventory if i["date_min"]), default=None),
        "date_max": max((i["date_max"] for i in inventory if i["date_max"]), default=None),
        "distinct_reporting_airlines": len(unique_carriers), "distinct_origin_airports": len(origins),
        "distinct_destination_airports": len(destinations), "distinct_tail_numbers_all_rows": len(unique_tails),
        "missingness_core_fields": missing,
        "validation_and_rotation_coverage": {
            "invalid_flight_dates": invalid_dates, "rows_outside_zip_expected_month": period_mismatch_total,
            "invalid_crs_departure_hhmm_rows": invalid_dep_hhmm, "invalid_crs_arrival_hhmm_rows": invalid_arr_hhmm,
            "operated_rows": operated_total, "cancelled_rows": cancelled_total, "diverted_rows": diverted_total,
            "operated_rows_with_arrdelay": operated_arrdelay_count,
            "operated_rows_with_tail": sum(operated_tail_counts.values()), "operated_unique_tails": len(operated_tail_counts),
            "tail_numbers_with_2plus_operated_flights": sum(v >= 2 for v in operated_tail_counts.values()),
            "tail_numbers_with_10plus_operated_flights": sum(v >= 10 for v in operated_tail_counts.values()),
            "candidate_flight_key_duplicate_rows_by_64bit_hash": key_duplicate_rows,
            "candidate_flight_key_duplicate_groups_by_64bit_hash": key_duplicate_groups,
            "expanded_period_full_row_duplicate_scan": "not repeated; exact full-row check is available for the Q1 2025 pilot audit",
        },
        "delay_clock_consistency_and_target_distribution": {
            "operated_with_valid_actual_departure_clock": dep_valid,
            "operated_departure_delay_clock_match_within_2min": dep_match,
            "operated_departure_delay_clock_mismatch_gt_2min": dep_mismatch,
            "operated_with_valid_actual_arrival_clock": arr_valid,
            "operated_arrival_delay_clock_match_within_2min": arr_match,
            "operated_arrival_delay_clock_mismatch_gt_2min": arr_mismatch,
            "operated_arrdelay_median_minutes": float(np.median(delays)) if len(delays) else None,
            "operated_arrdelay_p90_minutes": float(np.quantile(delays, .9)) if len(delays) else None,
            "operated_arrdelay_p95_minutes": float(np.quantile(delays, .95)) if len(delays) else None,
            "operated_arrdelay_ge_15_pct": round(100 * float((delays >= 15).mean()), 4) if len(delays) else None,
            "operated_arrdelay_negative_pct": round(100 * float((delays < 0).mean()), 4) if len(delays) else None,
        },
        "route_offset_diagnostic": {
            "route_count_with_usable_offset": int(len(route_modal)),
            "route_modal_agreement_median": float(route_agreement.median()) if len(route_agreement) else None,
            "route_modal_agreement_p10": float(route_agreement.quantile(.1)) if len(route_agreement) else None,
            "routes_with_modal_agreement_ge_99pct": int((route_agreement >= .99).sum()),
            "routes_with_modal_agreement_lt_95pct": int((route_agreement < .95).sum()),
            "inferred_offset_difference_distribution": {str(int(k)): int(v) for k, v in route_offset_distribution.items()},
        },
        "monthly_summary": monthly,
        "important_caveat": "All results describe BTS-reported operations; inferred tail chains may omit ferry, maintenance, non-reporting, or other unobserved legs.",
    }
    (args.output / "audit_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"row_count": total_rows, "date_min": summary["date_min"], "date_max": summary["date_max"], "validation": summary["validation_and_rotation_coverage"], "delay_metrics": summary["delay_clock_consistency_and_target_distribution"], "route_metrics": summary["route_offset_diagnostic"]}, indent=2))


if __name__ == "__main__":
    main()
