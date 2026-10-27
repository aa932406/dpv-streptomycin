#!/usr/bin/env python3
"""
figures.py -- matplotlib figures for the web UI.

Every label here is ASCII on purpose: a Windows box has Microsoft YaHei but a
bare Linux container has no CJK font at all, and Chinese text silently renders
as empty boxes.  The Chinese lives in the Streamlit UI, where the browser draws
it; the figures stay portable.
"""
from __future__ import annotations

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb

from dpv_pipeline import GRID, GROUP_ORDER, GROUP_COLOR, group_colors, setup_fonts

# Group names come from the file names and are usually Chinese ("材料", "靶标、无酶").
# Without a CJK font matplotlib draws them as empty boxes -- on Windows that means
# Microsoft YaHei, on a bare Linux container nothing at all.
setup_fonts()

DEFAULT_LABEL = {"material": "material", "material+MB": "material + MB",
                 "target_noEnz": "target, no enzyme", "target+Enz": "target + enzyme"}
PALETTE = ["#1f77b4", "#2ca02c", "#d62728", "#9467bd", "#ff7f0e", "#17becf", "#8c564b"]


def _colors(groups):
    """Same colour per group as the web UI (see dpv_pipeline.group_colors)."""
    return group_colors(groups)


def _finish(fig, tight=True):
    if tight:
        fig.tight_layout()
    return fig


def _axis(grid, n):
    """The x axis must be the same length as the curves, or matplotlib either
    raises a cryptic shape error or -- worse -- draws the curve against a
    different potential axis.  Callers always know their grid; pass it."""
    g = GRID if grid is None else np.asarray(grid, dtype=float).ravel()
    if len(g) != n:
        raise ValueError("x axis has %d points but the curves have %d; pass grid= "
                         "from build_table() instead of relying on the default"
                         % (len(g), n))
    return g


def fig_traces(df, curves, labels=None, title="Baseline-corrected DPV traces", grid=None):
    labels = labels or DEFAULT_LABEL
    grid = _axis(grid, np.asarray(curves).shape[1])
    groups = list(dict.fromkeys(df["group"].tolist()))
    col = _colors(groups)
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for g in groups:
        idx = np.where(df["group"].values == g)[0]
        for n, i in enumerate(idx):
            ax.plot(grid, curves[i], lw=0.9, color=col[g], alpha=0.75,
                    label=labels.get(g, g) if n == 0 else None)
    ax.axhline(0, color="0.6", lw=0.6)
    ax.set_xlabel("E (V vs reference)")
    ax.set_ylabel("I (uA, baseline removed)")
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=7, frameon=False, ncol=2)
    ax.invert_xaxis()
    return _finish(fig)


def fig_mean_sd(df, curves, labels=None, title="Mean +/- SD per condition", grid=None):
    labels = labels or DEFAULT_LABEL
    grid = _axis(grid, np.asarray(curves).shape[1])
    groups = list(dict.fromkeys(df["group"].tolist()))
    col = _colors(groups)
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for g in groups:
        idx = np.where(df["group"].values == g)[0]
        if len(idx) == 0:
            continue
        block = curves[idx]
        mu = block.mean(axis=0)
        sd = block.std(axis=0, ddof=1) if len(idx) > 1 else np.zeros_like(mu)
        ax.fill_between(grid, mu - sd, mu + sd, color=col[g], alpha=0.18, lw=0)
        ax.plot(grid, mu, color=col[g], lw=1.6, label="%s (n=%d)" % (labels.get(g, g), len(idx)))
    ax.axhline(0, color="0.6", lw=0.6)
    ax.set_xlabel("E (V vs reference)")
    ax.set_ylabel("I (uA)")
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=7, frameon=False)
    ax.invert_xaxis()
    return _finish(fig)


def fig_raw_example(grid, raw, corrected, baseline, fname=""):
    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.6))
    axes[0].plot(grid, raw, color="0.25", lw=1.0)
    axes[0].plot(grid, baseline, color="#d62728", lw=1.0, ls="--")
    axes[0].set_title("raw trace + fitted envelope", fontsize=9)
    axes[0].set_xlabel("E (V)")
    axes[0].set_ylabel("I (A/cm2)")
    axes[1].plot(grid, corrected, color="#1f77b4", lw=1.2)
    axes[1].axhline(0, color="0.6", lw=0.6)
    axes[1].set_title("after baseline removal", fontsize=9)
    axes[1].set_xlabel("E (V)")
    axes[1].set_ylabel("I (uA)")
    for a in axes:
        a.invert_xaxis()
    if fname:
        fig.suptitle(fname, fontsize=8, color="0.3")
    return _finish(fig)


