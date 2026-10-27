#!/usr/bin/env python3
"""
analysis_core.py -- every number the web UI shows, with no Streamlit in it.

Keeping the maths out of the UI means it can be unit-tested headlessly
(scripts/test_core.py) and reused from a notebook or a batch script.

Conventions
-----------
* curves are baseline-corrected peak current in microamps, positive = peak
  (the raw trace is negative-going; Icorr = (envelope - I) * 1e6)
* the MB peak lives in -0.42..-0.28 V, the MIL-101(Fe) internal reference
  peak in +0.25..+0.50 V
* ratio = I_MB / I_ref is the assay response: it cancels how much electrode
  area a given strip happened to have (I_ref varied 0.45..3.32 uA, 7x)
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy import stats

from dpv_pipeline import (parse_cor_bytes, baseline_envelope, resample,
                          extract_features, common_grid, select_window,
                          GRID, GROUP_ORDER, GROUP_COLOR, PEAK_TECHNIQUES)

MB_WIN = (-0.42, -0.28)
REF_WIN = (0.25, 0.50)
# same windows extract_features() uses for the anodic / cathodic peak heights
ANODIC_WIN = (0.15, 0.60)
CATHODIC_WIN = (-0.65, -0.15)

# how to name a technique in a message a user reads
TECHNIQUE_CN = {
    "DPV": "差分脉冲伏安 (DPV)",
    "DPV-stripping": "差分脉冲溶出伏安 (DPV-stripping)",
    "SWV": "方波伏安 (SWV)",
    "SWV-stripping": "方波溶出伏安 (SWV-stripping)",
    "CV": "循环伏安 (CV)",
    "SCV": "循环伏安 (SCV)",
    "i-t": "计时电流 (i-t)",
    "plain": "无表头的两列数据",
    "unknown": "未知扫描类型",
}

# a header-less dump is still a pulse trace; fold it in with the DPV family
TECH_ALIAS = {"plain": "DPV"}


def tech_key(technique) -> str:
    t = technique or "unknown"
    return TECH_ALIAS.get(t, t)


def _pick_technique(recs, technique: str):
    """Which pulse technique this batch is analysed as.

    A folder is allowed to mix techniques (20260926 holds 14 DPV + 17 SWV
    stripping + 6 SWV; 20260625 holds 16 DPV + 6 DPV stripping + 2 CV).  Peak
    currents from different techniques are not on the same scale, so one batch
    is analysed as ONE technique and the rest are listed with a reason.

    "auto" takes the most common pulse technique, but keeps plain DPV unless
    another technique is at least twice as common -- a folder that is mostly
    DPV with a stripping side-test is still a DPV folder.
    """
    counts = {}
    for _, _, rec in recs:
        counts[tech_key(rec.get("technique"))] = counts.get(tech_key(rec.get("technique")), 0) + 1
    peak = {k: v for k, v in counts.items() if k in PEAK_TECHNIQUES}
    if technique == "all":
        return "all", counts
    if technique and technique not in ("auto", "", None):
        want = tech_key(technique)
        return (want if want in peak else ""), counts
    if not peak:
        return "", counts
    order = [t for t in ("DPV", "SWV", "DPV-stripping", "SWV-stripping") if t in peak]
    top = max(peak, key=lambda k: peak[k])
    for t in order:
        if peak[t] >= 0.5 * peak[top]:
            return t, counts
    return top, counts


def technique_skip_reason(tech: str, used: str) -> str:
    cn = TECHNIQUE_CN.get(tech, tech)
    if tech in PEAK_TECHNIQUES:
        return ("本批按「%s」分析，这一条是「%s」—— 不同扫描方式的峰电流不在一个量纲上，"
                "混进来会把组间差异变成扫描方式的差异。想单独看它，把「扫描类型」改成「%s」。"
                % (TECHNIQUE_CN.get(used, used), cn, cn))
    return ("这是「%s」扫描，没有脉冲峰可读，所以不参与 DPV 分析。"
            "（CV 的正扫/回扫最高点不是峰，是换向造成的假象。）" % cn)

# feature columns that are worth showing a user (all in uA unless noted)
FEATURES = ["I_MB", "I_ref", "ratio", "anodic_H", "cathodic_H",
            "anodic_Ep", "cathodic_Ep", "Q", "ocp"]

FEATURE_LABEL = {
    "I_MB": "MB peak current (uA)",
    "I_ref": "internal reference peak (uA)",
    "ratio": "I_MB / I_ref",
    "anodic_H": "anodic peak height (uA)",
    "cathodic_H": "cathodic peak height (uA)",
    "anodic_Ep": "anodic peak potential (V)",
    "cathodic_Ep": "cathodic peak potential (V)",
    "Q": "total charge proxy (uA*V)",
    "ocp": "open circuit potential (V)",
}


# ---------------------------------------------------------------------------
# single trace
# ---------------------------------------------------------------------------
def window_cover(grid, win, min_frac=0.7):
    """Fraction of [win] that the shared potential axis actually covers.

    Folders from different dates were scanned over different windows (0.3..-0.3,
    0.6..-0.6, 0.19..-0.20 ...).  Reading a peak window that is half outside the
    axis returns the window edge, not a peak, so every caller must ask first.
    """
    lo, hi = min(win), max(win)
    span = hi - lo
    if span <= 0:
        return 0.0
    g_lo, g_hi = float(np.nanmin(grid)), float(np.nanmax(grid))
    ov = min(hi, g_hi) - max(lo, g_lo)
    return float(max(0.0, ov) / span)


def peak_in(grid, y, win):
    m = (grid >= win[0]) & (grid <= win[1])
    if not m.any():
        return float("nan"), float("nan")
    x, v = grid[m], y[m]
    i = int(np.argmax(v))
    return float(v[i]), float(x[i])


def analyse_trace(fname: str, raw: bytes, order: int = 4, grid=None):
    """bytes of one .cor -> (row dict, corrected curve, raw curve)."""
    rec = parse_cor_bytes(fname, raw)
    if len(rec["E"]) < 5:
        raise ValueError("no data rows found in this .cor file")
    grid = GRID if grid is None else np.asarray(grid, dtype=float)
    I = resample(rec["E"], rec["I"], grid)
    if not np.all(np.isfinite(I)):
        raise ValueError("这条曲线的电位范围盖不住本批共用的电位窗口")
    base = baseline_envelope(grid, I, order=order)
    y = (base - I) * 1e6

    # 0.9, not "any overlap": a window that is 20% outside the axis returns the
    # window edge as the "peak" (20260830 has +0.45..-0.27 V, so the reference
    # window is half cut and every trace looked like a dead electrode)
    mb_ok = window_cover(grid, MB_WIN) >= 0.9
    ref_ok = window_cover(grid, REF_WIN) >= 0.9
    nan = float("nan")
    i_mb, ep_mb = peak_in(grid, y, MB_WIN) if mb_ok else (nan, nan)
    i_ref, ep_ref = peak_in(grid, y, REF_WIN) if ref_ok else (nan, nan)

    row = {"file": fname,
           "I_MB": i_mb, "MB_Ep": ep_mb,
           "I_ref": i_ref, "ref_Ep": ep_ref,
           "mb_win_ok": bool(mb_ok), "ref_win_ok": bool(ref_ok),
           "anod_win_ok": window_cover(grid, ANODIC_WIN) >= 0.9,
           "cath_win_ok": window_cover(grid, CATHODIC_WIN) >= 0.9,
           "ratio": (i_mb / i_ref) if (np.isfinite(i_ref) and i_ref > 0) else nan}
    row.update(extract_features(grid, y, I, rec["ocp"], rec["parms"]))
    row["date"] = rec["date"]
    row["time"] = rec["time"]
    row["n_points"] = int(len(rec["E"]))
    row["technique"] = rec.get("technique", "unknown")
    row["incE"] = float(rec["parms"].get("IncE", "nan") or "nan")
    row["amplitude"] = float(rec["parms"].get("Amplitude", "nan") or "nan")
    return row, y, I


def build_table(items, order: int = 4, technique: str = "auto"):
    """items = [(filename, bytes), ...] -> (df, curves, errors, grid).

    The shared potential axis is derived from the data (select_window +
    common_grid), never hard-coded: folders from different dates were scanned
    over different windows, and interpolating a 0.6/-0.6 trace onto the old
    fixed 0.8/-0.78 axis silently flattened both ends of the curve.
    """
    recs, errors = [], []
    for fname, raw in items:
        try:
            rec = parse_cor_bytes(fname, raw)
            if len(rec["E"]) < 5:
                raise ValueError("这个 .cor 文件里没有数据行（表头写完了但一行数据都没有），"
                                 "多半是采集时中途停掉了，重新导出一遍即可。")
            recs.append((fname, raw, rec))
        except Exception as exc:                      # one bad file must not kill the batch
            errors.append({"file": fname, "error": str(exc)})

    if not recs:
        empty = pd.DataFrame()
        empty.attrs["technique"] = ""
        empty.attrs["technique_counts"] = {}
        return empty, np.empty((0, len(GRID))), errors, GRID

    # A folder can mix techniques -- a CV sitting next to the DPVs, or DPV
    # stripping next to plain DPV.  A CV sweeps out and back, so it has no pulse
    # peak (the highest point of -0.42..-0.28 V is a turn-around artefact, not
    # methylene blue).  Stripping scans DO have a peak, but their currents are
    # not on the same scale as plain DPV.  One batch = one technique; everything
    # else is listed with a reason the user can act on.
    used, counts = _pick_technique(recs, technique)
    if used:
        keep_ids = {id(c) for _, _, c in recs if tech_key(c.get("technique")) == used}
        dropped = [(f, c) for f, _, c in recs if id(c) not in keep_ids]
        if dropped:
            for fname, rec in dropped:
                errors.append({"file": fname,
                               "error": technique_skip_reason(
                                   tech_key(rec.get("technique")), used)})
            recs = [(f, r, c) for f, r, c in recs if id(c) in keep_ids]
    elif recs:
        # Nothing pulse-shaped here (a CV-only folder).  Keep the traces out of
        # the table: a CV has no pulse peak, and letting it through would make
        # the paper table and the group statistics read the turn-around point
        # as a signal.
        errors.append({"file": "*", "error":
                       "这个文件夹里没有可分析的脉冲伏安数据（DPV / SWV），只有其它扫描类型。"})
        recs = []

    lo, hi, kept = select_window([r for _, _, r in recs])
    kept_ids = {id(r) for r in kept}
    # never extrapolate: shrink the chosen window to what the kept traces cover
    los, his = [], []
    for r in kept:
        E = np.asarray(r["E"], dtype=float)
        E = E[np.isfinite(E)]
        if E.size >= 2:
            los.append(float(E.min()))
            his.append(float(E.max()))
    if los:
        lo, hi = max(lo, max(los)), min(hi, min(his))
        if hi <= lo:
            lo, hi = None, None
    grid = common_grid(kept, window=(lo, hi) if lo is not None else None)

    rows, curves = [], []
    for fname, raw, rec in recs:
        if id(rec) not in kept_ids:
            E = np.asarray(rec["E"], dtype=float)
            errors.append({"file": fname,
                           "error": "scanned over %.2f..%.2f V, which does not cover "
                                    "the %.2f..%.2f V window shared by the rest of "
                                    "this batch"
                                    % (np.nanmin(E), np.nanmax(E), lo, hi)})
            continue
        try:
            row, y, _ = analyse_trace(fname, raw, order=order, grid=grid)
        except Exception as exc:
            errors.append({"file": fname, "error": str(exc)})
            continue
        rows.append(row)
        curves.append(y)
    df = pd.DataFrame(rows)
    mat = np.asarray(curves) if curves else np.empty((0, len(grid)))
    df.attrs["technique"] = used
    df.attrs["technique_counts"] = counts
    return df, mat, errors, grid


# ---------------------------------------------------------------------------
# quality control
# ---------------------------------------------------------------------------
def add_qc(df, ref_min: float = 1.0, ref_frac: float = None):
    """Flag traces whose internal reference peak is too small to trust.

    A tiny I_ref means the electrode surface was poorly prepared, not that the
    sample had little analyte: the ratio then blows up for reasons that have
    nothing to do with streptomycin.  In the 2026-10-10 set dropping 4 such
    traces took one group CV from 85% to 12%.

    ref_frac, when given, replaces the fixed ref_min with a fraction of THIS
    batch's median I_ref.  A fixed microamp threshold does not travel: the
    reference peak itself drifts 2-7x between batches, so the same 1.0 uA cut
    rejects nothing in one folder and every single trace in the next.
    """
    df = df.copy()
    ok = (df["ref_win_ok"].astype(bool) if "ref_win_ok" in df.columns
          else pd.Series(True, index=df.index))
    iref = pd.to_numeric(df["I_ref"], errors="coerce")
    thr = float(ref_min)
    med = float("nan")
    if ref_frac is not None and float(ref_frac) > 0 and bool(ok.any()):
        med = float(np.nanmedian(iref[ok].values))
        if np.isfinite(med) and med > 0:
            thr = float(ref_frac) * med
    small = iref.fillna(0) < thr
    # no reference peak in range -> QC has nothing to judge, so do not reject
    df["qc_pass"] = (~small) | (~ok)
    df["qc_reason"] = ["" if (not s) or (not o)
                       else "internal reference peak below %.2f uA" % thr
                       for s, o in zip(small.values, ok.values)]
    df.attrs["qc_skipped"] = not bool(ok.any())
    df.attrs["ref_threshold"] = thr
    df.attrs["ref_median"] = med
    return df


METRIC_CN = {"ratio": "I_MB / I_ref 比值", "I_MB": "MB 峰电流",
             "cathodic_H": "阴极峰高", "anodic_H": "阳极峰高",
             "Q": "总电荷 Q", "ocp": "开路电位"}


# a metric is only usable when its peak window is actually inside the scan range:
# extract_features() happily returns a number for a window that is 90% outside the
# axis, and that number is the window edge, not a peak
_METRIC_NEEDS = {"ratio": "mb_win_ok", "I_MB": "mb_win_ok",
                 "cathodic_H": "cath_win_ok", "anodic_H": "anod_win_ok"}


def metric_availability(df, min_frac=0.5):
    """Which response metrics actually carry data in this batch, best first."""
    order = ["ratio", "I_MB", "cathodic_H", "anodic_H", "Q"]
    n = max(1, len(df))
    out = []
    for m in order:
        if m not in df.columns:
            continue
        if pd.to_numeric(df[m], errors="coerce").notna().sum() < min_frac * n:
            continue
        flag = _METRIC_NEEDS.get(m)
        if flag and flag in df.columns and not bool(df[flag].any()):
            continue
        out.append(m)
    return out or ["Q"]


def repeatability(df, group_col="group", electrode_col="electrode", metric="ratio"):
    """Within-electrode CV, i.e. how well one strip repeats itself."""
    rows = []
    for (g, e), sub in df.groupby([group_col, electrode_col]):
        v = sub[metric].dropna().values
        if len(v) < 2:
            continue
        rows.append({"group": g, "electrode": e, "n": len(v),
                     "mean": float(v.mean()), "sd": float(v.std(ddof=1)),
                     "cv_pct": float(v.std(ddof=1) / v.mean() * 100) if v.mean() else np.nan})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# group statistics
# ---------------------------------------------------------------------------
def group_stats(df, group_col="group", feats=None, min_n: int = 2):
    feats = [f for f in (feats or FEATURES) if f in df.columns]
    groups = [g for g in GROUP_ORDER if g in set(df[group_col])]
    groups += [g for g in df[group_col].unique() if g not in groups]
    out = []
    for f in feats:
        samples = [df.loc[df[group_col] == g, f].dropna().values for g in groups]
        samples = [s for s in samples if len(s) >= min_n]
        if len(samples) < 2:
            continue
        # constant features make f_oneway / kruskal divide by zero; the result is
        # NaN either way, so keep the table clean instead of spraying warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            F, p = stats.f_oneway(*samples)
        grand = np.concatenate(samples)
        ss_tot = float(((grand - grand.mean()) ** 2).sum())
        ss_b = float(sum(len(s) * (s.mean() - grand.mean()) ** 2 for s in samples))
        row = {"feature": f, "F": float(F), "p": float(p),
               "eta2": ss_b / ss_tot if ss_tot > 0 else np.nan, "n": int(len(grand))}
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                H, pk = stats.kruskal(*samples)
            row["kruskal_H"], row["kruskal_p"] = float(H), float(pk)
        except Exception:
            pass
        out.append(row)
    return pd.DataFrame(out)


def tukey_table(df, group_col="group", feat="ratio"):
    groups = [g for g in df[group_col].unique()
              if df.loc[df[group_col] == g, feat].notna().sum() >= 2]
    groups = sorted(groups, key=lambda g: (GROUP_ORDER.index(g) if g in GROUP_ORDER else 99))
    samples = [df.loc[df[group_col] == g, feat].dropna().values for g in groups]
    if len(samples) < 2:
        return pd.DataFrame()
    res = stats.tukey_hsd(*samples)
    ci = res.confidence_interval()
    rows = []
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            rows.append({"A": groups[i], "B": groups[j],
                         "diff": float(samples[i].mean() - samples[j].mean()),
                         "p": float(res.pvalue[i, j]),
                         "lo": float(ci.low[i, j]), "hi": float(ci.high[i, j])})
    return pd.DataFrame(rows)


def group_summary(df, group_col="group", metric="ratio"):
    rows = []
    for g in df[group_col].unique():
        v = df.loc[df[group_col] == g, metric].dropna().values
        if len(v) == 0:
            continue
        rows.append({"group": g, "n": int(len(v)), "mean": float(v.mean()),
                     "sd": float(v.std(ddof=1)) if len(v) > 1 else np.nan,
                     "cv_pct": float(v.std(ddof=1) / v.mean() * 100) if len(v) > 1 and v.mean() else np.nan})
    out = pd.DataFrame(rows)
    if len(out) and group_col == "group":
        out["_o"] = out["group"].map(lambda g: GROUP_ORDER.index(g) if g in GROUP_ORDER else 99)
        out = out.sort_values("_o").drop(columns="_o").reset_index(drop=True)
    return out


# ---------------------------------------------------------------------------
# PCA / classification with leave-one-electrode-out
# ---------------------------------------------------------------------------
def pca_scores(curves, n_components: int = 3):
    from sklearn.decomposition import PCA
    X = np.asarray(curves, dtype=float)
    if X.shape[0] < 3:
        return np.zeros((X.shape[0], 1)), np.array([1.0])
    Xc = X - X.mean(axis=0)
    k = int(min(n_components, X.shape[0] - 1, X.shape[1]))
    p = PCA(n_components=k).fit(Xc)
    return p.transform(Xc), p.explained_variance_ratio_


def _make_model(kind: str):
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if kind == "lda":
        return make_pipeline(StandardScaler(), LinearDiscriminantAnalysis())
    return RandomForestClassifier(n_estimators=300, random_state=0, class_weight="balanced")


def loeo_cv(X, y, groups, kind: str = "lda"):
    """Leave-one-ELECTRODE-out.  Never leave-one-scan-out: scans of the same
    strip are not independent and the score comes out flattering."""
    from sklearn.model_selection import LeaveOneGroupOut
    from sklearn.metrics import accuracy_score, confusion_matrix
    X, y, groups = np.asarray(X, float), np.asarray(y), np.asarray(groups)
    n_cls = len(np.unique(y))
    if len(y) <= n_cls:
        # LDA refuses to fit ("The number of samples must be more than the
        # number of classes") and the whole page died with a traceback.
        return {"error": "只有 %d 条曲线、%d 个分组 —— 曲线数不比类别多，分类器无从训练。"
                         "每个分组至少要 2 条曲线，最好 2 支以上独立电极。" % (len(y), n_cls)}
    pred = np.array([None] * len(y), dtype=object)
    logo = LeaveOneGroupOut()
    n_folds = 0
    for tr, te in logo.split(X, y, groups):
        if len(np.unique(y[tr])) < 2:
            continue
        try:
            m = _make_model(kind).fit(X[tr], y[tr])
        except Exception:              # a fold with classes > samples cannot be fitted
            continue
        pred[te] = m.predict(X[te])
        n_folds += 1
    ok = np.array([p is not None for p in pred])
    if ok.sum() < 2:
        return {"error": "not enough independent electrodes to cross-validate"}
    # cast the truth to str as well: a numeric y (e.g. concentration classes)
    # mixed with str predictions made sorted(set(yt) | set(yp)) raise
    # "ufunc 'greater' did not contain a loop with signature ..."
    yt = np.array([str(v) for v in y[ok]])
    yp = np.array([str(p) for p in pred[ok]])
    labels = sorted(set(yt) | set(yp))
    # Balanced accuracy = mean per-class recall.  Raw accuracy is dominated by
    # the biggest class: with 18 of 23 electrodes in one class a model that
    # always answers "standard" scores 78% while learning nothing.
    rec = []
    for lab in sorted(set(yt)):
        m = yt == lab
        if m.sum():
            rec.append(float((yp[m] == lab).mean()))
    bal = float(np.mean(rec)) if rec else float("nan")
    return {"accuracy": float(accuracy_score(yt, yp)),
            "balanced_accuracy": bal,
            "class_support": {str(l): int((yt == l).sum()) for l in sorted(set(yt))},
            "n_folds": int(n_folds), "n_scans": int(ok.sum()),
            "labels": labels,
            "confusion": confusion_matrix(yt, yp, labels=labels).tolist(),
            "y_true": [str(v) for v in yt], "y_pred": [str(v) for v in yp]}


def permutation_test(X, y, groups, kind: str = "rf", n_perm: int = 200, seed: int = 0):
    """Null distribution by shuffling labels BETWEEN electrodes.

    Shuffling single rows would leak: the model could still learn "this
    electrode", so the null would be far too optimistic.
    """
    rng = np.random.default_rng(seed)
    y = np.asarray(y)
    groups = np.asarray(groups)
    obs = loeo_cv(X, y, groups, kind)
    if "error" in obs:
        return obs
    uniq = list(dict.fromkeys(groups))
    lab = np.array([y[groups == g][0] for g in uniq])
    null = []
    for _ in range(n_perm):
        perm = rng.permutation(lab)
        yp = np.array([perm[uniq.index(g)] for g in groups])
        r = loeo_cv(X, yp, groups, kind)
        if "error" not in r:
            null.append(r["balanced_accuracy"])
    null = np.array(null)
    obs_v = obs["balanced_accuracy"]
    p = (1 + int((null >= obs_v).sum())) / (1 + len(null)) if len(null) else float("nan")
    return {"observed": obs_v, "observed_accuracy": obs["accuracy"],
            "null_mean": float(null.mean()) if len(null) else float("nan"),
            "null_p95": float(np.percentile(null, 95)) if len(null) else float("nan"),
            "null_max": float(null.max()) if len(null) else float("nan"),
            "null": [float(v) for v in null],
            "p_value": float(p), "n_perm": int(len(null))}


def feature_importance(X, y, feature_names, kind: str = "rf"):
    from sklearn.ensemble import RandomForestClassifier
    X = np.asarray(X, float)
    m = RandomForestClassifier(n_estimators=400, random_state=0, class_weight="balanced").fit(X, y)
    order = np.argsort(m.feature_importances_)[::-1]
    return [(str(feature_names[i]), float(m.feature_importances_[i])) for i in order]


# ---------------------------------------------------------------------------
# calibration and quantification
# ---------------------------------------------------------------------------
def _fit_line(x, y):
    b, a = np.polyfit(x, y, 1)
    yhat = a + b * x
    n = len(x)
    syx = float(np.sqrt(((y - yhat) ** 2).sum() / max(n - 2, 1)))
    return {"a": float(a), "b": float(b), "n": int(n), "syx": syx,
            "xbar": float(x.mean()), "Sxx": float(((x - x.mean()) ** 2).sum()),
            "r2": float(1 - ((y - yhat) ** 2).sum() / max(((y - y.mean()) ** 2).sum(), 1e-30))}


def fit_calibration(df, metric: str = "ratio", mode: str = "loglinear"):
    """Fit response vs log10(concentration).

    Returns a dict with the fit, the LOD and everything needed to invert a
    measurement into a concentration with a confidence interval.
    """
    d = df[df.get("concentration_M").notna() & (df["concentration_M"] > 0) & df[metric].notna()]
    blanks = df[df.get("concentration_M").notna() & (df["concentration_M"] == 0) & df[metric].notna()]
    levels = np.unique(np.round(d["concentration_M"].values, 20)) if len(d) else np.array([])

    if len(d) == 0:
        return {"error": "no row has a concentration_M value -- fill in the column first"}
    if len(d) < 4:
        return {"error": "need at least 4 standards with a known concentration, have %d" % len(d)}
    if len(levels) < 3:
        return {"error": "need at least 3 different concentrations, have %d (%s). "
                         "Every standard sits at the same level, so no slope can be estimated."
                         % (len(levels), ", ".join("%.2e M" % v for v in levels))}

    x = np.log10(d["concentration_M"].values.astype(float))
    y = d[metric].values.astype(float)

    if mode == "loglinear":
        fit = _fit_line(x, y)
        inv = lambda v, f=fit: (v - f["a"]) / f["b"]
        fit["params"] = {"a": fit["a"], "b": fit["b"]}
    else:
        from scipy.optimize import curve_fit
        f4 = lambda xx, bottom, top, ec50, hill: bottom + (top - bottom) / (1.0 + (10 ** ec50 / 10 ** xx) ** hill)
        p0 = [float(y.min()), float(y.max()), float(np.median(x)), 1.0]
        p, _ = curve_fit(f4, x, y, p0=p0, maxfev=60000,
                         bounds=([-np.inf, -np.inf, x.min() - 3, 0.1],
                                 [np.inf, np.inf, x.max() + 3, 10]))
        fit = {"n": int(len(x)), "r2": float(1 - ((y - f4(x, *p)) ** 2).sum() / max(((y - y.mean()) ** 2).sum(), 1e-30)),
               "syx": float(np.sqrt(((y - f4(x, *p)) ** 2).sum() / max(len(x) - 4, 1))),
               "xbar": float(x.mean()), "Sxx": float(((x - x.mean()) ** 2).sum()),
               "params": dict(zip(["bottom", "top", "log_ec50", "hill"], map(float, p)))}

        def inv(v, p=p):
            bottom, top, ec50, hill = p
            frac = np.clip((v - bottom) / (top - bottom), 1e-6, 1 - 1e-6)
            return ec50 - np.log10(1 / frac - 1) / hill

    fit["mode"] = mode
    fit["metric"] = metric
    fit["levels_M"] = [float(v) for v in levels]
    fit["dynamic_range_M"] = [float(d["concentration_M"].min()), float(d["concentration_M"].max())]

    # direction: does the response go up or down with concentration?
    fit["direction"] = "signal-off" if fit["b"] < 0 else "signal-on"

    # LOD / LOQ from blank replicates, if there are any
    if len(blanks) >= 3:
        bv = blanks[metric].values.astype(float)
        mu, sd = float(bv.mean()), float(bv.std(ddof=1))
        thr = mu + (3 * sd if fit["direction"] == "signal-on" else -3 * sd)
        try:
            lod = float(10 ** inv(thr))
            loq = float(10 ** inv(mu + (10 * sd if fit["direction"] == "signal-on" else -10 * sd)))
            lo, hi = fit["dynamic_range_M"]
            fit["blank"] = {"n": int(len(bv)), "mean": mu, "sd": sd, "threshold": thr}
            # an LOD far below the lowest standard is extrapolation just as much
            # as one above the highest -- both mean the blank is not resolved.
            if not np.isfinite(lod) or lod <= lo / 100.0 or lod > hi * 10:
                fit["LOD_error"] = ("LOD came out at %.2e M, outside the calibrated range "
                                    "(%.1e - %.1e M): the blank is not separated from the "
                                    "lowest standard" % (lod, lo, hi))
            else:
                fit["LOD_M"] = lod
                fit["LOQ_M"] = loq if np.isfinite(loq) and loq <= hi * 10 else None
        except Exception as exc:
            fit["LOD_error"] = str(exc)
    else:
        fit["LOD_error"] = "need at least 3 blank replicates (concentration = 0) to compute an LOD"

    if fit["r2"] < 0.8:
        fit["quality"] = "poor fit (r2 = %.2f): treat the slope and LOD with caution" % fit["r2"]
    return fit


def predict_concentration(fit: dict, y0: float, confidence: float = 0.95):
    """Invert one measured response into a concentration + interval.

    Uses the standard inverse-regression interval; it widens at both ends of
    the calibrated range, which is the honest behaviour.
    """
    if fit.get("error"):
        return {"error": fit["error"]}
    if not np.isfinite(y0):
        return {"error": "this sample has no usable response"}
    a, b = fit["a"], fit["b"]
    if not np.isfinite(b) or abs(b) < 1e-12:
        return {"error": "the calibration slope is zero, cannot invert"}
    x0 = (y0 - a) / b
    n, s = fit["n"], fit["syx"]
    tcrit = float(stats.t.ppf(0.5 + confidence / 2, max(n - 2, 1)))
    h = tcrit * s / abs(b) * np.sqrt(1 + 1 / n + (x0 - fit["xbar"]) ** 2 / max(fit["Sxx"], 1e-30))
    lo_c = fit["dynamic_range_M"][0]
    hi_c = fit["dynamic_range_M"][1]
    return {"x": float(x0), "C": float(10 ** x0),
            "C_lo": float(10 ** (x0 - h)), "C_hi": float(10 ** (x0 + h)),
            "in_range": bool(lo_c / 3 <= 10 ** x0 <= hi_c * 3),
            "below_range": bool(10 ** x0 < lo_c / 3),
            "above_range": bool(10 ** x0 > hi_c * 3)}


def decide(fit: dict, y0: float):
    """Turn a response into the sentence a food-safety person needs."""
    if fit.get("error"):
        return {"verdict": "unknown", "text": "还没有可用的校准曲线，无法定量", "detail": fit["error"]}
    pr = predict_concentration(fit, y0)
    if pr.get("error"):
        return {"verdict": "unknown", "text": "无法定量", "detail": pr["error"]}
    lod = fit.get("LOD_M")
    if lod and pr["C"] < lod:
        return {"verdict": "negative", "text": "未检出",
                "detail": "响应低于检出限 (%.1e M)，判定为阴性" % lod, "prediction": pr}
    if pr["above_range"]:
        return {"verdict": "positive", "text": "检出，且超出定量范围（需稀释复测）",
                "detail": "推算浓度 %.1e M 高于最高标准点" % pr["C"], "prediction": pr}
    if pr["below_range"]:
        return {"verdict": "negative", "text": "未检出（低于最低标准点）",
                "detail": "响应落在校准范围以下", "prediction": pr}
    return {"verdict": "positive", "text": "检出",
            "detail": "浓度 %s（95%% 置信区间 %s – %s）"
                      % (format_conc(pr["C"]), format_conc(pr["C_lo"]),
                         format_conc(pr["C_hi"])),
            "prediction": pr}


def qualitative_rule(df, group_col="group", metric="ratio", k=3.0):
    """Fallback when there is no calibration curve yet.

    Compares a designated negative group against the rest and reports where
    the cut-off sits, so a new sample can at least be called positive/negative.
    """
    if group_col not in df.columns:
        return {"error": "no grouping column"}
    gs = group_summary(df, group_col, metric)
    if len(gs) < 2:
        return {"error": "need at least two groups to set a cut-off"}
    neg = gs.loc[gs["mean"].idxmin()]
    sd = neg["sd"] if np.isfinite(neg["sd"]) else 0.0
    cut = neg["mean"] - k * sd
    return {"negative_group": neg["group"], "negative_mean": float(neg["mean"]),
            "negative_sd": float(sd), "cutoff": float(cut), "k": k, "metric": metric}


def screening_test(df, neg_group, pos_group, metric="ratio", k=3.0,
                   group_col="group", elec_col="electrode"):
    """No calibration needed: can this metric tell the negative control from
    the positive sample at all?

    The unit of replication is the ELECTRODE (mean of its repeated scans), not
    the scan -- otherwise the p-value is pseudo-replication.
    """
    if group_col not in df.columns or elec_col not in df.columns:
        return {"error": "数据表里没有分组列或电极列"}
    if metric not in df.columns:
        return {"error": "这个指标在这批数据里算不出来"}
    d = df[[group_col, elec_col, metric]].copy()
    d[metric] = pd.to_numeric(d[metric], errors="coerce")
    d = d[np.isfinite(d[metric].values.astype(float))]
    a = d[d[group_col] == neg_group]
    b = d[d[group_col] == pos_group]
    if len(a) < 2 or len(b) < 2:
        return {"error": "两组各自至少要 2 条曲线，现在 %d / %d 条" % (len(a), len(b))}
    ea = a.groupby(elec_col)[metric].mean().values.astype(float)
    eb = b.groupby(elec_col)[metric].mean().values.astype(float)
    if len(ea) < 2 or len(eb) < 2:
        return {"error": "两组各自至少要 2 支独立电极，现在 %d / %d 支" % (len(ea), len(eb))}
    ma, mb = float(ea.mean()), float(eb.mean())
    sa = float(ea.std(ddof=1))
    sb = float(eb.std(ddof=1))
    pooled = float(np.sqrt((sa ** 2 + sb ** 2) / 2.0))
    if pooled > 0:
        dval = (mb - ma) / pooled
    else:
        dval = float("nan")
    sign = 1.0 if mb >= ma else -1.0
    cutoff = ma + sign * k * sa
    p = float("nan")
    try:
        from scipy import stats as sst
        p = float(sst.mannwhitneyu(ea, eb, alternative="two-sided").pvalue)
    except Exception:
        pass
    ratio = float(mb / ma) if ma != 0 else float("nan")
    # exact two-sided p of a perfectly separated Mann-Whitney test: with few
    # electrodes the test CANNOT reach significance, so quote the floor.
    try:
        from math import comb
        p_floor = min(1.0, 2.0 / float(comb(len(ea) + len(eb), len(ea))))
    except Exception:
        p_floor = float("nan")
    X = np.concatenate([a[metric].values, b[metric].values]).astype(float).reshape(-1, 1)
    y = np.array([neg_group] * len(a) + [pos_group] * len(b))
    grp = np.array(["%s|%s" % (g, e) for g, e in
                    zip(list(a[group_col]) + list(b[group_col]),
                        list(a[elec_col]) + list(b[elec_col]))])
    # does the k-sigma cut-off actually split the two groups?  With a noisy
    # blank the 3-sigma line can land below zero and flag nothing at all.
    def _pos_side(v):
        return (float(v) - cutoff) * sign > 0
    false_pos = int(sum(1 for v in ea if _pos_side(v)))
    missed = int(sum(1 for v in eb if not _pos_side(v)))
    separates = bool(false_pos == 0 and missed == 0)
    acc = None
    if len(np.unique(grp)) >= 4:
        try:
            r = loeo_cv(X, y, grp, kind="lda")
            if "error" not in r:
                acc = float(r["accuracy"])
        except Exception:
            acc = None
    return {"neg_group": neg_group, "pos_group": pos_group, "metric": metric,
            "neg_mean": ma, "neg_sd": sa, "pos_mean": mb, "pos_sd": sb,
            "n_neg_elec": int(len(ea)), "n_pos_elec": int(len(eb)),
            "n_neg_scan": int(len(a)), "n_pos_scan": int(len(b)),
            "ratio": ratio, "effect_d": float(dval), "p": p, "p_floor": float(p_floor),
            "k": float(k),
            "sign": float(sign), "cutoff": float(cutoff),
            "direction": "signal-on" if sign > 0 else "signal-off",
            "false_pos": false_pos, "missed": missed, "separates": separates,
            "gap": float(abs(mb - ma)), "accuracy": acc}


def screen_sample(sc, y0):
    """Apply a screening cut-off to one reading.  Qualitative only."""
    if sc.get("error"):
        return {"verdict": "unknown", "text": "无法判定", "detail": sc["error"]}
    try:
        y0 = float(y0)
    except Exception:
        return {"verdict": "unknown", "text": "无法判定", "detail": "这条曲线的响应读不出来"}
    if not np.isfinite(y0):
        return {"verdict": "unknown", "text": "无法判定", "detail": "这条曲线的响应读不出来"}
    cut = float(sc["cutoff"])
    sd = float(sc["neg_sd"])
    if sd <= 0:
        sd = abs(float(sc["pos_mean"]) - float(sc["neg_mean"])) * 0.1
    if sd <= 0:
        sd = 1.0
    margin = (y0 - cut) * float(sc["sign"]) / sd
    if margin > 0:
        return {"verdict": "positive", "text": "检出（定性）",
                "detail": "响应 %.3g 越过截断值 %.3g，超出 %.1f 个空白 SD" % (y0, cut, margin),
                "margin": float(margin)}
    return {"verdict": "negative", "text": "未检出（定性）",
            "detail": "响应 %.3g 没有越过截断值 %.3g（差 %.1f 个空白 SD）" % (y0, cut, -margin),
            "margin": float(margin)}


def format_conc(c):
    if c is None or not np.isfinite(c):
        return "n/a"
    if c >= 1e-3:
        return "%.2f mM" % (c * 1e3)
    if c >= 1e-6:
        return "%.3g uM" % (c * 1e6)
    if c >= 1e-9:
        return "%.3g nM" % (c * 1e9)
    return "%.3g pM" % (c * 1e12)


def format_conc_range(lo, hi):
    """A short "a - b unit" string that fits inside one st.metric tile."""
    if lo is None or hi is None or not np.isfinite(lo) or not np.isfinite(hi):
        return "n/a"
    if hi <= 0:
        return "n/a"
    if hi >= 1e-3:
        u, s = "mM", 1e3
    elif hi >= 1e-6:
        u, s = "uM", 1e6
    elif hi >= 1e-9:
        u, s = "nM", 1e9
    else:
        u, s = "pM", 1e12
    a, b = lo * s, hi * s
    if b / max(a, 1e-30) >= 100:
        return "%.1f - %.0f %s" % (a, b, u)
    return "%.3g - %.3g %s" % (a, b, u)



# =====================================================================
# Per-batch calibration + explicit-truth helpers
#
# docs/跨批次分析.md found that 56% of the variance in the ratiometric
# response sits BETWEEN batches, while the chemical effect inside a batch is
# real (within-batch AUC 0.73 vs 0.51 pooled).  One pooled calibration line
# therefore cannot transfer.  The fix is what every POCT instrument does:
# keep one slope, give each batch its own intercept, and take that intercept
# from the same day's standards.
# =====================================================================

def negative_mask(df, group_col="group"):
    """Boolean mask of the negative controls (no target).

    Priority: explicit role / label metadata, then the group name.  The
    name-based fallback is what the tool used before those columns existed and
    is the fragile one -- a group called "material" carries no target info.
    """
    if "role" in df.columns:
        r = df["role"].astype(str).str.strip().str.lower()
        m = r.isin(["blank", "negative", "neg", "空白", "阴性", "对照", "control"])
        if bool(m.any()):
            return m.values
    if "label" in df.columns:
        lb = pd.to_numeric(df["label"], errors="coerce")
        m = lb.notna() & (lb == 0)
        if bool(m.any()):
            return m.values
    if group_col in df.columns:
        hints = ("no target", "notarget", "no_target", "无靶标", "无靶", "无目标",
                 "blank", "空白", "control", "对照")
        s = df[group_col].astype(str).str.lower()
        m = s.apply(lambda g: any(h in g for h in hints))
        if bool(m.any()):
            return m.values
    return np.zeros(len(df), dtype=bool)


def batch_thresholds(df, metric="ratio", k=3.0, batch_col="batch", group_col="group"):
    """Cut-off computed inside each batch, from that batch's own controls.

    Batch drift is common-mode within a batch, so a cut-off estimated on the
    same day's controls survives the 7x offset in absolute signal that the
    cross-batch analysis measured.  This is the L1/L3 deliverable.
    """
    if batch_col not in df.columns or metric not in df.columns:
        return {"error": "数据表里没有「批次」列或响应指标"}
    d = df[[batch_col, metric]].copy()
    d[metric] = pd.to_numeric(d[metric], errors="coerce")
    d = d[np.isfinite(d[metric].values.astype(float))]
    if not len(d):
        return {"error": "没有可用的响应值"}
    d["neg"] = negative_mask(df.loc[d.index], group_col)
    rows = []
    for b, g in d.groupby(batch_col):
        n = g[g["neg"]][metric].values.astype(float)
        q = g[~g["neg"]][metric].values.astype(float)
        if len(n) < 2:
            rows.append({"batch": str(b), "n_neg": int(len(n)), "n_pos": int(len(q)),
                         "mean": np.nan, "sd": np.nan, "cutoff": np.nan, "ok": False,
                         "direction": "", "note": "阴性对照不足 2 条"})
            continue
        mu, sd = float(n.mean()), float(n.std(ddof=1))
        sign = -1.0 if (len(q) and float(q.mean()) < mu) else 1.0
        rows.append({"batch": str(b), "n_neg": int(len(n)), "n_pos": int(len(q)),
                     "mean": mu, "sd": sd, "cutoff": mu + sign * k * sd,
                     "ok": bool(np.isfinite(sd) and sd > 0),
                     "direction": "signal-on" if sign > 0 else "signal-off",
                     "note": "" if sd > 0 else "阴性对照完全一样，SD = 0"})
    tab = pd.DataFrame(rows)
    tab.attrs["k"] = k
    tab.attrs["metric"] = metric
    return tab


def _shared_slope(x, y, g):
    """One slope for all batches, one intercept each (fixed-effects ANCOVA)."""
    xb = np.empty_like(x)
    yb = np.empty_like(y)
    for k in np.unique(g):
        m = g == k
        xb[m] = x[m].mean()
        yb[m] = y[m].mean()
    dx, dy = x - xb, y - yb
    den = float((dx * dx).sum())
    b = float((dx * dy).sum() / den) if den > 0 else float("nan")
    inter = {}
    for k in np.unique(g):
        m = g == k
        inter[str(k)] = float(yb[m][0] - b * xb[m][0])
    return b, inter


def _lobo_log_rmse(x, y, g):
    """Simulate "calibrate that day": the slope comes from the OTHER batches,
    the intercept from the held-out batch's own standards."""
    res = []
    for k in np.unique(g):
        m = g == k
        if (~m).sum() < 2:
            continue
        b, _ = _shared_slope(x[~m], y[~m], g[~m])
        if not np.isfinite(b) or abs(b) < 1e-12:
            continue
        a = float(y[m].mean() - b * x[m].mean())
        res.extend(((y[m] - a) / b - x[m]).tolist())
    return float(np.sqrt(np.mean(np.square(res)))) if res else float("nan")


