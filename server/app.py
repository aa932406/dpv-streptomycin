#!/usr/bin/env python3
"""
app.py -- FastAPI shell around analysis_core.py for the Next.js front end.

Every number the browser shows comes out of scripts/dump_ui_json.py, so the API
layer stays thin: no analysis logic lives here.

Run locally:
    .venv/Scripts/python.exe -m uvicorn server.app:app --port 8000

The Next.js dev/prod server proxies /api/* here (see web/next.config.ts), so the
browser never talks to this port directly and there is no CORS to configure.
"""
from __future__ import annotations

import base64
import io
import json
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT / "scripts"))

import area_calc  # noqa: E402
import cv_peaks  # noqa: E402
import dump_ui_json as dump  # noqa: E402
import predict_with_model as pm  # noqa: E402
import train_model as tm  # noqa: E402

DATA_DIR = PROJECT / "data"

app = FastAPI(title="DPV analysis API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_CACHE: dict[tuple, dict] = {}


def _folder(name: str) -> Path:
    # never let a query string walk out of data/
    p = (DATA_DIR / name).resolve()
    if not str(p).startswith(str(DATA_DIR.resolve())):
        raise HTTPException(400, "bad folder")
    if not p.is_dir():
        raise HTTPException(404, "no such folder: %s" % name)
    return p


def _stamp(p: Path) -> float:
    """Cache key: newest .cor OR the folder's own metadata.csv."""
    try:
        t = max((f.stat().st_mtime for f in p.glob("*.cor")), default=0.0)
        meta = p / "metadata.csv"
        if meta.exists():
            t = max(t, meta.stat().st_mtime)
        return t
    except OSError:
        return 0.0


def analyse(folder: str, order: int, ref_frac: float, technique: str = "auto") -> dict:
    p = _folder(folder)
    key = (folder, int(order), round(float(ref_frac), 3), technique, _stamp(p))
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    payload = dump.build(p, order=int(order), ref_frac=float(ref_frac),
                         technique=technique, with_regression=False)
    for k in list(_CACHE):
        if k[0] == folder:
            _CACHE.pop(k, None)
    _CACHE[key] = payload
    return payload


@app.get("/api/health")
def health():
    return {"ok": True, "data_dir": str(DATA_DIR)}


@app.get("/api/folders")
def folders():
    out = []
    if DATA_DIR.is_dir():
        for d in sorted(DATA_DIR.iterdir()):
            if not d.is_dir():
                continue
            n = len(list(d.glob("*.cor")))
            if n == 0:
                continue
            out.append({
                "id": d.name,
                "label": d.name,
                "n_files": n,
                "is_demo": d.name.startswith("demo"),
            })
    return {"folders": out}


META_COLS = ["file", "group", "electrode", "concentration_M", "batch", "label", "role", "note"]


@app.post("/api/metadata")
def api_save_metadata(body: dict):
    """Write data/<folder>/metadata.csv from the browser's table.

    The analysis picks this file up on the next call (it is read before the
    project-wide metadata/metadata.csv), so the user never edits CSV by hand.
    """
    import csv
    folder = body.get("folder")
    rows = body.get("rows") or []
    if not folder or not isinstance(rows, list):
        raise HTTPException(400, "need {folder, rows[]}")
    p = _folder(folder)
    target = p / "metadata.csv"
    try:
        with target.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=META_COLS, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in META_COLS})
    except OSError as exc:
        raise HTTPException(500, "cannot write %s: %s" % (target, exc))
    _CACHE.clear()
    return {"ok": True, "path": str(target), "rows": len(rows)}



