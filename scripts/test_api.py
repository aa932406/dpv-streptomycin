#!/usr/bin/env python3
"""Regression tests for API filesystem boundaries."""
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import app as api


class PathBoundaryTests(unittest.TestCase):
    def test_folder_accepts_child_and_rejects_prefix_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            root.mkdir()
            child = root / "batch-1"
            child.mkdir()
            sibling = Path(tmp) / "data-secret"
            sibling.mkdir()

            with patch.object(api, "DATA_DIR", root):
                self.assertEqual(api._folder("batch-1"), child.resolve())
                with self.assertRaises(HTTPException) as exc:
                    api._folder("../data-secret")

            self.assertEqual(exc.exception.status_code, 400)

    def test_folder_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            root.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()

            with patch.object(api, "DATA_DIR", root):
                with self.assertRaises(HTTPException) as exc:
                    api._folder("../outside")

            self.assertEqual(exc.exception.status_code, 400)

    def test_model_boundary_uses_path_components(self):
        root = Path(tempfile.gettempdir()) / "models"
        sibling = root.parent / "models-backup" / "weights.joblib"

        self.assertFalse(api._is_within(sibling.resolve(), root.resolve()))
        self.assertTrue(api._is_within((root / "weights.joblib").resolve(), root.resolve()))

    def test_upload_creates_new_folder_and_rejects_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            data_root.mkdir()
            client = TestClient(api.app)
            with patch.object(api, "DATA_DIR", data_root):
                response = client.post("/api/folders/upload", data={"folder": "upload-test"},
                                       files=[("files", ("sample.cor", b"test curve", "text/plain"))])
                duplicate = client.post("/api/folders/upload", data={"folder": "upload-test"},
                                        files=[("files", ("other.cor", b"other", "text/plain"))])

            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["files"], 1)
            self.assertEqual((data_root / "upload-test" / "sample.cor").read_bytes(), b"test curve")
            self.assertEqual(duplicate.status_code, 409)

    def test_report_contains_embedded_curve_figure_and_png_asset(self):
        payload = {
            "meta": {"folder": "batch", "n_curves": 2, "n_electrodes": 2,
                     "n_groups": 1, "n_qc": 2},
            "curves": {"grid": [0.2, 0.1, 0.0], "series": [
                {"name": "group A", "mean": [0.1, 0.5, 0.2], "color": "#2468ac"}
            ]},
            "groups": [], "samples": [], "stats": {}, "verdicts": [],
            "pca": {}, "calib_points": [],
        }
        client = TestClient(api.app)
        with (
            patch.object(api, "_folder", return_value=Path(".")),
            patch.object(api, "analyse", return_value=payload),
            patch.object(api, "regression_payload", return_value={"error": "no standards"}),
            patch.object(api, "paper_payload", return_value={"error": "no calibration"}),
        ):
            response = client.get("/api/report?folder=batch")

        self.assertEqual(response.status_code, 200, response.text)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertIn("figures/curves.png", archive.namelist())
            html = archive.read("report.html").decode("utf-8")
        self.assertIn("各条件平均曲线", html)
        self.assertIn("data:image/png;base64,", html)
        self.assertIn('alt="各条件 DPV 曲线"', html)

    def test_report_curve_matches_web_axis_direction_and_labels(self):
        payload = {
            "curves": {"grid": [0.8, 0.4, 0.0, -0.4], "series": [
                {"name": "group A", "mean": [0.1, 0.5, 0.2, 0.3],
                 "n": 3, "color": "#2468ac"}
            ]}
        }
        fig = api._curve_figure(payload)
        ax = fig.axes[0]

        self.assertLess(ax.get_xlim()[0], ax.get_xlim()[1])
        self.assertEqual(ax.get_xlabel(), "Potential (V)")
        self.assertEqual(ax.get_ylabel(), "Current (µA)")
        self.assertIn("group A  n=3", [text.get_text() for text in ax.get_legend().get_texts()])
        self.assertEqual(list(ax.lines[0].get_xdata()), payload["curves"]["grid"])
        import matplotlib.pyplot as plt
        plt.close(fig)

    def test_report_fails_instead_of_silently_omitting_curve_figure(self):
        payload = {"meta": {"folder": "batch", "n_curves": 1}}
        client = TestClient(api.app)
        with (
            patch.object(api, "_folder", return_value=Path(".")),
            patch.object(api, "analyse", return_value=payload),
            patch.object(api, "regression_payload", return_value={"error": "no standards"}),
            patch.object(api, "_figures", return_value={}),
        ):
            response = client.get("/api/report?folder=batch")

        self.assertEqual(response.status_code, 500)
        self.assertIn("曲线图生成失败", response.json()["detail"])

    def test_upload_rejects_unsafe_folder_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            data_root.mkdir()
            client = TestClient(api.app)
            with patch.object(api, "DATA_DIR", data_root):
                response = client.post("/api/folders/upload", data={"folder": "../outside"},
                                       files=[("files", ("sample.cor", b"test", "text/plain"))])

            self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
