#!/usr/bin/env python3
"""
make_demo_data.py -- synthesise complete calibration sets so the web UI can be
demonstrated before the real concentration series exists.

THIS DATA IS FAKE.  It is written in the real CHI .cor format so the whole
pipeline runs on it unchanged, but the concentrations are invented.  The UI
shows a red banner whenever one of these folders is loaded.

Two layouts:
  demo/         one batch, 3 blanks + 6 concentrations x 3 electrodes + 2 unknowns
                -> shows what a single pooled calibration looks like
  demo_batches/ 3 batches, each with its own log-scale offset and electrode gain
                -> shows why a pooled line fails and per-batch calibration works

Usage:  python make_demo_data.py [--out data/demo] [--mode single|batches]
"""
from __future__ import annotations
import argparse
import csv
from pathlib import Path

import numpy as np

E_START, E_STOP, E_STEP = 0.80, -0.78, -0.02
GRID = np.round(np.arange(E_START, E_STOP - 1e-9, E_STEP), 4)

LEVELS = [1e-12, 1e-11, 1e-10, 1e-9, 1e-8, 1e-7]        # M, streptomycin
UNKNOWNS = [("sample_U1", 5e-9), ("sample_U2", 5e-10)]   # truth kept out of the CSV

BATCH_LEVELS = [1e-11, 1e-10, 1e-9, 1e-8, 1e-7]
BATCH_UNKNOWNS = [("sample_B1", 3e-9), ("sample_B2", 4e-10)]

HEAD = ("file", "group", "concentration_M", "electrode", "batch", "label", "role", "note")


def _gauss(x, mu, sigma):
    return np.exp(-0.5 * ((x - mu) / sigma) ** 2)


def response(C, rng, noise=0.05, shift=0.0):
    """Assay response I_MB / I_ref as a function of streptomycin concentration.

    Signal-OFF: more target -> more dsDNA -> more Exo III cutting -> less MB on
    the electrode.  This mirrors what the 2026-10-10 data actually did.
    Linear in log10(C): 0.95 with no target, falling 0.14 per decade, so 0.11 at
    100 nM -- a 8x dynamic range, which makes a log-linear fit meaningful.

    The blank is 0.95 whatever C is set to 0: it is the no-target plateau, not
    "1e-14 M", and it must NOT be the lowest standard or the LOD has no anchor.
    """
    if C is None or float(C) <= 0:
        r = 0.95
    else:
        r = 0.95 - 0.14 * (np.log10(float(C)) + 13.0)
    r = float(np.clip(r + shift, 0.04, 1.40))
    return r * (1 + rng.normal(0, noise))


def make_trace(ratio, i_ref, rng):
    """Return the raw current array (A/cm2) for one strip."""
    amp_ref = i_ref * 1e-6                       # internal reference peak, uA -> A
    amp_mb = max(0.05, float(ratio)) * i_ref * 1e-6
    # a gently sloping background: real DPV baselines are smooth, and a smooth
    # one lets the envelope fit recover the peaks almost exactly.  The old
    # exponential was so steep that a quartic could not follow it and the
    # extracted ratio carried 20-60% error, which swamped the demo signal.
    base = 4.0e-6 + 5.0e-6 * (E_START - GRID) / (E_START - E_STOP)
    return (base
            - amp_mb * _gauss(GRID, -0.34, 0.055)
            - amp_ref * _gauss(GRID, 0.35, 0.075)
            + rng.normal(0, 7.0e-8, len(GRID)))


def write_cor(path: Path, I, stamp):
    lines = [
        "CORRW ASCII",
        "CorrTest for Windows: SN CS350H1907339 V5.6.1201.2",
        "ID_DiffPulseVA",
        "Data:%s Time:%s" % stamp,
        "ExpParmas:InitialE=0.8&-&FinalE=-0.8&-&IncE=0.02&-&Amplitude=0.06"
        "&-&PulseWidth=0.05&-&PulsePeriod=0.5&-&QuietTime=2&-&Sensitivity=1e-5"
        "&-&Area=1&-&REValue=0.241",
        "Open Circuit Potential (V):0.241",
        "E(V)\t\ti(A/cm^2)\t\tT(s)",
        "End Comments",
    ]
    for k, e in enumerate(GRID):
        lines.append("%.4f\t%.6e\t%.3f" % (e, I[k], 0.5 * k))
    path.write_text("\r\n".join(lines), encoding="latin-1")


def _write_meta(out_dir: Path, rows):
    meta = out_dir / "metadata.csv"
    # csv.writer, not ",".join -- the note column contains commas
    with open(meta, "w", newline="", encoding="utf-8-sig") as fh:
        csv.writer(fh).writerows(rows)


