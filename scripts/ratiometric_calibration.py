#!/usr/bin/env python3
"""
Ratiometric calibration for the streptomycin / MB-DNA sensor.

Model
-----
    r = I_MB / I_ref          (dimensionless, cancels electrode-to-electrode area)
    I_MB   = peak in the narrow window -0.42..-0.28 V  (excludes the MIL-101 Fe peak at -0.45)
    I_ref  = peak in the window +0.25..+0.50 V

    r = a + b * log10(C)      log-linear, the usual sensor calibration form
    or a 4-parameter logistic for a saturating response

QC
--
    A trace is rejected when I_ref < --ref-min (default 1.0 uA). The reference peak
    is the built-in electrode-quality gate: if the MOF signal did not develop, the
    whole trace is unreliable.

LOD
---
    From the blank replicates:  LOD = (r_blank + 3*sd_blank) mapped back to C
    through the fitted curve. Reported in mol/L.

Usage
-----
    python ratiometric_calibration.py --meta metadata.csv --data data --out .
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from sklearn.cross_decomposition import PLSRegression
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.metrics import r2_score

from dpv_pipeline import (parse_cor, group_of, electrode_of, resample,
                          baseline_envelope, auto_data_dir, default_out_dir)

GRID = np.round(np.arange(0.80, -0.7801, -0.02), 4)
MB_WIN = (-0.42, -0.28)      # narrow: keeps the MIL-101 Fe peak at -0.45 out
REF_WIN = (0.25, 0.50)


def peak_in(grid, y, win):
    m = (grid >= win[0]) & (grid <= win[1])
    if not m.any():
        return np.nan, np.nan
    x, v = grid[m], y[m]
    i = int(np.argmax(v))
    return float(v[i]), float(x[i])


def measure(path):
    rec = parse_cor(path)
    I = resample(rec["E"], rec["I"], GRID)
    base = baseline_envelope(GRID, I)
    y = (base - I) * 1e6
    mb, mb_ep = peak_in(GRID, y, MB_WIN)
    ref, ref_ep = peak_in(GRID, y, REF_WIN)
    return dict(file=rec["file"], group=group_of(rec["file"]), electrode=electrode_of(rec["file"]),
                I_MB=mb, MB_Ep=mb_ep, I_ref=ref, ref_Ep=ref_ep,
                ratio=mb / ref if ref and ref > 0 else np.nan), y


def four_pl(x, bottom, top, ec50, hill):
    return bottom + (top - bottom) / (1.0 + (10 ** ec50 / 10 ** x) ** hill)


def calibrate(df, mode="loglinear"):
    d = df[(df.concentration_M > 0) & df.ratio.notna()].copy()
    x = np.log10(d.concentration_M.values)
    y = d.ratio.values
    if len(d) < 4:
        return {"error": f"need >=4 calibration points, have {len(d)}"}
    levels = np.unique(np.round(d.concentration_M.values, 20))
    if len(levels) < 3:
        return {"error": "calibration needs at least 3 distinct concentration levels, "
                         "found %d (%s). Every standard sits at the same concentration, "
                         "so no slope can be estimated."
                         % (len(levels), ", ".join("%.2e M" % v for v in levels))}
    if mode == "loglinear":
        b, a = np.polyfit(x, y, 1)
        yhat = a + b * x
        inv = lambda r: 10 ** ((r - a) / b)
        params = {"a": float(a), "b": float(b)}
    else:
        p0 = [y.min(), y.max(), np.median(x), 1.0]
        p, _ = curve_fit(four_pl, x, y, p0=p0, maxfev=40000,
                         bounds=([-np.inf, -np.inf, x.min() - 3, 0.1],
                                 [np.inf, np.inf, x.max() + 3, 10]))
        yhat = four_pl(x, *p)
        params = dict(zip(["bottom", "top", "log_ec50", "hill"], map(float, p)))
        def inv(r, p=p):
            bottom, top, ec50, hill = p
            frac = (r - bottom) / (top - bottom)
            frac = np.clip(frac, 1e-6, 1 - 1e-6)
            return 10 ** (ec50 - np.log10(1 / frac - 1) / hill)
    r2 = r2_score(y, yhat)
    syx = float(np.sqrt(((y - yhat) ** 2).sum() / max(len(y) - 2, 1)))
    out = {"mode": mode, "params": params, "r2": r2, "syx": syx, "n_points": int(len(d)),
           "dynamic_range_M": [float(d.concentration_M.min()), float(d.concentration_M.max())]}
    if r2 < 0.8:
        out["quality"] = f"poor fit (r2={r2:.2f}): treat slope/LOD with caution"
    blanks = df[(df.concentration_M == 0) & df.ratio.notna()].ratio.values
    if len(blanks) >= 3:
        thr = blanks.mean() + 3 * blanks.std(ddof=1)
        try:
            lod = float(inv(thr))
            loq = float(inv(blanks.mean() + 10 * blanks.std(ddof=1)))
            out["blank"] = {"n": int(len(blanks)), "mean": float(blanks.mean()),
                            "sd": float(blanks.std(ddof=1)), "threshold_3sd": float(thr)}
            # sanity: an LOD far above the calibrated range is extrapolation
            # nonsense (near-zero slope, or blank indistinguishable from the
            # lowest standard).  Report that instead of a fake number.
            hi = out["dynamic_range_M"][1]
            if not np.isfinite(lod) or lod <= 0 or lod > hi * 10:
                out["LOD_error"] = (
                    f"LOD came out at {lod:.2e} M, outside the calibrated range "
                    f"(up to {hi:.1e} M): the blank is not separated from the "
                    f"lowest standard, so no LOD can be claimed")
            else:
                out["LOD_M"] = lod
                out["LOQ_M"] = loq if np.isfinite(loq) and loq <= hi * 10 else None
        except Exception as e:
            out["LOD_error"] = str(e)
    else:
        out["LOD_error"] = "need >=3 blank replicates (concentration_M = 0) to compute LOD"
    return out


def pls_curves(df, curves):
    # blanks have C = 0 -> log10 undefined; PLS runs on the calibration points only
    keep = (df.concentration_M.values > 0)
    df, curves = df[keep], np.asarray(curves)[keep]
    y = np.log10(df.concentration_M.values)
    g = df.electrode.values
    logo = LeaveOneGroupOut()
    pred = np.full_like(y, np.nan)
    for tr, te in logo.split(curves, y, g):
        if len(np.unique(y[tr])) < 2:
            continue
        m = PLSRegression(n_components=min(3, len(tr) - 1)).fit(curves[tr], y[tr])
        pred[te] = m.predict(curves[te]).ravel()
    ok = ~np.isnan(pred)
    if ok.sum() < 2:
        return {"error": "too few folds"}
    return {"n_folds": int(logo.get_n_splits(curves, y, g)),
            "r2_LOEO": float(r2_score(y[ok], pred[ok])),
            "rmsep_decades": float(np.sqrt(np.mean((y[ok] - pred[ok]) ** 2))),
            "y_true": y[ok].tolist(), "y_pred": pred[ok].tolist()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--data", default=None, help="folder with .cor files (default: auto)")
    ap.add_argument("--out", default=None, help="output folder (default: out/<date>)")
    ap.add_argument("--ref-min", type=float, default=1.0)
    ap.add_argument("--model", default="loglinear", choices=["loglinear", "4pl"])
    a = ap.parse_args()
    data_dir = auto_data_dir(a.data)
    out = Path(a.out) if a.out else default_out_dir(data_dir)
    (out / "figures").mkdir(parents=True, exist_ok=True)

    meta = pd.read_csv(a.meta)
    if "concentration_M" not in meta.columns:
        raise SystemExit("metadata needs a concentration_M column")
    meta = meta[meta.concentration_M.notna()]
    if meta.empty:
        raise SystemExit("no row has a concentration_M value -- fill in the column first")

    rows, curves = [], []
    for _, r in meta.iterrows():
        m, y = measure(data_dir / r["file"])
        m.update(r.to_dict())
        rows.append(m); curves.append(y)
    df = pd.DataFrame(rows)
    df["qc_pass"] = df.I_ref >= a.ref_min

    rejected = df[~df.qc_pass]
    good = df[df.qc_pass].copy()
    curves = [c for c, k in zip(curves, df.qc_pass.values) if k]

    res = {"qc": {"threshold_uA": a.ref_min, "n_total": int(len(df)),
                  "n_pass": int(len(good)), "rejected": rejected.file.tolist()},
           "calibration": calibrate(good, a.model),
           "pls": pls_curves(good, np.vstack(curves))}
    with open(out / "ratiometric_report.json", "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=2)

    c = res["calibration"]
    if "error" in c:
        print("calibration:", c["error"]); return
    print(f"calibration {c['mode']}: r2={c['r2']:.3f}  Syx={c['syx']:.3f}  n={c['n_points']}")
    print(f"range {c['dynamic_range_M'][0]:.2e} - {c['dynamic_range_M'][1]:.2e} M")
    if "LOD_M" in c:
        print(f"blank: {c['blank']['mean']:.2f} +- {c['blank']['sd']:.2f} (n={c['blank']['n']})")
        print(f"LOD = {c['LOD_M']:.2e} M   LOQ = {c['LOQ_M']:.2e} M")
    else:
        print("LOD:", c["LOD_error"])
    p = res["pls"]
    if "error" not in p:
        print(f"PLS LOEO: R2={p['r2_LOEO']:.3f}  RMSEP={p['rmsep_decades']:.2f} decades")

    # figure
    plt.rcParams.update({"figure.dpi": 160, "font.size": 9,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, axs = plt.subplots(1, 2, figsize=(10.5, 4.2))
    ax = axs[0]
    for cond, sub in good.groupby("condition" if "condition" in good else "group"):
        ax.scatter(np.log10(sub.concentration_M.replace(0, np.nan)), sub.ratio,
                   s=48, edgecolor="k", linewidth=0.4, label=str(cond), zorder=3)
    d = good[good.concentration_M > 0]
    xs = np.linspace(np.log10(d.concentration_M).min(), np.log10(d.concentration_M).max(), 100)
    if c["mode"] == "loglinear":
        ax.plot(xs, c["params"]["a"] + c["params"]["b"] * xs, "k-", lw=1.4,
                label=f"fit R2={c['r2']:.3f}")
    else:
        ax.plot(xs, four_pl(xs, *[c["params"][k] for k in ["bottom", "top", "log_ec50", "hill"]]),
                "k-", lw=1.4, label=f"4PL R2={c['r2']:.3f}")
    if "blank" in c:
        b = c["blank"]
        ax.axhline(b["mean"], color="0.5", ls="--", lw=1, label="blank")
        ax.axhline(b["threshold_3sd"], color="#d62728", ls=":", lw=1, label="blank+3sd")
    ax.set_xlabel("log10 [streptomycin] (M)"); ax.set_ylabel("I$_{MB}$ / I$_{ref}$")
    ax.set_title("Ratiometric calibration"); ax.legend(frameon=False, fontsize=7.5)

    ax = axs[1]
    if "error" not in p:
        ax.scatter(p["y_true"], p["y_pred"], s=48, color="#1f77b4", edgecolor="k", linewidth=0.4)
        lo, hi = min(p["y_true"]), max(p["y_true"])
        ax.plot([lo, hi], [lo, hi], "k--", lw=1)
        ax.set_xlabel("true log10 [S]"); ax.set_ylabel("PLS predicted log10 [S]")
        ax.set_title(f"PLS leave-one-electrode-out  R2={p['r2_LOEO']:.3f}")
    figpath = out / "figures" / "fig9_calibration.png"
    fig.tight_layout(); fig.savefig(figpath); plt.close(fig)
    print("figure ->", figpath)


if __name__ == "__main__":
    main()
