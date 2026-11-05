"""Small, evidence-first explainer for the AeroPulse research result."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "reports" / "full_2023-12_to_2026-08"
MODEL_DIR = RESULTS / "model"

st.set_page_config(page_title="AeroPulse | Flight-chain signal study", page_icon="✈️", layout="wide")
st.title("AeroPulse")
st.caption("Does a previous aircraft leg add useful signal for predicting arrival delay?")

with (MODEL_DIR / "model_comparison.json").open(encoding="utf-8") as f:
    result = json.load(f)
with (RESULTS / "rotation_summary.json").open(encoding="utf-8") as f:
    rotation = json.load(f)
monthly = pd.read_csv(MODEL_DIR / "monthly_test_metrics.csv")

a = result["final_test_metrics"]["A_schedule_only"]
b = result["final_test_metrics"]["B_plus_previous_leg"]
improvement = a["mae_minutes"] - b["mae_minutes"]
ci = result["paired_day_bootstrap"]["paired_day_bootstrap_95pct_ci"]
robust = result["route_offset_robustness_subset"]

st.info(
    f"**Finding:** Previous-leg features reduced test MAE by {improvement * 60:.1f} seconds "
    f"({improvement / a['mae_minutes'] * 100:.2f}%). This is a small statistical gain; "
    "the study does not establish operational or financial value."
)

left, right = st.columns(2)
with left:
    st.subheader("Same flights, two models")
    st.metric("Schedule-only baseline MAE", f"{a['mae_minutes']:.3f} min")
    st.metric("Plus previous-leg information MAE", f"{b['mae_minutes']:.3f} min", f"−{improvement * 60:.1f} sec")
    st.caption(
        f"Paired daily bootstrap 95% interval for the MAE gain: "
        f"{ci[0]:.3f}–{ci[1]:.3f} minutes across {result['paired_day_bootstrap']['days']} test days."
    )
with right:
    st.subheader("Does it hold on more consistent routes?")
    st.metric("Routes with ≥99% offset agreement", f"{robust['coverage_of_eligible_test_links_pct']:.1f}% of test links")
    st.metric("MAE gain in this subset", f"{robust['mae_improvement_minutes'] * 60:.1f} sec")
    st.caption("Time-offset agreement is derived from BTS schedule fields; it is not independent UTC ground truth.")

st.subheader("Month-by-month test result")
monthly = monthly.set_index("month")[["A_mae_minutes", "B_mae_minutes"]]
monthly.columns = ["Schedule only", "Plus previous leg"]
st.line_chart(monthly, y_label="Mean absolute error (minutes)")
st.caption("February is effectively flat; the positive average gain is not uniform in size.")

with st.expander("How the comparison was designed"):
    st.markdown(
        """
        - **Training:** January–December 2024
        - **Validation:** January–December 2025, used to choose categorical shrinkage
        - **Final test:** January–August 2026
        - **Eligible target:** an adjacent reported flight for the same tail and connecting airport, with the prior leg arrived at least 60 minutes before scheduled departure
        - **Model A:** carrier, airport, route, scheduled time, elapsed time, and distance
        - **Model B:** Model A plus previous-leg arrival/departure delay and scheduled turnaround gap
        - **Outcome:** BTS arrival delay (`ArrDelay`) in minutes for operated flights

        Both models were evaluated on the same future test rows. See `MODEL_CARD.md` and `reports/RESEARCH_FEASIBILITY.md` for full methods and caveats.
        """
    )

st.subheader("Sequence audit")
one, two, three = st.columns(3)
one.metric("Monthly archives", "33")
two.metric("BTS rows audited", "19.38 million")
three.metric("Candidate adjacent reported pairs", f"{rotation['same_tail_and_connecting_airport_adjacent_observations'] / 1_000_000:.2f} million")

st.warning(
    "BTS is a reporting-carrier dataset, not a census of every aircraft movement. "
    "A missing ferry, maintenance, or other flight can make reported flights look adjacent. "
    "This is a research demonstration, not an operational forecast tool."
)
