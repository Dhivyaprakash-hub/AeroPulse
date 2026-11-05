# AeroPulse: Flight Delay Propagation Analysis

**Decision: GO for a reproducible research portfolio project and analytical demonstration. NO-GO for an operational prediction product or a claim of practically meaningful uplift.**

## Executive summary

The BTS data support an out-of-time test of whether the previous reported flight of the same aircraft adds information about a target flight's arrival delay. Across 33 monthly files (December 2023–August 2026), the audit processed 19.38 million flights and reconstructed 18.72 million adjacent same-tail, same-airport reported-flight pairs. Of these, 11.85 million had a previous flight that had arrived at least 60 minutes before the target's scheduled departure.

The temporal pilot trained on 2024, selected category shrinkage on 2025, and tested on January–August 2026. On 2.82 million test flights with an eligible previous-leg link, adding previous-leg delay features reduced mean absolute error (MAE) from 19.317 to 19.218 minutes: a gain of 0.099 minutes, or about **5.9 seconds (0.51%)**. A paired daily bootstrap 95% interval for the mean daily gain was 0.081–0.115 minutes. On routes whose schedule-derived time-offset relationship agreed on at least 99% of audited records, covering 90.65% of the test cohort, the gain was 0.110 minutes (about 6.6 seconds).

This is a small but repeatable statistical improvement on this held-out period. The absolute gain is too small to support an operational-value claim, the test R² remains low (0.020 for Model B), and the link reconstruction is not ground truth. The portfolio value is the transparent end-to-end research process: provenance, data-quality audit, leakage-aware time split, uncertainty, robustness, and an honest boundary around what the result means.

## Research question and cohort

**Question:** Among operated BTS flights with a same-tail, same-connecting-airport previous reported flight that arrived by 60 minutes before target scheduled departure, does adding previous-leg delay information improve prediction of target `ArrDelay`?

The study uses a fixed 60-minute information cutoff. Cancelled and diverted target flights do not have a comparable arrival-delay outcome and are excluded from the regression cohort. Links are called *candidate links* or *adjacent reported flights* because BTS reporting omissions, ferry/maintenance operations, and other gaps can hide intervening movements.

## Data audit and sequence reconstruction

The 33 ZIP archives contained one monthly CSV apiece, each with 110 columns, for 19,379,806 total rows from 2023-12-01 through 2026-08-31. There were 19,020,539 operated flights, 305,426 cancellations, and 53,841 diversions. Nearly all operated rows had tail number and arrival delay. The stream audit found zero invalid dates and zero month-window mismatches.

| Check | Result | Interpretation |
|---|---:|---|
| Operated tail-number flights | 19,020,538 | Main sequence-building population. |
| Flights with inferred origin and arrival offsets | 19,020,327 (99.9989%) | Schedule-derived offset coverage, not official UTC coverage. |
| DST-regime crossing rows excluded from offset graph | 1,573 | Avoids applying one seasonal offset regime across the transition. |
| Adjacent same-tail, same-connecting-airport pairs | 18,717,451 | Candidate reported-flight links, not confirmed physical rotations. |
| Candidate targets with previous arrival ≥60 minutes before scheduled departure | 11,852,337 | Eligible for the declared forecast cutoff. |
| Negative reconstructed physical turnaround gaps | 262 / 18.72M pairs | Anomalies retained in aggregate sequence audit; not present in eligible 2026 model cohort. |
| Physical turnaround gaps under 15 minutes | 1,066 / 18.72M pairs | Small anomaly set; use caution for sequence interpretation. |
| Median physical turnaround gap | 73 minutes | Reconstructed from reported local times and delays. |
| Routes with ≥99% modal offset-difference agreement | 7,018 of 7,614 | Used as the high-consistency sensitivity threshold. |

The expanded-period key scan found one duplicate group / one extra row by 64-bit hash on the candidate flight key. An exact full-row duplicate scan was not repeated for all 33 months; the Q1 2025 pilot's exact full-row scan found none. The streaming audit initially treated a handful of `2400` midnight clock values as invalid HHMM; the parsers were corrected to accept 2400 as midnight before sequence reconstruction. Do not interpret the old 2 departure / 4 arrival parser flags as confirmed bad source records.

### Timestamp and link limitations

