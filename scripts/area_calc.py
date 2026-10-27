"""Working-electrode area from cyclic voltammetry (Randles-Sevcik).

The geometric area printed on a screen-printed electrode datasheet is not the
area the redox probe actually sees: printed carbon is porous and the effective
area typically runs 10-30 % higher.  Every paper that reports a sensitivity in
uA uM^-1 cm^-2 divides by *some* area, and when that number is a guess the
sensitivities stop being comparable.  This module measures it instead.

    ip = 2.69e5 * n^1.5 * A * sqrt(D) * C * sqrt(v)

ip in A, A in cm^2, D in cm^2/s, C in mol/cm^3, v in V/s.

So plot peak current against sqrt(v): the slope is
2.69e5 * n^1.5 * A * sqrt(D) * C and the area falls straight out of it.
The same plot also tells you whether the assumption holds -- if the peaks are
adsorbed rather than diffusing, ip is proportional to v, not sqrt(v), and the
Randles-Sevcik area is meaningless.
"""

from __future__ import annotations

import argparse
import json
import math

import numpy as np

RS_COEF = 2.69e5          # Randles-Sevcik constant, A per (cm^2 * sqrt(cm^2/s) * mol/cm^3 * sqrt(V/s))
D_DEFAULT = 7.6e-6        # ferricyanide in 0.1 M KCl, cm^2/s
MOL_PER_CM3_PER_MILLIMOLAR = 1e-6


def sevcik_uA(area_cm2, conc_mM, v_mV_s, n=1, d_cm2_s=D_DEFAULT):
    """Peak current of a reversible diffusing species, in uA."""
    c = float(conc_mM) * MOL_PER_CM3_PER_MILLIMOLAR
    v = float(v_mV_s) / 1000.0
    ip_a = RS_COEF * (n ** 1.5) * area_cm2 * math.sqrt(d_cm2_s) * c * math.sqrt(v)
    return ip_a * 1e6