def fig_box(df, metric="ratio", labels=None, title=None):
    labels = labels or DEFAULT_LABEL
    groups = list(dict.fromkeys(df["group"].tolist()))
    cmap = group_colors(groups)
    data, names, cols = [], [], []
    for i, g in enumerate(groups):
        v = df.loc[df["group"] == g, metric].dropna().values
        if len(v) == 0:
            continue
        data.append(v)
        names.append(labels.get(g, g))
        cols.append(cmap.get(g, PALETTE[i % len(PALETTE)]))
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    bp = ax.boxplot(data, patch_artist=True, widths=0.55,
                    medianprops=dict(color="0.15", lw=1.2))
    for patch, c in zip(bp["boxes"], cols):
        patch.set_facecolor(to_rgb(c) + (0.28,))
        patch.set_edgecolor(c)
    for i, v in enumerate(data):
        ax.scatter(np.full(len(v), i + 1) + np.random.default_rng(0).normal(0, 0.045, len(v)),
                   v, s=16, color=cols[i], edgecolor="white", linewidth=0.5, zorder=3)
    ax.set_xticks(range(1, len(names) + 1))
    ax.set_xticklabels(names, fontsize=8, rotation=15)
    ax.set_ylabel(metric)
    ax.set_title(title or ("%s by condition" % metric), fontsize=10)
    return _finish(fig)


def fig_ratio_scatter(df, labels=None):
    labels = labels or DEFAULT_LABEL
    groups = list(dict.fromkeys(df["group"].tolist()))
    col = _colors(groups)
    fig, ax = plt.subplots(figsize=(5.6, 4.4))
    for g in groups:
        sub = df[df["group"] == g]
        ax.scatter(sub["I_ref"], sub["I_MB"], s=34, color=col[g],
                   edgecolor="white", linewidth=0.6, label=labels.get(g, g), zorder=3)
    lim = max(float(df["I_ref"].max()), float(df["I_MB"].max()), 1e-6) * 1.15
    for r, ls in ((1.0, ":"), (0.5, "--")):
        ax.plot([0, lim], [0, lim * r], color="0.6", lw=0.8, ls=ls)
        ax.annotate("ratio %.1f" % r, (lim * 0.72, lim * 0.72 * r), fontsize=7, color="0.45")
    ax.set_xlabel("internal reference peak I_ref (uA)")
    ax.set_ylabel("MB peak current I_MB (uA)")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_title("MB signal vs internal reference", fontsize=10)
    ax.legend(fontsize=7, frameon=False)
    return _finish(fig)


def fig_pca(scores, var, groups, labels=None):
    labels = labels or DEFAULT_LABEL
    col = _colors(list(dict.fromkeys(groups)))
    fig, ax = plt.subplots(figsize=(5.6, 4.4))
    for g in dict.fromkeys(groups):
        m = np.array([x == g for x in groups])
        ax.scatter(scores[m, 0], scores[m, 1], s=40, color=col[g],
                   edgecolor="white", linewidth=0.6, label=labels.get(g, g), zorder=3)
    ax.set_xlabel("PC1 (%.1f%%)" % (var[0] * 100))
    ax.set_ylabel("PC2 (%.1f%%)" % (var[1] * 100) if len(var) > 1 else "")
    ax.set_title("PCA of the whole curve", fontsize=10)
    ax.legend(fontsize=7, frameon=False)
    return _finish(fig)


def fig_calibration(fit, df, metric="ratio", labels=None):
    labels = labels or DEFAULT_LABEL
    col = _colors(list(dict.fromkeys(df["group"].tolist())))
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.9))
    ax = axes[0]
    d = df[df["concentration_M"].notna() & (df["concentration_M"] > 0) & df[metric].notna()]
    for g in dict.fromkeys(df["group"].tolist()):
        sub = d[d["group"] == g]
        if len(sub):
            ax.scatter(np.log10(sub["concentration_M"]), sub[metric], s=32,
                       color=col[g], edgecolor="white", linewidth=0.6,
                       label=labels.get(g, g), zorder=3)
    xs = np.linspace(np.log10(d["concentration_M"]).min(), np.log10(d["concentration_M"]).max(), 100) if len(d) else np.array([])
    if "error" not in fit and len(xs):
        ax.plot(xs, fit["a"] + fit["b"] * xs, color="0.2", lw=1.3)
        lo, hi = fit["dynamic_range_M"]
        for v, txt in ((lo, "lowest standard"), (hi, "highest standard")):
            ax.axvline(np.log10(v), color="0.75", lw=0.7, ls=":")
        if fit.get("LOD_M"):
            ax.axvline(np.log10(fit["LOD_M"]), color="#d62728", lw=0.9, ls="--")
            ax.annotate("LOD %.1e M" % fit["LOD_M"], (np.log10(fit["LOD_M"]), ax.get_ylim()[1]),
                        fontsize=7, color="#d62728", ha="left", va="top", rotation=90)
    ax.set_xlabel("log10 concentration (M)")
    ax.set_ylabel(metric)
    ttl = "calibration" if "error" in fit else "calibration (r2 = %.3f)" % fit["r2"]
    ax.set_title(ttl, fontsize=10)
    ax.legend(fontsize=7, frameon=False)

    ax2 = axes[1]
    if "error" not in fit and len(d):
        x = np.log10(d["concentration_M"].values.astype(float))
        resid = d[metric].values - (fit["a"] + fit["b"] * x)
        ax2.axhline(0, color="0.6", lw=0.7)
        ax2.scatter(x, resid, s=28, color="#4c72b0", edgecolor="white", linewidth=0.6)
        ax2.set_xlabel("log10 concentration (M)")
        ax2.set_ylabel("residual")
        ax2.set_title("residuals", fontsize=10)
    else:
        ax2.text(0.5, 0.5, "no calibration", ha="center", va="center", color="0.5")
        ax2.set_axis_off()
    return _finish(fig)


