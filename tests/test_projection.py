import unittest

import numpy as np
import pandas as pd

from web.services.projection import (
    apply_projection,
    apply_spreadsheet_projection,
    apply_spreadsheet_projection_summary,
    fit_bunch_projection,
)


class ProjectionTest(unittest.TestCase):
    def test_lumi_bunch_projection_formula(self):
        reference = pd.DataFrame(
            {
                "pathname": ["L1_Test"] * 3,
                "init_lumi": [100.0, 200.0, 300.0],
                "rate": [20.0, 40.0, 60.0],
            }
        )
        models = fit_bunch_projection(reference, reference_bunches=10)

        current = pd.DataFrame(
            {
                "run": [2],
                "pathname": ["L1_Test"],
                "lumisection": [1],
                "init_lumi": [400.0],
                "rate": [100.0],
            }
        )
        projected = apply_projection(current, current_bunches=20, models=models, double_ratio_scale=1.625)

        self.assertAlmostEqual(projected.loc[0, "expected_rate"], 80.0)
        self.assertAlmostEqual(projected.loc[0, "ratio"], 1.25)
        self.assertAlmostEqual(projected.loc[0, "double_ratio"], 2.03125)
        self.assertAlmostEqual(projected.loc[0, "deviation"], 20.0)
        self.assertAlmostEqual(projected.loc[0, "deviation_pct"], 25.0)
        self.assertEqual(projected.loc[0, "model_status"], "ok")

    def test_missing_bunch_count_returns_warning_rows(self):
        reference = pd.DataFrame(
            {
                "pathname": ["L1_Test", "L1_Test"],
                "init_lumi": [100.0, 200.0],
                "rate": [20.0, 40.0],
            }
        )
        models = fit_bunch_projection(reference, reference_bunches=None)
        self.assertEqual(models["L1_Test"]["status"], "invalid_reference_bunches")

        current = pd.DataFrame(
            {
                "pathname": ["L1_Test"],
                "lumisection": [1],
                "init_lumi": [100.0],
                "rate": [20.0],
            }
        )
        projected = apply_projection(current, current_bunches=None, models=models)
        self.assertEqual(projected.loc[0, "model_status"], "invalid_current_bunches")
        self.assertTrue(np.isnan(projected.loc[0, "expected_rate"]))

    def test_empty_inputs_do_not_crash(self):
        models = fit_bunch_projection(pd.DataFrame(), reference_bunches=10)
        self.assertEqual(models, {})

        projected = apply_projection(pd.DataFrame(), current_bunches=10, models=models)
        self.assertTrue(projected.empty)
        self.assertIn("expected_rate", projected.columns)

    def test_insufficient_points_model_is_reported(self):
        reference = pd.DataFrame(
            {
                "pathname": ["L1_Test"],
                "init_lumi": [100.0],
                "rate": [20.0],
            }
        )
        models = fit_bunch_projection(reference, reference_bunches=10)
        self.assertEqual(models["L1_Test"]["status"], "insufficient_points")

    def test_spreadsheet_projection_formula(self):
        reference = pd.DataFrame(
            {
                "run": [1, 1],
                "bit": [7, 7],
                "pathname": ["L1_Test", "L1_Test"],
                "lumisection": [10, 11],
                "init_lumi": [6.0, 6.0],
                "rate": [100.0, 100.0],
            }
        )
        current = pd.DataFrame(
            {
                "run": [2],
                "bit": [7],
                "pathname": ["L1_Test"],
                "lumisection": [20],
                "init_lumi": [3.0],
                "rate": [80.0],
            }
        )
        projected = apply_spreadsheet_projection(reference, current)

        self.assertAlmostEqual(projected.loc[0, "reference_rate"], 100.0)
        self.assertAlmostEqual(projected.loc[0, "expected_rate"], 50.0)
        self.assertAlmostEqual(projected.loc[0, "rate"], 80.0)
        self.assertAlmostEqual(projected.loc[0, "lumi_ratio"], 0.5)
        self.assertAlmostEqual(projected.loc[0, "ratio"], 1.6)

    def test_spreadsheet_projection_skips_zero_lumi_points(self):
        reference = pd.DataFrame(
            {
                "run": [1, 1, 1],
                "bit": [7, 7, 7],
                "pathname": ["L1_Test", "L1_Test", "L1_Test"],
                "lumisection": [10, 11, 12],
                "init_lumi": [2.0, 2.0, 0.0],
                "rate": [100.0, 100.0, 0.0],
            }
        )
        current = pd.DataFrame(
            {
                "run": [1, 1, 1],
                "bit": [7, 7, 7],
                "pathname": ["L1_Test", "L1_Test", "L1_Test"],
                "lumisection": [10, 11, 12],
                "init_lumi": [2.0, 2.0, 0.0],
                "rate": [100.0, 100.0, 0.0],
            }
        )

        projected = apply_spreadsheet_projection(reference, current)

        self.assertEqual(list(projected["lumisection"]), [10, 11])
        self.assertTrue((projected["ratio"] == 1.0).all())

    def test_spreadsheet_summary_same_range_self_comparison_is_one(self):
        frame = pd.DataFrame(
            {
                "run": [1, 1, 1],
                "bit": [7, 7, 7],
                "pathname": ["L1_Test", "L1_Test", "L1_Test"],
                "lumisection": [10, 11, 12],
                "init_lumi": [2.0, 4.0, 0.0],
                "rate": [100.0, 200.0, 0.0],
            }
        )

        summary = apply_spreadsheet_projection_summary(frame, frame)

        self.assertEqual(len(summary), 1)
        self.assertEqual(summary.loc[0, "lumisection_min"], 10)
        self.assertEqual(summary.loc[0, "lumisection_max"], 11)
        self.assertAlmostEqual(summary.loc[0, "expected_rate"], 150.0)
        self.assertAlmostEqual(summary.loc[0, "rate"], 150.0)
        self.assertAlmostEqual(summary.loc[0, "ratio"], 1.0)
        self.assertAlmostEqual(summary.loc[0, "lumi_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
