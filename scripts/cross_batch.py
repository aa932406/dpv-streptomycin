"""Pool every data/<date>/ folder and answer the questions a single folder cannot.

1. Where does the spread come from -- batch, condition, electrode, repeat scan?
2. Within-electrode repeatability vs between-electrode reproducibility.
3. Does a "streptomycin present" rule survive a batch it was never trained on?
4. What changes when a bare/material-only electrode is counted as a negative
   control (it has no H1/H2 hairpin, so it is not one)?

Run:  python scripts/cross_batch.py
      python scripts/cross_batch.py --data data --out out/cross_batch
"""
import argparse
import json
import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dpv_pipeline import (group_of, electrode_of, PEAK_TECHNIQUES,   # noqa: E402
                          setup_fonts)
from analysis_core import build_table, add_qc, FEATURES               # noqa: E402

SKIP_FOLDERS = {"demo"}


# ---------------------------------------------------------------------------
# 1. load every folder
# ---------------------------------------------------------------------------
def load_all(data_root: Path, verbose=True):
    rows, folder_info = [], []
    for folder in sorted(p for p in data_root.iterdir() if p.is_dir()):
        if folder.name in SKIP_FOLDERS:
            continue
        files = sorted(f for f in folder.iterdir()
                       if f.is_file() and f.suffix.lower() == ".cor")
        if not files:
            continue
        items = [(f.name, f.read_bytes()) for f in files]
        df, curves, errors, grid = build_table(items)
        if df.empty:
            folder_info.append({"folder": folder.name, "files": len(files),
                                "curves": 0, "note": "nothing parsed"})
            continue
        df = df[df["technique"].isin(PEAK_TECHNIQUES)].copy()
        if df.empty:
            folder_info.append({"folder": folder.name, "files": len(files),
                                "curves": 0, "note": "no DPV/SWV traces"})
            continue
        df["folder"] = folder.name
        df["group"] = [group_of(f) for f in df["file"]]
        df["electrode"] = [electrode_of(f) for f in df["file"]]
        df = add_qc(df)
        # The absolute 1.0 uA gate is calibrated on 20261010, where I_ref runs
        # 2-3 uA.  I_ref itself differs ~7x between batches, so an absolute
        # threshold throws away whole folders.  Use a batch-relative gate for
        # the pooled view: keep a strip whose reference peak is at least a third
        # of that day's median.
        ref = pd.to_numeric(df["I_ref"], errors="coerce")
        med = ref[df["ref_win_ok"].astype(bool)].median() if "ref_win_ok" in df else np.nan
        rel_ok = (~df["ref_win_ok"].astype(bool)) if "ref_win_ok" in df else pd.Series(True, index=df.index)
        if np.isfinite(med) and med > 0:
            rel_ok = rel_ok | (ref >= 0.35 * med)
        df["qc_rel"] = rel_ok.fillna(True).astype(bool)
        rows.append(df)
        folder_info.append({"folder": folder.name, "files": len(files),
                            "curves": int(len(df)),
                            "electrodes": int(df.groupby(["group", "electrode"]).ngroups),
                            "groups": int(df["group"].nunique()),
                            "grid_lo": float(grid.min()), "grid_hi": float(grid.max()),
                            "grid_n": int(len(grid))})
        if verbose:
            print("  %-10s %3d files -> %3d curves, %2d groups"
                  % (folder.name, len(files), len(df), df["group"].nunique()))
    if not rows:
        raise SystemExit("no DPV data found under %s" % data_root)
    return pd.concat(rows, ignore_index=True), pd.DataFrame(folder_info)


# ---------------------------------------------------------------------------
# 2. chemistry labels from the free-text group names
# ---------------------------------------------------------------------------
_NO_T = re.compile(r"无靶标|无目标物|no[ _-]?target|notarget|无靶")
_YES_T = re.compile(r"有目标物|靶标|目标物|target")
_NO_E = re.compile(r"无酶|no[ _-]?enz|noenzyme|不加酶")
_YES_E = re.compile(r"有酶|加酶|酶|enz")
_BARE = re.compile(r"^(material|材料|裸|bare)", re.I)
_MB = re.compile(r"mb|亚甲基蓝|methylene", re.I)


