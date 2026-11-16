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
model_dir = root / 'reports/full_2023-12_to_2026-08/model'
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
print('PASS: Python syntax, JSON parsing, matched test cohorts, monthly weighted MAE reconciliation, and raw-data exclusion.')
