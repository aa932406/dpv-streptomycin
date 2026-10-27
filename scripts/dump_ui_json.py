#!/usr/bin/env python3
"""
dump_ui_json.py -- turn one folder of .cor files into the JSON the web UI eats.

This is the contract between the Python analysis core and the React frontend:
everything the browser needs for the overview screen comes out of here, so the
FastAPI layer can stay a thin shell around the same functions.

Run:
    python scripts/dump_ui_json.py --data data/20261010 --out out/ui/20261010.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(HERE))

import analysis_core as core
from dpv_pipeline import (GROUP_ORDER, GROUP_COLOR, PALETTE, group_of,
                           group_colors as _shared_group_colors,
                          electrode_of)


def load_prefill(folder: Path):
    """<data folder>/metadata.csv first, then <project>/metadata/metadata.csv."""
    cands = [folder / "metadata.csv", PROJECT / "metadata" / "metadata.csv"]
    for c in cands:
        if not c.exists():
            continue
        try:
            t = pd.read_csv(c)
        except Exception:
            continue
        if "file" not in t.columns:
            continue
        return {str(r["file"]): r.to_dict() for _, r in t.iterrows()}, str(c)
    return {}, None


def group_colors(names):
    """Kept as a thin alias -- the logic lives in dpv_pipeline so that the
    matplotlib figures and the web UI cannot drift apart."""
    return _shared_group_colors(names)


def _txt(v, default=""):
    """A CSV round-trip turns blanks into NaN; keep the caller's default."""
    if v is None:
        return default
    s = str(v).strip()
    return default if s in ("", "nan", "None", "NaN") else s


def read_items(folder: Path):
    return [(p.name, p.read_bytes()) for p in sorted(folder.glob("*.cor"))]


def num(x, nd=None):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    return round(v, nd) if nd is not None else v


def prepare(folder: Path, order: int = 4, ref_frac: float = 0.35, metric=None,
            technique: str = "auto"):
    """Shared front half of build(): parse -> metadata prefill -> QC -> metric.

    Kept as its own function so the modelling code (ml_models) sees exactly the
    same table the UI shows -- no second, silently diverging copy of the rules.
    Returns (df, curves, errors, grid, metric); metric is None when there is no
    usable data.
    """
    df, curves, errors, grid = core.build_table(read_items(folder), order=order,
                                                technique=technique)
    if not len(df):
        return df, curves, errors, grid, None

    df["group"] = df["file"].map(group_of)
    df["electrode"] = df["file"].map(electrode_of)

    prefill, prefill_src = load_prefill(folder)
    if prefill:
        df["group"] = df["file"].map(lambda f: prefill.get(f, {}).get("group") or group_of(f))
        df["electrode"] = df["file"].map(lambda f: prefill.get(f, {}).get("electrode") or electrode_of(f))
        df["concentration_M"] = df["file"].map(
            lambda f: pd.to_numeric(prefill.get(f, {}).get("concentration_M"), errors="coerce"))
        df["batch"] = df["file"].map(lambda f: _txt(prefill.get(f, {}).get("batch"), folder.name))
        df["label"] = df["file"].map(
            lambda f: pd.to_numeric(prefill.get(f, {}).get("label"), errors="coerce"))
        df["role"] = df["file"].map(lambda f: _txt(prefill.get(f, {}).get("role"), ""))
    else:
        df["concentration_M"] = np.nan
        df["batch"] = folder.name
        df["label"] = np.nan
        df["role"] = ""
    df = core.add_qc(df, ref_min=0.0, ref_frac=ref_frac)
    avail = core.metric_availability(df)
    if metric not in avail:
        metric = avail[0]
    return df, curves, errors, grid, metric



FEATURE_KEYS = ["I_MB", "I_ref", "ratio", "anodic_H", "cathodic_H", "anodic_Ep",
                "cathodic_Ep", "Q", "ocp", "I_start", "I_mid", "I_end"]


