# Full-period reproduction

The local reproduction audited and reconstructed all 33 official monthly BTS archives from December 2023 through August 2026, then refit and scored both models. The included [SHA-256 manifest](archive-checksums.csv) records the exact inputs. Python 3.13.7, NumPy 2.5.5, pandas 3.1.1, and tzdata 2026.6 were used.

- Audit row count matched the original 19,379,806. The refreshed clock diagnostics recognize `2400` as valid midnight. The route-offset table changed seven counts among 8,664 rows. Membership at the 99% modal-agreement threshold stayed the same.
- The monthly rotation table reconciles to 18,717,451 adjacent same-tail observations at connecting airports. This is 130 fewer than the previous monthly sum. The 60-minute cutoff still selects 11,852,337 links before the model-period selection.
- Both refitted models selected the same validation setting and matched the published pooled holdout MAE, RMSE, and R² exactly on 2,819,846 flights. All eight monthly holdout row counts and MAEs also matched. The pooled MAE improvement was 5.94 seconds. The uncertainty analysis and route-restricted comparison matched.
- The result remains retrospective. The study still lacks point-in-time aircraft assignments and an operational value threshold.

See the [model comparison](model/model_comparison.json), [monthly test metrics](model/monthly_test_metrics.csv), and [updated rotation summary](rotation_summary.json).