def label_of(group: str):
    """(target, enzyme, probe) -- True / False / None (unknown).

    A negated form wins, because "无靶标" contains "靶标".
    probe=False marks a bare or material-only electrode: no H1/H2 hairpin, so it
    is a different experiment, not a negative control for the assay.
    """
    g = str(group)
    low = g.lower()
    if _NO_T.search(low):
        target = False
    elif _YES_T.search(low):
        target = True
    else:
        target = None
    if _NO_E.search(low):
        enzyme = False
    elif _YES_E.search(low):
        enzyme = True
    else:
        enzyme = None
    probe = None
    if _BARE.search(g):
        probe = bool(_MB.search(low))
    return target, enzyme, probe


def attach_labels(df):
    """Explicit truth (the label column, 1 = analyte present) beats the group
    name -- a name is only ever a hint.  enzyme / probe still come from the name
    because nobody records those as a column yet."""
    lab = df["group"].map(label_of)
    df = df.copy()
    df["target"] = [t for t, e, p in lab]
    if "label" in df.columns:
        lab_col = pd.to_numeric(df["label"], errors="coerce")
        df["target"] = [bool(v) if np.isfinite(v) else t
                        for v, t in zip(lab_col, df["target"])]
    df["enzyme"] = [e for t, e, p in lab]
    df["probe"] = [p for t, e, p in lab]
    return df


# ---------------------------------------------------------------------------
# 3. variance decomposition (nested: batch > condition > electrode > scan)
# ---------------------------------------------------------------------------
def decompose(df, col):
    """Share of total sum of squares carried by each nesting level.

    Log scale for ratio/MB: one 20 uA outlier would otherwise own everything.
    The electrode term is only identified where a condition has >= 2 strips,
    so it is a LOWER bound -- see n_multi in the output.
    """
    d = df[["folder", "group", "electrode", col]].copy()
    d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d[np.isfinite(d[col])]
    if col != "I_ref":
        d = d[d[col] > 0]
    if len(d) < 4:
        return None
    d = d.assign(_y=np.log10(d[col].values) if col != "I_ref" else d[col].values)
    gm = d["_y"].mean()
    total = float(((d["_y"] - gm) ** 2).sum())
    if total <= 0:
        return None

    def ss(keys, parent=None):
        means = d.groupby(keys)["_y"].transform("mean")
        if parent is None:
            return float(((means - gm) ** 2).sum())
        pm = d.groupby(parent)["_y"].transform("mean")
        return float(((means - pm) ** 2).sum())

    ss_batch = ss(["folder"])
    ss_group = ss(["folder", "group"], ["folder"])
    ss_elec = ss(["folder", "group", "electrode"], ["folder", "group"])
    ss_scan = max(0.0, total - ss_batch - ss_group - ss_elec)
    multi = d.groupby(["folder", "group"])["electrode"].nunique()
    return {"metric": col, "n": int(len(d)),
            "batch_pct": 100 * ss_batch / total,
            "group_pct": 100 * ss_group / total,
            "electrode_pct": 100 * ss_elec / total,
            "scan_pct": 100 * ss_scan / total,
            "n_conditions_multi_elec": int((multi >= 2).sum())}


