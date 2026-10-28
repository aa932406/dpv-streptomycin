#!/usr/bin/env python3
"""
train_model.py -- train ONE model, save it to disk, take it away.

Why this script exists
----------------------
The web page "predict" retrains 18 candidates (9 models x 2 inputs) inside a
request and then throws them away.  Nothing is written to disk, so there is no
artefact you can carry to tomorrow's sample.  This script fixes the four steps
that actually make a model usable:

    pick  ->  validate (leave-one-electrode / leave-one-batch)  ->  refit on
    every standard  ->  save

It writes two files:

    models/<name>.joblib   the real model: sklearn estimator + every
                           preprocessing constant needed to reproduce the input
                           (grid, baseline order, QC ratio, feature list, scale)
    models/<name>.json     the model card: which folder, how many standards,
                           how many concentrations, the cross-validated scores,
                           and the concentration range the model may be trusted in

Usage
-----
    python scripts/train_model.py --data data/demo
    python scripts/train_model.py --data data/cd36_ngml --mode electrode
    python scripts/train_model.py --data data/demo --model SVR-RBF --input features
    python scripts/train_model.py --describe models/demo_curves_gpr.joblib

Read the numbers in the model card, not just R2: a model whose CV says
"factor 2.7x" must never be quoted as "predicted 100 nM" without that range.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pickle
import platform
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ml_models as ml          # noqa: E402
import dump_ui_json as dump     # noqa: E402

PROJECT = HERE.parent
MODEL_FORMAT = "dpv-model/1"

# model names are Chinese in the UI; file names must survive every filesystem
SLUG = {
    "线性回归": "linreg",
    "岭回归": "ridge",
    "PLS": "pls",
    "SVR-RBF": "svr-rbf",
    "SVR-线性核": "svr-lin",
    "随机森林": "rf",
    "梯度提升": "gbm",
    "BP-ANN": "bpann",
    "高斯过程": "gpr",
}


def resolve_folder(arg: str) -> Path:
    """'demo' / 'data/demo' / an absolute path all work."""
    p = Path(arg)
    if p.is_dir():
        return p.resolve()
    for cand in (PROJECT / "data" / arg, PROJECT / arg):
        if cand.is_dir():
            return cand.resolve()
    sys.exit("找不到数据文件夹：%s（试过 %s 和 %s）" % (arg, PROJECT / "data" / arg, PROJECT / arg))


def standards(df, curves, input_kind: str):
    """-> X, y, groups, kept rows.  Only rows with a known concentration > 0."""
    if "concentration_M" not in df.columns:
        sys.exit("这张表里没有 concentration_M 列 —— 先在「数据」页把标准品的浓度填进去。")
    conc = pd.to_numeric(df["concentration_M"], errors="coerce")
    mask = (conc.notna() & (conc > 0)).values
    if mask.sum() == 0:
        sys.exit("这个文件夹里没有一条标准点（concentration_M > 0）。"
                 "先在「数据」页把标准品的浓度填进去，再来训练。")
    d = df.loc[mask].reset_index(drop=True)
    y = conc[mask].to_numpy(float)
    if input_kind == "curves":
        X = np.asarray(curves, float)[mask]
    else:
        X = d[ml.FEATURE_KEYS].to_numpy(float)
    groups = d["electrode"].astype(str).to_numpy() if "electrode" in d.columns else np.arange(len(d)).astype(str)
    return X, y, groups, d


def detection_block(df, metric):
    """Blank statistics -> a "is there anything at all" threshold.

    A regression trained on log10(C) never sees C = 0, so on its own it happily
    reports "4 nM" for a blank.  The blank distribution is what says otherwise:
    anything inside blank_mean +/- 3 SD is "not detected", regardless of what the
    regressor mumbles.
    """
    if "concentration_M" not in df.columns or metric not in df.columns:
        return None
    conc = pd.to_numeric(df["concentration_M"], errors="coerce")
    blanks = pd.to_numeric(df.loc[conc == 0, metric], errors="coerce").dropna().to_numpy(float)
    if len(blanks) < 3:
        return None
    hi = pd.to_numeric(df.loc[conc > 0, metric], errors="coerce").dropna().to_numpy(float)
    if len(hi) == 0:
        return None
    mu, sd = float(np.mean(blanks)), float(np.std(blanks, ddof=1))
    if not np.isfinite(sd) or sd <= 0:
        return None
    # signal-on (higher response = more target) or signal-off
    sign = 1.0 if float(np.mean(hi)) > mu else -1.0
    return {"metric": metric, "n_blanks": int(len(blanks)), "mean": mu, "sd": sd,
            "sign": sign, "cutoff": mu + sign * 3.0 * sd}


def train(data, mode="electrode", input="auto", model="auto", order=4,
          ref_frac=0.35, target="链霉素", seed=0, out="models", fmt="joblib") -> dict:
    """Train + validate + refit on everything + save.  Returns a result dict.

    {'name', 'job', 'card_path', 'card', 'log': [str], 'leaderboard': [row]}

    Raises RuntimeError (Chinese message) when there is nothing to train, so the
    API can turn it into a 400 without the process dying.  main() is only a
    printer around this function.
    """
    try:
        return _train(data, mode=mode, input=input, model=model, order=order,
                      ref_frac=ref_frac, target=target, seed=seed, out=out, fmt=fmt)
    except SystemExit as exc:                      # standards()/resolve_folder() exit
        msg = exc.code if exc.code not in (None, 0) else "训练失败"
        raise RuntimeError(str(msg)) from None


def _train(data, mode, input, model, order, ref_frac, target, seed, out, fmt) -> dict:
    folder = resolve_folder(data)
    log = ["数据文件夹 : %s" % folder]
    df, curves, errors, grid, metric = dump.prepare(folder, order=order, ref_frac=ref_frac)
    if df is None or len(df) == 0:
        raise RuntimeError("这个文件夹里没有可用的 DPV 曲线。")
    if errors:
        log.append("解析失败   : %d 个文件（已跳过）" % len(errors))

    # A model that predicts concentration needs at least three distinct levels:
    # with one level every target value is identical, so any regressor either
    # returns that constant or fits noise.  Say so, instead of letting the
    # degeneracy guard fire later with a confusing "same number" message.
    conc = pd.to_numeric(df["concentration_M"], errors="coerce") if "concentration_M" in df.columns else None
    if conc is not None:
        levels = np.unique(np.round(conc[(conc > 0) & conc.notna()].values, 20))
        if len(levels) < 3:
            raise RuntimeError(
                "这个文件夹只有 %d 个不同浓度（%s），训不出浓度预测模型。"
                "至少需要 3 个浓度、每个浓度 2-3 支电极；一天能做完的最小方案是 "
                "空白 3 支 + 10 nM 3 支 + 1 µM 3 支 = 9 支电极。"
                % (len(levels), " / ".join("%.3g M" % v for v in levels) if len(levels) else "一条标准点都没有"))

    kinds = ["curves", "features"] if input == "auto" else [input]
    board = []
    for kind in kinds:
        X, y, groups, d = standards(df, curves, kind)
        n_units = len(set(groups))
        if n_units < 3:
            log.append("跳过 %s：只有 %d 个独立单元，做不了交叉验证" % (kind, n_units))
            continue
        res = ml.evaluate(X, y, groups, mode=mode, seed=seed)
        if res.get("error"):
            log.append("跳过 %s：%s" % (kind, res["error"]))
            continue
        for row in res["models"]:
            row = dict(row)
            row["set"] = "整条曲线" if kind == "curves" else "手工特征"
            row["kind"] = kind
            board.append(row)
    if not board:
        raise RuntimeError("没有任何模型能训练：标准点太少，或者独立单元（电极/批次）不够。")

    board.sort(key=lambda r: r["r2"], reverse=True)
    best = board[0]
    if model != "auto":
        hit = [r for r in board if r["name"] == model]
        if not hit:
            names = sorted({r["name"] for r in board})
            raise RuntimeError("没有叫 %s 的模型；可选：%s" % (model, " / ".join(names)))
        best = hit[0]

    kind = best["kind"]
    X, y, groups, d = standards(df, curves, kind)
    log.append("输入       : %s（%d 条标准点 × %d 维）" % (best["set"], X.shape[0], X.shape[1]))
    log.append("交叉验证   : 留一%s %d 折 → R²=%.3f  RPD=%.2f" % (
        "电极" if mode == "electrode" else "批次", best["n_folds"], best["r2"], best["rpd"]))

    # ---- refit on every standard, exactly the pipeline evaluate() used -------
    # evaluate() writes "log10(C)"; comparing to "log10" silently fell back to
    # fitting raw concentrations (1e-12..1e-7), where SVR's epsilon=0.05 tube
    # swallows every residual and the model returns one constant for everything.
    on_log = str(best.get("scale", "")).startswith("log10")
    t = ml._to_log(y) if on_log else np.asarray(y, float)
    zoo = ml.model_zoo(seed)
    est, param_grid = zoo[best["name"]]
    fitted = ml._fit_with_grid(est, param_grid, np.asarray(X, float), t, seed)

    in_sample = np.asarray(fitted.predict(np.asarray(X, float))).ravel()
    if np.std(in_sample) < 1e-9:
        raise RuntimeError("拟合失败：模型对每一条标准点都给出同一个数（%s）。"
                           "这通常意味着目标变量的尺度或 epsilon 设置不对，先别存这个模型。"
                           % ("%.3g" % in_sample[0] if len(in_sample) else "?"))
    ss_res = float(np.sum((in_sample - t) ** 2))
    ss_tot = float(np.sum((t - t.mean()) ** 2)) or 1.0
    in_r2 = 1.0 - ss_res / ss_tot

    name = "%s_%s_%s" % (folder.name, "curves" if kind == "curves" else "features",
                         SLUG.get(best["name"], "model"))
    out_p = Path(out)
    if out_p.suffix in (".joblib", ".pkl"):
        job_path = out_p
        fmt = "pkl" if out_p.suffix == ".pkl" else "joblib"
    else:
        out_p.mkdir(parents=True, exist_ok=True)
        job_path = out_p / (name + (".pkl" if fmt == "pkl" else ".joblib"))

    levels = sorted({float(v) for v in np.round(y, 20)})
    detect = detection_block(df, metric)
    card = {
        "format": MODEL_FORMAT,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "name": name,
        "target": target,
        "model": best["name"],
        "input": "curves" if kind == "curves" else "features",
        "feature_keys": None if kind == "curves" else list(ml.FEATURE_KEYS),
        "grid": [float(v) for v in np.asarray(grid, float)] if kind == "curves" else None,
        "baseline_order": int(order),
        "ref_frac": float(ref_frac),
        "metric": metric,
        "y_scale": "log10" if on_log else "linear",
        "in_sample_r2": float(in_r2),
        "cv": {
            "mode": mode,
            "n_folds": best["n_folds"],
            "r2": best["r2"],
            "rmse": best["rmse"],
            "mae": best["mae"],
            "rpd": best["rpd"],
            "rmse_dex": best.get("rmse_dex"),
            "factor": best.get("factor"),
            "rel_err_pct": best.get("rel_err_pct"),
            "folds": best.get("folds"),
        },
        "train": {
            "folder": str(folder),
            "n_standards": int(len(y)),
            "n_levels": len(levels),
            "n_units": int(len(set(groups))),
            "unit": "electrode" if mode == "electrode" else "batch",
            "levels_M": levels,
            "range_M": [min(levels), max(levels)],
        },
        "software": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "sklearn": _sklearn_version(),
        },
        "detection": detect,
        "leaderboard": [{k: r.get(k) for k in ("name", "set", "r2", "rpd", "rmse_dex", "factor")}
                        for r in board[:8]],
    }

    blob = {"card": card, "model": fitted}
    if fmt == "pkl":
        with job_path.open("wb") as fh:
            pickle.dump(blob, fh, protocol=5)
    else:
        import joblib
        joblib.dump(blob, job_path)
    card_path = job_path.with_suffix(".json")
    card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")

    log.append("样本内 R²  : %.3f（只用来确认模型没有退化成常数，不是成绩）" % in_r2)
    log.append("已保存     : %s (%.1f KB)" % (job_path, job_path.stat().st_size / 1024))
    log.append("模型卡     : %s" % card_path)
    log.append("适用范围   : %.2e - %.2e M（%d 个浓度、%d 条标准点、%d 个独立单元）" % (
        card["train"]["range_M"][0], card["train"]["range_M"][1],
        len(levels), len(y), card["train"]["n_units"]))
    if best.get("factor"):
        log.append("报告误差   : 约 %.1f 倍（报 100 nM 时真值大致在 %.0f - %.0f nM）" % (
            best["factor"], 100 / best["factor"], 100 * best["factor"]))
    if detect:
        log.append("检出阈值   : %s 空白 %.3f ± %.3f（n=%d）→ 判「检出」需 %s %.3f" % (
            detect["metric"], detect["mean"], detect["sd"], detect["n_blanks"],
            "≥" if detect["sign"] > 0 else "≤", detect["cutoff"]))
    else:
        log.append("检出阈值   : 没有足够的空白（<3 条），模型只能给浓度、不能判「有没有」")

    return {"name": name, "job": str(job_path), "card_path": str(card_path),
            "card": card, "log": log, "leaderboard": board, "format": fmt}


def main() -> None:
    ap = argparse.ArgumentParser(description="train + save one quantitative DPV model")
    ap.add_argument("--data", help="data folder: demo / data/demo / an absolute path")
    ap.add_argument("--describe", help="print the model card of an existing model file and exit")
    ap.add_argument("--mode", default="electrode", choices=["electrode", "batch"],
                    help="what counts as one independent unit in cross-validation")
    ap.add_argument("--input", default="auto", choices=["auto", "curves", "features"])
    ap.add_argument("--model", default="auto", help="'auto' picks the best from the leaderboard")
    ap.add_argument("--out", default="models", help="output folder (or a .joblib/.pkl path)")
    ap.add_argument("--format", default="joblib", choices=["joblib", "pkl"])
    ap.add_argument("--order", type=int, default=4, help="baseline polynomial order")
    ap.add_argument("--ref-frac", type=float, default=0.35, help="internal-standard QC floor")
    ap.add_argument("--target", default="链霉素", help="what the model predicts (written into the card)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    if args.describe:
        describe(args.describe)
        return
    if not args.data:
        ap.error("--data is required (or use --describe)")

    try:
        res = train(args.data, mode=args.mode, input=args.input, model=args.model,
                    order=args.order, ref_frac=args.ref_frac, target=args.target,
                    seed=args.seed, out=args.out, fmt=args.format)
    except RuntimeError as exc:
        sys.exit(str(exc))

    for line in res["log"]:
        print(line)
    print()
    print("下一步     : python scripts/predict_with_model.py --model %s --data <新样品的文件夹>" % res["job"])


def _sklearn_version() -> str:
    try:
        import sklearn
        return sklearn.__version__
    except Exception:
        return "?"


def describe(path: str) -> None:
    p = Path(path)
    if not p.is_file():
        sys.exit("找不到模型文件：%s" % path)
    if p.suffix == ".pkl":
        with p.open("rb") as fh:
            blob = pickle.load(fh)
    else:
        import joblib
        blob = joblib.load(p)
    card = blob.get("card", {})
    print(json.dumps(card, ensure_ascii=False, indent=2))
    print()
    print("estimator :", repr(blob.get("model"))[:400])


if __name__ == "__main__":
    main()