def regression_payload(folder: str, order: int = 4, ref_frac: float = 0.35,
                       technique: str = "auto") -> dict:
    """Quantitative prediction models (linear vs RBF-SVR vs BP-ANN ...).

    Split from /api/analyse on purpose: the nested search takes ~15 s on a
    folder with a real concentration series, and nobody should wait for it just
    to look at the raw curves.
    """
    p = _folder(folder)
    key = ("reg", folder, int(order), round(float(ref_frac), 3), technique, _stamp(p))
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    try:
        df, curves, errors, grid, metric = dump.prepare(
            p, order=int(order), ref_frac=float(ref_frac), technique=technique)
        if not len(df):
            return {"error": "这个文件夹没有可分析的曲线"}
        out = dump._regression_block(df, curves)
        out["meta"] = {"folder": folder, "n_points": int(curves.shape[1]),
                       "metric": metric, "n_curves": int(len(df))}
    except Exception as exc:                       # noqa: BLE001
        raise HTTPException(500, "%s: %s" % (type(exc).__name__, exc))
    _CACHE[key] = out
    return out


@app.get("/api/regression")
def api_regression(
    folder: str = Query(...),
    order: int = Query(4, ge=2, le=6),
    ref_frac: float = Query(0.35, ge=0.0, le=1.0),
    technique: str = Query("auto"),
):
    return JSONResponse(regression_payload(folder, order, ref_frac, technique))


AREA_PRESETS = {"2mm": 0.0314, "3mm": 0.0707, "4mm": 0.1257}


def paper_payload(folder: str, metric: str = "", area: str = "") -> dict:
    """The Food Chem style result table (linear range / LOD / R2 / RPD ...).

    Same numbers the CLI prints, so the paper draft and the web UI can never
    disagree.  Values the data cannot support come back as the reason, not as a
    number -- a fabricated LOD is worse than a missing one.
    """
    p = _folder(folder)
    area_cm2 = None
    if area == "saved":
        saved = area_calc.load_electrode(PROJECT)
        area_cm2 = float(saved["area_cm2"]) if saved and saved.get("area_cm2") else None
    elif area not in (None, "", "none"):
        if area in AREA_PRESETS:
            area_cm2 = AREA_PRESETS[area]
        else:
            try:
                area_cm2 = float(area)
            except (TypeError, ValueError):
                raise HTTPException(400, "area must be a number in cm^2 or one of 2mm/3mm/4mm")
            if not (0.001 <= area_cm2 <= 10):
                raise HTTPException(400, "area must be between 0.001 and 10 cm^2")
    _probe = dump.prepare(p)
    if not len(_probe[0]):
        # A CV-only folder has no DPV curves.  Say that, instead of letting the
        # metric lookup fail deep inside paper_table with "metric 'ratio' is not
        # in the feature table".
        return {"folder": folder, "metric": None, "area_cm2": area_cm2,
                "rows": [], "note": "", "markdown": "",
                "error": "这个文件夹里没有可分析的 DPV 曲线，文献表要读的是 DPV 峰电流。",
                "counts": {"n_curves": 0}}
    key = ("paper", folder, metric or "auto", area_cm2, _stamp(p))
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    import paper_table as pt
    try:
        r = pt.build(str(p), metric=(metric or None), area_cm2=area_cm2)
    except Exception as exc:                       # noqa: BLE001
        raise HTTPException(500, "%s: %s" % (type(exc).__name__, exc))
    if r.get("error"):
        return {"error": r["error"]}
    rows, note = pt.to_rows(r)
    out = {
        "folder": folder,
        "metric": r.get("metric"),
        "area_cm2": r.get("area_cm2"),
        "rows": [{"item": a, "ours": b, "ref": c} for a, b, c in rows],
        "note": note,
        "markdown": pt.to_markdown(r),
        "counts": {
            "n_standards": r.get("n_standards"),
            "n_blanks": r.get("n_blanks"),
            "n_levels": r.get("n_levels"),
            "n_electrodes": r.get("n_electrodes"),
            "n_curves": r.get("n_curves"),
        },
    }
    _CACHE[key] = out
    return out


@app.get("/api/paper")
def api_paper(
    folder: str = Query(...),
    metric: str = Query(""),
    area: str = Query(""),
):
    return JSONResponse(paper_payload(folder, metric, area))


@app.get("/api/electrode")
def api_electrode_get():
    """The saved working-electrode area (metadata/electrode.json)."""
    return JSONResponse(area_calc.load_electrode(PROJECT) or {})