def build(out_dir: Path, seed: int = 7, verbose: bool = True):
    """One batch: 3 blanks + 6 concentrations x 3 electrodes + 2 unknowns."""
    rng = np.random.default_rng(seed)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [HEAD]

    def emit(name, group, conc, label, role, note="", hide=False):
        i_ref = max(0.4, rng.normal(2.2, 0.35))
        I = make_trace(response(conc, rng), i_ref, rng)
        write_cor(out_dir / name, I, ("2026-10-10", "20:%02d:00" % (len(rows) % 60)))
        rows.append((name, group, "" if hide else "%.3e" % conc,
                     name.rsplit(".", 1)[0], "demo", label, role, note))

    for i in range(1, 4):
        emit("demo_blank_%02d.cor" % i, "blank", 0.0, 0, "blank", "no target, with enzyme")

    for li, C in enumerate(LEVELS):
        for j in range(1, 4):
            emit("demo_std_%d_%02d.cor" % (li + 1, j), "standard", C, 1, "standard",
                 "%.0e M streptomycin" % C)

    for name, truth in UNKNOWNS:
        emit(name + ".cor", "sample", truth, "", "sample",
             "unknown, truth %.1e M" % truth, hide=True)

    _write_meta(out_dir, rows)
    if verbose:
        print("wrote %d .cor files + metadata.csv to %s" % (len(rows) - 1, out_dir))
        print("TRUTH for the two unknowns: %s" % ", ".join("%s = %.1e M" % u for u in UNKNOWNS))
    return out_dir


def build_batches(out_dir: Path, seed: int = 11, n_batches: int = 3, verbose: bool = True):
    """Several batches, each with its own offset and electrode gain.

    This is the situation docs/跨批次分析.md describes: the chemical slope is
    real, but a constant per-batch offset makes one pooled line useless.
    """
    rng = np.random.default_rng(seed)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [HEAD]
    truth = {}

    # fixed offsets, not random draws: the demo has to SHOW the batch problem, and
    # random draws on one seed can land all three batches on top of each other.
    SHIFTS = [-0.22, 0.02, 0.22]
    GAINS = [0.88, 1.06, 0.96]
    for bi in range(1, n_batches + 1):
        batch = "B%d" % bi
        shift = SHIFTS[(bi - 1) % len(SHIFTS)]   # absolute offset of the response
        gain = GAINS[(bi - 1) % len(GAINS)]      # electrode-scale drift
        stamp = ("2026-11-%02d" % bi, "10:%02d:00" % bi)

        def emit(name, group, conc, label, role, note="", hide=False,
                 _b=batch, _s=shift, _g=gain, _st=stamp):
            i_ref = max(0.4, rng.normal(2.2, 0.35) * _g)
            I = make_trace(response(conc, rng, shift=_s), i_ref, rng)
            write_cor(out_dir / name, I, _st)
            rows.append((name, group, "" if hide else "%.3e" % conc,
                         name.rsplit(".", 1)[0], _b, label, role, note))
            if hide:
                truth[name] = conc

        # 5 blanks, not 3: the LOD comes from the blank SD, and with n=3 that
        # estimate swings by a decade between batches, which looks like a bug.
        for i in range(1, 6):
            emit("%s_blank_%02d.cor" % (batch, i), "blank", 0.0, 0, "blank",
                 "no target, with enzyme")
        for li, C in enumerate(BATCH_LEVELS):
            for j in range(1, 4):
                emit("%s_std_%d_%02d.cor" % (batch, li + 1, j), "standard", C, 1, "standard",
                     "%.0e M streptomycin" % C)
        for name, t in BATCH_UNKNOWNS:
            emit("%s_%s.cor" % (batch, name), "sample", t, "", "sample",
                 "unknown, truth %.1e M" % t, hide=True)

    _write_meta(out_dir, rows)
    if verbose:
        print("wrote %d .cor files in %d batches + metadata.csv to %s"
              % (len(rows) - 1, n_batches, out_dir))
        print("TRUTH for the unknowns: %s"
              % ", ".join("%s = %.1e M" % kv for kv in list(truth.items())[:4]))
    return out_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--mode", choices=["single", "batches"], default="single")
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()
    if a.mode == "batches":
        build_batches(Path(a.out or "data/demo_batches"), seed=a.seed or 11)
    else:
        build(Path(a.out or "data/demo"), seed=a.seed or 7)


if __name__ == "__main__":
    main()
