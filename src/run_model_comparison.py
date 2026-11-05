"""Temporal pilot comparing schedule-only and previous-leg delay features.

Uses an interpretable additive fixed-effect model implemented with NumPy/Pandas
so the analysis can run in the bundled runtime without external ML libraries.
The raw candidate table is temporary and should not be committed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

CAT_COLS = ["Reporting_Airline", "OriginAirportID", "DestAirportID", "route_code", "scheduled_dep_hour", "scheduled_dep_dow", "scheduled_dep_month", "route_hour_code"]


def build_numeric(frame: pd.DataFrame, cols: list[str], fit_mask: np.ndarray):
    raw = frame[cols].to_numpy(dtype=np.float64, copy=True)
    raw[~np.isfinite(raw)] = np.nan
    train = raw[fit_mask]
    medians = np.nanmedian(train, axis=0)
    raw = np.where(np.isnan(raw), medians, raw)
    means = raw[fit_mask].mean(axis=0)
    scales = raw[fit_mask].std(axis=0)
    scales[scales < 1e-8] = 1.0
    return ((raw - means) / scales).astype(np.float32), (medians, means, scales)


def fit_additive(cats_train, levels, x_train, y_train, alpha: float, passes: int = 4):
    effects = [np.zeros(n, dtype=np.float32) for n in levels]
    category_prediction = np.zeros(len(y_train), dtype=np.float32)
    beta = np.zeros(x_train.shape[1], dtype=np.float64)
    intercept = float(np.mean(y_train))
    xtx = x_train.T @ x_train
    ridge = np.eye(x_train.shape[1], dtype=np.float64) * 1e-2
    for _ in range(passes):
        for j, codes in enumerate(cats_train):
            current = effects[j]
            residual = y_train - intercept - x_train @ beta - category_prediction + current[codes]
            counts = np.bincount(codes, minlength=levels[j]).astype(np.float64)
            sums = np.bincount(codes, weights=residual, minlength=levels[j])
            updated = (sums / (counts + alpha)).astype(np.float32)
            category_prediction += updated[codes] - current[codes]
            effects[j] = updated
        residual = y_train - intercept - category_prediction
        beta = np.linalg.solve(xtx + ridge, x_train.T @ residual)
        intercept = float(np.mean(y_train - category_prediction - x_train @ beta))
    return {"effects": effects, "beta": beta, "intercept": intercept}


def predict_additive(model, cats, x):
    pred = np.full(len(x), model["intercept"], dtype=np.float64)
    for effect, codes in zip(model["effects"], cats):
        pred += effect[codes]
    pred += x @ model["beta"]
    return pred.astype(np.float32)


def metrics(y, pred):
    err = pred.astype(np.float64) - y.astype(np.float64)
    return {"rows": int(len(y)), "mae_minutes": float(np.mean(np.abs(err))), "rmse_minutes": float(np.sqrt(np.mean(err ** 2))), "r2": float(1 - np.sum(err ** 2) / np.sum((y - y.mean()) ** 2))}


def daily_bootstrap(y, pred_a, pred_b, dates, seed=214):
    rows = pd.DataFrame({
        "date": dates,
        "abs_a": np.abs(pred_a.astype(np.float64) - y.astype(np.float64)),
        "abs_b": np.abs(pred_b.astype(np.float64) - y.astype(np.float64)),
    }).groupby("date", observed=True).mean()
    delta = (rows["abs_a"] - rows["abs_b"]).to_numpy()
    rng = np.random.default_rng(seed)
    reps = np.empty(1500, dtype=np.float64)
    for i in range(len(reps)):
        reps[i] = rng.choice(delta, size=len(delta), replace=True).mean()
    return {"days": int(len(delta)), "mae_improvement_b_minus_a_minutes": float(delta.mean()), "paired_day_bootstrap_95pct_ci": [float(np.quantile(reps, .025)), float(np.quantile(reps, .975))]}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--features", required=True, type=Path)
    p.add_argument("--route-diagnostics", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    dtypes = {
        "Reporting_Airline": "category", "OriginAirportID": "int32", "DestAirportID": "int32",
        "CRSDepTime": "int16", "CRSElapsedTime": "float32", "Distance": "float32",
        "ArrDelay": "float32", "prev_arr_delay": "float32", "prev_dep_delay": "float32",
        "scheduled_dep_hour": "int8", "scheduled_dep_dow": "int8", "scheduled_dep_month": "int8",
        "turnaround_gap_min": "float32", "actual_turn_gap_min": "float32",
    }
    frame = pd.read_csv(args.features, compression="gzip", dtype=dtypes, parse_dates=["FlightDate"])
    frame = frame[frame["FlightDate"].dt.year.isin([2024, 2025, 2026])].copy()
    frame["route_code"] = (frame["OriginAirportID"].astype(np.int64) * 20000 + frame["DestAirportID"].astype(np.int64)).astype(np.int32)
    route_diagnostics = pd.read_csv(args.route_diagnostics)
    route_diagnostics["route_code"] = (route_diagnostics["OriginAirportID"].astype(np.int64) * 20000 + route_diagnostics["DestAirportID"].astype(np.int64)).astype(np.int32)
    route_confidence = route_diagnostics.groupby("route_code", observed=True)["share_of_route"].max()
    frame["route_offset_agreement"] = frame["route_code"].map(route_confidence).fillna(0).astype("float32")
    frame["route_hour_code"] = (pd.factorize(pd.MultiIndex.from_arrays([frame["route_code"], frame["scheduled_dep_hour"]]), sort=False)[0]).astype(np.int32)
    cat_arrays, levels = [], []
    for c in CAT_COLS:
        codes, uniques = pd.factorize(frame[c], sort=False)
        cat_arrays.append(codes.astype(np.int32))
        levels.append(len(uniques))
    all_cats = cat_arrays
    year = frame["FlightDate"].dt.year.to_numpy()
    masks = {y: year == y for y in (2024, 2025, 2026)}
    if not all(masks[y].any() for y in (2024, 2025, 2026)):
        raise ValueError("Feature table must include training 2024, validation 2025, and test 2026.")
    target_raw = frame["ArrDelay"].to_numpy(dtype=np.float32)
    target_fit = np.clip(target_raw, -120, 900).astype(np.float32)
    base_num_cols = ["CRSElapsedTime", "Distance"]
    prior_num_cols = ["prev_arr_delay", "prev_dep_delay", "turnaround_gap_min"]
    frame["prev_dep_delay_missing"] = frame["prev_dep_delay"].isna().astype("float32")
    prior_num_cols.append("prev_dep_delay_missing")
    candidates = [10.0, 50.0, 200.0]

    validation_results = []
    selected_alpha = {}
    for name, numeric_cols in (("A_schedule_only", base_num_cols), ("B_plus_previous_leg", base_num_cols + prior_num_cols)):
        x_all, _stats = build_numeric(frame, numeric_cols, masks[2024])
        tr, va = masks[2024], masks[2025]
        cats_tr = [a[tr] for a in all_cats]
        cats_va = [a[va] for a in all_cats]
        best = None
        for alpha in candidates:
            model = fit_additive(cats_tr, levels, x_all[tr], target_fit[tr], alpha)
            pred = predict_additive(model, cats_va, x_all[va])
            result = {"model": name, "category_shrinkage": alpha, **metrics(target_raw[va], pred)}
            validation_results.append(result)
            if best is None or result["mae_minutes"] < best["mae_minutes"]:
                best = result
        selected_alpha[name] = best["category_shrinkage"]

    test_metrics = {}
    test_predictions = {}
    test_x = {}
    tr = masks[2024] | masks[2025]
    te = masks[2026]
    for name, numeric_cols in (("A_schedule_only", base_num_cols), ("B_plus_previous_leg", base_num_cols + prior_num_cols)):
        x_all, _stats = build_numeric(frame, numeric_cols, tr)
        cats_tr = [a[tr] for a in all_cats]
        cats_te = [a[te] for a in all_cats]
        model = fit_additive(cats_tr, levels, x_all[tr], target_fit[tr], selected_alpha[name])
        pred = predict_additive(model, cats_te, x_all[te])
        test_metrics[name] = metrics(target_raw[te], pred)
        test_predictions[name] = pred

    y_test = target_raw[te]
    test_dates = frame.loc[te, "FlightDate"].dt.date.astype("string").to_numpy()
    pred_a, pred_b = test_predictions["A_schedule_only"], test_predictions["B_plus_previous_leg"]
    paired = daily_bootstrap(y_test, pred_a, pred_b, test_dates)
    hi = frame.loc[te, "actual_turn_gap_min"].to_numpy(dtype=np.float32) >= 15
    high_confidence = {"filter": "target actual departure minus previous actual arrival >= 15 minutes", "rows": int(hi.sum()), "coverage_of_eligible_test_links_pct": round(100 * float(hi.mean()), 4), "A_mae_minutes": metrics(y_test[hi], pred_a[hi])["mae_minutes"], "B_mae_minutes": metrics(y_test[hi], pred_b[hi])["mae_minutes"], "interpretation": "All eligible 2026 test links pass this filter; this check does not reduce the test cohort."}
    route_hi = frame.loc[te, "route_offset_agreement"].to_numpy(dtype=np.float32) >= .99
    route_robustness = {"filter": "route's modal schedule-derived UTC-offset difference agrees on >=99% of audited records", "rows": int(route_hi.sum()), "coverage_of_eligible_test_links_pct": round(100 * float(route_hi.mean()), 4), "A_mae_minutes": metrics(y_test[route_hi], pred_a[route_hi])["mae_minutes"], "B_mae_minutes": metrics(y_test[route_hi], pred_b[route_hi])["mae_minutes"], "mae_improvement_minutes": metrics(y_test[route_hi], pred_a[route_hi])["mae_minutes"] - metrics(y_test[route_hi], pred_b[route_hi])["mae_minutes"]}
    test_month = frame.loc[te, "FlightDate"].dt.to_period("M").astype("string").to_numpy()
    monthly_test = []
    for month in sorted(np.unique(test_month)):
        m = test_month == month
        a = metrics(y_test[m], pred_a[m])
        b = metrics(y_test[m], pred_b[m])
        monthly_test.append({"month": month, "rows": int(m.sum()), "A_mae_minutes": a["mae_minutes"], "B_mae_minutes": b["mae_minutes"], "mae_improvement_minutes": a["mae_minutes"] - b["mae_minutes"]})

    outputs = {
        "study_window": {"warmup": "2023-12", "train": "2024-01 through 2024-12", "validation": "2025-01 through 2025-12", "test": "2026-01 through 2026-08"},
        "input_candidate_rows": int(len(frame)),
        "rows_by_year": {str(y): int(masks[y].sum()) for y in (2024, 2025, 2026)},
        "target_clipping_for_model_fit_only_minutes": [-120, 900],
        "validation_models": validation_results,
        "selected_category_shrinkage_by_model": selected_alpha,
        "final_test_metrics": test_metrics,
        "paired_day_bootstrap": paired,
        "high_confidence_turnaround_subset": high_confidence,
        "route_offset_robustness_subset": route_robustness,
        "monthly_final_test_metrics": monthly_test,
        "model_description": "Additive fixed-effect model with shrinkage for categorical schedule features and linear numeric effects. Model B adds only previous-leg arrival/departure delay and the target scheduled-departure minus previous actual-arrival gap. Shared daily/monthly/airport/carrier/route schedule features are identical in A and B.",
        "limitations": [
            "The model is a transparent portfolio pilot, not an airline operational predictor.",
            "The first-order schedule-derived UTC offset method and reporting gaps can still create false or missing aircraft links.",
            "2024/2025/2026 performance may reflect reporting or operational distribution shifts; report monthly and carrier-level results before stronger claims.",
        ],
    }
    (args.output / "model_comparison.json").write_text(json.dumps(outputs, indent=2), encoding="utf-8")
    pd.DataFrame(validation_results).to_csv(args.output / "validation_metrics.csv", index=False)
    pd.DataFrame(monthly_test).to_csv(args.output / "monthly_test_metrics.csv", index=False)
    print(json.dumps({"validation_best_alpha": selected_alpha, "final_test": test_metrics, "paired_day_bootstrap": paired, "high_confidence_subset": high_confidence, "route_robustness": route_robustness, "monthly_test": monthly_test}, indent=2))


if __name__ == "__main__":
    main()