def _lod_from_blank(bv, a, b, direction, rng):
    """LOD / LOQ from blank replicates for one (intercept, slope) pair."""
    bv = np.asarray(bv, dtype=float)
    if len(bv) < 3:
        return {"error": "need at least 3 blank replicates (concentration = 0) to compute an LOD"}
    mu, sd = float(bv.mean()), float(bv.std(ddof=1))
    if not np.isfinite(sd) or sd <= 0:
        return {"error": "空白的波动为零，算不出 LOD"}
    if not np.isfinite(b) or abs(b) < 1e-12:
        return {"error": "斜率为零，算不出 LOD"}
    sign = 1.0 if direction == "signal-on" else -1.0
    thr = mu + sign * 3 * sd
    lod = float(10 ** ((thr - a) / b))
    loq = float(10 ** ((mu + sign * 10 * sd - a) / b))
    lo, hi = rng
    if not np.isfinite(lod) or lod <= lo / 100.0 or lod > hi * 10:
        return {"error": "LOD came out at %.2e M, outside the calibrated range "
                         "(%.1e - %.1e M): the blank is not separated from the "
                         "lowest standard" % (lod, lo, hi)}
    return {"LOD_M": lod, "LOQ_M": loq if np.isfinite(loq) and loq <= hi * 10 else None,
            "blank": {"n": int(len(bv)), "mean": mu, "sd": sd, "threshold": thr}}


