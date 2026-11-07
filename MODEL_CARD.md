# Model card: AeroPulse temporal pilot

## Intended use

This model comparison is intended for a portfolio research demonstration of reproducible, leakage-aware analytics. It estimates whether previous reported aircraft-leg information adds predictive signal for the arrival delay of an operated target flight in the BTS candidate-link cohort.

## Out-of-scope use

Do not use the model for dispatch, passenger rebooking, crew or aircraft assignment, safety decisions, customer promises, or airline operations. It has not been prospectively tested, independently validated with operational data, or reviewed by an aviation operations specialist.

## Data and population

- Source: BTS Reporting Carrier On-Time Performance, December 2023–August 2026.
- Final test period: January–August 2026.
- Population: 2,819,846 operated target flights with a reconstructed same-tail, same-airport previous reported flight that arrived at least 60 minutes before target scheduled departure.
- Outcome: BTS `ArrDelay`, in minutes.
- Candidate links: sequence adjacency inferred from reported rows and schedule-derived offsets; not verified ground-truth aircraft rotations.

## Model comparison

Model A uses carrier, airport, route, scheduled time categories, scheduled elapsed time, and distance. Model B adds prior-leg arrival delay, prior-leg departure delay, and the target scheduled departure minus prior actual arrival gap. Both use the same rows and chronological split. Categorical effects use shrinkage selected on the 2025 validation set.

| Metric | A | B |
|---|---:|---:|
| Test MAE | 19.317 min | 19.218 min |
| Test RMSE | 44.340 min | 44.235 min |
| Test R² | 0.0153 | 0.0199 |

The MAE improvement is about 5.9 seconds (0.51%). Paired daily bootstrap 95% interval: 0.081–0.115 minutes. On routes with >=99% offset-difference agreement, which cover 90.65% of test rows, the improvement is 0.110 minutes.

## Limitations and risks

- Improvement is statistically distinguishable from zero in the paired daily bootstrap, but small in absolute terms; practical benefit is unestablished.
- Test R² is low, and the model does not explain most flight-level variation.
- Only one additive model family was evaluated; no tree model, calibration analysis, placebo test, or prospective validation is included.
- BTS is a reporting dataset, and missing movements can make reported flights appear adjacent.
- Local times are converted to UTC using schedule-derived airport offset differences, not an official flight-level UTC field.
- Offset graphs and route agreement diagnostics were estimated across the audited period, including the test dates. The chronological split applies to model fitting and tuning. To test the complete pipeline prospectively, freeze an airport-offset mapping and route diagnostics using only earlier data or a versioned external timezone reference.
- The paired bootstrap gives each date equal weight. The overall MAE gives each flight equal weight, so the two quantities can differ. Resampling single dates also leaves possible dependence across neighboring days unmodeled.
- Aircraft tails and flight order come from final reported records. The study has no historical snapshot proving that the target aircraft assignment and predecessor identity were known at the 60-minute cutoff. The cutoff enforces prior-arrival timing, but full real-time feature availability is unverified.
- Results are conditioned on an eligible previous-flight link. Availability varies and must accompany any error metric.

## Fair and responsible presentation

Present the candidate-link definition, eligible cohort, chronological split, uncertainty, and practical scale together. Do not imply that statistical significance means a useful operational effect. Do not call reconstructed sequences confirmed aircraft rotations or describe the pilot as state of the art.
