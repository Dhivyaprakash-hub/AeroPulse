import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


class ReconstructRotationsTest(unittest.TestCase):
    def test_monthly_link_count_excludes_pairs_across_aircraft(self):
        header = (
            "FlightDate,Tail_Number,OriginAirportID,Origin,DestAirportID,Dest,"
            "CRSDepTime,DepDelay,CRSArrTime,ArrDelay,Cancelled,Diverted,CRSElapsedTime"
        )
        rows = [header]
        for tail in ("N100AA", "N200AA"):
            rows.extend([
                f"2025-01-05,{tail},1,ATL,2,CLT,900,0,1000,0,0,0,60",
                f"2025-01-05,{tail},2,CLT,1,ATL,1100,0,1200,0,0,0,60",
            ])

        script = Path(__file__).resolve().parents[1] / "src" / "reconstruct_rotations.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "flights.zip"
            output = root / "output"
            with zipfile.ZipFile(archive, "w") as files:
                files.writestr("flights.csv", "\n".join(rows))
            result = subprocess.run(
                [sys.executable, str(script), "--output", str(output), str(archive)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((output / "rotation_summary.json").read_text(encoding="utf-8"))

        self.assertEqual(report["same_tail_and_connecting_airport_adjacent_observations"], 2)
        self.assertEqual(report["linked_targets_by_month"][0]["consecutive_same_tail_same_airport"], 2)
        self.assertEqual(report["previous_leg_arrived_by_60_min_prediction_cutoff"], 2)
