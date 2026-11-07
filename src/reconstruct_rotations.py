"""Assess same-aircraft consecutive legs using schedule-derived time offsets.

The method infers airport UTC-offset differences from BTS scheduled local HHMM
times and CRSElapsedTime, then checks route consistency against an ATL anchor
using IANA America/New_York. It is an audit method, not a substitute for a
published BTS UTC timestamp. Optional row-level pilot features are written only
when explicitly requested and should remain outside the public repository.
"""
from __future__ import annotations

import argparse
import json
import zipfile
from collections import defaultdict, deque
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


COLS = [
    "FlightDate", "Tail_Number", "OriginAirportID", "Origin", "DestAirportID",
    "Dest", "CRSDepTime", "DepDelay", "CRSArrTime", "ArrDelay", "Cancelled",
    "Diverted", "CRSElapsedTime",
]
FEATURE_COLS = ["Reporting_Airline", "Distance"]
STR = ["FlightDate", "Tail_Number", "Origin", "Dest", "Reporting_Airline"]
NUM = [c for c in COLS + FEATURE_COLS if c not in STR]
ANCHOR_CODE = "ATL"


def hhmm_minutes(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    h, m = np.floor(x / 100), x % 100
    midnight_2400 = x.eq(2400)
    ok = x.notna() & (((h >= 0) & (h < 24) & (m >= 0) & (m < 60)) | midnight_2400)
    return (h * 60 + m).where(ok).mask(midnight_2400, 0)


def regime(local_date: pd.Series, local_min: pd.Series) -> pd.Series:
    year = local_date.dt.year
    march_first = pd.to_datetime(year.astype("Int64").astype("string") + "-03-01", errors="coerce")
    nov_first = pd.to_datetime(year.astype("Int64").astype("string") + "-11-01", errors="coerce")
    # US daylight-saving time starts on the second Sunday in March at 02:00
    # and ends on the first Sunday in November at 02:00 (rules since 2007).
    start_day = march_first + pd.to_timedelta((6 - march_first.dt.dayofweek) % 7 + 7, unit="D")
    end_day = nov_first + pd.to_timedelta((6 - nov_first.dt.dayofweek) % 7, unit="D")
    before_start = (local_date < start_day) | ((local_date == start_day) & (local_min < 120))
    after_end = (local_date > end_day) | ((local_date == end_day) & (local_min >= 120))
    return pd.Series(np.where(before_start | after_end, "EST", "EDT"), index=local_date.index)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--feature-output", type=Path, help="Optional local CSV.GZ for a temporary model pilot; do not publish row-level data.")
    p.add_argument("zips", nargs="+", type=Path)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    pieces = []
    atl_id_values: set[int] = set()
    for path in args.zips:
        read_cols = COLS + (FEATURE_COLS if args.feature_output else [])
        read_types = {c: "string" for c in ("FlightDate", "Tail_Number", "Origin", "Dest")}
        if args.feature_output:
            read_types["Reporting_Airline"] = "string"
        with zipfile.ZipFile(path) as zf:
            csv_name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
            with zf.open(csv_name) as stream:
                df = pd.read_csv(stream, usecols=read_cols, dtype=read_types, low_memory=False)
        for c in NUM:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce", downcast="float" if c in ("DepDelay", "ArrDelay", "Distance") else "integer")
        df["FlightDate"] = pd.to_datetime(df["FlightDate"], format="%Y-%m-%d", errors="coerce")
        for c in ["Tail_Number", "Origin", "Dest"]:
            df[c] = df[c].str.strip().str.upper()
        df["Tail_Number"] = df["Tail_Number"].replace({"": pd.NA, "NAN": pd.NA})
        atl_id_values.update(df.loc[df["Origin"] == ANCHOR_CODE, "OriginAirportID"].dropna().astype(int).unique().tolist())
        atl_id_values.update(df.loc[df["Dest"] == ANCHOR_CODE, "DestAirportID"].dropna().astype(int).unique().tolist())
        df["operated"] = df["Cancelled"].fillna(0).eq(0) & df["Diverted"].fillna(0).eq(0)
        df = df[df["operated"] & df["Tail_Number"].notna() & df["ArrDelay"].notna()].copy()
        df["Tail_Number"] = pd.util.hash_pandas_object(df["Tail_Number"], index=False).to_numpy(dtype=np.uint64)
        df = df.drop(columns=["Origin", "Dest", "Cancelled", "Diverted", "operated"])
        pieces.append(df)
        print(f"Loaded {path.name}: {len(df):,} operated tail flights", flush=True)
    x = pd.concat(pieces, ignore_index=True)

    dep_min = hhmm_minutes(x["CRSDepTime"])
    arr_min = hhmm_minutes(x["CRSArrTime"])
    raw_delta = arr_min - dep_min - x["CRSElapsedTime"]
    delta_min = ((raw_delta + 720) % 1440) - 720
    nearest = (delta_min / 60).round() * 60
    residual = (delta_min - nearest).abs()
    x["offset_delta_min"] = nearest.where(residual <= 2)
    x["offset_residual"] = residual
    dep_day_roll = pd.to_numeric(x["CRSDepTime"], errors="coerce").eq(2400).astype("int16")
    x["sched_arr_day_roll"] = ((dep_min + dep_day_roll * 1440 + x["CRSElapsedTime"] + x["offset_delta_min"] - arr_min) / 1440).round()
    x["sched_dep_local"] = x["FlightDate"] + pd.to_timedelta(dep_min + dep_day_roll * 1440, unit="m")
    x["sched_arr_date"] = x["FlightDate"] + pd.to_timedelta(x["sched_arr_day_roll"], unit="D")
    x["sched_arr_min"] = arr_min
    x["dep_regime"] = regime(x["sched_dep_local"].dt.normalize(), x["sched_dep_local"].dt.hour * 60 + x["sched_dep_local"].dt.minute)
    x["arr_regime"] = regime(x["sched_arr_date"], arr_min)
    x["regime_consistent"] = x["dep_regime"] == x["arr_regime"]

    # Find the BTS AirportID for the known Eastern-time anchor ATL.
    if len(atl_id_values) != 1:
        raise RuntimeError(f"ATL airport ID not unique in period: {sorted(atl_id_values)}")
    atl_id = next(iter(atl_id_values))

    # Infer relative airport offsets separately in EST and EDT regimes.
    potential_by_regime: dict[str, dict[int, int]] = {}
    graph_diagnostics = {}
    for r in ("EST", "EDT"):
        sub = x[(x["dep_regime"] == r) & x["regime_consistent"] & x["offset_delta_min"].notna()]
        route = (
            sub.groupby(["OriginAirportID", "DestAirportID", "offset_delta_min"], dropna=True)
            .size().rename("n").reset_index()
        )
        totals = route.groupby(["OriginAirportID", "DestAirportID"])["n"].sum().rename("total")
        route = route.join(totals, on=["OriginAirportID", "DestAirportID"])
        route["share"] = route["n"] / route["total"]
        route = route.sort_values("n", ascending=False).drop_duplicates(["OriginAirportID", "DestAirportID"])
        route = route[route["share"] >= 0.98]
        adj: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
        for row in route.itertuples(index=False):
            a, b, d = int(row.OriginAirportID), int(row.DestAirportID), int(row.offset_delta_min)
            if d % 60 != 0:
                continue
            h = d // 60
            adj[a].append((b, h, int(row.n)))
            adj[b].append((a, -h, int(row.n)))
        for node in adj:
            adj[node].sort(key=lambda e: e[2], reverse=True)
        offset = {atl_id: 0}
        q = deque([atl_id])
        conflicts = 0
        while q:
            a = q.popleft()
            for b, dh, _ in adj.get(a, []):
                proposed = offset[a] + dh
                if b not in offset:
                    offset[b] = proposed
                    q.append(b)
                elif offset[b] != proposed:
                    conflicts += 1
        potential_by_regime[r] = offset
        graph_diagnostics[r] = {
            "stable_route_edges_ge_98pct_agreement": int(len(route)),
            "airports_reached_from_ATL": int(len(offset)),
            "airports_in_audit": int(pd.concat([sub["OriginAirportID"], sub["DestAirportID"]]).nunique()),
            "cycle_conflicts_encountered_during_spanning_walk": int(conflicts),
        }

    # Anchor the relative offset graph with the known IANA zone for Atlanta.
    def anchor_offset_hours(r: str) -> int:
        date = pd.Timestamp("2025-01-15" if r == "EST" else "2025-03-15")
        return int(ZoneInfo("America/New_York").utcoffset(date.to_pydatetime()).total_seconds() // 3600)

    # Create flight timestamps only for flights whose two airport regimes are
    # covered by the inferred graph; special DST-switch-crossing flights are
    # excluded from this first pass.
    x["origin_utc_offset_h"] = np.nan
    x["dest_utc_offset_h"] = np.nan
    for r, offset_map in potential_by_regime.items():
        origin_mask = x["dep_regime"].eq(r)
        destination_mask = x["arr_regime"].eq(r)
        x.loc[origin_mask, "origin_utc_offset_h"] = (
            x.loc[origin_mask, "OriginAirportID"].map(offset_map) + anchor_offset_hours(r)
        )
        x.loc[destination_mask, "dest_utc_offset_h"] = (
            x.loc[destination_mask, "DestAirportID"].map(offset_map) + anchor_offset_hours(r)
        )

    # Scheduled and actual local datetimes. BTS ArrDelay/DepDelay are elapsed
    # minutes relative to their respective scheduled local timestamps.
    x["sched_arr_local"] = x["sched_arr_date"] + pd.to_timedelta(arr_min, unit="m")
    x["actual_dep_local"] = x["sched_dep_local"] + pd.to_timedelta(x["DepDelay"], unit="m")
    x["actual_arr_local"] = x["sched_arr_local"] + pd.to_timedelta(x["ArrDelay"], unit="m")
    x["actual_arr_regime"] = regime(x["actual_arr_local"].dt.normalize(), x["actual_arr_local"].dt.hour * 60 + x["actual_arr_local"].dt.minute)
    # Correct destination offsets for actual arrival if a late flight crosses
    # the March DST boundary. The current graph has both EST and EDT potentials.
    x["actual_dest_utc_offset_h"] = np.nan
    for r, offset_map in potential_by_regime.items():
        mask = x["actual_arr_regime"].eq(r)
        x.loc[mask, "actual_dest_utc_offset_h"] = (
            x.loc[mask, "DestAirportID"].map(offset_map) + anchor_offset_hours(r)
        )
    x["sched_dep_utc"] = x["sched_dep_local"] - pd.to_timedelta(x["origin_utc_offset_h"], unit="h")
    x["actual_dep_utc"] = x["actual_dep_local"] - pd.to_timedelta(x["origin_utc_offset_h"], unit="h")
    x["actual_arr_utc"] = x["actual_arr_local"] - pd.to_timedelta(x["actual_dest_utc_offset_h"], unit="h")

    usable = x[
        x["origin_utc_offset_h"].notna() & x["actual_dest_utc_offset_h"].notna()
        & x["actual_dep_utc"].notna() & x["actual_arr_utc"].notna()
    ].copy()
    # Dedupe physical records that share tail, actual departure, and route.
    physical_key = ["Tail_Number", "actual_dep_utc", "OriginAirportID", "DestAirportID"]
    duplicate_physical_rows = int(usable.duplicated(physical_key, keep=False).sum())
    usable = usable.sort_values(["Tail_Number", "actual_dep_utc", "actual_arr_utc"])
    usable = usable.drop_duplicates(physical_key, keep="first")
    usable["prev_tail"] = usable["Tail_Number"].shift(1)
    usable["prev_arrival_utc"] = usable["actual_arr_utc"].shift(1)
    usable["prev_dest_id"] = usable["DestAirportID"].shift(1)
    usable["prev_arr_delay"] = usable["ArrDelay"].shift(1)
    usable["prev_dep_delay"] = usable["DepDelay"].shift(1)
    usable["prev_flight_date"] = usable["FlightDate"].shift(1)
    same_tail_previous_row = usable["Tail_Number"] == usable["prev_tail"]
    same_airport = usable["OriginAirportID"] == usable["prev_dest_id"]
    same_tail_airport = same_tail_previous_row & same_airport
    cutoff_utc = usable["sched_dep_utc"] - pd.Timedelta(minutes=60)
    previous_available = usable["prev_arrival_utc"] <= cutoff_utc
    valid_previous = same_tail_airport & previous_available
    month_labels = usable["FlightDate"].dt.to_period("M").astype("string")
    usable["same_tail_previous_row"] = same_tail_previous_row
    usable["same_tail_and_airport_as_previous"] = same_tail_airport
    usable["valid_previous_leg_at_60m_cutoff"] = valid_previous
    usable["month"] = month_labels
    monthly_links = (
        usable
        .groupby("month")
        .agg(
            operated_tail_flights=("Tail_Number", "size"),
            consecutive_same_tail_same_airport=("same_tail_and_airport_as_previous", "sum"),
            previous_arrived_at_least_60m_before_sched_dep=("valid_previous_leg_at_60m_cutoff", "sum"),
            distinct_tails=("Tail_Number", "nunique"),
        ).reset_index()
    )
    monthly_links.to_csv(args.output / "rotation_links_by_month.csv", index=False)
    schema_cols = [
        "FlightDate", "Tail_Number", "OriginAirportID", "DestAirportID", "CRSDepTime",
        "CRSElapsedTime", "ArrDelay", "DepDelay", "prev_flight_date", "prev_arr_delay",
        "prev_dep_delay", "sched_dep_utc", "prev_arrival_utc",
    ]
    if "Reporting_Airline" in usable.columns:
        schema_cols.insert(1, "Reporting_Airline")
    if "Distance" in usable.columns:
        schema_cols.append("Distance")
    usable.loc[valid_previous, schema_cols].head(0).to_csv(args.output / "candidate_link_schema.csv", index=False)

    # Additional diagnostics: transition conditions, duplicated physical keys,
    # and clock-delta confirmation against HHMM arithmetic.
    gap = usable["sched_dep_utc"] - usable["prev_arrival_utc"]
    actual_turn_gap = usable["actual_dep_utc"] - usable["prev_arrival_utc"]
    paired_gap = actual_turn_gap[same_tail_airport].dt.total_seconds() / 60
    if args.feature_output:
        candidate_features = usable.loc[valid_previous, [
            "FlightDate", "Reporting_Airline", "OriginAirportID", "DestAirportID",
            "CRSDepTime", "CRSElapsedTime", "Distance", "ArrDelay",
            "prev_arr_delay", "prev_dep_delay",
        ]].copy()
        candidate_features["scheduled_dep_hour"] = np.floor(
            pd.to_numeric(candidate_features["CRSDepTime"], errors="coerce") / 100
        ).astype("Int16")
        scheduled_dep_date = candidate_features["FlightDate"] + pd.to_timedelta(
            pd.to_numeric(candidate_features["CRSDepTime"], errors="coerce").eq(2400).astype("int16"), unit="D"
        )
        candidate_features["scheduled_dep_dow"] = scheduled_dep_date.dt.dayofweek.astype("Int8")
        candidate_features["scheduled_dep_month"] = scheduled_dep_date.dt.month.astype("Int8")
        candidate_features["turnaround_gap_min"] = gap[valid_previous].dt.total_seconds() / 60
        candidate_features["actual_turn_gap_min"] = actual_turn_gap[valid_previous].dt.total_seconds() / 60
        args.feature_output.parent.mkdir(parents=True, exist_ok=True)
        candidate_features.to_csv(args.feature_output, index=False, compression="gzip")
    summary = {
        "method": "Schedule-derived UTC-offset differences (CRS local HHMM and CRSElapsedTime), anchored to Atlanta via IANA America/New_York; consecutive reported flights ordered by actual departure UTC; previous leg must arrive >=60 minutes before target scheduled departure.",
        "dst_transition_boundary": "Flights whose scheduled origin and destination local timestamps fall on different US EST/EDT regimes are excluded from the first-pass offset graph; regime dates use the US second-Sunday-in-March and first-Sunday-in-November rules for each year.",
        "atl_airport_id": atl_id,
        "offset_graph_by_regime": graph_diagnostics,
        "operated_tail_flights_loaded": int(len(x)),
        "flights_with_inferred_origin_and_arrival_offsets": int(len(usable)),
        "coverage_pct_of_operated_tail_flights": round(100 * len(usable) / max(len(x), 1), 4),
        "dst_regime_crossing_rows_excluded": int((~x["regime_consistent"]).sum()),
        "unmapped_origin_offset_rows": int(x["origin_utc_offset_h"].isna().sum()),
        "unmapped_actual_arrival_offset_rows": int(x["actual_dest_utc_offset_h"].isna().sum()),
        "duplicate_physical_key_rows_before_dedup": duplicate_physical_rows,
        "same_tail_and_connecting_airport_adjacent_observations": int(same_tail_airport.sum()),
        "previous_leg_arrived_by_60_min_prediction_cutoff": int(valid_previous.sum()),
        "same_tail_airport_pairs_arrival_after_cutoff": int((same_tail_airport & ~previous_available).sum()),
        "median_scheduled_gap_after_previous_actual_arrival_minutes": round(float(gap[same_tail_airport].dt.total_seconds().median() / 60), 3) if same_tail_airport.any() else None,
        "p01_scheduled_gap_after_previous_actual_arrival_minutes": round(float(gap[same_tail_airport].dt.total_seconds().quantile(0.01) / 60), 3) if same_tail_airport.any() else None,
        "negative_gap_pairs": int((same_tail_airport & (gap < pd.Timedelta(0))).sum()),
        "actual_turnaround_gap_minutes": {
            "pairs": int(paired_gap.notna().sum()),
            "negative_pairs": int((paired_gap < 0).sum()),
            "under_15_min_pairs": int((paired_gap < 15).sum()),
            "median": round(float(paired_gap.median()), 3),
            "p01": round(float(paired_gap.quantile(0.01)), 3),
            "p99": round(float(paired_gap.quantile(0.99)), 3),
        },
        "linked_targets_by_month": monthly_links.to_dict(orient="records"),
        "limitations": [
            "BTS local-time fields do not directly provide UTC timestamps; inferred airport offsets depend on scheduled elapsed-time consistency and a known Atlanta anchor.",
            "Non-reporting, ferry, maintenance, or otherwise omitted legs may interrupt observed BTS tail sequences.",
            "The first archive boundary can hide a previous leg outside the supplied window.",
            "The 60-minute cutoff is a prespecified analytical choice for this audit, not a claim about airline decision practice.",
        ],
    }
    (args.output / "rotation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
