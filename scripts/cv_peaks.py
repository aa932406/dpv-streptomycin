"""CV (.cor) reader: split the sweeps, find the peaks, report ipa/ipc.

The CHI export writes one flat table of E, I, T; the branches (forward/reverse)
are only implied by the direction the potential moves.  A file can hold several
cycles (the last row of each carries a trailing "  N CYCLE"), so the reader
splits on direction changes and keeps the last complete cycle by default.

Everything is baseline-corrected the same way: a straight line through the two
ends of the branch, subtracted before the peak is read.  Without that, the
capacitive current makes the "peak" simply the point furthest from zero.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np


def _params(line):
    out = {}
    if not line.startswith("ExpParmas:"):
        return out
    for chunk in line[len("ExpParmas:"):].split("&-&"):
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def read_cv(path):
    """Parse a CHI .cor CV file into branches.

    Returns {file, scan_rate_mV_s, e_lo, e_hi, cycles, branches[]} where each
    branch is {dir, E, I} with I in uA.
    """
    path = Path(path)
    raw = path.read_bytes().decode("latin-1")
    lines = raw.splitlines()
    parms = {}
    e_lo = e_hi = None
    start = None
    technique = ""
    for i, ln in enumerate(lines):
        if ln.startswith("ID_") and not technique:
            technique = ln.strip()
        if ln.startswith("ExpParmas:"):
            parms = _params(ln)
        if ln.strip().startswith("E(V)") or ln.strip().startswith("Potential"):
            start = i + 1
            break
    if start is None:
        raise ValueError("%s: no data header (E(V)) -- is this a CV file?" % path.name)

    E, I, T = [], [], []
    for ln in lines[start:]:
        s = ln.strip()
        if not s or s.startswith("End"):
            continue
        parts = s.replace("  ", " ").split()
        if len(parts) < 2:
            continue
        try:
            e = float(parts[0]); cur = float(parts[1])
        except ValueError:
            continue
        t = float(parts[2]) if len(parts) > 2 and parts[2].replace(".", "").replace("-", "").isdigit() else np.nan
        E.append(e); I.append(cur * 1e6); T.append(t)
    if len(E) < 20:
        raise ValueError("%s: only %d data rows" % (path.name, len(E)))

    E = np.asarray(E); I = np.asarray(I); T = np.asarray(T)
    e_lo, e_hi = float(np.min(E)), float(np.max(E))

    # split on potential-direction changes (a flat stretch does not count)
    d = np.diff(E)
    step = max(1e-9, float(np.median(np.abs(d[d != 0]))) if np.any(d != 0) else 1e-9)
    sign = np.sign(np.where(np.abs(d) < step * 0.1, 0, d))
    branches = []
    i0 = 0
    cur_sign = 0
    for i, s in enumerate(sign):
        if s == 0:
            continue
        if cur_sign == 0:
            cur_sign = s
        elif s != cur_sign:
            if i - i0 >= 8:
                branches.append({"dir": int(cur_sign), "E": E[i0:i + 1], "I": I[i0:i + 1]})
            i0 = i
            cur_sign = s
    if len(E) - i0 >= 8:
        branches.append({"dir": int(cur_sign), "E": E[i0:], "I": I[i0:]})

    try:
        rate = float(parms.get("ScanRate", "nan"))
    except ValueError:
        rate = float("nan")

    return {"file": path.name, "technique": technique, "scan_rate_mV_s": rate, "e_lo": e_lo, "e_hi": e_hi,
            "cycles": int(float(parms.get("Cycles", 0) or 0)),
            "branches": branches, "n_points": int(len(E))}


def _pick_peak(E, I, direction, win=None):
    """Local maximum (forward) / minimum (reverse) with the flanking-valley baseline.

    The baseline is the straight line joining the two valleys either side of the
    peak -- that is the usual "extrapolated charging current" reading, and it is
    what peak_prominences uses to decide a peak is real.  A raw argmax would
    just return the end of the sweep, where the capacitive current is largest.
    """
    from scipy.signal import find_peaks, peak_prominences

    if win:
        lo, hi = min(win), max(win)
        m = (E >= lo) & (E <= hi)
        if m.sum() >= 12:
            E, I = E[m], I[m]
    if len(E) < 12:
        return None
    sig = I if direction > 0 else -I
    span = float(np.max(sig) - np.min(sig))
    prom = max(0.05, 0.01 * span)
    idx, _ = find_peaks(sig, prominence=prom)
    if len(idx) == 0:
        return None
    prom_all = peak_prominences(sig, idx)
    best = int(np.argmax(prom_all[0]))
    k = int(idx[best])
    lb, rb = int(prom_all[1][best]), int(prom_all[2][best])
    if rb <= lb:
        base = float(sig[k])
    else:
        base = float(np.interp(k, [lb, rb], [sig[lb], sig[rb]]))
    height = float(sig[k] - base)
    return {"i_uA": height if direction > 0 else -height,
            "e_v": float(E[k]), "i_raw_uA": float(I[k]),
            "n_peaks": int(len(idx))}


def peaks(branch, win=None):
    """Baseline-corrected peak of one branch, in uA and V."""
    return _pick_peak(branch["E"], branch["I"], branch["dir"], win)


def _branch_table(E, I, direction, win=None, top=3):
    """All peaks above the noise, strongest first -- useful when the trace is messy."""
    from scipy.signal import find_peaks, peak_prominences

    if win:
        lo, hi = min(win), max(win)
        m = (E >= lo) & (E <= hi)
        if m.sum() >= 12:
            E, I = E[m], I[m]
    sig = I if direction > 0 else -I
    span = float(np.max(sig) - np.min(sig))
    idx, _ = find_peaks(sig, prominence=max(0.05, 0.01 * span))
    if len(idx) == 0:
        return []
    pr = peak_prominences(sig, idx)
    out = []
    for j in np.argsort(-pr[0])[:top]:
        k = int(idx[j])
        lb, rb = int(pr[1][j]), int(pr[2][j])
        base = float(np.interp(k, [lb, rb], [sig[lb], sig[rb]])) if rb > lb else float(sig[k])
        out.append({"e_v": float(E[k]), "i_uA": float(sig[k] - base) * (1 if direction > 0 else -1),
                    "prom_uA": float(pr[0][j])})
    return out


def summarise(path, win=None, cycle="last"):
    """One CV file -> {scan_rate, ipa, epa, ipc, epc, dEp}."""
    d = read_cv(path)
    if d["technique"] and d["technique"] != "ID_CV":
        return {"file": d["file"], "error": "这不是 CV 文件（%s）" % d["technique"]}
    br = d["branches"]
    if not br:
        return {"file": d["file"], "error": "没有解析出扫描支（数据太短或电位没变化）"}
    fwd = [b for b in br if b["dir"] > 0]
    rev = [b for b in br if b["dir"] < 0]
    if not fwd or not rev:
        return {"file": d["file"], "error": "只有单向扫描，不是 CV（DPV/LSV 用别的页面看）"}
    if cycle == "last":
        fwd = fwd[-1:]
        rev = rev[-1:]
    pa = peaks(fwd[0], win) if fwd else None
    pc = peaks(rev[0], win) if rev else None
    out = {"file": d["file"], "scan_rate_mV_s": d["scan_rate_mV_s"],
           "e_lo": d["e_lo"], "e_hi": d["e_hi"], "n_branches": len(br),
           "n_points": d["n_points"]}
    if pa:
        out.update(ipa_uA=pa["i_uA"], epa_v=pa["e_v"])
    if pc:
        out.update(ipc_uA=pc["i_uA"], epc_v=pc["e_v"])
    if pa and pc:
        out["dEp_mV"] = abs(pa["e_v"] - pc["e_v"]) * 1000.0
    return out


def main():
    # "--win -0.1,0.6" reads as an option to argparse; join it back to --win=...
    argv = []
    i = 0
    while i < len(sys.argv):
        if sys.argv[i] == "--win" and i + 1 < len(sys.argv):
            argv.append("--win=" + sys.argv[i + 1])
            i += 2
            continue
        argv.append(sys.argv[i])
        i += 1
    ap = argparse.ArgumentParser(description="CV 峰电流读取")
    ap.add_argument("--data", required=True, help="文件夹或单个 .cor 文件")
    ap.add_argument("--win", default=None, help="只在这个电位窗里找峰，例如 -0.1,0.5")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv[1:])
    win = None
    if a.win:
        win = tuple(float(x) for x in a.win.split(","))
    p = Path(a.data)
    files = sorted(p.glob("*.cor")) if p.is_dir() else [p]
    rows = []
    for f in files:
        try:
            d = read_cv(f)
        except Exception:
            continue
        if d.get("technique") not in ("", "ID_CV"):
            continue
        if not d["branches"]:
            continue
        r = summarise(f, win)
        if "error" not in r:
            rows.append(r)
    if not rows:
        raise SystemExit("没找到 CV 文件（数据表头是 E(V) 且电位有正反两个方向）")
    if a.json:
        import json
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return
    print("%-34s %8s %9s %8s %9s %8s %8s" % ("文件", "扫速", "ipa(µA)", "Epa(V)", "ipc(µA)", "Epc(V)", "ΔEp(mV)"))
    for r in rows:
        print("%-34s %8.0f %9.2f %8.3f %9.2f %8.3f %8.0f" % (
            r["file"][:34], r.get("scan_rate_mV_s", float("nan")),
            r.get("ipa_uA", float("nan")), r.get("epa_v", float("nan")),
            r.get("ipc_uA", float("nan")), r.get("epc_v", float("nan")),
            r.get("dEp_mV", float("nan"))))


if __name__ == "__main__":
    main()
