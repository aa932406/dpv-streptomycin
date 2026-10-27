#!/usr/bin/env python3
"""
report.py -- turn the finished analysis into a folder a human can hand in.

Produces a .zip containing:
    report.html   self-contained, images embedded, opens in any browser
    report.docx   Word version (only if python-docx is installed)
    figures/*.png
    tables/*.csv
"""
from __future__ import annotations

import base64
import io
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd


def _fig_png(fig, dpi=170) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    buf.seek(0)
    return buf.read()


def _b64(png: bytes) -> str:
    return base64.b64encode(png).decode("ascii")


CSS = """
body{font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;max-width:960px;
     margin:32px auto;padding:0 20px;color:#1f2328;line-height:1.6}
h1{border-bottom:3px solid #1f77b4;padding-bottom:8px;font-size:24px}
h2{margin-top:34px;border-left:5px solid #1f77b4;padding-left:10px;font-size:18px}
h3{margin-top:22px;font-size:15px;color:#333}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}
th,td{border:1px solid #d8dee4;padding:6px 9px;text-align:left}
th{background:#f0f3f6;font-weight:600}
tr:nth-child(even) td{background:#fafbfc}
img{max-width:100%;margin:10px 0;border:1px solid #eaeef2;border-radius:4px}
.kpi{display:flex;gap:14px;flex-wrap:wrap;margin:16px 0}
.kpi div{flex:1;min-width:170px;background:#f6f8fa;border:1px solid #e1e6eb;
         border-radius:8px;padding:12px 14px}
.kpi b{display:block;font-size:22px;color:#0969da;margin-top:4px}
.note{background:#fff8e5;border-left:4px solid #d4a72c;padding:10px 14px;margin:14px 0;
      border-radius:0 6px 6px 0;font-size:13px}
.fake{background:#ffecec;border-left:4px solid #cf222e}
.pos{color:#cf222e;font-weight:700}.neg{color:#1a7f37;font-weight:700}
.meta{color:#656d76;font-size:12px}
"""


def build_html(summary: dict, figures: dict, tables: dict, extra_html: str = "") -> str:
    parts = ["<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
             "<title>%s</title><style>%s</style></head><body>" % (summary.get("title", "DPV 分析报告"), CSS),
             "<h1>%s</h1>" % summary.get("title", "DPV 分析报告"),
             "<p class='meta'>生成时间 %s &nbsp;|&nbsp; %s</p>" %
             (datetime.now().strftime("%Y-%m-%d %H:%M"), summary.get("subtitle", ""))]

    if summary.get("warning"):
        parts.append("<div class='note fake'>%s</div>" % summary["warning"])

    kpis = summary.get("kpis") or []
    if kpis:
        parts.append("<div class='kpi'>")
        for k, v in kpis:
            parts.append("<div>%s<b>%s</b></div>" % (k, v))
        parts.append("</div>")

    for heading, text in summary.get("sections", []):
        parts.append("<h2>%s</h2>" % heading)
        parts.append(text)

    for name, fig in figures.items():
        parts.append("<h2>%s</h2>" % name)
        parts.append("<img src='data:image/png;base64,%s'>" % _b64(_fig_png(fig)))

    for name, df in tables.items():
        parts.append("<h2>%s</h2>" % name)
        parts.append(df.to_html(index=False, border=0, float_format=lambda v: "%.4g" % v))

    parts.append(extra_html)
    parts.append("</body></html>")
    return "".join(parts)


def _build_docx(summary, figures, tables):
    try:
        from docx import Document
        from docx.shared import Inches, Pt
    except Exception:
        return None
    doc = Document()
    doc.add_heading(summary.get("title", "DPV 分析报告"), level=0)
    doc.add_paragraph("生成时间 %s    %s" % (datetime.now().strftime("%Y-%m-%d %H:%M"),
                                          summary.get("subtitle", "")))
    if summary.get("warning"):
        p = doc.add_paragraph(summary["warning"])
        p.runs[0].bold = True
    for heading, text in summary.get("sections", []):
        doc.add_heading(heading, level=1)
        doc.add_paragraph(_strip_tags(text))
    for name, fig in figures.items():
        doc.add_heading(name, level=1)
        doc.add_picture(io.BytesIO(_fig_png(fig)), width=Inches(6.2))
    for name, df in tables.items():
        doc.add_heading(name, level=1)
        df2 = df.copy()
        t = doc.add_table(rows=1, cols=len(df2.columns))
        t.style = "Light Grid Accent 1"
        for i, c in enumerate(df2.columns):
            t.rows[0].cells[i].text = str(c)
        for _, row in df2.iterrows():
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = ("%.4g" % v) if isinstance(v, float) else str(v)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _strip_tags(s: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ")


def build_zip(summary, figures, tables, extra_html="", raw_files=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.html", build_html(summary, figures, tables, extra_html))
        for name, fig in figures.items():
            z.writestr("figures/%s.png" % _safe(name), _fig_png(fig))
        for name, df in tables.items():
            z.writestr("tables/%s.csv" % _safe(name),
                       df.to_csv(index=False).encode("utf-8-sig"))
        docx = _build_docx(summary, figures, tables)
        if docx:
            z.writestr("report.docx", docx)
        for name, data in (raw_files or {}).items():
            z.writestr("data/%s" % name, data)
    buf.seek(0)
    return buf.read()


def _safe(name: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in name)[:60]