def fit_calibration_batch(df, metric="ratio", batch_col="batch"):
    """Calibration that survives batch drift.

    Models, picked automatically:
      * per-batch -- every batch has >= 3 levels, so each gets its own line
      * shared    -- one slope for all batches, one intercept each
    The pooled single line is reported alongside so you can see what batch
    drift actually costs on your own data.
    """
    if "concentration_M" not in df.columns:
        return {"error": "no row has a concentration_M value -- fill in the column first"}
    if batch_col not in df.columns:
        return {"error": "数据表里没有「批次」列：按批标定需要知道每条曲线属于哪一批"}
    conc = pd.to_numeric(df["concentration_M"], errors="coerce")
    ok = conc.notna() & df[metric].notna()
    d = df[ok].copy()
    d["_c"] = conc[ok].astype(float)
    std = d[d["_c"] > 0]
    blanks = d[d["_c"] == 0]
    if len(std) == 0:
        return {"error": "no row has a concentration_M value -- fill in the column first"}
    if len(std) < 4:
        return {"error": "need at least 4 standards with a known concentration, have %d" % len(std)}
    g = std[batch_col].astype(str).values
    ug = np.unique(g)
    if len(ug) < 2:
        return {"error": "只有一个批次（%s）：按批标定没有意义，用普通校准即可" % ug[0]}

    x = np.log10(std["_c"].values.astype(float))
    y = std[metric].values.astype(float)
    info = {}
    for k in ug:
        m = g == k
        info[str(k)] = {"n": int(m.sum()),
                        "levels": int(len(np.unique(np.round(std["_c"].values[m], 20))))}
    model = "per-batch" if all(v["levels"] >= 3 and v["n"] >= 4 for v in info.values()) else "shared"

    batches = []
    if model == "per-batch":
        yhat = np.empty_like(y)
        for k in ug:
            m = g == k
            f = _fit_line(x[m], y[m])
            yhat[m] = f["a"] + f["b"] * x[m]
            batches.append({"batch": str(k), "n": f["n"], "levels": info[str(k)]["levels"],
                            "a": f["a"], "b": f["b"], "r2": f["r2"], "syx": f["syx"],
                            "xbar": f["xbar"], "Sxx": f["Sxx"], "source": "own"})
        dof = sum(max(b["n"] - 2, 1) for b in batches)
        syx = float(np.sqrt(sum(b["syx"] ** 2 * max(b["n"] - 2, 1) for b in batches) / dof))
        slope = float(np.mean([b["b"] for b in batches]))
    else:
        slope, inter = _shared_slope(x, y, g)
        yhat = np.array([inter[gi] + slope * xi for gi, xi in zip(g, x)])
        dof = max(len(x) - len(ug) - 1, 1)
        syx = float(np.sqrt(((y - yhat) ** 2).sum() / dof))
        for k in ug:
            m = g == k
            ss = float(((y[m] - y[m].mean()) ** 2).sum())
            batches.append({"batch": str(k), "n": int(m.sum()),
                            "levels": info[str(k)]["levels"],
                            "a": float(inter[str(k)]), "b": float(slope),
                            "r2": float(1 - ((y[m] - yhat[m]) ** 2).sum() / ss)
                            if ss > 0 and int(m.sum()) > 2 else float("nan"),
                            "syx": syx, "xbar": float(x[m].mean()),
                            "Sxx": float(((x[m] - x[m].mean()) ** 2).sum()),
                            "source": "shared"})

    ss_tot = float(((y - y.mean()) ** 2).sum())
    fit = {"model": model, "metric": metric, "slope": slope, "batches": batches,
           "n": int(len(x)), "n_batches": int(len(ug)),
           "r2": float(1 - ((y - yhat) ** 2).sum() / max(ss_tot, 1e-30)), "syx": syx,
           "levels_M": [float(v) for v in np.unique(np.round(std["_c"].values, 20))],
           "dynamic_range_M": [float(std["_c"].min()), float(std["_c"].max())],
           "direction": "signal-off" if slope < 0 else "signal-on",
           "rmse_log": float(np.sqrt(np.mean((yhat - y) ** 2))),
           "rmse_log_lobo": _lobo_log_rmse(x, y, g)}
    pf = _fit_line(x, y)
    fit["pooled_r2"] = float(pf["r2"])
    fit["pooled_slope"] = float(pf["b"])

    fit["LOD_by_batch"] = {}
    for b in batches:
        bb = blanks[blanks[batch_col].astype(str) == b["batch"]][metric].values.astype(float)
        r = _lod_from_blank(bb, b["a"], b["b"], fit["direction"], fit["dynamic_range_M"])
        fit["LOD_by_batch"][b["batch"]] = r
        if "error" not in r:
            b["LOD_M"] = r["LOD_M"]
            b["LOQ_M"] = r["LOQ_M"]
    r = _lod_from_blank(blanks[metric].values.astype(float),
                        float(np.mean([b["a"] for b in batches])), slope,
                        fit["direction"], fit["dynamic_range_M"])
    if "error" in r:
        fit["LOD_error"] = r["error"]
    else:
        fit.update(r)
    return fit