# ---------------------------------------------------------------------------
# 4. repeatability: within-electrode vs between-electrode
# ---------------------------------------------------------------------------
def repeat_split(df, metric="ratio"):
    rows = []
    for (folder, group), sub in df.groupby(["folder", "group"]):
        sub = sub[np.isfinite(pd.to_numeric(sub[metric], errors="coerce"))]
        if sub.empty:
            continue
        within = []
        for _, e in sub.groupby("electrode"):
            v = pd.to_numeric(e[metric], errors="coerce").dropna().values
            if len(v) >= 2 and v.mean() != 0:
                within.append(v.std(ddof=1) / abs(v.mean()) * 100)
        means = sub.groupby("electrode")[metric].mean().dropna().values
        between = (means.std(ddof=1) / abs(means.mean()) * 100) \
            if len(means) >= 2 and means.mean() else np.nan
        rows.append({"folder": folder, "group": group,
                     "n_elec": int(len(means)), "n_scan": int(len(sub)),
                     "within_cv": float(np.median(within)) if within else np.nan,
                     "between_cv": float(between),
                     "mean": float(means.mean())})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 5. present / absent at electrode level
# ---------------------------------------------------------------------------
def electrode_table(df, metric="ratio", mode="strict"):
    """One row per electrode.  mode='loose' also counts bare / material-only
    electrodes as 'absent' -- the shortcut that makes the numbers look good."""
    d = df.copy()
    if mode == "loose":
        d.loc[d["probe"] == False, "target"] = False               # noqa: E712
        keep = d["target"].notna()
    else:
        keep = d["target"].notna() & (d["probe"] != False)         # noqa: E712
    d = d[keep].copy()
    feats = [f for f in FEATURES if f in d.columns]
    agg = {f: (f, "mean") for f in feats}
    agg["target"] = ("target", "first")
    agg["n_scan"] = (metric, "size")
    g = d.groupby(["folder", "group", "electrode"]).agg(**agg).reset_index()
    return g


def auc_ci(y, s, n_boot=2000, seed=0):
    from sklearn.metrics import roc_auc_score
    y = np.asarray(y).astype(int)
    s = np.asarray(s, float)
    ok = np.isfinite(s)
    y, s = y[ok], s[ok]
    if len(np.unique(y)) < 2:
        return np.nan, np.nan, np.nan
    a = float(roc_auc_score(y, s))
    rng = np.random.default_rng(seed)
    boot = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(y), len(y))
        if len(np.unique(y[idx])) < 2:
            continue
        boot.append(roc_auc_score(y[idx], s[idx]))
    if not boot:
        return a, np.nan, np.nan
    return a, float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


def youden_cutoff(y, s):
    y = np.asarray(y).astype(int)
    s = np.asarray(s, float)
    order = np.argsort(s)
    best, cut = -1.0, float(np.median(s))
    for i in range(1, len(order)):
        t = (s[order[i - 1]] + s[order[i]]) / 2
        pred = (s >= t).astype(int)
        sens = pred[y == 1].mean() if (y == 1).any() else 0.0
        spec = 1 - pred[y == 0].mean() if (y == 0).any() else 0.0
        j = sens + spec - 1
        if j > best:
            best, cut = j, float(t)
    return cut


def sign_of(elec, metric):
    m = elec.groupby("target")[metric].mean()
    if True not in m.index or False not in m.index:
        return 1.0
    return 1.0 if m.loc[True] > m.loc[False] else -1.0


def lobo_rule(elec, metric="ratio"):
    rows = []
    batches = [b for b in elec["folder"].unique()
               if elec[elec.folder == b]["target"].nunique() == 2]
    for b in batches:
        tr, te = elec[elec.folder != b], elec[elec.folder == b]
        if tr["target"].nunique() < 2 or te.empty:
            continue
        sgn = sign_of(tr, metric)
        cut = youden_cutoff(tr["target"].astype(int), sgn * tr[metric])
        y = te["target"].astype(int).values
        pred = (sgn * te[metric].values >= cut).astype(int)
        rows.append({"batch": b, "n": int(len(te)), "n_pos": int(y.sum()),
                     "n_neg": int((1 - y).sum()), "sign": sgn, "cutoff": cut,
                     "sens": float(pred[y == 1].mean()) if (y == 1).any() else np.nan,
                     "spec": float(1 - pred[y == 0].mean()) if (y == 0).any() else np.nan,
                     "acc": float((pred == y).mean())})
    return pd.DataFrame(rows)