@app.post("/api/electrode")
async def api_electrode_post(body: dict):
    try:
        area_cm2 = float(body.get("area_cm2"))
    except (TypeError, ValueError):
        raise HTTPException(400, "need {area_cm2}")
    if not (0.0001 <= area_cm2 <= 10):
        raise HTTPException(400, "area_cm2 looks wrong (0.0001 - 10 cm^2)")
    p, doc = area_calc.save_electrode(
        PROJECT, area_cm2, model=str(body.get("model") or ""),
        method=str(body.get("method") or "randles-sevcik"),
        detail=body.get("detail") or {})
    _CACHE.clear()
    return {"ok": True, "path": str(p), "electrode": doc}


@app.post("/api/area")
async def api_area(body: dict):
    """Randles-Sevcik fit: (scan rate, peak current) pairs -> effective area."""
    pts = body.get("points") or []
    pairs = []
    for row in pts:
        try:
            pairs.append((float(row.get("v_mV_s")), float(row.get("ip_uA"))))
        except (TypeError, ValueError):
            continue
    r = area_calc.fit_area(
        pairs,
        body.get("conc_mM", 1.0),
        n=body.get("n", 1.0),
        d_cm2_s=body.get("d_cm2_s", area_calc.D_DEFAULT))
    return JSONResponse(r)


@app.get("/api/cvfiles")
def api_cvfiles(folder: str = Query(...)):
    """CV .cor files in a folder, with the peak currents already read.

    The area card used to make you type four numbers by hand out of the CHI
    window; this reads them from the files instead.  DPV/LSV traces are skipped
    (they only sweep one way and their "peak" is just the end of the sweep).
    """
    p = _folder(folder)
    out = []
    for f in sorted(p.glob("*.cor")):
        try:
            r = cv_peaks.summarise(f)
        except Exception:
            continue
        if r.get("error"):
            continue
        out.append(r)
    out.sort(key=lambda r: (r.get("scan_rate_mV_s") or 0))
    return JSONResponse({"folder": folder, "files": out})


@app.get("/api/analyse")
def api_analyse(
    folder: str = Query(...),
    order: int = Query(4, ge=2, le=6),
    ref_frac: float = Query(0.35, ge=0.0, le=1.0),
    technique: str = Query("auto"),
):
    try:
        return JSONResponse(analyse(folder, order, ref_frac, technique))
    except HTTPException:
        raise
    except Exception as exc:                       # noqa: BLE001
        raise HTTPException(500, "%s: %s" % (type(exc).__name__, exc))


# ---------------------------------------------------------------------------
# report bundle
# ---------------------------------------------------------------------------
def _png(fig) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    return buf.getvalue()