def _batch_entry(fb, batch):
    for b in fb.get("batches", []):
        if str(b["batch"]) == str(batch):
            return b
    return None


def predict_concentration_batch(fb, y0, batch=None, confidence=0.95):
    """Invert a response using that batch's own intercept."""
    if fb.get("error"):
        return {"error": fb["error"]}
    if y0 is None or not np.isfinite(y0):
        return {"error": "this sample has no usable response"}
    e = _batch_entry(fb, batch) if batch is not None else None
    if e is not None:
        a, b, n, s = e["a"], e["b"], e["n"], e["syx"]
        xbar, Sxx, src = e["xbar"], e["Sxx"], e["batch"]
    else:
        a = float(np.mean([q["a"] for q in fb["batches"]]))
        b, s, n = fb["slope"], fb["syx"], fb["n"]
        xbar = float(np.mean([q["xbar"] for q in fb["batches"]]))
        Sxx = float(np.sum([q["Sxx"] for q in fb["batches"]]))
        src = "全部批次的平均截距"
    if not np.isfinite(b) or abs(b) < 1e-12:
        return {"error": "the calibration slope is zero, cannot invert"}
    x0 = (y0 - a) / b
    tcrit = float(stats.t.ppf(0.5 + confidence / 2, max(n - 2, 1)))
    h = tcrit * s / abs(b) * np.sqrt(1 + 1 / n + (x0 - xbar) ** 2 / max(Sxx, 1e-30))
    lo_c, hi_c = fb["dynamic_range_M"]
    C = float(10 ** x0)
    return {"x": float(x0), "C": C, "C_lo": float(10 ** (x0 - h)),
            "C_hi": float(10 ** (x0 + h)), "batch_used": src,
            "in_range": bool(lo_c / 3 <= C <= hi_c * 3),
            "below_range": bool(C < lo_c / 3), "above_range": bool(C > hi_c * 3)}


