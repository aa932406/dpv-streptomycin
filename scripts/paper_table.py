"""Literature-format result table.

The two Food Chemistry 2025 papers this project is modelled on report the same
handful of numbers, so the same numbers are produced here in the same order:

    linear range / sensitivity (uA uM-1 cm-2) / LOD / LOQ /
    R2 (linear) / R2 (RBF-SVR) / RPD / recovery

Nothing is invented: every number comes out of analysis_core + ml_models on the
folder you point at, and anything the data cannot support is reported as a
missing item instead of a plausible-looking figure.

Usage
    python scripts/paper_table.py --data 20261010
    python scripts/paper_table.py --data 20261010 --area 0.0707
    python scripts/paper_table.py --data demo --metric ratio

--area is the geometric area of the working electrode in cm^2.  Screen-printed
carbon electrodes are sold by working-electrode diameter:

    3 mm -> 0.0707 cm^2      4 mm -> 0.1257 cm^2      2 mm -> 0.0314 cm^2

Without --area the sensitivity is reported per electrode (uA uM-1) and the
area-normalised column is left blank, because dividing by a guessed area is how
papers end up with sensitivities that cannot be reproduced.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analysis_core as core          # noqa: E402
import dump_ui_json as dump           # noqa: E402
import ml_models as ml                # noqa: E402

AREA_PRESETS = {"2mm": 0.0314, "3mm": 0.0707, "4mm": 0.1257}

# what the two reference papers report, for the side-by-side column
REFERENCE = [
    {"work": "Food Chem 2025 (STO-VG / Cd2+)", "range": "0.1 - 200 uM", "lod": "1.80 nM",
     "model": "linear + RBF-SVR", "r2": "0.9904 - 0.9948", "rpd": "3.37", "recovery": "95.6 - 105.2 %"},
    {"work": "Food Chem 2025 (ZIF-8/MnMoO4 / CAP,NFZ,MNZ)", "range": "0.005 - 500 uM",
     "lod": "0.08 / 0.29 / 0.23 uM", "model": "BP-ANN (multi-analyte)", "r2": "> 0.99",
     "rpd": "n/a", "recovery": "90 - 110 %"},
]


def _fmt(v, nd=3):
    """Number for the table; an em dash when there is nothing to report.

    The dash matters: a blank cell reads as "forgot to fill it in", an em dash
    reads as "this quantity does not exist for this data".
    """
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)) and not np.isfinite(v):
        return "—"
    return ("%." + str(nd) + "g") % v


def linear_range(df, metric):
    """Straight-line fit of response against concentration (NOT log).

    Papers quote "linear range" and "sensitivity" from this fit, while LOD comes
    from the blank.  Doing both is the reason their tables have a slope in
    uA uM-1 and a LOD in nM at the same time.
    """
    d = df[(df["concentration_M"] > 0) & df[metric].notna()]
    if len(d) < 4 or d["concentration_M"].nunique() < 3:
        return {"error": "linear range needs at least 4 standards over 3 levels, "
                         "have %d over %d" % (len(d), d["concentration_M"].nunique())}
    x = d["concentration_M"].values * 1e6            # uM
    y = d[metric].values.astype(float)
    b, a = np.polyfit(x, y, 1)
    yp = a + b * x
    ss = ((y - y.mean()) ** 2).sum()
    r2 = 1 - ((y - yp) ** 2).sum() / ss if ss > 0 else float("nan")
    return {"slope_uA_per_uM": float(b), "intercept_uA": float(a), "r2": float(r2),
            "n": int(len(d)), "lo_uM": float(x.min()), "hi_uM": float(x.max())}


def build(folder, metric=None, area_cm2=None, seed=0):
    folder = Path(folder)
    df, curves, errors, grid, auto_metric = dump.prepare(folder)
    metric = metric or auto_metric or "ratio"
    if metric not in df.columns:
        return {"error": "metric %r is not in the feature table" % metric}

    out = {"folder": folder.name, "metric": metric, "n_curves": int(len(df)),
           "n_electrodes": int(df["electrode"].nunique()), "errors": errors}

    conc = df["concentration_M"]
    out["n_standards"] = int(((conc > 0) & df[metric].notna()).sum())
    out["n_blanks"] = int(((conc == 0) & df[metric].notna()).sum())
    out["n_levels"] = int(conc[conc > 0].nunique())

    # ---- what the papers call "linear range / sensitivity"
    lin = linear_range(df, metric)
    out["linear"] = lin
    if area_cm2 and not lin.get("error"):
        out["sensitivity_uA_per_uM_per_cm2"] = lin["slope_uA_per_uM"] / area_cm2
        out["area_cm2"] = float(area_cm2)

    # ---- LOD / LOQ from the blanks (same rule the app uses)
    fit = core.fit_calibration(df, metric=metric)
    out["calibration"] = {k: fit.get(k) for k in
                          ("error", "r2", "syx", "a", "b", "direction",
                           "LOD_M", "LOQ_M", "LOD_error", "dynamic_range_M")}
    if fit.get("error"):
        out["calibration_error"] = fit["error"]

    # ---- ML side: same nine models the papers compare against each other
    std = (conc > 0).values & df[metric].notna().values
    if out["n_standards"] >= 6 and out["n_levels"] >= 3 and df.loc[std, "electrode"].nunique() >= 3:
        Xc = curves[std]
        y = conc.values[std]
        g = df.loc[std, "electrode"].astype(str).values
        out["ml_curves"] = ml.evaluate(Xc, y, g, mode="electrode", seed=seed)
        Xf = df.loc[std, ml.FEATURE_KEYS].fillna(0).values
        out["ml_features"] = ml.evaluate(Xf, y, g, mode="electrode", seed=seed)
        for key in ("ml_curves", "ml_features"):
            blk = out[key]
            if blk.get("error"):
                continue
            blk["models"] = [r for r in blk["models"] if r["name"] in
                             ("线性回归", "SVR-RBF", "SVR-线性核", "BP-ANN", "高斯过程")]
    else:
        out["ml_error"] = ("prediction model needs >= 6 standards over >= 3 concentrations "
                           "and >= 3 electrodes; have %d standards over %d concentration(s) "
                           "and %d electrode(s)"
                           % (out["n_standards"], out["n_levels"],
                              df.loc[std, "electrode"].nunique()))

    # ---- recovery: only possible if spiked samples carry a known truth
    sp = df[df["role"].astype(str).str.lower().isin(("sample", "unknown"))] if "role" in df else df.iloc[:0]
    sp = sp[sp["concentration_M"].notna() & (sp["concentration_M"] > 0)]
    if fit.get("error") or not len(sp):
        out["recovery"] = {"error": "no spiked sample with a known concentration "
                                    "(-- recovery needs metadata role=sample + concentration_M)"}
    else:
        preds = []
        for _, r in sp.iterrows():
            p = core.predict_concentration(fit, r[metric])
            if p.get("C") is not None:
                preds.append(100.0 * p["C"] / r["concentration_M"])
        out["recovery"] = ({"n": len(preds), "lo": float(min(preds)), "hi": float(max(preds)),
                            "mean": float(np.mean(preds))} if preds else
                           {"error": "none of the spiked samples fell inside the calibrated range"})
    return out


def conc_text(v):
    """Concentration in whatever unit keeps the number readable."""
    for unit, scale in (("M", 1.0), ("mM", 1e3), ("µM", 1e6), ("nM", 1e9), ("pM", 1e12)):
        if v * scale >= 1:
            return "%.3g %s" % (v * scale, unit)
    return "%.3g pM" % (v * 1e12)


def to_rows(r):
    """(item, our value, literature value) triples.

    One source of truth for both outputs: the markdown file the CLI writes and
    the table the web UI renders.  Anything the data cannot support carries the
    reason instead of a number.
    """
    lin = r.get("linear") or {}
    cal = r.get("calibration") or {}
    rows = []

    rng = (conc_text(lin["lo_uM"] * 1e-6) + " – " + conc_text(lin["hi_uM"] * 1e-6)
           if not lin.get("error") else "— 需要 ≥4 个标准点、≥3 个浓度")
    rows.append(("线性范围", rng, "0.1 – 200 µM"))

    off = (cal.get("direction") == "signal-off")
    sens = ("%.3g µA·µM⁻¹" % abs(lin["slope_uA_per_uM"])) if not lin.get("error") else "—"
    if not lin.get("error") and off:
        sens += "（信号关闭型，取绝对值）"
    if r.get("sensitivity_uA_per_uM_per_cm2"):
        sens += " · %.3g µA·µM⁻¹·cm⁻²（面积 %.4g cm²）" % (
            abs(r["sensitivity_uA_per_uM_per_cm2"]), r["area_cm2"])
    rows.append(("灵敏度", sens, "155.6 µA·µM⁻¹·cm⁻²"))

    lod = cal.get("LOD_M")
    if lod:
        lod_txt = conc_text(lod)
    elif r["n_levels"] < 3:
        lod_txt = "— 只有 %d 个浓度水平，没有浓度梯度，算不出 LOD" % r["n_levels"]
    elif r["n_blanks"] < 3:
        lod_txt = "— 只有 %d 条空白，LOD 至少要 3 条空白才能算" % r["n_blanks"]
    else:
        lod_txt = "— 空白与最低标准点分不开，LOD 落在校准范围之外"
    rows.append(("LOD", lod_txt, "1.80 nM"))
    loq = cal.get("LOQ_M")
    rows.append(("LOQ", conc_text(loq) if loq else "—", "—"))

    rows.append(("R²（线性拟合）", _fmt(lin.get("r2"), 4), "0.9904 – 0.9948"))
    rows.append(("R²（对数线性 I = a + b·log C）", _fmt(cal.get("r2"), 4), "—"))

    blk = r.get("ml_curves") or {}
    if blk.get("error"):
        rows.append(("R²（RBF-SVR）", "— 标准点不足，没跑模型", "0.9904 – 0.9948"))
    elif not r.get("ml_curves"):
        if r["n_levels"] < 3:
            why = "— 只有 %d 个浓度水平，没有浓度梯度，训练不出预测模型" % r["n_levels"]
        elif r["n_standards"] < 6:
            why = "— 只有 %d 条标准点，至少要 6 条" % r["n_standards"]
        else:
            why = "— 标准点集中在 %d 支电极上，至少要 3 支才能做留一电极验证" % r["n_electrodes"]
        rows.append(("R²（RBF-SVR）", why, "0.9904 – 0.9948"))
    else:
        by_name = {m["name"]: m for m in blk.get("models", [])}
        svr = by_name.get("SVR-RBF", {})
        rows.append(("R²（RBF-SVR，留一电极）", _fmt(svr.get("r2"), 4), "0.9904 – 0.9948"))
        rows.append(("RPD（最佳模型 %s）" % blk.get("best"),
                     _fmt((blk.get("best_row") or {}).get("rpd")), "3.37"))

    rec = r.get("recovery") or {}
    rows.append(("加标回收率",
                 "%.1f – %.1f %%" % (rec["lo"], rec["hi"]) if rec.get("n")
                 else "— 没有加标样品（需要 metadata 里 role=sample 且填了浓度真值）",
                 "95.6 – 105.2 %"))

    note = ""
    if lin.get("r2") is not None and lin["r2"] < 0.9 and not lin.get("error"):
        note = ("全范围直线拟合 R² 只有 %.2f：这个体系是**对数线性**（I 与 log C 成直线），"
                "不是浓度线性。论文里 0.1–200 µM 的线性范围来自吸附溶出这类近线性响应；"
                "要报线性范围，得把标准点铺密，在信号饱和之前找那一段。" % lin["r2"])
    return rows, note


def to_markdown(r):
    rows, note = to_rows(r)
    lines = ["| 项目 | 本次数据 | 论文对照 |", "|---|---|---|"]
    lines += ["| %s | %s | %s |" % (a, b, c) for a, b, c in rows]
    if note:
        lines += ["", "> " + note]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="folder name under data/, or a path")
    ap.add_argument("--metric", default=None)
    ap.add_argument("--area", default=None,
                    help="working-electrode area in cm^2 (0.0707 = 3 mm, 0.1257 = 4 mm)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    area = a.area
    if area in AREA_PRESETS:
        area = AREA_PRESETS[area]
    area = float(area) if area not in (None, "") else None

    root = Path(__file__).resolve().parent.parent
    folder = Path(a.data)
    if not folder.exists():
        cand = root / "data" / a.data
        if not cand.exists():
            sys.exit("no such folder: %s (tried %s and %s)" % (a.data, folder, cand))
        folder = cand

    r = build(folder, a.metric, area)
    if r.get("error"):
        sys.exit(r["error"])

    out_dir = Path(a.out) if a.out else (root / "out" / folder.name)
    out_dir.mkdir(parents=True, exist_ok=True)

    md = to_markdown(r)
    (out_dir / "paper_table.md").write_text(md, encoding="utf-8")
    (out_dir / "paper_table.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=float),
                                              encoding="utf-8")
    if r.get("ml_curves") and not r["ml_curves"].get("error"):
        pd.DataFrame(r["ml_curves"]["models"]).to_csv(out_dir / "paper_models.csv", index=False,
                                                     encoding="utf-8-sig")

    print("folder      :", r["folder"], "| metric:", r["metric"])
    print("curves      :", r["n_curves"], "| electrodes:", r["n_electrodes"],
          "| standards:", r["n_standards"], "| blanks:", r["n_blanks"], "| levels:", r["n_levels"])
    print()
    print(md)
    if r.get("ml_error"):
        print("\nML        :", r["ml_error"])
    print("\nwritten ->", out_dir / "paper_table.md")


if __name__ == "__main__":
    main()