def _regression_block(df, curves):
    """The quantitative prediction block: linear vs non-linear, compared.

    Mirrors the Food Chem Cd paper (linear calibration + RBF-SVR, R2 / RPD) and
    the Food Chem antibiotics paper (a neural net reading the signal), but the
    validation unit is always a whole electrode or a whole batch.
    """
    import ml_models as ml

    out = {}
    if "concentration_M" not in df.columns:
        return {"error": "没有浓度列：预测模型需要标准点的真实浓度"}
    conc = pd.to_numeric(df["concentration_M"], errors="coerce")
    mask = (conc.notna() & (conc > 0)).values
    n_std = int(mask.sum())
    levels = int(conc[mask].round(20).nunique()) if n_std else 0
    elec = (df["electrode"].astype(str) if "electrode" in df.columns
            else pd.Series([str(i) for i in df.index], index=df.index))
    batch = (df["batch"].astype(str) if "batch" in df.columns
             else pd.Series([""] * len(df), index=df.index))
    n_elec = int(elec[mask].nunique()) if n_std else 0
    n_batch = int(batch[mask].nunique()) if n_std else 0
    out.update({"n_standards": n_std, "n_levels": levels,
                "n_electrodes": n_elec, "n_batches": n_batch})
    if n_std < 6 or levels < 3:
        out["error"] = ("预测模型至少要 6 条标准点、3 个不同浓度；现在只有 %d 条标准点、%d 个浓度。"
                        % (n_std, levels))
        return out
    mode = "electrode" if n_elec >= 3 else ("batch" if n_batch >= 2 else None)
    if mode is None:
        out["error"] = ("预测模型必须留出独立单元做验证：至少 3 支电极，或 2 个批次；"
                        "现在只有 %d 支电极、%d 个批次。" % (n_elec, n_batch))
        return out

    y = conc[mask].values.astype(float)
    g = (elec if mode == "electrode" else batch)[mask].values
    feats = [c for c in FEATURE_KEYS if c in df.columns]
    Xc = np.asarray(curves, float)[mask]
    Xf = df.loc[mask, feats].apply(pd.to_numeric, errors="coerce").values

    runs = []
    for tag, X in (("整条曲线", Xc), ("手工特征", Xf)):
        r = ml.evaluate(X, y, g, mode=mode)
        if r.get("error"):
            runs.append({"set": tag, "error": r["error"]})
        else:
            runs.append({"set": tag, "X": X, **r})
    good = [r for r in runs if not r.get("error")]
    if not good:
        out["error"] = runs[0].get("error") if runs else "拟合失败"
        return out

    rows = []
    for r in good:
        for m in r["models"]:
            rows.append({"set": r["set"], **m})
    rows.sort(key=lambda m: -m["r2"])
    for m in rows:
        m.pop("folds", None)
    best = rows[0]
    on_log = good[0]["scale"] == "log10(C)"
    out.update({"mode": mode, "unit": "电极" if mode == "electrode" else "批次",
                "n_units": int(len(set(g.tolist()))),
                "decades": float(np.log10(y.max() / y.min())),
                "scale": good[0]["scale"], "models": rows,
                "best": best["name"], "best_set": best["set"], "best_row": best})

    for r in good:
        if r["set"] != best["set"]:
            continue
        bp = r.get("best_pred") or {}
        if bp and on_log:                        # undo the log fit for display
            out["best_pred"] = {"true": [float(10 ** v) for v in bp["true"]],
                                "pred": [float(10 ** v) for v in bp["pred"]]}
        else:
            out["best_pred"] = bp
        try:
            out["learning"] = ml.learning_curve(r["X"], y, g, name=best["name"], mode=mode)
        except Exception as exc:                 # noqa: BLE001
            out["learning"] = {"error": str(exc)[:120]}
        break
    try:
        imp = ml.importance(Xf, y, g, feats, name="随机森林")
        if imp.get("rows"):
            imp["rows"] = [{"feature": r["feature"], "v": num(r["v"], 6),
                            "sd": num(r["sd"], 6)} for r in imp["rows"]]
        out["importance"] = imp
    except Exception as exc:                     # noqa: BLE001
        out["importance"] = {"error": str(exc)[:120]}
    return out