def lda_lobo(elec, feats=None):
    """Train on every batch but one, predict the held-out batch."""
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    feats = [f for f in (feats or FEATURES) if f in elec.columns]
    # a folder whose scan window misses the MB peak leaves ratio = NaN; LDA
    # refuses NaN outright, so impute the column median inside the pipeline
    X = elec[feats].apply(pd.to_numeric, errors="coerce").values
    y = elec["target"].astype(int).values
    rows = []
    for b in elec["folder"].unique():
        te = (elec["folder"] == b).values
        tr = ~te
        if len(np.unique(y[tr])) < 2 or te.sum() == 0:
            continue
        if len(np.unique(y[te])) < 2:
            continue
        m = make_pipeline(SimpleImputer(strategy="median"),
                          StandardScaler(), LinearDiscriminantAnalysis())
        m.fit(X[tr], y[tr])
        p = m.predict(X[te])
        rows.append({"batch": b, "n": int(te.sum()),
                     "acc": float((p == y[te]).mean()),
                     "sens": float(p[y[te] == 1].mean()) if (y[te] == 1).any() else np.nan,
                     "spec": float(1 - p[y[te] == 0].mean()) if (y[te] == 0).any() else np.nan})
    return pd.DataFrame(rows)


def wilson(k, n, z=1.96):
    if n == 0:
        return np.nan, np.nan
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def within_batch_auc(elec, metric="ratio"):
    """AUC computed inside each batch, then averaged.

    This is the honest measure of discriminability: it never compares two
    electrodes measured on different days, so a batch offset cannot inflate it.
    """
    from sklearn.metrics import roc_auc_score
    rows = []
    for b, sub in elec.groupby("folder"):
        s = pd.to_numeric(sub[metric], errors="coerce")
        ok = np.isfinite(s)
        sub, s = sub[ok], s[ok]
        y = sub["target"].astype(int).values
        if len(np.unique(y)) < 2:
            continue
        sgn = 1.0 if sub[sub.target == True][metric].astype(float).mean() >                      sub[sub.target == False][metric].astype(float).mean() else -1.0
        rows.append({"batch": b, "n": int(len(y)), "n_pos": int(y.sum()),
                     "auc": float(roc_auc_score(y, sgn * s.values))})
    df = pd.DataFrame(rows)
    if len(df):
        df["w"] = df["n"]
    return df


def direction_table(elec, metric="ratio"):
    """Per batch: does 'present' push the signal up or down?"""
    rows = []
    for b, sub in elec.groupby("folder"):
        if sub["target"].nunique() < 2:
            continue
        pos = sub[sub.target == True][metric].astype(float).values   # noqa: E712
        neg = sub[sub.target == False][metric].astype(float).values  # noqa: E712
        pos, neg = pos[np.isfinite(pos)], neg[np.isfinite(neg)]
        if not len(pos) or not len(neg):
            continue
        rows.append({"batch": b, "n_pos": len(pos), "n_neg": len(neg),
                     "pos_mean": float(pos.mean()), "neg_mean": float(neg.mean()),
                     "diff": float(pos.mean() - neg.mean()),
                     "direction": "present HIGHER" if pos.mean() > neg.mean()
                                  else "present LOWER"})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 6. figures
