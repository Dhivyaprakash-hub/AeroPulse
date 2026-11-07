import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


class ModelComparisonTest(unittest.TestCase):
    def test_missing_categories_and_empty_diagnostic_subsets(self):
        rows = []
        for year in (2024, 2025, 2026):
            for day in (1, 2):
                rows.append({
                    "FlightDate": f"{year}-01-{day:02}",
                    "Reporting_Airline": None if day == 1 else ("XX" if year == 2026 else "AA"),
                    "OriginAirportID": 101,
                    "DestAirportID": 102,
                    "CRSDepTime": 900,
                    "CRSElapsedTime": 90,
                    "Distance": 300,
                    "ArrDelay": 10 if year == 2026 else day * 5,
                    "prev_arr_delay": day * 4,
                    "prev_dep_delay": None,
                    "scheduled_dep_hour": 9,
                    "scheduled_dep_dow": day,
                    "scheduled_dep_month": 1,
                    "turnaround_gap_min": 65,
                    "actual_turn_gap_min": 10,
                })

        script = Path(__file__).resolve().parents[1] / "src" / "run_model_comparison.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            features = root / "features.csv.gz"
            diagnostics = root / "routes.csv"
            output = root / "output"
            pd.DataFrame(rows).to_csv(features, index=False)
            diagnostics.write_text(
                "OriginAirportID,DestAirportID,share_of_route\n101,102,0.95\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(script), "--features", str(features),
                 "--route-diagnostics", str(diagnostics), "--output", str(output)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((output / "model_comparison.json").read_text(encoding="utf-8"))

        self.assertEqual(report["rows_by_year"], {"2024": 2, "2025": 2, "2026": 2})
        for model in report["final_test_metrics"].values():
            self.assertEqual(model["rows"], 2)
            self.assertIsNotNone(model["mae_minutes"])
            self.assertIsNone(model["r2"])
        self.assertEqual(report["high_confidence_turnaround_subset"]["rows"], 0)
        self.assertIsNone(report["high_confidence_turnaround_subset"]["A_mae_minutes"])
        self.assertEqual(report["route_offset_robustness_subset"]["rows"], 0)
        self.assertIsNone(report["route_offset_robustness_subset"]["mae_improvement_minutes"])
