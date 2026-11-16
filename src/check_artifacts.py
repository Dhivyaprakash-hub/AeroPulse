import ast
import csv
import json
import math
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
tracked_paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).split(b'\0')
for entry in filter(None, tracked_paths):
    path = root / entry.decode('utf-8')
    if path.name.lower().endswith(('.zip', '.csv.gz', '.parquet')):
        raise SystemExit(f'Raw-data artifact tracked by Git: {path.relative_to(root)}')
    if path.suffix == '.py':
        ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    if path.suffix == '.json':
        json.loads(path.read_text(encoding='utf-8-sig'))
study = root / 'reports/full_2023-12_to_2026-08'
rotation = json.loads((study / 'rotation_summary.json').read_text(encoding='utf-8'))
with (study / 'rotation_links_by_month.csv').open(newline='', encoding='utf-8') as f:
    links_by_month = list(csv.DictReader(f))
for monthly_column, total_key in (
    ('consecutive_same_tail_same_airport', 'same_tail_and_connecting_airport_adjacent_observations'),
    ('previous_arrived_at_least_60m_before_sched_dep', 'previous_leg_arrived_by_60_min_prediction_cutoff'),
):
    total = sum(int(row[monthly_column]) for row in links_by_month)
    if total != rotation[total_key]:
        raise SystemExit(f'Monthly {monthly_column} total {total} does not match {rotation[total_key]}')

model_dir = study / 'model'
result = json.loads((model_dir / 'model_comparison.json').read_text())
a = result['final_test_metrics']['A_schedule_only']
b = result['final_test_metrics']['B_plus_previous_leg']
assert a['rows'] == b['rows'] == result['rows_by_year']['2026']
with (model_dir / 'monthly_test_metrics.csv').open() as f:
    rows = list(csv.DictReader(f))
assert sum(int(r['rows']) for r in rows) == a['rows']
for label, metric in [('A', a), ('B', b)]:
    weighted = sum(int(r['rows']) * float(r[f'{label}_mae_minutes']) for r in rows) / a['rows']
    assert math.isclose(weighted, metric['mae_minutes'], abs_tol=1e-8)
print('PASS: Python syntax, JSON parsing, monthly rotation totals, matched test cohorts, monthly weighted MAE reconciliation, and raw-data exclusion.')
