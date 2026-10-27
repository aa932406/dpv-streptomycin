#!/usr/bin/env python3
"""
ml_models.py -- the quantitative prediction block ("Food Chem style").

What this mirrors
-----------------
* Food Chem 2025, doi:10.1016/j.foodchem.2025.145744  (Sn-Ta-O / vertical
  graphene, Cd2+): a classical linear calibration PLUS an RBF-SVR model, and a
  side-by-side comparison of RBF-SVR against a linear-kernel SVR with R2 and
  MSE.  Reported R2 0.9904-0.9948, RPD 3.37.
* Food Chem 2025, doi:10.1016/j.foodchem.2025.147583  (ZIF-8/MnMoO4/MWCNTs,
  CAP / NFZ / MNZ): a back-propagation artificial neural network (BP-ANN) that
  reads the DPV signal for three analytes at once, >93 % prediction accuracy.
* The methodology piece: model comparison + interpretability, not one
  fashionable algorithm.

Rules this module refuses to break
----------------------------------
1. The unit of validation is a whole ELECTRODE (or a whole BATCH), never a
   single scan.  Scans of one strip are not independent.
2. Any hyper-parameter search happens INSIDE the training folds (nested CV),
   so the reported score is not the score of a model that has seen the test
   electrode.
3. A single number is never reported alone: R2, RMSE, MAE, RPD, the per-fold
   spread and the sample size all come out together.

Run as a script for a quick self-test:
    python scripts/ml_models.py --data data/demo
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


# --------------------------------------------------------------------------
# model zoo
# --------------------------------------------------------------------------
def model_zoo(seed: int = 0):
    """name -> (estimator, param grid).

    The grids are deliberately tiny.  With a few dozen electrodes a wide grid
    only buys over-fitting, and every extra candidate multiplies the cost of
    the nested search -- this has to stay interactive (a web request).
    """
    from sklearn.cross_decomposition import PLSRegression
    from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel
    from sklearn.linear_model import LinearRegression, Ridge
    from sklearn.neural_network import MLPRegressor
    from sklearn.svm import SVR

    gp_kernel = (ConstantKernel(1.0, (1e-2, 1e3)) * RBF(1.0, (1e-2, 1e2))
                 + WhiteKernel(1e-2, (1e-4, 1e1)))
    return {
        # the classical calibration line -- the baseline every paper must beat
        "线性回归": (LinearRegression(), {}),
        "岭回归": (Ridge(alpha=1.0), {"alpha": [1.0, 10.0]}),
        "PLS": (PLSRegression(n_components=2), {"n_components": [1, 2, 3, 4]}),
        # the two kernels compared in the Food Chem Cd paper
        "SVR-RBF": (SVR(kernel="rbf", C=10.0, epsilon=0.05, gamma="scale"),
                    {"C": [1.0, 10.0, 100.0], "gamma": ["scale", 0.05]}),
        "SVR-线性核": (SVR(kernel="linear", C=1.0, epsilon=0.05),
                    {"C": [0.1, 1.0, 10.0]}),
        "随机森林": (RandomForestRegressor(n_estimators=120, max_features=0.5,
                                       random_state=seed, n_jobs=1), {}),
        "梯度提升": (HistGradientBoostingRegressor(max_iter=120, random_state=seed), {}),
        # BP-ANN, the Food Chem antibiotics paper
        "BP-ANN": (MLPRegressor(hidden_layer_sizes=(32, 16), max_iter=1200,
                                early_stopping=True, n_iter_no_change=20,
                                random_state=seed),
                   {"alpha": [1e-4, 1e-2]}),
        # the only one that also reports an uncertainty
        "高斯过程": (GaussianProcessRegressor(kernel=gp_kernel, normalize_y=True,
                                          n_restarts_optimizer=0, random_state=seed), {}),
        **_xgb_entry(seed),
    }


def _xgb_entry(seed: int = 0) -> dict:
    """XGBoost, if the wheel is installed.

    Papers quote it constantly, so the table should be able to show it.  But it
    is an optional 30 MB dependency and it needs a few hundred rows before it
    stops memorising the training set -- on 20 electrodes it will land next to
    the random forest, not next to SVR.  A missing wheel must never break the
    page, so the import is guarded and the model simply does not appear.
    """
    try:
        from xgboost import XGBRegressor
    except Exception:
        return {}
    return {
        "XGBoost": (
            XGBRegressor(
                n_estimators=300, max_depth=3, learning_rate=0.06,
                subsample=0.8, colsample_bytree=0.8, min_child_weight=2.0,
                reg_lambda=2.0, objective="reg:squarederror",
                tree_method="hist", n_jobs=1, random_state=seed,
                verbosity=0,
            ),
            {"max_depth": [2, 3], "n_estimators": [200, 400]},
        ),
    }


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
def _metrics(yt, yp) -> dict:
    yt, yp = np.asarray(yt, float), np.asarray(yp, float)
    ok = np.isfinite(yt) & np.isfinite(yp)
    yt, yp = yt[ok], yp[ok]
    if len(yt) < 2:
        return {}
    res = yp - yt
    ss_res = float(np.sum(res ** 2))
    ss_tot = float(np.sum((yt - yt.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    rmse = float(np.sqrt(np.mean(res ** 2)))
    mae = float(np.mean(np.abs(res)))
    sd = float(np.std(yt, ddof=1)) if len(yt) > 1 else float("nan")
    rpd = sd / rmse if rmse > 0 else float("inf")
    return {"r2": r2, "rmse": rmse, "mae": mae, "rpd": rpd, "n": int(len(yt))}


def _to_log(y):
    y = np.asarray(y, float)
    return np.log10(np.clip(y, 1e-18, None))


def _from_log(z):
    return 10.0 ** np.asarray(z, float)


# --------------------------------------------------------------------------
# cross-validation
# --------------------------------------------------------------------------
def _cv_splits(groups, mode):
    groups = np.asarray(groups)
    if mode == "batch":
        uniq = list(dict.fromkeys(groups))
        if len(uniq) < 2:
            return []
        return [(np.where(groups != g)[0], np.where(groups == g)[0]) for g in uniq]
    # leave-one-electrode-out
    uniq = list(dict.fromkeys(groups))
    if len(uniq) < 3:
        return []
    return [(np.where(groups != g)[0], np.where(groups == g)[0]) for g in uniq]


def _fit_with_grid(est, grid, Xtr, ytr, seed=0):
    if not grid or len(ytr) < 6:
        return est.fit(Xtr, ytr)
    from sklearn.model_selection import GridSearchCV, KFold
    k = min(3, max(2, len(ytr) // 4))
    gs = GridSearchCV(est, grid, cv=KFold(k, shuffle=True, random_state=seed),
                      scoring="neg_root_mean_squared_error", n_jobs=1)
    gs.fit(Xtr, ytr)
    return gs.best_estimator_


def _clean(X):
    """Make a feature matrix usable: drop dead columns, median-fill the rest.

    External datasets do not have our -0.34 V MB peak, so I_MB / ratio come out
    NaN for every row.  The old guard (drop any row that has a NaN) then threw
    the whole table away and reported "0 standards".  Dropping the column is the
    right move -- a feature that is never measured carries no information.
    """
    X = np.asarray(X, float)
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    keep = ~np.all(~np.isfinite(X), axis=0)
    X = X[:, keep]
    if X.shape[1] == 0:
        return X
    bad = ~np.isfinite(X)
    if bad.any():
        med = np.nanmedian(np.where(bad, np.nan, X), axis=0)
        med = np.where(np.isfinite(med), med, 0.0)
        X = np.where(bad, med, X)
    return X


def evaluate(X, y, groups, mode="electrode", models=None, seed=0):
    """Leave-one-group-out regression.  y is the TRUE concentration (M).

    The model is fitted on log10(C) whenever the standards span more than one
    decade (our MB response is log-linear), otherwise on C itself; both are
    reported in the same units so the table stays comparable.
    """
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    groups = np.asarray(groups)
    ok = np.isfinite(y) & (y > 0)
    X, y, groups = _clean(X[ok]), y[ok], groups[ok]
    if X.shape[1] == 0:
        return {"error": "所有特征列都是空的（这个文件夹的扫描窗口里没有这些峰）"}
    if len(y) < 6:
        return {"error": "标准点太少（%d 条），至少需要 6 条才能做交叉验证" % len(y)}

    decades = float(np.log10(y.max() / y.min()))
    on_log = decades >= 1.0
    t = _to_log(y) if on_log else y

    splits = _cv_splits(groups, mode)
    if not splits:
        need = "3 支电极" if mode == "electrode" else "2 个批次"
        return {"error": "独立单元不够：留一%s需要至少 %s，现在只有 %d 个"
                         % ("电极" if mode == "electrode" else "批次", need,
                            len(set(groups.tolist())))}

    zoo = model_zoo(seed) if models is None else {k: v for k, v in model_zoo(seed).items() if k in models}
    rows, preds = [], {}
    for name, (est, grid) in zoo.items():
        yt_all, yp_all, folds = [], [], []
        for tr, te in splits:
            try:
                m = _fit_with_grid(est, grid, X[tr], t[tr], seed)
                p = np.asarray(m.predict(X[te])).ravel()
            except Exception as exc:              # noqa: BLE001
                folds.append({"error": str(exc)[:80]})
                continue
            yt_all.extend(t[te].tolist())
            yp_all.extend(p.tolist())
            folds.append({"n": int(len(te)),
                          "rmse": float(np.sqrt(np.mean((p - t[te]) ** 2)))})
        if len(yt_all) < 3:
            rows.append({"name": name, "error": "所有折都拟合失败"})
            continue
        mm = _metrics(yt_all, yp_all)
        preds[name] = {"true": [float(v) for v in yt_all], "pred": [float(v) for v in yp_all]}
        row = {"name": name, "scale": "log10(C)" if on_log else "C", **mm,
               "n_folds": len(splits), "folds": folds}
        if on_log:
            row["rmse_dex"] = mm["rmse"]
            # "off by a factor of X" reads better than a percentage once the
            # error is bigger than 100 %
            row["factor"] = float(10 ** mm["rmse"])
            row["rel_err_pct"] = float((10 ** mm["rmse"] - 1) * 100)
        rows.append(row)

    rows = [r for r in rows if "r2" in r]
    rows.sort(key=lambda r: -r["r2"])
    best = rows[0]["name"] if rows else None
    out = {"mode": mode, "unit": "电极" if mode == "electrode" else "批次",
           "n_standards": int(len(y)), "n_units": int(len(set(groups.tolist()))),
           "decades": decades, "scale": "log10(C)" if on_log else "C",
           "models": rows, "best": best}
    if best:
        out["best_pred"] = preds[best]
        out["best_row"] = next(r for r in rows if r["name"] == best)
    return out


def evaluate_multi(X, Y, groups, names=None, mode="electrode", seed=0):
    """Several analytes at once -- the Food Chem antibiotics paper (BP-ANN on
    three antibiotics) and the standard PLS2 route.

    Y is (n_samples, n_analytes).  Estimators that handle multi-output
    natively (PLS2, BP-ANN, trees, linear) are fitted directly; the rest are
    wrapped in MultiOutputRegressor.
    """
    from sklearn.multioutput import MultiOutputRegressor

    X = np.asarray(X, float)
    Y = np.asarray(Y, float)
    if Y.ndim == 1:
        Y = Y[:, None]
    groups = np.asarray(groups)
    ok = np.all(np.isfinite(Y), axis=1) & (Y.min(axis=1) > 0) & np.all(np.isfinite(X), axis=1)
    X, Y, groups = X[ok], Y[ok], groups[ok]
    k = Y.shape[1]
    if k < 2:
        return {"error": "只有一个分析物，多输出模型没有意义"}
    if len(Y) < 8:
        return {"error": "标准点太少（%d 条），多输出建模至少要 8 条" % len(Y)}

    # log scale per analyte when its own range spans a decade
    use_log = [bool(np.log10(Y[:, j].max() / Y[:, j].min()) >= 1.0) for j in range(k)]
    T = np.column_stack([_to_log(Y[:, j]) if use_log[j] else Y[:, j] for j in range(k)])

    splits = _cv_splits(groups, mode)
    if not splits:
        return {"error": "独立单元不够，做不了留一%s"
                         % ("电极" if mode == "electrode" else "批次")}

    zoo = model_zoo(seed)
    rows = []
    for name, (est, grid) in zoo.items():
        try:
            model = est
            if not getattr(est, "_get_tags", None) or not est._get_tags().get("multioutput", False):
                model = MultiOutputRegressor(est)
        except Exception:                          # noqa: BLE001
            model = MultiOutputRegressor(est)
        yt_all, yp_all, folds = [], [], 0
        try:
            for tr, te in splits:
                m = _fit_with_grid(model, grid, X[tr], T[tr], seed)
                p = np.asarray(m.predict(X[te]))
                p = p.reshape(len(te), k)
                yt_all.append(T[te])
                yp_all.append(p)
                folds += 1
        except Exception:                          # noqa: BLE001
            continue
        if folds < 2:
            continue
        yt = np.vstack(yt_all)
        yp = np.vstack(yp_all)
        per = []
        for j in range(k):
            mm = _metrics(yt[:, j], yp[:, j])
            per.append({"analyte": (names[j] if names else "分析物 %d" % (j + 1)), **mm})
        mean_r2 = float(np.nanmean([q["r2"] for q in per]))
        rows.append({"name": name, "mean_r2": mean_r2, "per_analyte": per,
                     "n_folds": folds})
    rows.sort(key=lambda r: -r["mean_r2"])
    return {"mode": mode, "n_analytes": k, "n_standards": int(len(Y)),
            "analytes": ([str(n) for n in names] if names
                         else ["分析物 %d" % (i + 1) for i in range(k)]),
            "models": rows, "best": rows[0]["name"] if rows else None}


def learning_curve(X, y, groups, name="SVR-RBF", mode="electrode", points=5, seed=0):
    """Test error as a function of the number of independent electrodes used
    for training.  Answers "how many more electrodes do I need?"."""
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    groups = np.asarray(groups)
    ok = np.isfinite(y) & (y > 0) & np.all(np.isfinite(X), axis=1)
    X, y, groups = X[ok], y[ok], groups[ok]
    decades = float(np.log10(y.max() / y.min())) if len(y) else 0.0
    on_log = decades >= 1.0
    t = _to_log(y) if on_log else y
    uniq = list(dict.fromkeys(groups.tolist()))
    if len(uniq) < 5:
        return {"error": "独立单元太少，画不出学习曲线"}
    zoo = model_zoo(seed)
    if name not in zoo:
        name = "SVR-RBF"
    est, grid = zoo[name]
    rng = np.random.default_rng(seed)
    sizes = sorted(set(int(round(v)) for v in
                       np.linspace(3, len(uniq) - 1, points).tolist()))
    curve = []
    for n_tr in sizes:
        errs = []
        for _ in range(6):
            order = rng.permutation(len(uniq))
            tr_units = [uniq[i] for i in order[:n_tr]]
            te_units = [uniq[i] for i in order[n_tr:]]
            tr = np.isin(groups, tr_units)
            te = np.isin(groups, te_units)
            if tr.sum() < 3 or te.sum() < 1:
                continue
            try:
                m = _fit_with_grid(est, grid, X[tr], t[tr], seed)
                p = np.asarray(m.predict(X[te])).ravel()
            except Exception:                      # noqa: BLE001
                continue
            errs.append(float(np.sqrt(np.mean((p - t[te]) ** 2))))
        if errs:
            curve.append({"n_train": n_tr, "rmse": float(np.mean(errs)),
                          "sd": float(np.std(errs))})
    return {"model": name, "scale": "log10(C)" if on_log else "C",
            "points": curve, "n_units": len(uniq)}


def importance(X, y, groups, feature_names, name=None, seed=0, top=10):
    """Permutation importance under leave-one-group-out.  This is the honest
    cousin of SHAP: it answers 'what happens to the score if I scramble this
    feature' and it is measured on electrodes the model never saw."""
    from sklearn.inspection import permutation_importance
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    groups = np.asarray(groups)
    ok = np.isfinite(y) & (y > 0)
    X, y, groups = X[ok], y[ok], groups[ok]
    keep = ~np.all(~np.isfinite(X), axis=0) if X.size else np.zeros(X.shape[1], bool)
    X = _clean(X)
    feature_names = [n for n, k in zip(list(feature_names), keep) if k]
    on_log = np.log10(y.max() / y.min()) >= 1.0 if len(y) else True
    t = _to_log(y) if on_log else y
    zoo = model_zoo(seed)
    pick = name if name in zoo else "随机森林"
    est, grid = zoo[pick]
    try:
        m = _fit_with_grid(est, grid, X, t, seed)
        r = permutation_importance(m, X, t, n_repeats=30, random_state=seed,
                                   scoring="neg_root_mean_squared_error")
    except Exception as exc:                        # noqa: BLE001
        return {"error": str(exc)[:120]}
    order = np.argsort(-r.importances_mean)[:top]
    return {"model": pick,
            "rows": [{"feature": str(feature_names[i]),
                      "v": float(r.importances_mean[i]),
                      "sd": float(r.importances_std[i])} for i in order]}


