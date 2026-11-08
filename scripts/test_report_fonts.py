#!/usr/bin/env python3
"""Regression tests for report figure font configuration."""
import io
import sys
import unittest
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import app as api


class ReportFigureTests(unittest.TestCase):
    def test_report_png_uses_available_cjk_font(self):
        fig, ax = plt.subplots()
        ax.plot([0, 1], [0, 1], label="g1 有酶有目标物 dpv_2")
        ax.set_title("Baseline-corrected DPV")
        ax.legend()

        image = api._png(fig)
        self.assertTrue(image.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(plt.rcParams["font.sans-serif"][0] in {
            "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC",
            "Source Han Sans SC", "WenQuanYi Zen Hei", "PingFang SC",
        })
        plt.close(fig)


if __name__ == "__main__":
    unittest.main()
