#!/usr/bin/env python3
"""Regression tests for the calibration and quantification core."""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analysis_core as core
from dpv_pipeline import parse_cor_bytes


def calibration_data(direction="signal-on", blank_responses=None):
    concentrations = np.repeat([1e-9, 1e-8, 1e-7, 1e-6], 2)
    log_concentration = np.log10(concentrations) + 9
    response = 1 + log_concentration if direction == "signal-on" else 4 - log_concentration
    data = pd.DataFrame({"concentration_M": concentrations, "ratio": response})
    if blank_responses is not None:
        blanks = pd.DataFrame({"concentration_M": np.zeros(len(blank_responses)),
                               "ratio": blank_responses})
        data = pd.concat([data, blanks], ignore_index=True)
    return data


class CalibrationTests(unittest.TestCase):
    def test_corrtest_current_density_is_scaled_by_recorded_electrode_area(self):
        raw = ("CORRW ASCII\nCorrTest for Windows\nID_DiffPulseVA\n"
               "ExpParmas:CellParam=Area=0.5&-&IncE=0.02\n"
               "E(V)\t\ti(A/cm^2)\t\tT(s)\nEnd Comments\n"
               "0.1\t2.0e-6\t0\n-0.1\t-4.0e-6\t1\n").encode("ascii")

        rec = parse_cor_bytes("area.cor", raw)

        self.assertEqual(rec["source_current_unit"], "A/cm^2")
        self.assertEqual(rec["current_unit"], "A")
        self.assertEqual(rec["area_cm2"], 0.5)
        np.testing.assert_allclose(rec["I"], [1.0e-6, -2.0e-6])

    def test_corrtest_surface_area_fallback_is_supported(self):
        raw = ("CORRW ASCII\nCorrTest for Windows\nID_DiffPulseVA\n"
               "Surface Area: 2.0\nE(V)\t\ti(A/cm2)\t\tT(s)\n"
               "End Comments\n0.1\t2.0e-6\t0\n-0.1\t-4.0e-6\t1\n").encode("ascii")

        rec = parse_cor_bytes("surface-area.cor", raw)

        self.assertEqual(rec["area_cm2"], 2.0)
        np.testing.assert_allclose(rec["I"], [4.0e-6, -8.0e-6])

    def test_current_density_without_area_is_rejected(self):
        raw = ("CORRW ASCII\nCorrTest for Windows\nID_DiffPulseVA\n"
               "E(V)\t\ti(A/cm^2)\t\tT(s)\nEnd Comments\n"
               "0.1\t2.0e-6\t0\n-0.1\t-4.0e-6\t1\n").encode("ascii")

        with self.assertRaisesRegex(ValueError, "electrode area is missing or invalid"):
            parse_cor_bytes("no-area.cor", raw)

    def test_current_in_ampere_is_not_rescaled(self):
        raw = ("CORRW ASCII\nCorrTest for Windows\nID_DiffPulseVA\n"
               "E(V)\t\ti(A)\t\tT(s)\nEnd Comments\n"
               "0.1\t2.0e-6\t0\n-0.1\t-4.0e-6\t1\n").encode("ascii")

        rec = parse_cor_bytes("current.cor", raw)

        self.assertEqual(rec["current_unit"], "A")
        self.assertEqual(rec["source_current_unit"], "A")
        self.assertIsNone(rec["area_cm2"])
        np.testing.assert_allclose(rec["I"], [2.0e-6, -4.0e-6])

    def test_requires_four_standards_and_three_levels(self):
        too_few = pd.DataFrame({"concentration_M": [1e-9, 1e-8, 1e-7],
                                "ratio": [1.0, 2.0, 3.0]})
        same_level = pd.DataFrame({"concentration_M": [1e-9] * 4,
                                   "ratio": [1.0, 1.1, 0.9, 1.2]})

        self.assertIn("at least 4 standards", core.fit_calibration(too_few)["error"])
        self.assertIn("at least 3 different concentrations",
                      core.fit_calibration(same_level)["error"])

    def test_fewer_than_three_blanks_never_reports_lod(self):
        fit = core.fit_calibration(calibration_data(blank_responses=[0.1, 0.2]))

        self.assertNotIn("LOD_M", fit)
        self.assertIn("at least 3 blank replicates", fit["LOD_error"])

    def test_blank_threshold_follows_calibration_direction(self):
        signal_on = core.fit_calibration(
            calibration_data("signal-on", [0.1, 0.2, 0.3]))
        signal_off = core.fit_calibration(
            calibration_data("signal-off", [4.1, 4.2, 4.3]))

        self.assertEqual(signal_on["direction"], "signal-on")
        self.assertAlmostEqual(signal_on["blank"]["threshold"],
                               0.2 + 3 * np.std([0.1, 0.2, 0.3], ddof=1))
        self.assertEqual(signal_off["direction"], "signal-off")
        self.assertAlmostEqual(signal_off["blank"]["threshold"],
                               4.2 - 3 * np.std([4.1, 4.2, 4.3], ddof=1))

    def test_inverse_prediction_recovers_known_concentration(self):
        fit = core.fit_calibration(calibration_data())
        prediction = core.predict_concentration(fit, y0=2.0)

        self.assertAlmostEqual(prediction["C"], 1e-8, delta=1e-20)
        self.assertLess(prediction["C_lo"], prediction["C"])
        self.assertGreater(prediction["C_hi"], prediction["C"])
        self.assertTrue(prediction["in_range"])


if __name__ == "__main__":
    unittest.main()