# ---------------------------------------------------------------------------
def make_figures(decomp, rep, elec, lobo, direc, outdir: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.metrics import roc_curve
    outdir.mkdir(parents=True, exist_ok=True)
    saved = []

    if decomp:
        fig, ax = plt.subplots(figsize=(7.4, 3.2))
        keys = ["batch_pct", "group_pct", "electrode_pct", "scan_pct"]
        names = ["batch (date)", "condition", "electrode", "repeat scan"]
        colors = ["#c44e52", "#dd8452", "#4c72b0", "#9aa0a6"]
        left = np.zeros(len(decomp))
        labels = [d["metric"] for d in decomp]
        for k, nm, c in zip(keys, names, colors):
            v = np.array([d[k] for d in decomp])
            ax.barh(labels, v, left=left, color=c, label=nm)
            for i, (val, l0) in enumerate(zip(v, left)):
                if val > 7:
                    ax.text(l0 + val / 2, i, "%.0f" % val, ha="center",
                            va="center", fontsize=8, color="white")
            left += v
        ax.set_xlabel("share of total variance (%)")
        ax.set_xlim(0, 100)
        ax.legend(ncol=4, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, 1.24))
        ax.set_title("Where the spread comes from")
        fig.tight_layout()
        p = outdir / "fig_variance.png"
        fig.savefig(p, dpi=160); plt.close(fig); saved.append(p)

    r = rep.dropna(subset=["within_cv", "between_cv"])
    r = r[r["n_elec"] >= 2]
    if len(r) >= 3:
        fig, ax = plt.subplots(figsize=(5.8, 4.6))
        ax.scatter(r["within_cv"], r["between_cv"], s=46, alpha=.8,
                   color="#4c72b0", edgecolor="k", linewidth=.4)
        lim = max(r["within_cv"].max(), r["between_cv"].max()) * 1.1
        ax.plot([0, lim], [0, lim], "--", color="gray", lw=1)
        ax.text(lim * .55, lim * .45, "y = x", color="gray", fontsize=8, rotation=35)
        ax.set_xlabel("within-electrode CV (%) - repeat scans of one strip")
        ax.set_ylabel("between-electrode CV (%) - strips, same condition")
        ax.set_title("Measurement error vs fabrication error")
        fig.tight_layout()
        p = outdir / "fig_repeatability.png"
        fig.savefig(p, dpi=160); plt.close(fig); saved.append(p)

    if len(direc) >= 2:
        fig, ax = plt.subplots(figsize=(7.6, 3.6))
        x = np.arange(len(direc))
        w = 0.38
        ax.bar(x - w / 2, direc["pos_mean"], w, label="streptomycin present",
               color="#4c72b0")
        ax.bar(x + w / 2, direc["neg_mean"], w, label="absent (control)",
               color="#9aa0a6")
        ax.set_xticks(x)
        ax.set_xticklabels(direc["batch"])
        ax.set_ylabel("I_MB / I_ref")
        ax.set_title("The direction of the effect is not the same in every batch")
        ax.legend(fontsize=8)
        fig.tight_layout()
        p = outdir / "fig_direction.png"
        fig.savefig(p, dpi=160); plt.close(fig); saved.append(p)

    fig, ax = plt.subplots(figsize=(5.4, 4.8))
    for m, c in zip(["ratio", "I_MB"], ["#4c72b0", "#dd8452"]):
        e = elec[np.isfinite(pd.to_numeric(elec[m], errors="coerce"))]
        if e["target"].nunique() < 2:
            continue
        y = e["target"].astype(int).values
        sgn = sign_of(e, m)
        s = sgn * pd.to_numeric(e[m], errors="coerce").values
        fpr, tpr, _ = roc_curve(y, s)
        a, lo, hi = auc_ci(y, s, n_boot=500)
        ax.plot(fpr, tpr, color=c, lw=2,
                label="%s  AUC=%.2f [%.2f-%.2f]" % (m, a, lo, hi))
    ax.plot([0, 1], [0, 1], "--", color="gray", lw=1)
    ax.set_xlabel("false positive rate")
    ax.set_ylabel("true positive rate")
    ax.set_title("Present / absent, one point per electrode (n=%d)" % len(elec))
    ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    p = outdir / "fig_roc.png"
    fig.savefig(p, dpi=160); plt.close(fig); saved.append(p)

    if len(lobo):
        fig, ax = plt.subplots(figsize=(7.4, 3.4))
        x = np.arange(len(lobo))
        w = 0.38
        ax.bar(x - w / 2, lobo["sens"] * 100, w, label="sensitivity", color="#4c72b0")
        ax.bar(x + w / 2, lobo["spec"] * 100, w, label="specificity", color="#55a868")
        for i, (_, r0) in enumerate(lobo.iterrows()):
            ax.text(i - w / 2, r0["sens"] * 100 + 2, "%.0f" % (r0["sens"] * 100),
                    ha="center", fontsize=8)
            ax.text(i + w / 2, r0["spec"] * 100 + 2, "%.0f" % (r0["spec"] * 100),
                    ha="center", fontsize=8)
        ax.set_xticks(x)
        ax.set_xticklabels(["%s\nn=%d" % (b, n) for b, n in zip(lobo["batch"], lobo["n"])])
        ax.set_ylim(0, 118)
        ax.set_ylabel("%")
        ax.set_title("Cutoff fitted on the other batches, tested on this one")
        ax.legend(fontsize=8)
        fig.tight_layout()
        p = outdir / "fig_lobo.png"
        fig.savefig(p, dpi=160); plt.close(fig); saved.append(p)
    return saved


