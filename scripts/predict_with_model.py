#!/usr/bin/env python3
"""
predict_with_model.py -- load a saved model and read new .cor files with it.

This is the "调用" half of the pair with train_model.py.  It rebuilds exactly the
input the model was trained on (same potential grid, same baseline order, same
feature list -- all read from the model card), so a curve measured tomorrow is
preprocessed the same way as a curve measured last month.

Usage
-----
    python scripts/predict_with_model.py --model models/demo_curves_gpr.joblib \
        --data data/demo
    python scripts/predict_with_model.py --model models/x.joblib --data path/to/new/cor
    python scripts/predict_with_model.py --model models/x.joblib --data data/demo --out out/pred.csv

The printed range is not decoration: it is 10 ** (+/- CV rmse in decades), i.e.
the spread the model actually showed when it was asked about an electrode it had
never seen.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import analysis_core as core    # noqa: E402
import ml_models as ml          # noqa: E402

PROJECT = HERE.parent


def fmt_conc(c) -> str:
    if c is None or not np.isfinite(c):
        return "—"
    for unit, scale in (("M", 1.0), ("mM", 1e-3), ("µM", 1e-6), ("nM", 1e-9), ("pM", 1e-12)):
        if c >= scale * 0.999:
            return "%.3g %s" % (c / scale, unit)
    return "%.3g pM" % (c / 1e-12)


def resolve(arg: str) -> Path:
    p = Path(arg)
    if p.is_dir():
        return p.resolve()
    for cand in (PROJECT / "data" / arg, PROJECT / arg):
        if cand.is_dir():
            return cand.resolve()
    sys.exit("找不到数据文件夹：%s" % arg)


def load_blob(path):
    """Load a model saved by train_model.py -- .joblib (joblib) or .pkl (plain pickle)."""
    p = Path(path)
    if not p.is_file():
        raise RuntimeError("找不到模型文件：%s" % path)
    if p.suffix == ".pkl":
        import pickle
        with p.open("rb") as fh:
            return pickle.load(fh)
    import joblib
    return joblib.load(p)


def predict(model_path, items, verbose: bool = False) -> dict:
    """Read raw .cor bytes with a saved model.

    items   : [(filename, bytes)] -- in memory, so the API can feed uploads.
    returns : {'card', 'rows': [...], 'bad': [{'file','error'}], 'log': [str]}
    """
    blob = load_blob(model_path)
    card = blob.get("card") or {}
    model = blob["model"]
    log = []
    if card.get("format") != "dpv-model/1":
        log.append("警告：模型卡格式是 %r，按当前版本读取" % card.get("format"))

    grid = np.asarray(card.get("grid") or [], float)
    order = int(card.get("baseline_order", 4))
    kind = card.get("input", "curves")
    keys = card.get("feature_keys") or list(ml.FEATURE_KEYS)
    cv = card.get("cv") or {}
    factor = cv.get("factor")
    det = card.get("detection") or {}
    rel = cv.get("rel_err_pct")

    rows, bad = [], []
    for name, raw in items:
        try:
            rec = core.analyse_trace(name, raw, order=order, grid=grid)
            row, y, _ = rec
            if kind == "curves":
                x = np.asarray(y, float).reshape(1, -1)
            else:
                x = np.array([[float(row.get(k, np.nan)) for k in keys]], float)
            if not np.all(np.isfinite(x)):
                raise ValueError("特征里出现 NaN（这条曲线的电位范围盖不住训练时的窗口）")
            pred = float(np.asarray(model.predict(x)).ravel()[0])
            conc = 10 ** pred if card.get("y_scale") == "log10" else pred
            if factor and np.isfinite(factor) and factor > 1:
                lo, hi = conc / factor, conc * factor
            elif rel:
                lo, hi = conc * (1 - rel / 100.0), conc * (1 + rel / 100.0)
            else:
                lo = hi = float("nan")
            # the regressor cannot say "nothing here" -- the blank distribution can
            hit = None
            if det:
                mv = float(row.get(det["metric"], np.nan))
                if np.isfinite(mv):
                    hit = bool((mv - det["cutoff"]) * det["sign"] > 0)
            rows.append({"file": name, "detected": hit, "pred_M": conc, "lo_M": lo, "hi_M": hi,
                         "group": row.get("group", ""), "I_MB": row.get("I_MB"),
                         "I_ref": row.get("I_ref"), "ratio": row.get("ratio")})
        except Exception as exc:
            bad.append({"file": name, "error": str(exc)})

    return {"card": card, "rows": rows, "bad": bad, "log": log}


def main() -> None:
    ap = argparse.ArgumentParser(description="predict new .cor files with a saved model")
    ap.add_argument("--model", required=True, help="path to a .joblib/.pkl written by train_model.py")
    ap.add_argument("--data", required=True, help="folder holding the new .cor files")
    ap.add_argument("--out", default=None, help="CSV path (default: out/predictions_<model>_<folder>.csv)")
    ap.add_argument("--show", action="store_true", help="print the model card first")
    args = ap.parse_args()

    folder = resolve(args.data)
    files = sorted(folder.glob("*.cor"))
    if not files:
        sys.exit("这个文件夹里没有 .cor 文件：%s" % folder)

    try:
        res = predict(args.model, [(f.name, f.read_bytes()) for f in files])
    except RuntimeError as exc:
        sys.exit(str(exc))
    card, rows, bad = res["card"], res["rows"], res["bad"]
    if args.show:
        import json
        print(json.dumps(card, ensure_ascii=False, indent=2))
        print()

    cv = card.get("cv") or {}
    factor = cv.get("factor")
    det = card.get("detection") or {}
    rng = card.get("train", {}).get("range_M") or [np.nan, np.nan]

    print("模型       : %s（%s / %s）" % (card.get("name", args.model), card.get("model"), card.get("input")))
    print("适用范围   : %s - %s" % (fmt_conc(rng[0]), fmt_conc(rng[1])))
    print("验证成绩   : R²=%.3f  RPD=%.2f  %s" % (
        cv.get("r2", float("nan")), cv.get("rpd", float("nan")),
        ("误差约 %.1f 倍" % factor) if factor else ""))
    print()
    if det:
        print("检出阈值   : %s 空白 %.3f ± %.3f → 判「检出」需 %s %.3f" % (
            det["metric"], det["mean"], det["sd"],
            "≥" if det["sign"] > 0 else "≤", det["cutoff"]))
    print()
    print("%-34s %8s %14s %24s" % ("文件", "判定", "预测浓度", "可能的范围"))
    for r in rows:
        if r["detected"] is False:
            print("%-34s %8s %14s %24s" % (r["file"][:34], "未检出", "—", "—"))
        else:
            print("%-34s %8s %14s %24s" % (r["file"][:34],
                                           "检出" if r["detected"] else "—",
                                           fmt_conc(r["pred_M"]),
                                           "%s - %s" % (fmt_conc(r["lo_M"]), fmt_conc(r["hi_M"]))))
    for b in bad:
        print("%-34s %14s %s" % (b["file"][:34], "失败", b["error"]))

    out = Path(args.out) if args.out else (PROJECT / "out" /
                                           ("predictions_%s_%s.csv" % (card.get("name", "model"), folder.name)))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "detected", "pred_M", "lo_M", "hi_M",
                                           "group", "I_MB", "I_ref", "ratio"])
        w.writeheader()
        w.writerows(rows)
    print()
    print("已写出     : %s（%d 条预测，%d 个失败）" % (out, len(rows), len(bad)))


if __name__ == "__main__":
    main()