def decide_batch(fb, y0, batch=None):
    """Same verdict vocabulary as decide(), but calibrated per batch."""
    if fb.get("error"):
        return {"verdict": "unknown", "text": "还没有可用的校准曲线，无法定量", "detail": fb["error"]}
    pr = predict_concentration_batch(fb, y0, batch)
    if pr.get("error"):
        return {"verdict": "unknown", "text": "无法定量", "detail": pr["error"]}
    e = _batch_entry(fb, batch) if batch is not None else None
    lod = (e or {}).get("LOD_M") or fb.get("LOD_M")
    if lod and pr["C"] < lod:
        return {"verdict": "negative", "text": "未检出",
                "detail": "响应低于检出限 (%.1e M)，判定为阴性" % lod, "prediction": pr}
    if pr["above_range"]:
        return {"verdict": "positive", "text": "检出，且超出定量范围（需稀释复测）",
                "detail": "推算浓度 %.1e M 高于最高标准点" % pr["C"], "prediction": pr}
    if pr["below_range"]:
        return {"verdict": "negative", "text": "未检出（低于最低标准点）",
                "detail": "响应落在校准范围以下", "prediction": pr}
    return {"verdict": "positive", "text": "检出",
            "detail": "浓度 %s（95%% 置信区间 %s – %s）"
                      % (format_conc(pr["C"]), format_conc(pr["C_lo"]),
                         format_conc(pr["C_hi"])), "prediction": pr}


def batch_table(fb):
    """Display frame for the per-batch fits."""
    if not fb or fb.get("error"):
        return pd.DataFrame()
    rows = []
    for b in fb["batches"]:
        rows.append({"批次": b["batch"], "标准点": b["n"], "浓度数": b["levels"],
                     "截距 a": round(b["a"], 4), "斜率 b": round(b["b"], 4),
                     "R²": (round(b["r2"], 3) if np.isfinite(b["r2"]) else np.nan),
                     "模型": "本批单独拟合" if b["source"] == "own" else "共用斜率",
                     "LOD": format_conc(b.get("LOD_M")),
                     "LOQ": format_conc(b.get("LOQ_M"))})
    return pd.DataFrame(rows)