BTS local HHMM times are not UTC timestamps. Airport offset differences are inferred from scheduled local departure/arrival times and scheduled elapsed time, anchored at Atlanta and solved separately for EST/EDT. Route consistency is high, but it is an internal check using the same schedule fields; it is not independent timestamp verification. Actual departure/arrival instants are reconstructed by adding BTS delay minutes to scheduled times under the inferred offsets.

BTS covers reporting carriers within its regulatory scope. A missing or unreported flight can make two rows look consecutive when they were not. Tail identifiers, codeshares, ferry movements, maintenance legs, and disruptions can also affect the sequences. Results therefore concern candidate links in BTS-reported data.

The tail assignment and actual flight ordering are retrospective. No historical assignment snapshot proves that the target aircraft and predecessor identity were known 60 minutes before departure. The arrival-time cutoff prevents using a previous arrival that occurs too late, but does not by itself establish complete real-time availability of the linked features. Interpret the comparison as conditional on the reconstructed aircraft assignment.

## Model comparison

The same eligible rows and chronological partitions were used for both models:

| Period | Use | Rows |
|---|---|---:|
| December 2023 | Warm-up for early links | Included in sequence reconstruction |
| January–December 2024 | Training | 4,382,083 |
| January–December 2025 | Validation and shrinkage selection | 4,278,754 |
| January–August 2026 | Untouched final test | 2,819,846 |

Model A is a transparent additive fixed-effect baseline with carrier, origin/destination, route, scheduled departure hour/day/month, route-hour effects, scheduled elapsed time, and distance. Model B adds previous-leg arrival delay, previous-leg departure delay, the scheduled target departure minus previous actual arrival gap, and a missingness indicator for previous departure delay. Category shrinkage was selected on validation data (200 for both models). The target was clipped to [-120, 900] only during model fitting; metrics use the original target values.

| Test metric | Model A: schedule only | Model B: plus previous leg |
|---|---:|---:|
| MAE | 19.317 min | 19.218 min |
| RMSE | 44.340 min | 44.235 min |
| R² | 0.0153 | 0.0199 |

The mean daily MAE gain was 0.09797 minutes across 243 test days (paired daily bootstrap 95% interval: 0.08050–0.11534 minutes). The route-confidence sensitivity included 2,556,152 flights (90.6486% of test rows): Model A MAE 19.442 minutes; Model B MAE 19.332 minutes; gain 0.10981 minutes. The actual-turnaround ≥15-minute filter retained all eligible test links, so it is not an independent reduction in the test cohort.

The gain was positive in seven test months and effectively zero in February. Per-month MAE gains ranged from 0.0001 to 0.1854 minutes. Results are in `full_2023-12_to_2026-08/model/monthly_test_metrics.csv`.

## Decision and next use

Proceed with AeroPulse as a research-focused GitHub showcase: publish the code, aggregate outputs, methods, model comparison, and a compact analytical explorer or report. Position it as **“measuring the incremental predictive value and availability of aircraft-chain signals”**, not as a new delay-propagation discovery, state-of-the-art predictor, or airline operations tool.

Do not claim that a six-second average MAE gain has operational or financial value. Establish a practically meaningful threshold with an aviation practitioner before any further model-selection exercise. The current pilot is one model family, has no carrier-specific test breakdown or placebo/permutation test yet, and does not evaluate classification calibration or a prospective deployment. Those are reasonable research extensions, but they are not required to present the completed feasibility study honestly.

## Reproducibility artifacts

- `src/audit_bts.py`: detailed Q1 2025 pilot audit.
- `src/audit_bts_streaming.py`: chunked 33-month aggregate audit.
- `src/reconstruct_rotations.py`: schedule-offset graph, sequence audit, and optional temporary row-level feature export.
- `src/run_model_comparison.py`: time-split additive model comparison and robustness summaries.
- `reports/full_2023-12_to_2026-08/`: aggregate audit, route diagnostics, sequence summaries, model metrics, and monthly results.
- `research/EXPERIMENT_SPEC.md`: research question, leakage controls, split, metrics, and extensions.
- `research/DATA_SOURCE_REGISTER.md`: official BTS sources, coverage limitations, and related benchmark context.

The original archives remain in the user's Downloads folder. The temporary row-level feature table is not a publication artifact and must not be committed. The project reports aggregate results only.
