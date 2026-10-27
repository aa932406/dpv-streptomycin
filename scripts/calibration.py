
#!/usr/bin/env python3
"""
Calibration / regression module.

The current dataset has ONE concentration per condition, so it can only be used
for classification. This module is the regression half of the pipeline: give it a
metadata CSV that has a real concentration column and it will produce a
calibration curve, LOD/LOQ, and a PLS model validated leave-one-electrode-out.

metadata.csv columns
--------------------
file            .cor file name (must match data/)
electrode       electrode / spot ID -- the unit of independent replication
concentration_M analyte concentration in mol/L (0 for the blank)
batch           experiment batch (date, material lot, ...)
group           optional condition label

Usage
-----
python calibration.py --meta metadata.csv --data data --out .
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.cross_decomposition import PLSRegression
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.metrics import r2_score, mean_squared_error

from dpv_pipeline import (parse_cor, group_of, electrode_of, resample,
                          baseline_envelope, extract_features,
                          auto_data_dir, default_out_dir)

GRID = np.round(np.arange(0.80, -0.7801, -0.02), 4)


def load(meta_path, data_dir):
    meta = pd.read_csv(meta_path)
    need = {"file", "electrode", "concentration_M"}
    missing = need - set(meta.columns)
    if missing:
        raise SystemExit(f"metadata is missing columns: {sorted(missing)}")
    meta = meta[meta.concentration_M.notna()].copy()
    if meta.empty:
        raise SystemExit("no row has a concentration_M value -- fill in the column first")

    rows, curves = [], []
    for _, r in meta.iterrows():
        rec = parse_cor(Path(data_dir) / r["file"])
        I = resample(rec["E"], rec["I"], GRID)
        base = baseline_envelope(GRID, I)
        Icorr = (base - I) * 1e6
        f = extract_features(GRID, Icorr, I, rec["ocp"], rec["parms"])
        f.update(r.to_dict())          # metadata columns win on name clashes
        rows.append(f)
        curves.append(Icorr)
    return pd.DataFrame(rows), np.vstack(curves)


def calibration_curve(df, peak_col="cathodic_H"):
    """Ip = a + b*log10(C) over the non-blank standards, then inverse-calibrate.

    LOD is the concentration whose response sits 3.3 sigma above the BLANK
    response:
        y_LOD = mean(blank) + 3.3 * sd(blank)
        LOD   = 10 ** ((y_LOD - a) / b)
    so blank replicates (concentration_M = 0) are required for a real LOD.
    Without them we refuse to invent one -- the old "3.3*syx/|b| decades"
    shortcut silently produced values like 1e2 M, because the fitted intercept
    sits at C = 1 M and not at C -> 0.
    """
    d = df[(df.concentration_M > 0) & df[peak_col].notna()].copy()
    if len(d) < 4:
        return {"error": "need at least 4 non-blank calibration points"}
    levels = np.unique(np.round(d.concentration_M.values, 20))
    if len(levels) < 3:
        return {"error": "calibration needs at least 3 distinct concentration levels, "
                         "found %d (%s). Every standard sits at the same concentration, "
                         "so no slope can be estimated."
                         % (len(levels), ", ".join("%.2e M" % v for v in levels))}
    x = np.log10(d.concentration_M.values)
    y = d[peak_col].values
    b, a = np.polyfit(x, y, 1)
    yhat = a + b * x
    n = len(x)
    syx = float(np.sqrt(((y - yhat) ** 2).sum() / (n - 2)))
    r2 = float(r2_score(y, yhat))
    if r2 < 0.2 or abs(b) < 1e-6:
        return {"error": "calibration is not usable: the peak current does not track "
                         "concentration (r2=%.3f, slope=%.3f). Check that concentration_M "
                         "is filled in and that the peak column is the right one." % (r2, b),
                "r2": float(r2), "slope": float(b)}

    lo, hi = float(d.concentration_M.min()), float(d.concentration_M.max())
    out = {
        "slope_uA_per_decade": float(b),
        "intercept_uA": float(a),
        "r2": r2,
        "syx_uA": syx,
        "n_points": int(n),
        "dynamic_range_M": [lo, hi],
    }

    blanks = df[(df.concentration_M == 0) & df[peak_col].notna()][peak_col].values
    if len(blanks) < 3:
        out["LOD_error"] = (
            "LOD needs at least 3 blank replicates (concentration_M = 0); "
            f"found {len(blanks)}. The curve itself is still valid.")
        return out

    y_lod = blanks.mean() + 3.3 * blanks.std(ddof=1)
    y_loq = blanks.mean() + 10.0 * blanks.std(ddof=1)
    lod = float(10 ** ((y_lod - a) / b))
    loq = float(10 ** ((y_loq - a) / b))
    out["blank"] = {"n": int(len(blanks)), "mean": float(blanks.mean()),
                    "sd": float(blanks.std(ddof=1))}
    if not np.isfinite(lod) or lod <= 0 or lod > hi * 10:
        out["LOD_error"] = (
            f"LOD came out at {lod:.2e} M, outside the calibrated range (up to {hi:.1e} M): "
            "the blank is not separated from the lowest standard, so no LOD can be claimed")
    else:
        out["LOD_M"] = lod
        out["LOQ_M"] = loq if np.isfinite(loq) and 0 < loq <= hi * 10 else None
    return out


def pls_model(df, curves, n_components=3):
    """PLS on the whole baseline-corrected curve, leave-one-electrode-out."""
    # blanks (concentration_M == 0) give log10 = -inf -> must be dropped first,
    # otherwise sklearn raises "Input y contains infinity"
    keep = df.concentration_M.values > 0
    d = df[keep].reset_index(drop=True)
    X = np.asarray(curves, dtype=float)[keep]
    if len(d) < 3:
        return {"error": "need at least 3 non-blank samples for PLS"}
    y = np.log10(d.concentration_M.values)
    groups = d.electrode.values
    logo = LeaveOneGroupOut()
    pred = np.full_like(y, np.nan, dtype=float)
    for tr, te in logo.split(X, y, groups):
        if len(np.unique(y[tr])) < 2:
            continue
        m = PLSRegression(n_components=min(n_components, len(tr) - 1)).fit(X[tr], y[tr])
        pred[te] = m.predict(X[te]).ravel()
    ok = ~np.isnan(pred)
    if ok.sum() < 2:
        return {"error": "too few folds"}
    return {
        "n_folds": int(logo.get_n_splits(X, y, groups)),
        "r2_LOEO": float(r2_score(y[ok], pred[ok])),
        "rmsep_decades": float(np.sqrt(mean_squared_error(y[ok], pred[ok]))),
        "y_true_log10M": y[ok].tolist(),
        "y_pred_log10M": pred[ok].tolist(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--data", default=None, help="folder with .cor files (default: auto)")
    ap.add_argument("--out", default=None, help="output folder (default: out/<date>)")
    ap.add_argument("--peak", default="cathodic_H")
    a = ap.parse_args()
    data_dir = auto_data_dir(a.data)
    out = Path(a.out) if a.out else default_out_dir(data_dir)
    figdir = out / "figures"; figdir.mkdir(parents=True, exist_ok=True)
    df, curves = load(a.meta, data_dir)
    cc = calibration_curve(df, a.peak)
    res = {"calibration": cc, "pls": pls_model(df, curves)}
    with open(out / "calibration_report.json", "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=2)

    if "error" in cc:
        print("calibration:", cc["error"])
        return
    print(f"calibration  r2={cc['r2']:.3f}  slope={cc['slope_uA_per_decade']:.2f} uA/decade")
    if "LOD_M" in cc:
        print(f"LOD = {cc['LOD_M']:.3e} M   LOQ = {cc['LOQ_M']:.3e} M"
              if cc.get("LOQ_M") else f"LOD = {cc['LOD_M']:.3e} M   (LOQ not resolvable)")
    else:
        print("LOD:", cc.get("LOD_error", "not available"))
    p = res["pls"]
    if "error" not in p:
        print(f"PLS LOEO     R2={p['r2_LOEO']:.3f}  RMSEP={p['rmsep_decades']:.2f} decades")

    # figure
    plt.rcParams.update({"figure.dpi": 160, "font.size": 9,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, axs = plt.subplots(1, 2, figsize=(10, 4))
    d = df[(df.concentration_M > 0) & df[a.peak].notna()]
    ax = axs[0]
    ax.scatter(np.log10(d.concentration_M), d[a.peak], s=40, color="#d62728",
               edgecolor="k", linewidth=0.4, zorder=3, label="data")
    xs = np.linspace(np.log10(d.concentration_M).min(), np.log10(d.concentration_M).max(), 50)
    ax.plot(xs, cc["intercept_uA"] + cc["slope_uA_per_decade"] * xs, "k-", lw=1.5,
            label=f"fit  R2={cc['r2']:.3f}")
    ax.set_xlabel("log10 [target] (M)"); ax.set_ylabel(f"{a.peak} (uA)")
    ttl = f"Calibration  LOD={cc['LOD_M']:.2e} M" if "LOD_M" in cc else "Calibration"
    ax.set_title(ttl); ax.legend(frameon=False, fontsize=8)

    ax = axs[1]
    if "error" not in p:
        ax.scatter(p["y_true_log10M"], p["y_pred_log10M"], s=40, color="#1f77b4",
                   edgecolor="k", linewidth=0.4)
        lo = min(p["y_true_log10M"]); hi = max(p["y_true_log10M"])
        ax.plot([lo, hi], [lo, hi], "k--", lw=1)
        ax.set_xlabel("true log10 [target]"); ax.set_ylabel("PLS predicted log10 [target]")
        ax.set_title(f"PLS leave-one-electrode-out  R2={p['r2_LOEO']:.3f}")
    fig.tight_layout(); fig.savefig(figdir / "fig7_calibration.png"); plt.close(fig)
    print("figure ->", figdir / "fig7_calibration.png")


if __name__ == "__main__":
    main()
