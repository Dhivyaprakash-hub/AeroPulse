# AeroPulse: Flight Delay Propagation Analysis

**A reproducible research project measuring whether an aircraft's previous reported leg adds useful signal for predicting its next flight's arrival delay.**

## Result at a glance

Across 2.82 million future test flights (January–August 2026), adding previous-leg features lowered MAE from 19.317 to 19.218 minutes, a gain of about six seconds. The gain remains on routes with highly consistent inferred time-offset relationships. This is evidence of a small incremental signal, not evidence of operational value. BTS candidate links are not confirmed aircraft rotations, and the model is a research baseline, not a deployed airline predictor.

## Work completed

| Work | Evidence produced | Why it matters |
|---|---|---|
| Audited 33 monthly source archives | 19.38 million records, missingness and clock checks, monthly inventories | Establishes whether the data can answer the question before modelling. |
| Reconstructed candidate aircraft chains | 18.72 million adjacent reported same-tail/airport pairs, DST and turnaround diagnostics | Turns separate flight records into a testable sequence problem while exposing reconstruction uncertainty. |
| Defined information availability | Previous leg arrived by a fixed 60-minute prediction cutoff | Prevents a model from using information that would arrive too late for the stated decision. |
| Compared two matched models | Identical cohorts; 2024 training, 2025 validation, 2026 test | Measures the added value of previous-leg features without changing the evaluated flights. |
| Quantified uncertainty and sensitivity | Daily bootstrap interval, monthly results, route-consistency subset | Checks whether the small improvement persists beyond one pooled score. |
| Packaged the study for inspection | Reproduction scripts, aggregate tables, research report, model card, Streamlit explorer | Lets another analyst inspect assumptions and reproduce the investigation. |

## Business relevance

For an operations analytics team, the useful question is whether collecting and integrating aircraft-chain information improves a forecast enough to justify the effort. AeroPulse demonstrates how to measure that incremental value before committing to a larger system. In this pilot the average gain is small, so a spending or deployment recommendation would need more evidence and a domain-specific value threshold.

For a Business Analytics portfolio, the project provides concrete evidence of data engineering, temporal reasoning, experiment design, predictive modelling, uncertainty analysis, and communication of a go/no-go decision. The completed work is a retrospective research study. Live airline integration, recovery optimisation, causal attribution, and financial savings remain future possibilities rather than delivered capabilities.

## Why this is distinctive

Flight delay propagation is an established research topic. AeroPulse does not claim to invent it or outperform established systems. The contribution is an end-to-end, auditable study using public BTS data: multi-year data checks, explicit aircraft-link reconstruction, declared prediction-time cutoff, strict time-based holdout, paired uncertainty, route-confidence sensitivity, and a clear account of where the result is too small to justify an operational claim.

## Study design

- **Question:** Does the previous reported flight of the same aircraft add predictive signal for target arrival delay?
- **Cutoff:** Previous flight must have arrived at least 60 minutes before target scheduled departure.
- **Outcome:** `ArrDelay` in minutes for operated flights.
- **Time split:** 2024 training; 2025 validation/model selection; January–August 2026 final test; December 2023 warm-up.
- **Comparison:** Shared schedule/route baseline versus the same model plus previous-leg delays and turnaround gap.
- **Audit window:** 33 monthly BTS archives, December 2023–August 2026; 19.38 million rows.
- **Limit:** Links are adjacent reported flights reconstructed from BTS, not independently verified physical aircraft rotations.
- **Availability caveat:** Final reported tail assignments and actual flight ordering are retrospective; historical aircraft-assignment snapshots are unavailable. The prior-arrival cutoff is enforced, but predecessor identity at prediction time is unverified.

See [the feasibility and results report](reports/RESEARCH_FEASIBILITY.md), [the experiment specification](research/EXPERIMENT_SPEC.md), and [the data source register](research/DATA_SOURCE_REGISTER.md).

## Open the research explorer

After installing dependencies, run:

```powershell
streamlit run app.py
```

The explorer uses only the aggregate result files committed in `reports/`; it does not load flight-level records.

## Reproduce the analysis

Download the official BTS Reporting Carrier On-Time Performance monthly ZIP files for December 2023 through August 2026. Keep archives outside this repository and note their paths. The output folder must have enough disk space for aggregate results and, if running the model, the temporary compressed feature table (about 227 MB in this run). Python 3.10+ is recommended.

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run the streaming audit over all 33 monthly ZIPs:

```powershell
$archives = @(Get-ChildItem 'C:\path\to\monthly\zips\*.zip' | Select-Object -ExpandProperty FullName)
python src/audit_bts_streaming.py --output reports/full_2023-12_to_2026-08 @archives
```

Reconstruct candidate links and write the temporary row-level feature table outside the repository:

```powershell
python src/reconstruct_rotations.py --output reports/full_2023-12_to_2026-08 --feature-output C:\path\to\private\work\candidate_links.csv.gz @archives
```

Run the model comparison using the route diagnostic produced by the audit:

```powershell
python src/run_model_comparison.py --features C:\path\to\private\work\candidate_links.csv.gz --route-diagnostics reports/full_2023-12_to_2026-08\route_offset_diagnostic.csv --output reports/full_2023-12_to_2026-08\model
```

For a smaller initial check, the original Q1 scripts can be run with the January, February, and March 2025 archives. Those pilot outputs are retained under `reports/audit/`.

## Repository contents

To check the published artifacts without downloading BTS data, run `python src/check_artifacts.py`. It checks Python syntax and JSON readability, reconciles monthly weighted MAE against the pooled results, verifies matched test cohort sizes, and checks that source archives and compressed row-level features are absent. GitHub Actions runs this check on pushes and pull requests.

- `src/` — audit, sequence reconstruction, and model comparison scripts.
- `app.py` — compact, interactive research-result explainer.
- `MODEL_CARD.md` — intended use, scope, results, and limitations.
- `reports/` — aggregate outputs and the interpretation of results. No row-level flight data is included.
- `research/` — source register and experiment specification.
- `references/` — research context and source notes.

## Data handling

Do not commit BTS archives, extracted monthly CSVs, or the generated row-level candidate feature table. The scripts read source ZIPs in place and publish aggregate outputs only. Review the BTS terms before redistribution. The DOT OIG has noted that completeness of carrier-reported data is not fully verified, which is especially important when inferring aircraft chains.

## Next extensions

Before attempting productization, establish a minimum practically worthwhile improvement with an aviation reviewer. Then consider carrier-level performance, delayed-flight classification and calibration, a predeclared cutoff sensitivity, and a placebo test. Keep the future test period isolated from any additional tuning.

## Decision

**Research portfolio project: go. Operational prediction product: no-go on current evidence.** A small, honest result with strong reproducibility is more credible than presenting a marginal score change as a major aviation solution.