def build(folder: Path, order: int = 4, ref_frac: float = 0.35, metric=None,
          technique: str = "auto", with_regression: bool = True):
    df, curves, errors, grid, metric = prepare(folder, order, ref_frac, metric, technique)
    if not len(df):
        return {"meta": {"folder": folder.name, "n_curves": 0,
                         "technique": "", "technique_counts": df.attrs.get("technique_counts", {}),
                         "technique_options": []}, "errors": errors}

    out = {
        "meta": {
            "folder": folder.name,
            "n_curves": int(len(df)),
            "n_electrodes": int(df["electrode"].nunique()),
            "n_groups": int(df["group"].nunique()),
            "n_qc": int(df["qc_pass"].sum()),
            "n_points": int(curves.shape[1]),
            "window": [num(grid.min(), 3), num(grid.max(), 3)],
            "metric": metric,
            "metric_cn": core.METRIC_CN.get(metric, metric),
            "metric_available": list(core.metric_availability(df)),
            "qc_threshold": num(df.attrs.get("ref_threshold"), 3),
            "qc_median": num(df.attrs.get("ref_median"), 3),
            # which pulse technique this batch was analysed as, and what else is
            # in the folder (the UI offers a picker built from these two)
            "technique": df.attrs.get("technique") or "",
            "technique_cn": core.TECHNIQUE_CN.get(df.attrs.get("technique") or "", ""),
            "technique_counts": df.attrs.get("technique_counts") or {},
            "technique_options": sorted(
                k for k in (df.attrs.get("technique_counts") or {})
                if k in core.PEAK_TECHNIQUES),
        },
        "errors": errors,
        "groups": [],
        "samples": [],
        "curves": {"grid": [num(v, 4) for v in grid], "series": []},
    }

    cmap = group_colors(df["group"].tolist())

    gs = core.group_summary(df, metric=metric)
    for _, r in gs.iterrows():
        sub = df[df["group"] == r["group"]]
        good = sub[sub["qc_pass"]] if "qc_pass" in sub.columns else sub.iloc[0:0]
        out["groups"].append({
            "name": str(r["group"]),
            "n": int(r["n"]),
            "n_elec": int(sub["electrode"].nunique()),
            "mean": num(r["mean"], 4),
            "sd": num(r["sd"], 4),
            "cv_pct": num(r["cv_pct"], 1),
            "color": cmap.get(str(r["group"])),
            # same numbers on QC-passed curves only -- what the bar chart shows
            "n_qc": int(len(good)),
            "mean_qc": num(good[metric].mean() if len(good) else None, 4),
            "sd_qc": num(good[metric].std(ddof=1) if len(good) > 1 else None, 4),
        })

    for _, r in df.iterrows():
        out["samples"].append({
            "file": str(r["file"]),
            "group": str(r["group"]),
            "electrode": str(r["electrode"]),
            "value": num(r.get(metric), 4),
            "I_MB": num(r.get("I_MB"), 3),
            "I_ref": num(r.get("I_ref"), 3),
            "qc_pass": bool(r.get("qc_pass")),
            "batch": str(r.get("batch") or ""),
            "label": num(r.get("label")),
            "concentration_M": num(r.get("concentration_M")),
            "role": str(r.get("role") or ""),
        })

    # mean +/- SD band per condition, on the shared grid
    g_arr = grid
    for g in [x["name"] for x in out["groups"]]:
        idx = np.where(df["group"].values == g)[0]
        if not len(idx):
            continue
        sub = curves[idx, :]
        out["curves"]["series"].append({
            "name": g,
            "mean": [num(v, 5) for v in sub.mean(axis=0)],
            "sd": [num(v, 5) for v in sub.std(axis=0, ddof=1)] if len(idx) > 1 else None,
            "n": int(len(idx)),
            "color": cmap.get(str(g)),
        })

    # individual traces, thinned so a 240-point folder does not blow up the payload
    out["curves"]["raw"] = []
    step = max(1, len(df) // 40)
    for i in range(0, len(df), step):
        r = df.iloc[i]
        out["curves"]["raw"].append({
            "file": str(r["file"]), "group": str(r["group"]),
            "y": [num(v, 5) for v in curves[i, :]],
        })

    # ---- statistics ----------------------------------------------------
    y_lab = df["group"].astype(str).values
    g_lab = df["electrode"].astype(str).values
    try:
        an = core.group_stats(df)
        out["stats"] = {
            "anova": [{"feature": str(r["feature"]),
                       "label": core.FEATURE_LABEL.get(str(r["feature"]), str(r["feature"])),
                       "F": num(r["F"], 3), "p": num(r["p"], 6),
                       "eta2": num(r["eta2"], 3), "n": int(r["n"])}
                      for _, r in an.iterrows()],
            "tukey": [], "summary": [],
        }
        tk = core.tukey_table(df, feat=metric)
        for _, r in tk.iterrows():
            out["stats"]["tukey"].append({
                "A": str(r["A"]), "B": str(r["B"]), "diff": num(r["diff"], 4),
                "p": num(r["p"], 6), "lo": num(r["lo"], 4), "hi": num(r["hi"], 4)})
        sm = core.group_summary(df, metric=metric)
        for _, r in sm.iterrows():
            out["stats"]["summary"].append({
                "group": str(r["group"]), "n": int(r["n"]), "mean": num(r["mean"], 4),
                "sd": num(r["sd"], 4), "cv_pct": num(r["cv_pct"], 1)})
    except Exception as exc:                     # noqa: BLE001
        out["stats"] = {"error": str(exc), "anova": [], "tukey": [], "summary": []}

    # ---- PCA on the whole curve ---------------------------------------
    try:
        sc, var = core.pca_scores(curves, n_components=3)
        pts = []
        for i, (_, r) in enumerate(df.iterrows()):
            if i >= len(sc):
                break
            pts.append({
                "file": str(r["file"]), "group": str(r["group"]),
                "pc1": num(sc[i, 0], 4),
                "pc2": num(sc[i, 1], 4) if sc.shape[1] > 1 else 0.0,
                "pc3": num(sc[i, 2], 4) if sc.shape[1] > 2 else 0.0})
        out["pca"] = {"var": [num(v, 4) for v in var], "points": pts}
    except Exception as exc:                     # noqa: BLE001
        out["pca"] = {"error": str(exc), "var": [], "points": []}

    # ---- leave-one-electrode-out classification ------------------------
    try:
        r = core.loeo_cv(curves, y_lab, g_lab, kind="lda")
        if "error" in r:
            out["model"] = {"error": r["error"]}
        else:
            perm = core.permutation_test(curves, y_lab, g_lab, kind="lda", n_perm=100)
            supp = {}
            for gname, elec in zip(y_lab, g_lab):
                supp.setdefault(str(gname), set()).add(str(elec))
            elec_per_class = {k: len(v) for k, v in supp.items()}
            out["model"] = {
                "accuracy": num(r["accuracy"], 4),
                "balanced_accuracy": num(r.get("balanced_accuracy"), 4),
                "class_support": r.get("class_support", {}),
                "elec_per_class": elec_per_class,
                "min_elec_per_class": min(elec_per_class.values()) if elec_per_class else 0,
                "n_scans": int(r["n_scans"]),
                "n_folds": int(r["n_folds"]), "labels": r["labels"],
                "confusion": r["confusion"],
                "chance": round(1.0 / max(len(set(y_lab)), 1), 4),
                "perm": {"observed": num(perm.get("observed"), 4),
                         "observed_accuracy": num(perm.get("observed_accuracy"), 4),
                         "null_mean": num(perm.get("null_mean"), 4),
                         "null_p95": num(perm.get("null_p95"), 4),
                         "p_value": num(perm.get("p_value"), 5),
                         "null": [num(v, 4) for v in perm.get("null", [])][:400]},
            }
    except Exception as exc:                     # noqa: BLE001
        out["model"] = {"error": str(exc)}

    try:
        names = [f for f in core.FEATURES if f in df.columns]
        imp = core.feature_importance(df[names].fillna(0.0).values, y_lab, names, kind="rf")
        out["importance"] = [{"feature": n, "label": core.FEATURE_LABEL.get(n, n),
                              "v": round(float(v), 4)} for n, v in imp[:8]]
    except Exception:                            # noqa: BLE001
        out["importance"] = []

    # ---- standards on the calibration plot -----------------------------
    out["calib_points"] = []
    if "concentration_M" in df.columns:
        for (_, r), c0 in zip(df.iterrows(), pd.to_numeric(df["concentration_M"], errors="coerce").values):
            if not np.isfinite(c0):
                continue
            v = num(r.get(metric))
            if v is None:
                continue
            out["calib_points"].append({
                "file": str(r["file"]), "group": str(r["group"]),
                "conc_M": float(c0), "logc": round(float(np.log10(c0)) if c0 > 0 else -14.0, 4),
                "value": v})

    # calibration (only if a concentration column exists with a gradient)
    try:
        fit = core.fit_calibration(df, metric=metric)
    except Exception as exc:                     # noqa: BLE001 - reported to the UI
        fit = {"error": str(exc)}
    out["fit"] = {k: (num(v) if isinstance(v, (int, float, np.floating)) else v)
                  for k, v in fit.items() if k in
                  ("error", "a", "b", "r2", "syx", "direction", "LOD_M", "LOQ_M",
                   "LOD_error", "quality", "n_std", "levels_M")}

    # per-batch calibration: only meaningful with more than one batch
    out["fit_batch"] = None
    out_fb = None
    try:
        if df["batch"].astype(str).nunique() > 1:
            fb = core.fit_calibration_batch(df, metric=metric)
            out_fb = fb
            out["fit_batch"] = {
                "model": fb.get("model"), "r2": num(fb.get("r2"), 4),
                "pooled_r2": num(fb.get("pooled_r2"), 4),
                "rmse_log_lobo": num(fb.get("rmse_log_lobo"), 4),
                "direction": fb.get("direction"),
                "error": fb.get("error"),
                "LOD_M": num(fb.get("LOD_M")), "LOQ_M": num(fb.get("LOQ_M")),
                "batches": [{k: (num(v) if k in ("LOD_M", "LOQ_M")
                                 else num(v, 4) if isinstance(v, (int, float, np.floating)) else v)
                             for k, v in b.items()} for b in fb.get("batches", [])],
            }
    except Exception as exc:                     # noqa: BLE001
        out["fit_batch"] = {"error": str(exc), "batches": []}

    # qualitative screening: pick the most plausible negative / positive pair
    try:
        pos = neg = None
        if df["label"].notna().any():            # explicit 0/1 beats guessing from names
            p_rows = df[df["label"] == 1]
            n_rows = df[df["label"] == 0]
            if len(p_rows) and len(n_rows):
                pos = {"name": p_rows["group"].value_counts().index[0]}
                neg = {"name": n_rows["group"].value_counts().index[0]}
        if pos is None:
            pos = next((g for g in out["groups"] if "enz" in g["name"].lower()
                        and "no" not in g["name"].lower()), None)
        if neg is None:
            neg = next((g for g in out["groups"] if "material" in g["name"].lower()), None)
        if pos and neg:
            sc = core.screening_test(df, neg["name"], pos["name"], metric=metric)
            out["screening"] = {k: (num(v, 4) if isinstance(v, (int, float, np.floating)) else v)
                                for k, v in sc.items()}
    except Exception as exc:                     # noqa: BLE001
        out["screening"] = {"error": str(exc)}


    # The prediction block is the only expensive part (nested search over nine
    # models); the web UI pulls it from /api/regression so the first paint of
    # the overview stays fast.
    if with_regression:
        try:
            out["regression"] = _regression_block(df, curves)
        except Exception as exc:                 # noqa: BLE001
            out["regression"] = {"error": str(exc)}

    # ---- verdicts ------------------------------------------------------
    # Only rows that are neither a standard nor a blank can be "samples";
    # standards already have a known concentration, blanks are not asked.
    import re as _re
    def _is_reference(g):
        return bool(_re.search(r"blank|material|空白|对照|control|buffer", str(g), _re.I))

    out["verdicts"] = []
    conc = pd.to_numeric(df.get("concentration_M"), errors="coerce") if "concentration_M" in df.columns else pd.Series([np.nan] * len(df))
    fb_ok = bool(out.get("fit_batch") and not out["fit_batch"].get("error"))
    use_batch = fb_ok                       # per-batch always beats one pooled line
    if not out["fit"].get("error") or use_batch:
        for (_, r), c0 in zip(df.iterrows(), conc.values):
            if np.isfinite(c0) or _is_reference(r["group"]):
                continue
            y0 = num(r.get(metric))
            if y0 is None:
                continue
            dec = (core.decide_batch(out_fb, y0, batch=str(r.get("batch")))
                   if use_batch else core.decide(fit, y0))
            pr = dec.get("prediction", {}) or {}
            cval = num(pr.get("C"))
            out["verdicts"].append({
                "file": str(r["file"]), "group": str(r["group"]),
                "electrode": str(r["electrode"]), "value": y0,
                "batch": str(r.get("batch") or ""),
                "verdict": dec.get("verdict"), "text": dec.get("text"),
                "detail": dec.get("detail"),
                "C": cval,
                "C_lo": num(pr.get("C_lo")),
                "C_hi": num(pr.get("C_hi")),
                "C_text": (core.format_conc(cval) if cval is not None else None),
            })

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--order", type=int, default=4)
    ap.add_argument("--ref-frac", type=float, default=0.35)
    ap.add_argument("--technique", default="auto",
                    help="auto | DPV | DPV-stripping | SWV | SWV-stripping | all")
    args = ap.parse_args()

    folder = Path(args.data)
    payload = build(folder, order=args.order, ref_frac=args.ref_frac,
                    technique=args.technique)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", out, out.stat().st_size, "bytes")
    print("curves", payload["meta"].get("n_curves"), "groups",
          [g["name"] for g in payload.get("groups", [])])


if __name__ == "__main__":
    main()