# ---------------------------------------------------------------------------
def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    setup_fonts()
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--metric", default="ratio")
    a = ap.parse_args()

    root = HERE.parent
    data_root = Path(a.data) if a.data else (root / "data")
    if not data_root.is_dir():
        raise SystemExit("no such folder: %s" % data_root)
    outdir = Path(a.out) if a.out else (root / "out" / "cross_batch")
    outdir.mkdir(parents=True, exist_ok=True)

    print("loading %s" % data_root)
    df, info = load_all(data_root)
    df = attach_labels(df)
    n_all = len(df)
    df = df[df["qc_rel"]].copy()
    print("\n%d curves -> %d after the batch-relative reference QC, %d electrodes, %d folders"
          % (n_all, len(df), df.groupby(["folder", "group", "electrode"]).ngroups,
             df["folder"].nunique()))

    print("\n[1] variance decomposition (log scale)")
    decomp = []
    for m in [a.metric, "I_MB", "I_ref"]:
        if m in df.columns:
            d = decompose(df, m)
            if d:
                decomp.append(d)
                print("  %-6s n=%3d  batch %5.1f%%  condition %5.1f%%  "
                      "electrode %5.1f%%  scan %5.1f%%  (%d conditions with 2+ strips)"
                      % (m, d["n"], d["batch_pct"], d["group_pct"],
                         d["electrode_pct"], d["scan_pct"], d["n_conditions_multi_elec"]))

    print("\n[2] repeatability")
    rep = repeat_split(df, a.metric)
    rep.to_csv(outdir / "repeatability.csv", index=False, encoding="utf-8-sig")
    w = rep["within_cv"].dropna()
    b = rep["between_cv"].dropna()
    print("  %d conditions measured; within-electrode CV median %.0f%% (n=%d);"
          " between-electrode CV median %.0f%% (n=%d)"
          % (len(rep), w.median() if len(w) else np.nan, len(w),
             b.median() if len(b) else np.nan, len(b)))

    print("\n[3] present / absent at electrode level")
    variants = {}
    for mode in ("strict", "loose"):
        elec = electrode_table(df, a.metric, mode)
        if elec["target"].nunique() < 2 or len(elec) < 6:
            continue
        y = elec["target"].astype(int).values
        sgn = sign_of(elec, a.metric)
        auc, lo, hi = auc_ci(y, sgn * elec[a.metric].astype(float).values)
        variants[mode] = {"n": int(len(elec)), "n_pos": int(y.sum()),
                          "n_neg": int((1 - y).sum()), "auc": auc, "lo": lo, "hi": hi}
        print("  %-6s  n=%2d (%d present / %d absent)   AUC %.2f [%.2f-%.2f]"
              % (mode, len(elec), int(y.sum()), int((1 - y).sum()), auc, lo, hi))
    print("  strict = bare / material-only electrodes are NOT counted as controls")

    elec = electrode_table(df, a.metric, "strict")
    direc = direction_table(elec, a.metric)
    if len(direc):
        print("\n[4] direction of the effect, batch by batch")
        for _, r0 in direc.iterrows():
            print("  %-10s present %.2f vs absent %.2f  (%+.2f)  %s"
                  % (r0["batch"], r0["pos_mean"], r0["neg_mean"],
                     r0["diff"], r0["direction"]))
        flips = direc["direction"].nunique() > 1
        print("  -> the direction %s across batches" % ("FLIPS" if flips else "is consistent"))

    wauc = within_batch_auc(elec, a.metric)
    if len(wauc):
        wmean = float(np.average(wauc["auc"], weights=wauc["w"]))
        print("\n[4b] AUC computed inside each batch (batch offset cannot leak in):")
        for _, r0 in wauc.iterrows():
            print("    %-10s n=%2d  AUC %.2f" % (r0["batch"], r0["n"], r0["auc"]))
        print("    weighted mean within-batch AUC %.2f  (0.50 = no signal at all)" % wmean)
        wauc.to_csv(outdir / "within_batch_auc.csv", index=False, encoding="utf-8-sig")

    lobo = pd.DataFrame()
    if elec["target"].nunique() == 2:
        y = elec["target"].astype(int).values
        sgn = sign_of(elec, a.metric)
        cut = youden_cutoff(y, sgn * elec[a.metric].astype(float).values)
        pred = (sgn * elec[a.metric].astype(float).values >= cut).astype(int)
        sens = pred[y == 1].mean()
        spec = 1 - pred[y == 0].mean()
        acc = (pred == y).mean()
        print("\n[5] a single pooled cutoff: %.2f -> sens %.0f%% spec %.0f%% acc %.0f%%"
              % (cut, sens * 100, spec * 100, acc * 100))
        lobo = lobo_rule(elec, a.metric)
        if len(lobo):
            print("  leave-one-batch-out (cutoff fitted on the other batches):")
            for _, r0 in lobo.iterrows():
                print("    %-10s n=%2d  sens %5.0f%%  spec %5.0f%%  acc %5.0f%%"
                      % (r0["batch"], r0["n"], r0["sens"] * 100,
                         r0["spec"] * 100, r0["acc"] * 100))
            print("    mean accuracy %.0f%%" % (lobo["acc"].mean() * 100))
            lobo.to_csv(outdir / "lobo.csv", index=False, encoding="utf-8-sig")
        l2 = lda_lobo(elec)
        if len(l2):
            print("  leave-one-batch-out with LDA on %d features: mean accuracy %.0f%%"
                  % (len(FEATURES), l2["acc"].mean() * 100))
            for _, r0 in l2.iterrows():
                print("    %-10s n=%2d  sens %5.0f%%  spec %5.0f%%  acc %5.0f%%"
                      % (r0["batch"], r0["n"], r0["sens"] * 100,
                         r0["spec"] * 100, r0["acc"] * 100))
            l2.to_csv(outdir / "lda_lobo.csv", index=False, encoding="utf-8-sig")

    figs = make_figures(decomp, rep, elec, lobo, direc, outdir / "figures")
    print("\nfigures -> %s" % (outdir / "figures"))
    for p in figs:
        print("   ", p.name)

    summary = {"curves": int(len(df)),
               "electrodes": int(df.groupby(["folder", "group", "electrode"]).ngroups),
               "folders": info.to_dict("records"),
               "variance": decomp,
               "repeatability": {"within_median": float(w.median()) if len(w) else None,
                                 "between_median": float(b.median()) if len(b) else None,
                                 "n_conditions": int(len(rep))},
               "variants": variants,
               "direction": direc.to_dict("records"),
               "lobo": lobo.to_dict("records") if len(lobo) else []}
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                         encoding="utf-8")
    print("\nsummary -> %s" % (outdir / "summary.json"))


if __name__ == "__main__":
    main()