def _figures(payload: dict) -> dict[str, bytes]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    out: dict[str, bytes] = {}
    grid = np.asarray(payload["curves"]["grid"], float)

    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    for s in payload["curves"]["series"]:
        ax.plot(grid, s["mean"], lw=1.6, label=s["name"], color=s.get("color"))
    ax.invert_xaxis()
    ax.set_xlabel("E (V)")
    ax.set_ylabel("i (uA)")
    ax.set_title("Baseline-corrected DPV")
    ax.legend(fontsize=7, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    out["curves.png"] = _png(fig)
    plt.close(fig)

    pca = payload.get("pca") or {}
    if pca.get("points"):
        fig, ax = plt.subplots(figsize=(4.6, 3.8))
        seen = {}
        for p in pca["points"]:
            seen.setdefault(p["group"], []).append((p["pc1"], p["pc2"]))
        for g, pts in seen.items():
            a = np.asarray(pts)
            ax.scatter(a[:, 0], a[:, 1], s=34, label=g, alpha=0.85)
        var = pca.get("var") or [0, 0]
        ax.set_xlabel("PC1 (%.1f%%)" % (var[0] * 100))
        ax.set_ylabel("PC2 (%.1f%%)" % (var[1] * 100 if len(var) > 1 else 0))
        ax.legend(fontsize=7, frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        out["pca.png"] = _png(fig)
        plt.close(fig)

    pts = payload.get("calib_points") or []
    fit = payload.get("fit") or {}
    if pts and "error" not in fit:
        fig, ax = plt.subplots(figsize=(5.0, 3.8))
        seen = {}
        for p in pts:
            seen.setdefault(p["group"], []).append((p["logc"], p["value"]))
        for g, xy in seen.items():
            a = np.asarray(xy)
            ax.scatter(a[:, 0], a[:, 1], s=34, label=g, alpha=0.85)
        xs = np.array([p["logc"] for p in pts])
        ax.plot(xs, fit["a"] + fit["b"] * xs, color="k", lw=1.2)
        ax.set_xlabel("log10 C (M)")
        ax.set_ylabel(payload["meta"]["metric_cn"])
        ax.set_title("Calibration R2 = %.3f" % fit.get("r2", float("nan")))
        ax.legend(fontsize=7, frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        out["calibration.png"] = _png(fig)
        plt.close(fig)

    return out


def _csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    import csv
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def _html(payload: dict, figs: dict[str, bytes]) -> str:
    meta = payload["meta"]
    groups = payload.get("groups") or []
    g_rows = "".join(
        "<tr><td>%s</td><td>%d</td><td>%d</td><td>%.3f</td><td>%.3f</td><td>%s</td></tr>"
        % (g["name"], g["n"], g["n_elec"], g["mean"] or 0, g["sd"] or 0,
           "-" if g["cv_pct"] is None else "%.1f%%" % g["cv_pct"])
        for g in groups)
    imgs = "".join(
        '<div class="fig"><img src="data:image/png;base64,%s"/><div class="cap">%s</div></div>'
        % (base64.b64encode(v).decode(), k)
        for k, v in figs.items())
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>DPV 报告 %s</title><style>
body{font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif;margin:40px auto;max-width:900px;color:#101828}
h1{font-size:22px}h2{font-size:15px;margin-top:28px;border-bottom:1px solid #eaecf0;padding-bottom:6px}
table{border-collapse:collapse;width:100%%;font-size:13px}th,td{border-bottom:1px solid #f2f4f7;padding:6px 8px;text-align:left}
th{color:#667085;font-weight:500;font-size:12px}.fig{margin:16px 0}.fig img{width:100%%}
.cap{font-size:12px;color:#98a2b3;margin-top:4px}code{background:#f2f4f7;padding:1px 5px;border-radius:4px}
</style></head><body>
<h1>链霉素 DPV 检测报告</h1>
<p><code>%s</code> · %d 条曲线 · %d 支独立电极 · %d 个分组 · QC 合格 %d</p>
<h2>各条件响应</h2>
<table><tr><th>条件</th><th>曲线</th><th>电极</th><th>均值</th><th>SD</th><th>CV</th></tr>%s</table>
<h2>图</h2>%s
<p style="margin-top:32px;font-size:12px;color:#98a2b3">由 DPV 检测平台自动生成。图内文字为英文，因生成环境无中文字体。</p>
</body></html>""" % (meta["folder"], meta["folder"], meta["n_curves"], meta["n_electrodes"],
                    meta["n_groups"], meta["n_qc"], g_rows, imgs)


@app.get("/api/report")
def api_report(
    folder: str = Query(...),
    order: int = Query(4, ge=2, le=6),
    ref_frac: float = Query(0.35, ge=0.0, le=1.0),
    technique: str = Query("auto"),
):
    payload = analyse(folder, order, ref_frac, technique)
    # the model comparison is the expensive part (~13 s); a folder without a
    # concentration gradient simply gets no models.csv instead of a failed zip
    try:
        reg = regression_payload(folder, order, ref_frac, technique)
    except Exception:                              # noqa: BLE001
        reg = {"error": "regression unavailable"}
    try:
        figs = _figures(payload)
    except Exception:                              # noqa: BLE001 - a missing
        figs = {}                                  # figure must not kill the zip

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.html", _html(payload, figs))
        z.writestr("analysis.json", json.dumps(payload, ensure_ascii=False, indent=1))
        z.writestr("tables/samples.csv", _csv(payload.get("samples") or []))
        z.writestr("tables/groups.csv", _csv(payload.get("groups") or []))
        z.writestr("tables/anova.csv", _csv((payload.get("stats") or {}).get("anova") or []))
        z.writestr("tables/verdicts.csv", _csv(payload.get("verdicts") or []))
        if reg.get("models"):
            keep = ("set", "name", "r2", "rmse", "mae", "rpd", "n", "n_folds",
                    "scale", "rmse_dex", "factor", "rel_err_pct")
            models = [{k: r.get(k) for k in keep if k in r} for r in reg["models"]]
            lc = (reg.get("learning") or {}).get("points") or []
            imp = (reg.get("importance") or {}).get("rows") or []
            z.writestr("tables/models.csv", _csv(models))
            z.writestr("tables/learning_curve.csv", _csv(lc))
            z.writestr("tables/importance.csv", _csv(imp))
            z.writestr("tables/predictions.csv",
                       _csv([{"true_M": t, "pred_M": p}
                             for t, p in zip((reg.get("best_pred") or {}).get("true") or [],
                                             (reg.get("best_pred") or {}).get("pred") or [])]))
        else:
            z.writestr("tables/models.csv", "error\n" + str(reg.get("error", "")) + "\n")
        # the paper-shaped table (linear range / LOD / R2 / RPD / recovery)
        try:
            pap = paper_payload(folder, "", "")
            if pap.get("error"):
                z.writestr("tables/paper_table.md", pap["error"] + "\n")
            else:
                z.writestr("tables/paper_table.md", pap["markdown"] + "\n")
                z.writestr("tables/paper_table.csv",
                           _csv([{"item": r["item"], "ours": r["ours"], "paper": r["ref"]}
                                 for r in pap["rows"]]))
        except Exception as exc:                   # noqa: BLE001
            z.writestr("tables/paper_table.md", "unavailable: %s\n" % exc)
        for name, data in figs.items():
            z.writestr("figures/" + name, data)
        src = _folder(folder)
        for f in sorted(src.glob("*.cor")):
            z.write(f, "data/" + f.name)

    fn = "dpv_report_%s.zip" % folder
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="%s"' % fn},
    )

# --------------------------------------------------------------------- models
# The browser trains, lists, downloads and applies models through these four
# endpoints.  Nothing here is analysis logic: train_model.py / predict_with_model.py
# own it, so the CLI and the web UI can never disagree about what a model is.
MODELS_DIR = PROJECT / "models"


def _model_path(name: str) -> Path:
    """Resolve models/<name>.joblib or .pkl, refusing anything that walks out."""
    base = str(name or "").strip()
    if not base or base != Path(base).name or base.startswith("."):
        raise HTTPException(400, "bad model name")
    for ext in (".joblib", ".pkl"):
        p = (MODELS_DIR / (base + ext)).resolve()
        if str(p).startswith(str(MODELS_DIR.resolve())) and p.is_file():
            return p
    raise HTTPException(404, "no such model: %s" % base)


def _model_row(path: Path) -> dict:
    card = {}
    j = path.with_suffix(".json")
    if j.is_file():
        try:
            card = json.loads(j.read_text(encoding="utf-8"))
        except Exception:                          # noqa: BLE001
            card = {}
    cv = card.get("cv") or {}
    tr = card.get("train") or {}
    return {
        "name": path.stem,
        "file": path.name,
        "format": path.suffix.lstrip("."),
        "size_kb": round(path.stat().st_size / 1024, 1),
        "created": card.get("created"),
        "target": card.get("target"),
        "model": card.get("model"),
        "input": card.get("input"),
        "r2": cv.get("r2"),
        "rpd": cv.get("rpd"),
        "factor": cv.get("factor"),
        "n_standards": tr.get("n_standards"),
        "n_levels": tr.get("n_levels"),
        "n_units": tr.get("n_units"),
        "range_M": tr.get("range_M"),
        "has_detection": bool(card.get("detection")),
        "download": "/api/models/%s/download" % path.stem,
    }


@app.get("/api/models")
def api_models():
    rows = []
    if MODELS_DIR.is_dir():
        files = [p for p in MODELS_DIR.iterdir() if p.suffix in (".joblib", ".pkl")]
        for p in sorted(files, key=lambda q: q.stat().st_mtime, reverse=True):
            try:
                rows.append(_model_row(p))
            except OSError:
                continue
    return {"models": rows, "dir": str(MODELS_DIR)}


_JOBS: dict[str, dict] = {}


def _run_train_job(job_id: str, params: dict) -> None:
    job = _JOBS[job_id]
    try:
        res = tm.train(**params)
        job["result"] = {
            "ok": True,
            "name": res["name"],
            "job": res["job"],
            "log": res["log"],
            "download": "/api/models/%s/download" % res["name"],
            "model": _model_row(Path(res["job"])),
        }
        job["state"] = "done"
    except RuntimeError as exc:                     # "nothing to train" is not a crash
        job["state"] = "error"
        job["error"] = str(exc)
    except Exception as exc:                        # noqa: BLE001
        job["state"] = "error"
        job["error"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        job["finished"] = time.time()


@app.post("/api/train")
def api_train(body: dict):
    """Start training in the background; return a job id immediately.

    Training takes tens of seconds to minutes on a busy machine, and Next's
    rewrite proxy drops any single request that runs longer than 30 s
    ("socket hang up" -> 500).  So the work happens in a thread and the browser
    polls /api/train/{id}, whose answers are sub-second.
    """
    folder = (body.get("folder") or "").strip()
    if not folder:
        raise HTTPException(400, "need {folder}")
    _folder(folder)                                 # validates + 404s
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for k, v in list(_JOBS.items()):                # keep the registry small
        if v.get("finished") and now - v["finished"] > 3600:
            _JOBS.pop(k, None)
    job_id = uuid.uuid4().hex[:12]
    params = dict(
        data=folder,
        mode=body.get("mode") or "electrode",
        input=body.get("input") or "auto",
        model=body.get("model") or "auto",
        order=int(body.get("order") or 4),
        ref_frac=float(body.get("ref_frac") or 0.35),
        target=body.get("target") or "链霉素",
        seed=int(body.get("seed") or 0),
        out=str(MODELS_DIR),
        fmt="pkl" if body.get("format") == "pkl" else "joblib",
    )
    _JOBS[job_id] = {"id": job_id, "state": "running", "started": now, "params": params}
    threading.Thread(target=_run_train_job, args=(job_id, params), daemon=True).start()
    return {"job_id": job_id, "state": "running"}


@app.get("/api/train/{job_id}")
def api_train_status(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "no such job: %s" % job_id)
    out = {"job_id": job["id"], "state": job["state"],
           "elapsed": round(time.time() - job["started"], 1)}
    if job.get("error"):
        out["error"] = job["error"]
    if job.get("result"):
        out.update(job["result"])
    return out


@app.get("/api/models/{name}/download")
def api_model_download(name: str):
    p = _model_path(name)
    return Response(
        content=p.read_bytes(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="%s"' % p.name},
    )


@app.delete("/api/models/{name}")
def api_model_delete(name: str):
    p = _model_path(name)
    for q in (p, p.with_suffix(".json")):
        try:
            q.unlink()
        except OSError:
            pass
    return {"ok": True, "deleted": p.stem}


@app.post("/api/predict")
def api_predict(body: dict):
    """Apply a saved model to uploaded .cor files (bytes in, table out)."""
    name = (body.get("model") or "").strip()
    if not name:
        raise HTTPException(400, "need {model, files[]}")
    path = _model_path(name)
    items = []
    for f in (body.get("files") or [])[:200]:
        fn = Path(str(f.get("name") or "upload.cor")).name
        try:
            raw = base64.b64decode(f.get("b64") or "")
        except Exception:                          # noqa: BLE001
            continue
        if raw:
            items.append((fn, raw))
    if not items:
        raise HTTPException(400, "没有收到任何文件")
    try:
        res = pm.predict(path, items)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:                       # noqa: BLE001
        raise HTTPException(500, "%s: %s" % (type(exc).__name__, exc))
    card = res["card"]
    return {
        "ok": True,
        "model": _model_row(path),
        "card": card,
        "rows": res["rows"],
        "bad": res["bad"],
        "log": res["log"],
    }

