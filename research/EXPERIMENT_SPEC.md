# Prespecified experiment: previous-leg information and arrival delay

## Question and estimand

Among operated BTS target flights for which a same-tail prior reported flight is shown to have arrived by a fixed prediction cutoff, does adding the prior leg's observed delay reduce out-of-time arrival-delay prediction error versus a baseline that uses only information available by that same cutoff?

The target is `ArrDelay` in minutes. Report `ArrDel15` (arrival delay of at least 15 minutes) as a secondary operational classification target. This is a predictive comparison, not a causal claim that upstream delay causes downstream delay.

## Prediction time and eligible population

Fix the decision time at **60 minutes before target scheduled departure**. An eligible Model B row must have a same-tail, same-connecting-airport previous operated leg whose actual arrival occurred no later than the cutoff. Define links using actual chronological timestamps, with timestamp reconstruction documented and stress-tested. Model A and Model B must use exactly the same target rows. Report coverage: eligible rows / all operated target rows, by month, airport, carrier and scheduled-turnaround length.

The Q1 audit identified 1,053,283 candidate targets meeting the cutoff from a same-tail adjacent reported flight. These are provisional links, not ground-truth physical aircraft rotations.

## Models

- **A — schedule/network baseline:** carrier, origin/destination airport IDs, scheduled local departure hour/day/month, scheduled elapsed time, distance, and historical features computed only from training-period data. Do not include post-cutoff observations.
- **B — previous-leg signal:** Model A plus prior-leg arrival delay, prior-leg departure delay and scheduled gap/turnaround features that are available at cutoff. Prefer one simple regularized linear model and one tree-based model; compare A/B within each learner to isolate the value of these features.
- **C — optional sequence extension:** only after robust multi-leg reconstruction and a prespecified rationale. Not part of the minimum experiment.

Do not include target flight's actual departure time/delay, actual arrival time/delay, actual elapsed time, taxi times, cancellation/diversion outcomes, or reported delay causes. Do not include a prior-leg field unless its information was available by the declared cutoff.

## Split and evaluation

Use chronological train/validation/test periods and preserve a final untouched future test period. The three-month pilot is enough for feasibility only; it is not a strong seasonal or external validation. Recommended split: January–December 2024 for training, January–December 2025 for validation and model selection, and January–August 2026 for final testing (the latest BTS period listed as available when this plan was revised). Include December 2023 as a warm-up month to reconstruct early January 2024 predecessor legs. Freeze all transformations, encoders, historical aggregates, and tuning on training/validation periods.

Primary metric: MAE for `ArrDelay`, with paired daily-block bootstrap confidence intervals for the A-minus-B improvement on identical test rows. Secondary: RMSE; for `ArrDel15`, PR-AUC, ROC-AUC, Brier score and calibration. Report by carrier, airport, month, route frequency and delay quantile; include the eligible-row coverage alongside error. Compare to a simple historical/route-time baseline so model complexity has a clear hurdle.

## Robustness and falsification checks

1. Reconstruct offsets separately by seasonal regime and independently validate timestamps against BTS local clock-delay fields and elapsed-time identities.
2. Compare alternate minimum prediction cutoffs (e.g., 30, 60, 90 minutes) without selecting the best after seeing test performance.
3. Repeat on links with high confidence only (stable route-offset agreement and reasonable physical turnaround), and compare with all candidate links.
4. Check one-to-one preceding/following assignments, impossible negative actual turnaround gaps, duplicate tail-time-route keys, tails with suspicious route/time jumps, and sensitivity to boundary flights.
5. Run a placebo/permutation check that breaks the prior-leg association within comparable carrier/airport/time strata; it should not yield a stable advantage.
6. Evaluate model A and B on the same rows and same time split; do not compare different sample sizes.

## Go/no-go thresholds

Continue to productizing the analysis only if sequence integrity remains strong in the expanded period, B reduces test MAE by a practically meaningful amount with uncertainty intervals that do not suggest a zero/negative average gain, the gain persists in high-confidence links and across major carriers, and coverage is clearly disclosed. Otherwise publish a valuable negative result or pivot to a better-supported question. Do not choose an arbitrary performance threshold after seeing results; define a minimum worthwhile MAE improvement with an aviation domain reviewer before model training.

## Reproducibility artifacts

Publish code, exact source metadata, data dictionary, fixed cutoff and split dates, environment lockfile, aggregate audit tables, a short methods/results report, model cards, and limitations. Do not commit BTS row-level archives or Aeolus data. Never state the model is suitable for airline operations absent prospective validation, access to current operational data, and domain review.

## Completed pilot and decision

The minimum temporal pilot has now been run on the expanded December 2023–August 2026 archive set. The executed model is a transparent additive fixed-effect model with shrinkage for categorical schedule features and linear numeric effects; Model B adds previous-leg arrival/departure delays and the scheduled target departure minus previous actual arrival gap. It is one model family, not the planned comparison across linear and tree-based learners.

On the 2,819,846-row January–August 2026 test set, Model A MAE was 19.317 minutes and Model B MAE was 19.218 minutes (0.099 minutes, approximately 5.9 seconds improvement). The paired daily bootstrap 95% interval was 0.081–0.115 minutes. On the >=99% route-offset-agreement subset (2,556,152 rows, 90.65% coverage), the gain was 0.110 minutes. The gain was positive in seven months and effectively zero in February. Test R² was 0.020 for Model B.

This satisfies a research-showcase go decision because the incremental signal persists in the route-confidence sensitivity. It does **not** satisfy a productization or operational-value gate: practical value was not defined with an aviation reviewer before test analysis, the absolute improvement is small, one learner was evaluated, and carrier-level, classification-calibration, placebo, and prospective checks remain open. Do not tune on the final test set; treat any future investigation that changes model design as a new, clearly labeled experiment.
