"""Synthetic ferricyanide CVs, so the area card can be tried before the real run.

The whole point of the demo is that the answer is known: the curves are built
from Randles-Sevcik with A = 0.0707 cm^2, so if the reader + fit come back with
0.0707 the chain works end to end.  A real electrode will land somewhere in
0.05-0.12 cm^2, not on this number.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

AREA_TRUE = 0.0707          # cm^2, 3 mm disc
CONC_M = 1e-3               # 1 mM ferricyanide
D_CM2_S = 7.6e-6
E_START, E_STOP = -0.20, 0.60
EPA, EPC = 0.235, 0.150     # V vs Ag/AgCl on a carbon SPE
WIDTH = 0.055               # Gaussian half-width of the peak shape


def sevcik_uA(v_mV_s):
    v = v_mV_s / 1000.0
    c = CONC_M * 1e-3       # mol/L -> mol/cm^3
    return 2.69e5 * 1.0 ** 1.5 * AREA_TRUE * np.sqrt(D_CM2_S) * c * np.sqrt(v) * 1e6


def trace(v_mV_s, rng, n=900):
    fwd_e = np.linspace(E_START, E_STOP, n)
    rev_e = np.linspace(E_STOP, E_START, n)
    ipa = sevcik_uA(v_mV_s)
    ipc = -0.95 * ipa
    charge = 0.9 * (v_mV_s / 100.0)      # uA of capacitive current at the turn
    # forward: anodic peak + a charging offset that grows with potential
    ia = ipa * np.exp(-0.5 * ((fwd_e - EPA) / WIDTH) ** 2) + charge * (fwd_e - E_START) / (E_STOP - E_START)
    # reverse: cathodic peak, charging offset flips sign
    ic = ipc * np.exp(-0.5 * ((rev_e - EPC) / WIDTH) ** 2) + charge * (1 - (E_STOP - rev_e) / (E_STOP - E_START))
    e = np.concatenate([fwd_e, rev_e])
    i = np.concatenate([ia, ic]) + rng.normal(0, 0.02, 2 * n)
    return e, i


def write_cor(path, v_mV_s, e, i):
    lines = [
        "CORRW ASCII",
        "CorrTest for Windows: SN CS350H1907339  V5.6.1201.2  2.5H6.221207",
        "ID_CV",
        "Data:2026-10-28   Time:09:00:00",
        ("ExpParmas:ExpType=ID_CV&-&StepVolt1=%.3f&-&StepVolt2=%.3f&-&Times=10&-&ScanRate=%.1f"
         "&-&ScanDirection=0&-&IsNCV=True&-&FileName=%s&-&Cycles=3&-&OcpValue=0.18"
         % (E_START, E_STOP, v_mV_s, path.name)),
        "Open Circuit Potential (V):0.1800",
        "",
        "Temperature(°C):   25",
        "E(V)\t\ti(A/cm^2)\t\tT(s)",
        "End Comments",
    ]
    dt = 1.0 / (v_mV_s / 1000.0) / (len(e) / 2)
    for k, (ee, ii) in enumerate(zip(e, i)):
        lines.append("%.5E\t%.5E\t%.4f" % (ee, ii * 1e-6, k * dt))
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")


def build(out_dir, seed=3):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    rows = ["file,group,concentration_M,batch,note"]
    for v in (20, 50, 100, 200):
        e, i = trace(v, rng)
        name = "CV_%03d.cor" % v
        write_cor(out / name, v, e, i)
        rows.append("%s,demo_cv,,demo_cv,ferricyanide 1 mM" % name)
    (out / "metadata.csv").write_text("\n".join(rows) + "\n", encoding="utf-8-sig")
    return out


def main():
    ap = argparse.ArgumentParser(description="生成 4 个扫速的演示 CV")
    ap.add_argument("--out", default="data/demo_cv")
    a = ap.parse_args()
    p = build(a.out)
    print("wrote", p, "true area %.4f cm^2" % AREA_TRUE)


if __name__ == "__main__":
    main()