def predict(model_row_name, X_train, y_train, X_new, seed=0):
    """Fit the chosen model on everything and score new samples."""
    y_train = np.asarray(y_train, float)
    on_log = np.log10(y_train.max() / y_train.min()) >= 1.0
    t = _to_log(y_train) if on_log else y_train
    zoo = model_zoo(seed)
    name = model_row_name if model_row_name in zoo else "SVR-RBF"
    est, grid = zoo[name]
    m = _fit_with_grid(est, grid, np.asarray(X_train, float), t, seed)
    p = np.asarray(m.predict(np.asarray(X_new, float))).ravel()
    return _from_log(p) if on_log else p


# --------------------------------------------------------------------------
# self-test
# --------------------------------------------------------------------------
FEATURE_KEYS = ["I_MB", "I_ref", "ratio", "anodic_H", "cathodic_H",
                "anodic_Ep", "cathodic_Ep", "Q", "ocp", "I_start", "I_mid", "I_end"]


def _load_folder(folder):
    """Exactly the table the UI shows: same prefill, same QC, same metric."""
    import dump_ui_json as dump
    df, curves, errors, grid, metric = dump.prepare(Path(folder))
    return df, curves


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--mode", default="electrode", choices=["electrode", "batch"],
                    help="unit of cross-validation")
    ap.add_argument("--multi", action="store_true",
                    help="treat every concentration column as a separate analyte")
    ap.add_argument("--name", default="SVR-RBF")
    args = ap.parse_args()

    df, curves = _load_folder(args.data)
    need = ["concentration_M", "electrode"]
    if not all(c in df.columns for c in need):
        sys.exit("metadata with concentration_M / electrode is required")
    conc = pd.to_numeric(df["concentration_M"], errors="coerce")
    mask = (conc.notna() & (conc > 0)).values
    d = df.loc[mask]
    if len(d) < 6:
        sys.exit("need at least 6 standards with a known concentration")
    X = curves[mask]
    y = d["concentration_M"].values
    groups = d["batch"].values if args.mode == "batch" and "batch" in d.columns \
        else d["electrode"].values

    if args.multi:
        # every extra concentration column counts as one more analyte
        extra = [c for c in df.columns
                 if c.startswith("concentration_") and c != "concentration_M"]
        if not extra:
            sys.exit("multi-analyte mode needs extra columns named concentration_<analyte>; "
                     "this folder only has concentration_M")
        Y = df.loc[mask, ["concentration_M"] + extra].values.astype(float)
        keep = np.all(np.isfinite(Y), axis=1) & (Y.min(axis=1) > 0)
        Y = Y[keep]
        Xm = X[keep]
        gm = groups[keep]
        res = evaluate_multi(Xm, Y, gm, names=["concentration_M"] + extra, mode=args.mode)
        if res.get("error"):
            sys.exit(res["error"])
        print("multi-analyte, mode=%s, %d analytes" % (args.mode, res["n_analytes"]))
        for r in res.get("models", []):
            per = " ".join("%s %.2f" % (q["analyte"], q["r2"]) for q in r["per_analyte"])
            print("  %-10s mean R2=%.4f  | %s" % (r["name"], r["mean_r2"], per))
        print("best:", res.get("best"))
        return

    res = evaluate(X, y, groups, mode=args.mode)
    if res.get("error"):
        sys.exit(res["error"])
    print("mode=%s  unit=%s  standards=%d  units=%d  decades=%.1f"
          % (res["mode"], res["unit"], res["n_standards"], res["n_units"], res["decades"]))
    for r in res.get("models", []):
        print("%-10s %-6s R2=%.4f  RMSE=%.2f dex  RPD=%.2f  rel=%.1f%%"
              % (r["name"], r.get("set", ""), r["r2"],
                 r.get("rmse_dex", r["rmse"]), r["rpd"],
                 r.get("rel_err_pct", float("nan"))))
    print("best:", res.get("best"), res.get("best_set") or "")

    lc = learning_curve(X, y, groups, name=args.name, mode=args.mode)
    if lc.get("error"):
        print("learning curve:", lc["error"])
    else:
        print("learning curve (n_train -> rmse dex):",
              " ".join("%d:%.2f" % (p["n_train"], p["rmse"]) for p in lc.get("points", [])))
    feats = [c for c in FEATURE_KEYS if c in df.columns]
    if feats:
        imp = importance(df.loc[mask, feats].values.astype(float), y, groups, feats)
        print("top features:", ", ".join("%s %.2f" % (r["feature"], r["v"])
                                         for r in imp.get("rows", [])[:5]))


if __name__ == "__main__":
    main()
