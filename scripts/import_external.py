#!/usr/bin/env python
"""Import an EXTERNAL dataset into our own .cor layout.

Source: https://github.com/miralab-ai/biosensors-AI (MIT) -- 60 DPV curves of
CD36 on an anti-CD36 immunosensor, 12 levels x 5 replicates.

Why bother: the point is to prove our tool chain can eat somebody else's files.
The xlsx are converted to the CHI "CORRW ASCII" text that the rest of the
project already parses, and a metadata.csv is written next to them, so the
folder shows up in the web UI like any of our own measurement days.

One honest caveat, written into every note field: the paper reports the
concentration in ng/mL.  Our pipeline speaks molarity, so ng/mL is converted
with a CD36 molar mass of 80 kDa.  That number is an assumption (CD36 is
78-88 kDa); if the paper means ng per assay rather than ng/mL, every molarity
here is off by a constant factor -- the SHAPE of the curve and every R^2 are
unaffected, only the absolute axis moves.

Usage:
    python scripts/import_external.py --src /path/to/lab_measurements \
        --out data/cd36_ngml
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import numpy as np

# 80 kDa: CD36 is 78-88 kDa depending on glycosylation.  Only affects the
# absolute molarity, never the goodness of fit.
CD36_MW_G_PER_MOL = 80000.0

LEVELS = {
    "0 ng": 0.0, "0.005 ng": 0.005, "0.010 ng": 0.010, "0.025 ng": 0.025,
    "0.035 ng": 0.035, "0.050 ng": 0.050, "01 ng": 1.0, "05 ng": 5.0,
    "10 ng": 10.0, "15 ng": 15.0, "20 ng": 20.0, "25 ng": 25.0,
}

HEAD = """CORRW ASCII
CorrTest for Windows: SN CS350H1907339 V5.6.1201.2
ID_DiffPulseVA
Data:{date} Time:12:00:00
ExpParmas:FileName={fname}&-&InitialE={e0:.5f}&-&FinalE={e1:.5f}&-&IncE={inc:.5f}&-&Amplitude=0.05&-&PulseWidth=0.05&-&PulsePeriod=0.5&-&Area=1
Open Circuit Potential (V):0.000
E(V)\t\ti(A/cm^2)\t\tT(s)
End Comments
"""


def ng_to_M(ng_per_mL: float) -> float:
    """ng/mL -> mol/L: 1 ng/mL = 1e-6 g/L, divided by the molar mass."""
    return float(ng_per_mL) * 1e-6 / CD36_MW_G_PER_MOL


def read_one(path) -> tuple:
    import pandas as pd

    df = pd.read_excel(path, sheet_name=0, header=0)
    e = pd.to_numeric(df.iloc[1:, 0], errors="coerce")
    i = pd.to_numeric(df.iloc[1:, 1], errors="coerce")
    ok = e.notna() & i.notna()
    return e[ok].values.astype(float), i[ok].values.astype(float)


def write_cor(dst, E, I_uA, fname, date):
    """I is written as A/cm^2 so the parser multiplies it back to uA."""
    lines = [HEAD.format(fname=fname, e0=E[0], e1=E[-1],
                         inc=float(np.median(np.abs(np.diff(E)))), date=date)]
    for k, (ev, iv) in enumerate(zip(E, I_uA)):
        lines.append("%.5f\t%.9e\t%.2f" % (ev, iv * 1e-6, k * 0.5))
    dst.write_text("\n".join(lines) + "\n", encoding="latin-1")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="the repo's data/lab_measurements")
    ap.add_argument("--out", default="data/cd36_ngml")
    ap.add_argument("--date", default="2026-10-27")
    args = ap.parse_args()

    src = Path(args.src)
    if not (src / "0 ng").is_dir():
        alt = src / "data" / "lab_measurements"
        if alt.is_dir():
            src = alt
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for folder in sorted(os.listdir(src)):
        d = src / folder
        if not d.is_dir() or folder not in LEVELS:
            continue
        level = LEVELS[folder]
        for k, fn in enumerate(sorted(f for f in os.listdir(d) if f.endswith(".xlsx")), 1):
            E, I = read_one(d / fn)
            name = "cd36_%s_r%d.cor" % (folder.replace(" ", "").replace(".", "p"), k)
            write_cor(out / name, E, I, name, args.date)
            rows.append({
                "file": name,
                "group": folder,
                "electrode": "%s#%d" % (folder, k),
                "concentration_M": "" if level == 0 else "%.6e" % ng_to_M(level),
                "batch": "biosensors-AI",
                "label": "0" if level == 0 else "1",
                "role": "material" if level == 0 else "standard",
                "note": ("external: miralab-ai/biosensors-AI, %g ng/mL, "
                         "M computed with MW 80 kDa" % level),
            })

    with open(out / "metadata.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote %d .cor + metadata.csv -> %s" % (len(rows), out))
    print("levels (M): %s" % ", ".join(
        "%.2e" % ng_to_M(v) for v in sorted(set(LEVELS.values())) if v > 0))


if __name__ == "__main__":
    main()
