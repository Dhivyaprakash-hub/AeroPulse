import ast
import csv
import json
import math
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for p in root.rglob('*.py'):
    ast.parse(p.read_text(encoding='utf-8-sig'))
for p in root.rglob('*.json'):
    json.loads(p.read_text(encoding='utf-8-sig'))
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
assert not list(root.rglob('*.zip'))
assert not list(root.rglob('*.csv.gz'))
print('PASS: Python syntax, JSON parsing, matched test cohorts, monthly weighted MAE reconciliation, and raw-data exclusion.')