def fit_area(points, conc_mM, n=1, d_cm2_s=D_DEFAULT):
    """Area from a table of (scan rate mV/s, peak current uA).

    Returns a dict with the fit, the area and any warnings that should stop the
    number from being quoted.
    """
    pts = [(float(v), float(ip)) for v, ip in points
           if v is not None and ip is not None and float(v) > 0]
    if len(pts) < 3:
        return {"error": "至少需要 3 个扫速（3 个点才能看出是不是直线），现在只有 %d 个。" % len(pts)}
    if conc_mM is None or float(conc_mM) <= 0:
        return {"error": "探针浓度必须大于 0（单位 mM）。"}
    if n is None or float(n) <= 0:
        return {"error": "电子数 n 必须大于 0。"}
    if d_cm2_s is None or float(d_cm2_s) <= 0:
        return {"error": "扩散系数必须大于 0。"}

    v = np.array([p[0] for p in pts], dtype=float)
    ip = np.array([p[1] for p in pts], dtype=float)
    if np.allclose(ip, ip[0]):
        return {"error": "所有扫速的峰电流都一样，这样的数据量不出面积。"}

    x = np.sqrt(v / 1000.0)                      # sqrt(V/s)
    slope, intercept = np.polyfit(x, ip, 1)
    pred = slope * x + intercept
    ss_res = float(np.sum((ip - pred) ** 2))
    ss_tot = float(np.sum((ip - ip.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # same points against v itself: adsorption control would fit better
    slope_v, intercept_v = np.polyfit(v, ip, 1)
    pred_v = slope_v * v + intercept_v
    ss_res_v = float(np.sum((ip - pred_v) ** 2))
    r2_v = 1.0 - ss_res_v / ss_tot if ss_tot > 0 else 0.0

    c = float(conc_mM) * MOL_PER_CM3_PER_MILLIMOLAR
    denom = RS_COEF * 1e6 * (float(n) ** 1.5) * math.sqrt(float(d_cm2_s)) * c
    area = slope / denom if denom > 0 else float("nan")

    warns = []
    if slope <= 0:
        warns.append("斜率是负的：峰电流随扫速升高反而下降，这不是扩散控制的伏安图，检查一下读的是不是同一个峰。")
    if r2 < 0.98:
        warns.append("ip 与 √v 的直线拟合 R² 只有 %.3f（低于 0.98）：面积会被低估或高估，先把 CV 重做干净再报。" % r2)
    if r2_v > r2:
        warns.append("ip 对 v 拟合（R² = %.3f）比对 √v（R² = %.3f）更好：这是吸附控制，不是扩散控制，"
                     "Randles-Ševčík 不适用 —— 面积要用表面覆盖度那套公式算，不能用这张表。" % (r2_v, r2))
    if math.isfinite(area) and not (0.001 <= area <= 5.0):
        warns.append("算出的面积 %.3g cm² 不合常理（丝网印刷电极通常 0.03-0.3 cm²）：检查单位 —— "
                     "浓度是 mM、扫速是 mV/s、峰电流是 µA 吗？" % area)

    return {
        "area_cm2": float(area),
        "slope_uA_per_sqrt_V_s": float(slope),
        "intercept_uA": float(intercept),
        "r2": float(r2),
        "r2_vs_v": float(r2_v),
        "n_points": len(pts),
        "conc_mM": float(conc_mM),
        "n_electrons": float(n),
        "d_cm2_s": float(d_cm2_s),
        "resid": [{"v_mV_s": float(a), "ip_uA": float(b), "pred_uA": float(p)}
                  for (a, b), p in zip(pts, pred)],
        "warnings": warns,
    }


def save_electrode(project_dir, area_cm2, model="", method="randles-sevcik", detail=None):
    """Persist the measured area so every later table uses the same number."""
    from pathlib import Path
    import datetime as _dt
    p = Path(project_dir) / "metadata" / "electrode.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {"model": model or "", "area_cm2": float(area_cm2), "method": method,
           "measured": _dt.date.today().isoformat(), "detail": detail or {}}
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return p, doc


def load_electrode(project_dir):
    from pathlib import Path
    p = Path(project_dir) / "metadata" / "electrode.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser(description="工作电极有效面积（Randles-Sevcik）")
    ap.add_argument("--conc", type=float, default=1.0, help="探针浓度 mM（铁氰化钾常用 1 或 5）")
    ap.add_argument("--v", required=True, help="扫速，逗号分隔，单位 mV/s，例如 20,50,100,200")
    ap.add_argument("--ip", required=True, help="对应峰电流，逗号分隔，单位 µA")
    ap.add_argument("--n", type=float, default=1.0, help="电子数（铁氰化钾 = 1）")
    ap.add_argument("--d", type=float, default=D_DEFAULT, help="扩散系数 cm^2/s")
    ap.add_argument("--save", action="store_true", help="保存到 metadata/electrode.json")
    a = ap.parse_args()

    vs = [float(x) for x in a.v.split(",") if x.strip()]
    ips = [float(x) for x in a.ip.split(",") if x.strip()]
    if len(vs) != len(ips):
        raise SystemExit("--v 和 --ip 的个数不一样：%d vs %d" % (len(vs), len(ips)))
    r = fit_area(list(zip(vs, ips)), a.conc, n=a.n, d_cm2_s=a.d)
    if r.get("error"):
        raise SystemExit(r["error"])
    print("扫速/峰电流：")
    for row in r["resid"]:
        print("  %6.0f mV/s  实测 %7.2f µA   拟合 %7.2f µA" % (row["v_mV_s"], row["ip_uA"], row["pred_uA"]))
    print("斜率 %.4g µA/√(V/s)   截距 %.3g µA   R² %.4f" % (
        r["slope_uA_per_sqrt_V_s"], r["intercept_uA"], r["r2"]))
    print("有效面积 A = %.4f cm²" % r["area_cm2"])
    for w in r["warnings"]:
        print("⚠ " + w)
    if a.save:
        from pathlib import Path
        p, _ = save_electrode(Path(__file__).resolve().parent.parent, r["area_cm2"], detail=r)
        print("已保存 ->", p)


if __name__ == "__main__":
    main()