def fig_prediction(fit, samples, metric="ratio"):
    """Where the unknown samples land on the fitted line."""
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    lo, hi = fit["dynamic_range_M"]
    xs = np.linspace(np.log10(lo) - 0.5, np.log10(hi) + 0.5, 200)
    ax.plot(xs, fit["a"] + fit["b"] * xs, color="0.2", lw=1.3, label="calibration")
    if fit.get("LOD_M"):
        ax.axhline(fit["a"] + fit["b"] * np.log10(fit["LOD_M"]), color="#d62728",
                   lw=0.9, ls="--", label="LOD")
    for name, y0, c in samples:
        ax.scatter([(y0 - fit["a"]) / fit["b"]], [y0], s=55,
                   color=c, edgecolor="white", zorder=4, label=name)
    ax.set_xlabel("log10 concentration (M)")
    ax.set_ylabel(metric)
    ax.set_title("sample read-out", fontsize=10)
    ax.legend(fontsize=7, frameon=False)
    return _finish(fig)


def fig_confusion(result):
    labels = result["labels"]
    cm = np.array(result["confusion"], dtype=float)
    fig, ax = plt.subplots(figsize=(4.6, 4.0))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.set_yticklabels(labels, fontsize=8)
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, int(cm[i, j]), ha="center", va="center", fontsize=9,
                    color="white" if cm[i, j] > cm.max() * 0.55 else "0.15")
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    ax.set_title("leave-one-electrode-out (%.0f%%)" % (result["accuracy"] * 100), fontsize=10)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    return _finish(fig)


def fig_permutation(perm, title="permutation test"):
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    null = perm.get("null") or []
    if len(null):
        ax.hist(null, bins=20, color="#9ecae1", edgecolor="white", label="shuffled labels")
    ax.axvline(perm["observed"], color="#d62728", lw=1.5,
               label="observed %.0f%%" % (perm["observed"] * 100))
    ax.axvline(perm["null_p95"], color="0.45", lw=0.9, ls="--",
               label="95th pct of null %.0f%%" % (perm["null_p95"] * 100))
    ax.set_xlim(0, 1)
    ax.set_xlabel("leave-one-electrode-out accuracy")
    ax.set_ylabel("shuffles")
    ax.set_title("%s (n = %d shuffles)" % (title, perm["n_perm"]), fontsize=10)
    ax.legend(fontsize=7, frameon=False)
    return _finish(fig)


def fig_importance(pairs, k=8):
    pairs = pairs[:k][::-1]
    fig, ax = plt.subplots(figsize=(5.6, 0.32 * len(pairs) + 1.2))
    ax.barh([p[0] for p in pairs], [p[1] for p in pairs], color="#4c72b0", height=0.62)
    ax.set_xlabel("importance")
    ax.set_title("what the model actually uses", fontsize=10)
    return _finish(fig)


def fig_sample_size():
    from scipy.stats import beta
    n = np.arange(4, 161)
    p = 0.8
    width = np.array([(beta.ppf(0.975, p * k + 1, (1 - p) * k + 1) -
                       beta.ppf(0.025, p * k + 1, (1 - p) * k + 1)) * 100 for k in n])
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.plot(n, width, color="#1f77b4", lw=1.6)
    for k, lab in ((9, "you are here (9 electrodes)"), (30, "tier A"), (60, "tier B"), (150, "tier C")):
        ax.axvline(k, color="0.75", lw=0.8, ls=":")
        ax.annotate(lab, (k, width.max() * 0.96), fontsize=7, rotation=90, va="top", color="0.4")
    ax.set_xlabel("number of independent electrodes")
    ax.set_ylabel("95% CI width of accuracy (percentage points)")
    ax.set_title("how much data a believable accuracy needs", fontsize=10)
    return _finish(fig)
