#!/usr/bin/env python
"""Validate our models on an EXTERNAL public dataset.

Target: https://github.com/miralab-ai/biosensors-AI
        Yeke et al., "A machine learning framework for advanced analytical
        detection of CD36 using immunosensors below limit of detection",
        Biosensors and Bioelectronics: X (2026).  MIT licence.

What that repo ships: 60 real DPV curves, 12 concentration levels (0, 0.005,
0.010, 0.025, 0.035, 0.050, 1, 5, 10, 15, 20, 25 ng/mL) x 5 replicates, all on
an identical grid (-0.400 .. +0.798 V, 239 points, 5 mV).

What that paper does NOT do: group the cross-validation.  Its split is
train_test_split(X, y, test_size=0.2, random_state=40, stratify=y) -- a random
80/20 split of ROWS, so every test curve sits next to four curves of the SAME
concentration in the training set, and in its "augmented" mode the training set
literally contains convex combinations of the test curves.  A random split
answers "can you recognise a repeat of a level you already measured", not
"can you quantify a sample".

This script therefore runs three protocols on the same 60 curves:

  P1  their protocol       random 80/20 stratified split, y = class index
  P2  leave one replicate  out of 60 folds, y = log10 concentration
  P3  leave one LEVEL out  12 folds -- never seen this concentration before

P3 is the only one that answers the sensor question.  P1 vs P3 is the size of
the leak, measured on somebody else's data instead of ours.

Usage:
    python scripts/validate_external.py --data /path/to/lab_measurements
    python scripts/validate_external.py --data ... --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ml_models as ml  # noqa: E402

# folder name -> concentration in ng/mL.  The repo folder names are not
# machine-friendly ("01 ng" is 1 ng, "05 ng" is 5 ng), so map them explicitly.
LEVELS = {
    "0 ng": 0.0,
    "0.005 ng": 0.005,
    "0.010 ng": 0.010,
    "0.025 ng": 0.025,
    "0.035 ng": 0.035,
    "0.050 ng": 0.050,
    "01 ng": 1.0,
    "05 ng": 5.0,
    "10 ng": 10.0,
    "15 ng": 15.0,
    "20 ng": 20.0,
    "25 ng": 25.0,
}


def load_repo(root) -> dict:
    """Read every .xlsx in data/lab_measurements/<level>/<rep>.xlsx."""
    import pandas as pd

    root = Path(root)
    if not root.is_dir():
        sys.exit("--data %s: not a directory" % root)
    if not (root / "0 ng").is_dir():
        alt = root / "data" / "lab_measurements"
        if alt.is_dir():
            root = alt

    curves, conc, rep, cls_name, files = [], [], [], [], []
    grid = None
    for folder in sorted(os.listdir(root)):
        d = root / folder
        if not d.is_dir():
            continue
        if folder not in LEVELS:
            print("  ! skipping unknown folder %r" % folder)
            continue
        level = LEVELS[folder]
        names = sorted(f for f in os.listdir(d) if f.endswith((".xlsx", ".xls")))
        if not names:
            continue
        for k, fn in enumerate(names, 1):
            df = pd.read_excel(d / fn, sheet_name=0, header=0)
            e = pd.to_numeric(df.iloc[1:, 0], errors="coerce")
            i = pd.to_numeric(df.iloc[1:, 1], errors="coerce")
            ok = e.notna() & i.notna()
            ev, iv = e[ok].values.astype(float), i[ok].values.astype(float)
            if grid is None:
                grid = ev
            elif len(ev) != len(grid) or not np.allclose(ev, grid, atol=1e-4):
                print("  ! %s does not share the common potential grid, skipped" % fn)
                continue
            curves.append(iv)
            conc.append(level)
            rep.append("%s#%d" % (folder, k))
            cls_name.append(folder)
            files.append(fn)

    if not curves:
        sys.exit("no DPV curves found under %s" % root)
    return {
        "grid": grid,
        "X": np.vstack(curves),
        "conc": np.array(conc, float),
        "rep": np.array(rep),
        "cls": np.array(cls_name),
        "files": files,
        "root": str(root),
    }


def features(X, grid) -> np.ndarray:
    """A small physical feature set -- what a chemist reads off by hand."""
    cols = []
    for v in (0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.60):
        k = int(np.argmin(np.abs(grid - v)))
        cols.append(X[:, k])
    peak = X[:, 40:180].max(axis=1)
    base = np.median(np.c_[X[:, :40], X[:, 180:]], axis=1)
    cols += [peak, peak - base, X.max(axis=1), np.trapezoid(np.abs(X), grid, axis=1)]
    return np.column_stack(cols)


def their_protocol(X, y_class, seed=40, test_size=0.2) -> list:
    """Random stratified 80/20 row split -- exactly what the repo does."""
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import accuracy_score, mean_squared_error, r2_score
    from sklearn.model_selection import train_test_split
    from sklearn.neighbors import KNeighborsRegressor
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVR
    from sklearn.tree import DecisionTreeRegressor

    models = {
        "线性回归": LinearRegression(),
        "SVR": SVR(),
        "决策树": DecisionTreeRegressor(random_state=seed),
        "随机森林": RandomForestRegressor(n_estimators=100, random_state=seed),
        "梯度提升": GradientBoostingRegressor(random_state=seed),
        "高斯过程": GaussianProcessRegressor(random_state=seed),
        "KNN": KNeighborsRegressor(),
        "BP-ANN": MLPRegressor(random_state=seed),
    }
    out = []
    for win in [(100, 120), (80, 140), (60, 160)]:
        Xw = X[:, win[0]:win[1]]
        Xtr, Xte, ytr, yte = train_test_split(
            Xw, y_class, test_size=test_size, random_state=seed, stratify=y_class)
        sc = StandardScaler().fit(Xtr)
        for name, m in models.items():
            m.fit(sc.transform(Xtr), ytr)
            p = m.predict(sc.transform(Xte))
            out.append({
                "window": "%d-%d" % win,
                "model": name,
                "r2": float(r2_score(yte, p)),
                "rmse": float(np.sqrt(mean_squared_error(yte, p))),
                "acc": float(accuracy_score(yte, np.clip(np.round(p), 0, 11))),
            })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True,
                    help="the repo's data/lab_measurements folder")
    ap.add_argument("--json", default="", help="write the full result table here")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--perm", type=int, default=100)
    args = ap.parse_args()

    d = load_repo(args.data)
    X, grid, conc = d["X"], d["grid"], d["conc"]
    levels = np.unique(conc)
    print("=" * 78)
    print("external dataset: %s" % d["root"])
    print("  %d curves | %d levels | %d replicates/level | %d points (%.3f .. %.3f V)"
          % (len(conc), len(levels), len(conc) // max(len(levels), 1),
             X.shape[1], grid[0], grid[-1]))
    print("  levels (ng/mL): %s" % ", ".join("%g" % v for v in levels))

    print("")
    print("-- signal level by concentration (current at +0.15 V, uA) --")
    k15 = int(np.argmin(np.abs(grid - 0.15)))
    for lv in levels:
        m = conc == lv
        v = X[m, k15]
        sd = v.std(ddof=1) if len(v) > 1 else 0.0
        print("   %8.3f ng/mL  mean %6.2f  sd %5.2f  cv %5.1f%%  n=%d"
              % (lv, v.mean(), sd, 100 * sd / abs(v.mean()) if v.mean() else 0, len(v)))

    y_class = np.array([list(levels).index(c) for c in conc], float)
    res = {"root": d["root"], "n_curves": int(len(conc)),
           "levels": [float(v) for v in levels]}

    print("")
    print("=" * 78)
    print("P1  paper protocol: random 80/20 split (same-level replicates stay in train)")
    p1 = their_protocol(X, y_class, seed=40)
    best = {}
    for row in p1:
        k = row["window"]
        if k not in best or row["r2"] > best[k]["r2"]:
            best[k] = row
    for w in sorted(best):
        row = best[w]
        print("   window %-8s best %-6s R2 %8.4f  RMSE %6.3f  acc %.2f"
              % (w, row["model"], row["r2"], row["rmse"], row["acc"]))
    print("   -> best R2 over all windows/models: %.4f" % max(r["r2"] for r in p1))
    res["P1"] = p1

    F = features(X, grid)
    sets = [("整条曲线（%d 点）" % X.shape[1], X),
            ("手工特征（%d 个）" % F.shape[1], F)]
    for title, key, groups, mode in [
        ("P2  leave one replicate out: 60 folds (4 same-level replicates stay in train)",
         "P2", d["rep"], "electrode"),
        ("P3  leave one LEVEL out: 12 folds (this concentration never seen)", "P3",
         d["cls"], "batch"),
    ]:
        print("")
        print("=" * 78)
        print(title)
        block = []
        for sname, M in sets:
            try:
                r = ml.evaluate(M, conc, groups, mode=mode, seed=args.seed)
            except Exception as exc:                       # noqa: BLE001
                print("   %-24s ERROR %s" % (sname, exc))
                continue
            br = r["best_row"]
            print("   %-24s best=%-10s R2 %8.4f  %6.3f dex  %6.2fx  RPD %5.2f"
                  % (sname, r["best"], br["r2"], br.get("rmse_dex") or 0,
                     br.get("factor") or 0, br["rpd"]))
            for row in r["models"]:
                block.append({"protocol": key, "set": sname,
                              "name": row["name"], "r2": row["r2"],
                              "rmse": row["rmse"], "mae": row["mae"],
                              "rpd": row["rpd"], "n": row["n"],
                              "n_folds": row["n_folds"],
                              "rmse_dex": row.get("rmse_dex")})
        res[key] = block

    print("")
    print("=" * 78)
    print("permutation test (P2 unit, shuffle the 60 concentration labels, %d rounds)"
          % args.perm)
    rng = np.random.default_rng(args.seed)
    # a FIXED SVR (no inner grid search): a grid inside 60 folds x N rounds is
    # 12 fits per fold and turns the permutation test into a two-hour job.
    from sklearn.svm import SVR
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    one = {"SVR-RBF": (Pipeline([("sc", StandardScaler()), ("m", SVR(C=10.0, gamma="scale"))]), {})}
    obs = ml.evaluate(F, conc, d["rep"], mode="electrode", seed=args.seed, models=one)
    obs_r2 = obs["best_row"]["r2"]
    null = []
    for _i in range(args.perm):
        if _i and _i % 10 == 0:
            print("   ... %d / %d" % (_i, args.perm))
        yp = rng.permutation(conc)
        try:
            rr = ml.evaluate(F, yp, d["rep"], mode="electrode", seed=args.seed, models=one)
            null.append(rr["best_row"]["r2"])
        except Exception:                                   # noqa: BLE001
            pass
    null = np.array(null)
    p = (1 + int((null >= obs_r2).sum())) / (1 + len(null))
    print("   observed R2 %.4f | null mean %.4f  p95 %.4f  max %.4f | p = %.4f"
          % (obs_r2, null.mean(), np.percentile(null, 95), null.max(), p))
    res["permutation"] = {"observed_r2": float(obs_r2),
                          "null_mean": float(null.mean()),
                          "null_p95": float(np.percentile(null, 95)),
                          "null_max": float(null.max()),
                          "p_value": float(p)}

    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=2, ensure_ascii=False), "utf-8")
        print("")
        print("full table -> %s" % args.json)


if __name__ == "__main__":
    main()
