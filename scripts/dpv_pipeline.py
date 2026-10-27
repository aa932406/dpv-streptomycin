
#!/usr/bin/env python3
"""
DPV (Differential Pulse Voltammetry) analysis pipeline for CHI .cor files.

Stage 1  parse      : .cor -> tidy long table (one row per data point)
Stage 2  baseline   : iterative reweighted polynomial envelope (upper envelope)
Stage 3  features   : peak detection -> Ep, Ip, FWHM, area + curve descriptors
Stage 4  statistics : ANOVA / Tukey HSD / Kruskal-Wallis / effect sizes
Stage 5  models     : PCA, LDA, PLS-DA, RandomForest with leave-one-ELECTRODE-out CV
Stage 6  figures    : publication-style PNGs

Usage:  python dpv_pipeline.py [--data DIR] [--out DIR]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import find_peaks
from scipy import stats
from sklearn.decomposition import PCA
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.cross_decomposition import PLSRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import LeaveOneGroupOut, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import confusion_matrix, accuracy_score

# numpy 2 renamed trapz -> trapezoid; keep working on numpy 1.x too
_trapz = getattr(np, "trapezoid", None) or getattr(np, "trapz", None)

# colours for the four conditions the project was built around, plus a fallback
# cycle so that arbitrary folders (older dates use free-form Chinese filenames)
# never hit a KeyError on GROUP_COLOR[g].
PALETTE = ["#1f77b4", "#2ca02c", "#d62728", "#9467bd", "#ff7f0e", "#8c564b",
           "#e377c2", "#17becf", "#bcbd22", "#7f7f7f"]


def group_color(g, i=0):
    return GROUP_COLOR.get(g) or PALETTE[i % len(PALETTE)]


def setup_fonts():
    """Pick a CJK-capable font when one exists, so Chinese labels are not tofu.

    The Linux container has no CJK font, so the web UI keeps figure text ASCII.
    On a Chinese Windows box this switches matplotlib to Microsoft YaHei.
    """
    from matplotlib import font_manager
    try:
        have = {f.name for f in font_manager.fontManager.ttflist}
    except Exception:
        have = set()
    for name in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC",
                 "Source Han Sans SC", "WenQuanYi Zen Hei", "PingFang SC"):
        if name in have:
            plt.rcParams["font.sans-serif"] = [name] + list(plt.rcParams.get("font.sans-serif", []))
            break
    plt.rcParams["axes.unicode_minus"] = False

# --- Windows console safety -------------------------------------------------
# Chinese .cor filenames are printed; a cp1252/cp437 console would crash the run
# with UnicodeEncodeError halfway through.  Never let that happen.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def default_out_dir(data_dir: Path) -> Path:
    """out/<date> when the data came from data/<date>/, else out/."""
    if data_dir.name in (".", "data", ""):
        return Path("out")
    return Path("out") / data_dir.name


def auto_data_dir(explicit=None) -> Path:
    """Locate the folder holding the .cor files.

    Accepted forms of --data:
        20261010              a date folder under data/
        data/20261010         an explicit path
        <any folder>          used as-is

    Without --data: the NEWEST data/<date>/ that contains .cor files, then
    data/ itself, then the current folder.  So as you add 20261105/, the
    pipeline picks it up automatically without touching any argument.
    """
    if explicit:
        p = Path(explicit)
        if p.is_dir():
            return p
        alt = Path("data") / explicit
        if alt.is_dir():
            return alt
        raise SystemExit(f"--data {explicit!r}: no such folder "
                         f"(tried {p.resolve()} and {alt.resolve()})")

    data = Path("data")
    if data.is_dir():
        dated = sorted(d for d in data.iterdir()
                       if d.is_dir() and any(d.glob("*.cor")))
        if dated:
            return dated[-1]                       # newest date folder
        if any(data.glob("*.cor")):
            return data
    if any(Path(".").glob("*.cor")):
        return Path(".")
    raise SystemExit(
        "no .cor files found.\n"
        "Expected data/<date>/*.cor, e.g. data/20261010/.\n"
        "Point somewhere else with:  --data <folder>")

# ----------------------------------------------------------------------------
# Stage 1: parse
# ----------------------------------------------------------------------------
def parse_cor_bytes(fname: str, raw: bytes) -> dict:
    txt = raw.decode("latin-1")                 # .cor is ASCII + GBK in path fields
    lines = txt.splitlines()

    parms = {}
    for line in lines:
        if line.startswith("ExpParmas:"):
            for kv in line[len("ExpParmas:"):].split("&-&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    parms[k] = v
            break

    m = re.search(r"Data:\s*(\S+)\s*Time:\s*(\S+)", txt)
    date, time = (m.group(1), m.group(2)) if m else ("", "")

    m = re.search(r"Open Circuit Potential \(V\):\s*(\S+)", txt)
    ocp = float(m.group(1)) if m else np.nan

    etype = next((l.strip() for l in lines if l.startswith("ID_")), "")

    hdr = next((i for i, l in enumerate(lines) if l.startswith("E(V)")), None)
    # A few CHI exports are saved as plain two-column text with no header at all
    # (no CORRW line, no ID_, no "E(V)" row) -- two such traces sat in
    # data/20260625 and were thrown away as "no data rows", which was wrong:
    # the numbers are all there.  Fall back to reading every numeric pair.
    body = lines[hdr + 1:] if hdr is not None else lines
    rows = []
    for line in body:
        parts = line.replace("\t", " ").split()
        if len(parts) < 2:
            continue
        try:
            e, i = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        t = float(parts[2]) if len(parts) > 2 else np.nan
        rows.append((e, i, t))

    # a few exported files hold a header and no data rows at all; arr[:, 0] on an
    # empty 1-D array raised "IndexError: too many indices" and killed the run
    arr = np.array(rows, dtype=float).reshape(-1, 3) if rows else np.zeros((0, 3))
    # header-less data cannot name its technique; "plain" is treated as DPV
    # downstream (see analysis_core.tech_key) but stays visible in the UI
    technique = technique_of(etype) if (hdr is not None or not rows) else "plain"
    return dict(file=fname, etype=etype, technique=technique,
                header=hdr is not None,
                date=date, time=time, ocp=ocp, parms=parms,
                E=arr[:, 0], I=arr[:, 1], T=arr[:, 2])


def parse_cor(path) -> dict:
    # accept str too: callers often pass a glob() result straight in
    path = Path(path)
    return parse_cor_bytes(path.name, path.read_bytes())

# Fallback axis for a single trace: 0.80 -> -0.78 V, 20 mV step.  Real datasets
# get their own axis from common_grid(), because the scan window changes a lot
# between dates (0.6/-0.6, 0.5/-0.5, 0.3/-0.3, 0.45/-0.3 ...).
GRID = np.round(np.arange(0.80, -0.7801, -0.02), 4)

GROUP_ORDER = ["material", "material+MB", "target_noEnz", "target+Enz"]
GROUP_COLOR = {"material": "#1f77b4", "material+MB": "#2ca02c",
               "target_noEnz": "#d62728", "target+Enz": "#9467bd"}


def group_colors(names):
    """One stable colour per group name, shared by the web UI and matplotlib.

    Only the four conditions the project was designed around have a fixed
    colour.  Every other folder uses free-form group names (older dates carry
    Chinese filenames), so those take the palette in order of appearance while
    skipping the colours the canonical conditions already own -- otherwise two
    groups can end up identical, which is exactly what happened before.
    """
    seen = []
    for g in names:
        g = str(g)
        if g not in seen:
            seen.append(g)
    used = {GROUP_COLOR[g] for g in seen if g in GROUP_COLOR}
    free = [c for c in PALETTE if c not in used] or list(PALETTE)
    out, k = {}, 0
    for g in seen:
        if g in GROUP_COLOR:
            out[g] = GROUP_COLOR[g]
        else:
            out[g] = free[k % len(free)]
            k += 1
    return out

# CHI writes the experiment type into an ID_ line
TECHNIQUE = {
    "ID_DiffPulseVA": "DPV",
    "ID_DPVStripping": "DPV-stripping",
    "ID_SquarewaveVA": "SWV",
    "ID_SWVStripping": "SWV-stripping",
    "ID_CV": "CV",
}
# techniques that give peak-shaped curves this pipeline can baseline-correct
PEAK_TECHNIQUES = ("DPV", "DPV-stripping", "SWV", "SWV-stripping")


def technique_of(etype: str) -> str:
    return TECHNIQUE.get(etype, "unknown")


def select_window(recs, eps: float = 1e-9, tol: float = None):
    """Pick the potential window shared by the LARGEST number of traces.

    Older folders mix scan windows freely (0.3/-0.3 next to 1.5/-0.2 in the same
    folder).  A plain intersection of everything then collapses to a few dozen
    millivolts and every peak falls outside it, so the peaks silently came out
    as 0.  Instead: try each trace's own window, keep the one that the most
    traces fully cover, and analyse only those traces.

    tol is how far short of that window a trace may fall and still count as
    covering it; it defaults to half the median sampling step.  With the old
    eps=1e-9 a trace ending at 0.799 V instead of 0.800 V (1 mV, one twentieth
    of a step) was thrown out as "outside the shared window" even though it
    covered the whole thing -- 材料10uM.MB-CV.cor died that way.
    """
    bounds, steps = [], []
    for r in recs:
        E = np.asarray(r["E"], dtype=float)
        E = E[np.isfinite(E)]
        if E.size >= 2:
            bounds.append((float(E.min()), float(E.max()), r))
            d = np.abs(np.diff(E))
            d = d[d > 0]
            if d.size:
                steps.append(float(np.median(d)))
    if not bounds:
        return None, None, list(recs)
    if tol is None:
        tol = max(eps, 0.5 * float(np.median(steps))) if steps else eps
    best = None
    for lo, hi, _ in bounds:
        if hi - lo <= eps:
            continue
        kept = [r for l2, h2, r in bounds if l2 <= lo + tol and h2 >= hi - tol]
        key = (len(kept), round(hi - lo, 6))
        if best is None or key > best[0]:
            best = (key, lo, hi, kept)
    if best is None:
        lo = max(b[0] for b in bounds)
        hi = min(b[1] for b in bounds)
        return lo, hi, list(recs)
    _, lo, hi, kept = best
    return lo, hi, kept


def common_grid(recs, n_max: int = 240, min_points: int = 8, window=None):
    """Shared potential axis = the OVERLAP of every trace.

    The old code interpolated everything onto a fixed 0.80..-0.78 grid.  For a
    0.6..-0.6 scan np.interp silently clamps outside the data, so both ends of
    the curve became flat plateaus, the "peaks" moved and Q / I_start / I_end
    were nonsense.  Taking the intersection means no trace is ever extrapolated.
    """
    los, his, steps = [], [], []
    for r in recs:
        E = np.asarray(r["E"], dtype=float)
        E = E[np.isfinite(E)]
        if E.size < 2:
            continue
        los.append(float(E.min()))
        his.append(float(E.max()))
        d = np.abs(np.diff(E))
        d = d[d > 0]
        if d.size:
            steps.append(float(np.median(d)))
    if not los:
        return GRID.copy()
    if window is not None:
        lo, hi = float(window[0]), float(window[1])
    else:
        lo, hi = max(los), min(his)
        if hi <= lo:                  # no common window: fall back to the union
            lo, hi = min(los), max(his)
    step = float(np.median(steps)) if steps else 0.02
    if not np.isfinite(step) or step <= 0:
        step = 0.02
    n = int(np.floor((hi - lo) / step + 1e-6)) + 1   # 1e-6: 0.02 is not exact in binary
    n = max(min_points, min(n, n_max))
    return np.round(np.linspace(hi, lo, n), 6)


_RESTART = re.compile(r"(?:_ReStart\d*)+$")
# trailing experiment tag, e.g. "材料 dpv", "G1 swv溶出", "10-0.5dpv"
_TECH_TAG = re.compile(r"[\s_\-]*(?:dpv\d*|dpvt|dpv反|swv\w*|cv\w*|wv|s|r|t|溶出)$", re.I)


def _stem(fname: str) -> str:
    return _RESTART.sub("", fname.rsplit(".", 1)[0])


def clean_label(stem: str) -> str:
    """Drop trailing experiment tags so repeats of one sample share a group."""
    lab = stem.strip()
    for _ in range(3):
        new = _TECH_TAG.sub("", lab).strip(" _-")
        if not new or new == lab:
            break
        lab = new
    return lab or stem


def group_of(fname: str) -> str:
    """Condition label.  Known 2026-10-10 names map to the four study groups;
    anything else falls back to the cleaned file name, so an arbitrary older
    folder still gets one group per sample instead of a single 'unknown'."""
    b = _stem(fname)
    if b.startswith("材料10uM"):   return "material+MB"
    if b.startswith("材料"):       return "material"
    if b.startswith("靶标、无酶"):  return "target_noEnz"
    if b.startswith("靶标、酶"):    return "target+Enz"
    return clean_label(b)


def electrode_of(fname: str) -> str:
    return _stem(fname)

# ----------------------------------------------------------------------------
# Stage 2: baseline (iterative reweighted polynomial -> upper envelope)
# ----------------------------------------------------------------------------
def baseline_envelope(x, y, order=4, iters=12, keep=0.70):
    w = np.ones_like(y)
    b = np.zeros_like(y)
    for _ in range(iters):
        coef = np.polyfit(x, y, order, w=w)
        b = np.polyval(coef, x)
        r = y - b
        thr = np.quantile(r, 1.0 - keep)
        w = np.where(r > thr, 1.0, 1e-3)
    return b

def resample(E, I, grid):
    """Interpolate one trace onto the shared axis.

    NaN-safe and duplicate-E-safe: CHI occasionally writes two samples at the
    same potential, and np.interp then returns the last one unpredictably.
    """
    E = np.asarray(E, dtype=float)
    I = np.asarray(I, dtype=float)
    ok = np.isfinite(E) & np.isfinite(I)
    E, I = E[ok], I[ok]
    if E.size < 2:
        return np.full(len(grid), np.nan)
    order = np.argsort(E)
    E, I = E[order], I[order]
    keep = np.concatenate(([True], np.diff(E) > 0))
    return np.interp(grid, E[keep], I[keep])

# ----------------------------------------------------------------------------
# Stage 3: features
# ----------------------------------------------------------------------------
def extract_features(grid, Icorr, Iraw, ocp, parms):
    feats = {"ocp": ocp}
    # two expected windows: anodic ~ +0.2..+0.55 ; cathodic ~ -0.15..-0.65
    windows = {"anodic": (0.15, 0.60), "cathodic": (-0.65, -0.15)}
    for name, (lo, hi) in windows.items():
        sel = (grid >= lo) & (grid <= hi)
        xs, ys = grid[sel], Icorr[sel]
        if len(xs) < 5:
            feats[f"{name}_H"] = 0.0
            feats[f"{name}_Ep"] = np.nan
            feats[f"{name}_W"] = np.nan
            feats[f"{name}_A"] = 0.0
            continue
        if not np.all(np.isfinite(ys)):
            feats[f"{name}_H"] = 0.0
            feats[f"{name}_Ep"] = np.nan
            feats[f"{name}_W"] = np.nan
            feats[f"{name}_A"] = 0.0
            continue
        peaks, props = find_peaks(ys, prominence=0.05, width=1)
        if len(peaks) == 0:
            feats[f"{name}_H"] = 0.0
            feats[f"{name}_Ep"] = np.nan
            feats[f"{name}_W"] = np.nan
            feats[f"{name}_A"] = 0.0
            continue
        k = peaks[np.argmax(ys[peaks])]
        feats[f"{name}_H"] = float(ys[k])
        feats[f"{name}_Ep"] = float(xs[k])
        feats[f"{name}_W"] = float(props["widths"][np.argmax(ys[peaks])] * abs(grid[1] - grid[0]))
        # area by trapezoid above 0 in the window
        feats[f"{name}_A"] = float(_trapz(np.clip(ys, 0, None), xs))
    feats["Q"] = float(_trapz(np.abs(Iraw), grid))
    feats["I_start"] = float(Iraw[0])
    feats["I_end"] = float(Iraw[-1])
    feats["I_mid"] = float(Iraw[len(Iraw) // 2])
    for k in ("Amplitude", "IncE", "PulseWidth", "PulsePeriod"):
        feats[k] = float(parms.get(k, "nan")) if parms.get(k, "nan") not in ("", "nan") else np.nan
    return feats

# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None,
                    help="folder with the .cor files (default: ./data if present, else .)")
    ap.add_argument("--out", default=None,
                    help="output folder (default: out/<date>)")
    ap.add_argument("--technique", default="auto",
                    choices=["auto", "DPV", "DPV-stripping", "SWV", "SWV-stripping", "all"],
                    help="which technique to analyse (default: auto = the most common "
                         "peak-shaped one, normally DPV)")
    args = ap.parse_args()

    data_dir = auto_data_dir(args.data)
    out = Path(args.out) if args.out else default_out_dir(data_dir)
    out.mkdir(parents=True, exist_ok=True)
    figdir = out / "figures"; figdir.mkdir(exist_ok=True)

    files = sorted(data_dir.glob("*.cor"))
    if not files:
        sys.exit(f"no .cor files found in {data_dir.resolve()} -- pass --data <folder>")

    recs = [parse_cor(f) for f in files]
    good = [r for r in recs if len(r["E"]) >= 5]
    empty = [r["file"] for r in recs if len(r["E"]) < 5]
    print(f"data dir: {data_dir.resolve()}")
    print(f"parsed {len(recs)} files, {len(good)} with data"
          + (f", {len(empty)} empty/unreadable" if empty else ""))
    for f in empty[:10]:
        print(f"  skipped (no data rows): {f}")
    if len(empty) > 10:
        print(f"  ... and {len(empty) - 10} more")

    tech_counts = {}
    for r in good:
        tech_counts[r["technique"]] = tech_counts.get(r["technique"], 0) + 1
    print("techniques:", ", ".join(f"{k}={v}" for k, v in
                                   sorted(tech_counts.items(), key=lambda kv: -kv[1])))

    if args.technique == "auto":
        # DPV is what this project is built on; only fall back to another
        # peak-shaped technique when a folder has no DPV at all.
        order = ["DPV", "DPV-stripping", "SWV", "SWV-stripping"]
        have = [x for x in order if tech_counts.get(x, 0) >= 2]
        tech = have[0] if have else None
        if tech:
            others = ", ".join(f"{k}={v}" for k, v in tech_counts.items() if k != tech)
            print(f"analysing {tech}" + (f"  (also present: {others})" if others else "")
                  + "  -- use --technique to override")
    elif args.technique == "all":
        tech = None
        print("analysing every technique together -- peak currents are NOT comparable "
              "across techniques, use this only to look at the shapes")
    else:
        tech = args.technique
        print(f"analysing {tech}")

    # A header-less CHI export cannot name its technique, so it is recorded as
    # "plain"; those files are DPV scans and must not be dropped when the folder
    # is analysed as DPV (20260625 lost 2 good curves this way).
    TECH_ALIAS = {"plain": "DPV"}
    sel = [r for r in good
           if tech is None or TECH_ALIAS.get(r["technique"], r["technique"]) == tech]
    if len(sel) < 2:
        sys.exit(f"not enough {tech or ''} traces to analyse: got {len(sel)} in "
                 f"{data_dir.resolve()}. Techniques present: {tech_counts}")

    n_before = len(sel)
    lo, hi, sel = select_window(sel)
    if len(sel) < n_before:
        print(f"window selection: kept {len(sel)}/{n_before} traces that share "
              f"{hi:+.3f} -> {lo:+.3f} V (the rest were scanned over a different range)")
    grid = common_grid(sel, window=(lo, hi))
    print(f"common axis: {grid[0]:+.3f} -> {grid[-1]:+.3f} V, {len(grid)} points "
          f"(step {abs(grid[1] - grid[0]) * 1000:.1f} mV)")
    if len(sel) < 2:
        sys.exit("no two traces share a usable potential window -- check the .cor files")

    long_rows, feat_rows, curves = [], [], []
    for r in sel:
        grp, elec = group_of(r["file"]), electrode_of(r["file"])
        I = resample(r["E"], r["I"], grid)
        base = baseline_envelope(grid, I)
        Icorr = (base - I) * 1e6                    # uA, positive = peak
        for e, i, b, c in zip(grid, I * 1e6, base * 1e6, Icorr):
            long_rows.append(dict(file=r["file"], group=grp, electrode=elec,
                                  date=r["date"], time=r["time"],
                                  E_V=round(float(e), 4), I_uA=round(float(i), 5),
                                  baseline_uA=round(float(b), 5),
                                  I_corr_uA=round(float(c), 5)))
        f = extract_features(grid, Icorr, I, r["ocp"], r["parms"])
        f.update(file=r["file"], group=grp, electrode=elec, technique=r["technique"],
                 date=r["date"], time=r["time"])
        feat_rows.append(f)
        curves.append(Icorr)

    long_df = pd.DataFrame(long_rows)
    feat_df = pd.DataFrame(feat_rows)
    long_df.to_csv(out / "dpv_long.csv", index=False)
    feat_df.to_csv(out / "dpv_features.csv", index=False)
    print(f"long table  {long_df.shape} -> dpv_long.csv")
    print(f"features    {feat_df.shape} -> dpv_features.csv")

    # ---- conditions --------------------------------------------------------
    present = list(dict.fromkeys(feat_df.group))
    labels = [g for g in GROUP_ORDER if g in present] + \
             [g for g in present if g not in GROUP_ORDER]
    groups = [feat_df[feat_df.group == g] for g in labels]
    color = {g: group_color(g, i) for i, g in enumerate(labels)}
    report = {"n_traces": len(feat_df), "n_files": len(recs), "technique": tech or "all",
              "axis": {"from": float(grid[0]), "to": float(grid[-1]), "n": int(len(grid))},
              "groups": {}}

    def _mean_sd(v):
        v = np.asarray(v, dtype=float)
        v = v[np.isfinite(v)]
        if v.size == 0:
            return float("nan"), float("nan")
        return float(v.mean()), (float(v.std(ddof=1)) if v.size > 1 else 0.0)

    for g, sub in zip(labels, groups):
        report["groups"][g] = {
            "n_traces": int(len(sub)),
            "n_electrodes": int(sub.electrode.nunique()),
            "anodic_H": list(_mean_sd(sub.anodic_H)),
            "cathodic_H": list(_mean_sd(sub.cathodic_H)),
            "cathodic_Ep": [float(sub.cathodic_Ep.mean(skipna=True))],
        }

    # ---- statistics --------------------------------------------------------
    stat_block = {}
    for feat in ["anodic_H", "cathodic_H", "Q", "ocp"]:
        vals = [sub[feat].dropna().values for sub in groups]
        vals = [v for v in vals if len(v) >= 2]      # f_oneway needs >= 2 per group
        if len(vals) < 2:
            stat_block[feat] = {"skipped": "needs at least 2 conditions with 2+ traces each"}
            continue
        grand = np.concatenate(vals)
        if not np.isfinite(grand).all() or grand.std() == 0:
            stat_block[feat] = {"skipped": "the value is constant across every trace"}
            continue
        F, p = stats.f_oneway(*vals)
        try:
            H, pk = stats.kruskal(*vals)
        except Exception:
            H, pk = float("nan"), float("nan")
        ssb = sum(len(v) * (v.mean() - grand.mean()) ** 2 for v in vals)
        ssw = sum(((v - v.mean()) ** 2).sum() for v in vals)
        eta2 = ssb / (ssb + ssw) if (ssb + ssw) > 0 else float("nan")
        try:
            tuk = stats.tukey_hsd(*vals)
            pairs = {}
            for a in range(len(vals)):
                for b in range(a + 1, len(vals)):
                    pairs[f"cond{a + 1} vs cond{b + 1}"] = {
                        "p": float(tuk.pvalue[a, b]),
                        "diff": float(vals[a].mean() - vals[b].mean()),
                    }
        except Exception:
            pairs = {}
        stat_block[feat] = {"F": float(F), "p_anova": float(p),
                            "H": float(H), "p_kruskal": float(pk),
                            "eta2": float(eta2), "tukey": pairs}
    report["statistics"] = stat_block

    # ---- PCA ---------------------------------------------------------------
    X = np.vstack(curves)
    Xs = StandardScaler().fit_transform(X)
    n_comp = max(2, min(5, X.shape[0] - 1, X.shape[1]))
    pca = PCA(n_components=n_comp).fit(Xs)
    scores = pca.transform(Xs)
    report["pca_explained_var"] = [float(v) for v in pca.explained_variance_ratio_]

    # ---- models with leave-one-electrode-out CV ----------------------------
    feat_cols = ["anodic_H", "anodic_Ep", "anodic_W", "cathodic_H",
                 "cathodic_Ep", "cathodic_W", "Q", "ocp", "I_start", "I_end"]
    M = feat_df[feat_cols].copy()
    M = M.fillna(M.median()).fillna(0.0)
    y = feat_df.group.values
    grp_id = feat_df.electrode.values
    logo = LeaveOneGroupOut()

    model_report = {}
    models = {
        "LDA":  make_pipeline(StandardScaler(), LinearDiscriminantAnalysis()),
        "RF":   make_pipeline(StandardScaler(), RandomForestClassifier(n_estimators=500, random_state=0)),
    }
    if len(labels) >= 2 and len(np.unique(grp_id)) >= 2:
        for name, mdl in models.items():
            try:
                pred = cross_val_predict(mdl, M, y, groups=grp_id, cv=logo)
                model_report[name] = {
                    "accuracy_LOEO": float(accuracy_score(y, pred)),
                    "confusion": confusion_matrix(y, pred, labels=labels).tolist(),
                    "labels": labels,
                    "n_splits": int(logo.get_n_splits(M, y, grp_id)),
                }
            except Exception as e:
                model_report[name] = {"error": str(e)}
    else:
        for name in models:
            model_report[name] = {"skipped": "needs >= 2 conditions and >= 2 independent electrodes"}
    report["models_leave_one_electrode_out"] = model_report

    # feature importance (fit on everything: descriptive only)
    try:
        if len(labels) >= 2:
            rf = RandomForestClassifier(n_estimators=1000, random_state=0).fit(M.values, y)
            report["feature_importance_rf"] = dict(sorted(
                zip(feat_cols, [float(v) for v in rf.feature_importances_]),
                key=lambda kv: -kv[1]))
        else:
            report["feature_importance_rf"] = {"skipped": "only one condition"}
    except Exception as e:
        report["feature_importance_rf"] = {"error": str(e)}

    with open(out / "report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    # ---- figures -----------------------------------------------------------
    setup_fonts()
    plt.rcParams.update({"figure.dpi": 160, "font.size": 9,
                         "axes.spines.top": False, "axes.spines.right": False})

    # fig1 raw curves -- one panel per condition, however many there are
    ncol = min(3, len(labels))
    nrow = int(np.ceil(len(labels) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(3.1 * ncol, 2.6 * nrow + 0.6),
                             sharex=True, sharey=True, squeeze=False)
    flat = axes.ravel()
    for ax, g in zip(flat, labels):
        for _, row in long_df[long_df.group == g].groupby("file"):
            ax.plot(row.E_V, row.I_uA, lw=1, color=color[g], alpha=0.75)
        ax.set_title(g, fontsize=8.5, color=color[g])
        ax.axhline(0, color="0.85", lw=0.5)
    for ax in flat[len(labels):]:
        ax.set_visible(False)
    for ax in axes[-1]:
        ax.set_xlabel("E (V vs reference)")
    for ax in axes[:, 0]:
        ax.set_ylabel("I (uA)")
    fig.suptitle("Raw traces by condition (%s)" % (tech or "all"), y=0.995)
    fig.tight_layout()
    fig.savefig(figdir / "fig1_raw_traces.png"); plt.close(fig)

    # fig2 mean +- sd
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for g in labels:
        sub = long_df[long_df.group == g]
        piv = sub.pivot_table(index="E_V", columns="file", values="I_uA")
        m, s = piv.mean(axis=1), piv.std(axis=1, ddof=1)
        ax.fill_between(m.index, m - s, m + s, color=color[g], alpha=0.18, lw=0)
        ax.plot(m.index, m.values, color=color[g], lw=2, label=g)
    ax.set_xlabel("E (V vs reference)"); ax.set_ylabel("I (uA)")
    ax.legend(frameon=False, fontsize=7)
    ax.set_title("Mean trace +/- 1 SD")
    fig.tight_layout(); fig.savefig(figdir / "fig2_mean_sd.png"); plt.close(fig)

    # fig3 baseline-corrected mean
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for g in labels:
        sub = long_df[long_df.group == g]
        piv = sub.pivot_table(index="E_V", columns="file", values="I_corr_uA")
        m = piv.mean(axis=1)
        ax.plot(m.index, m.values, color=color[g], lw=2, label=g)
    ax.axhline(0, color="0.7", lw=0.6)
    ax.set_xlabel("E (V vs reference)"); ax.set_ylabel("I - baseline (uA)")
    ax.legend(frameon=False, fontsize=7)
    ax.set_title("Baseline-corrected (peak current positive)")
    fig.tight_layout(); fig.savefig(figdir / "fig3_baseline_corrected.png"); plt.close(fig)

    # fig4 peak height strip plot
    fig, axs = plt.subplots(1, 2, figsize=(max(6.0, 1.5 * len(labels) + 2), 4.2))
    for ax, col, ttl in zip(axs, ["anodic_H", "cathodic_H"],
                            ["Anodic peak H (~+0.35 V)", "Cathodic peak H (~-0.36 V)"]):
        rng = np.random.RandomState(0)
        for i, g in enumerate(labels):
            v = feat_df[feat_df.group == g][col].dropna().values
            if v.size == 0:
                continue
            jit = (rng.rand(len(v)) - 0.5) * 0.28
            ax.scatter(np.full(len(v), i) + jit, v, s=26, color=color[g],
                       edgecolor="k", linewidth=0.4, zorder=3)
            if v.size > 1:
                m, s = v.mean(), v.std(ddof=1)
                ax.plot([i - 0.28, i + 0.28], [m] * 2, "k-", lw=2)
                ax.plot([i - 0.28, i + 0.28], [m + s] * 2, "k-", lw=0.8)
                ax.plot([i - 0.28, i + 0.28], [m - s] * 2, "k-", lw=0.8)
                ax.plot([i, i], [m - s, m + s], "k-", lw=0.8)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, fontsize=6.5, rotation=40, ha="right")
        ax.set_ylabel("peak height (uA)"); ax.set_title(ttl, fontsize=9)
    fig.tight_layout(); fig.savefig(figdir / "fig4_peak_heights.png"); plt.close(fig)

    # fig5 PCA
    fig, ax = plt.subplots(figsize=(5.6, 4.8))
    for g in labels:
        m = feat_df.group.values == g
        ax.scatter(scores[m, 0], scores[m, 1], s=42, color=color[g],
                   edgecolor="k", linewidth=0.5, label=g)
    ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]*100:.0f}%)")
    ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]*100:.0f}%)")
    ax.legend(frameon=False, fontsize=7)
    ax.set_title("PCA of baseline-corrected curves")
    fig.tight_layout(); fig.savefig(figdir / "fig5_pca.png"); plt.close(fig)

    # fig6 LDA discriminant space (needs >= 2 conditions AND more samples than
    # classes -- LDA raises "The number of samples must be more than the number
    # of classes", which used to crash the whole run on folders like data/demo)
    if len(labels) >= 2 and len(y) > len(labels):
        n_ld = min(2, len(labels) - 1)
        lda = make_pipeline(StandardScaler(), LinearDiscriminantAnalysis(n_components=n_ld))
        Z = None
        try:
            Z = lda.fit_transform(M, y)
        except Exception as exc:               # noqa: BLE001
            print(f"LDA discriminant plot skipped: {exc}")
        if Z is not None:
            fig, ax = plt.subplots(figsize=(5.8, 4.8))
            for g in labels:
                m = y == g
                ax.scatter(Z[m, 0], Z[m, 1] if n_ld > 1 else np.zeros(m.sum()),
                           s=42, color=color[g], edgecolor="k", linewidth=0.5, label=g)
            ax.set_xlabel("LD1")
            ax.set_ylabel("LD2" if n_ld > 1 else "")
            ax.legend(frameon=False, fontsize=7)
            acc = model_report.get("LDA", {}).get("accuracy_LOEO")
            ax.set_title("LDA discriminant space" +
                         (f" (LOEO acc = {acc:.0%})" if acc is not None else ""))
            fig.tight_layout(); fig.savefig(figdir / "fig6_lda.png"); plt.close(fig)

    print("\n--- summary ---")
    for g in labels:
        s = report["groups"][g]
        print(f"{g[:22]:22s} n={s['n_traces']:3d} elec={s['n_electrodes']}  "
              f"H_anodic={s['anodic_H'][0]:.2f}+-{s['anodic_H'][1]:.2f}  "
              f"H_cathodic={s['cathodic_H'][0]:.2f}+-{s['cathodic_H'][1]:.2f}")
    for k, v in stat_block.items():
        if "skipped" in v:
            print(f"{k:12s} skipped -- {v['skipped']}")
        else:
            print(f"{k:12s} ANOVA F={v['F']:.2f} p={v['p_anova']:.2e} eta2={v['eta2']:.3f} "
                  f"| Kruskal p={v['p_kruskal']:.2e}")
    print("PCA var:", [f"{v*100:.1f}%" for v in report["pca_explained_var"]])
    for k, v in model_report.items():
        if "accuracy_LOEO" in v:
            print(f"{k:4s} LOEO accuracy = {v['accuracy_LOEO']:.1%}  ({v['n_splits']} folds)")
        elif "skipped" in v:
            print(f"{k:4s} skipped -- {v['skipped']}")
    fi = report.get("feature_importance_rf", {})
    if fi and "error" not in fi and "skipped" not in fi:
        print("RF feature importance:", ", ".join(f"{k}={v:.2f}" for k, v in list(fi.items())[:5]))
    print("figures ->", figdir)


if __name__ == "__main__":
    main()
