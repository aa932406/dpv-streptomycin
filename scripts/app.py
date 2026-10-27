#!/usr/bin/env python3
"""
app.py -- 链霉素 DPV 检测平台 (Streamlit)

Run:   streamlit run scripts/app.py
       or double-click run_web.bat

The UI is deliberately built around one question: 有没有链霉素？浓度是多少？
Everything else (curves, PCA, ANOVA, models) is evidence for that answer.
"""
from __future__ import annotations

import hashlib
import io
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(HERE))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from dpv_pipeline import (GRID, GROUP_ORDER, group_of, electrode_of,
                          baseline_envelope, resample, parse_cor_bytes)
import analysis_core as core
import figures as fg
import report as rp

UNITS = {"pM": 1e-12, "nM": 1e-9, "uM": 1e-6, "mM": 1e-3, "M": 1.0}
DATA_DIR = PROJECT / "data"


def show(fig):
    st.pyplot(fig)
    plt.close(fig)


def to_value_unit(c):
    if c is None or (isinstance(c, float) and not np.isfinite(c)):
        return np.nan, "nM"
    c = float(c)
    if c == 0:
        return 0.0, "nM"
    for u in ("pM", "nM", "uM", "mM", "M"):
        v = c / UNITS[u]
        if 1 <= v < 1000:
            return float(round(v, 4)), u
    return c / 1e-6, "uM"


def local_folders():
    if not DATA_DIR.is_dir():
        return []
    return [d for d in sorted(DATA_DIR.iterdir())
            if d.is_dir() and any(d.glob("*.cor"))]


def read_items(folder: Path):
    return [(p.name, p.read_bytes()) for p in sorted(folder.glob("*.cor"))]


@st.cache_data(show_spinner=False, max_entries=8)
def build_cached(items: tuple, order: int):
    return core.build_table(items, order=order)


@st.cache_data(show_spinner=False, max_entries=32)
def trace_parts(name: str, raw: bytes, order: int, grid=None):
    rec = parse_cor_bytes(name, raw)
    grid = GRID if grid is None else np.asarray(grid, dtype=float)
    I = resample(rec["E"], rec["I"], grid)
    base = baseline_envelope(grid, I, order=order)
    return I, base


def sidebar():
    st.sidebar.title("链霉素 DPV 检测平台")
    st.sidebar.caption("差分脉冲伏安 · 定性筛查 + 定量")

    folders = local_folders()
    opts = ["上传 .cor 文件"] + (["使用本地 data/ 文件夹"] if folders else [])
    src = st.sidebar.radio("数据来源", opts, index=1 if folders else 0)

    folder, uploads = None, None
    if src == "使用本地 data/ 文件夹":
        names = ["%s（%d 条）" % (d.name, len(list(d.glob("*.cor")))) for d in folders]
        # open on the newest *measured* folder: sorted() puts "demo" after every
        # date, so a plain index=-1 would greet the user with synthetic data
        default = len(names) - 1
        real = [i for i, d in enumerate(folders) if not d.name.startswith("demo")]
        if real:
            default = real[-1]
        pick = st.sidebar.selectbox("选择日期文件夹", names, index=default)
        folder = folders[names.index(pick)]
    else:
        uploads = st.sidebar.file_uploader("把 .cor 文件拖进来（可多选）",
                                          accept_multiple_files=True, type=["cor", "txt"])

    with st.sidebar.expander("分析参数", expanded=False):
        order = st.slider("基线拟合阶数", 2, 6, 4,
                          help="越高越贴合弯曲的基线，但会吃掉宽峰。默认 4。")
        ref_frac = st.slider("内参峰 QC 下限（占本批中位数的比例）", 0.0, 1.0, 0.35, 0.05,
                             help="内参峰低于「本批内参中位数 × 这个比例」判为电极制备不良，"
                                  "默认剔除。用相对值是因为内参峰本身在批次间会差 2-7 倍，"
                                  "固定的微安门槛在一个文件夹里一条不剔、在另一个里全剔。"
                                  "设 0 表示不剔除。")
        metric = st.selectbox("响应指标", ["ratio", "I_MB"], index=0,
                              format_func=lambda m: "I_MB / I_ref（推荐，可抵消电极面积差异）"
                              if m == "ratio" else "只用 I_MB")
        use_qc = st.checkbox("只用 QC 合格的曲线", value=True)

    st.sidebar.divider()
    if st.sidebar.button("生成演示数据（单批次）"):
        import make_demo_data
        make_demo_data.build(DATA_DIR / "demo", verbose=False)
        st.sidebar.success("已生成 data/demo/，请在上方切过去")
        st.rerun()
    if st.sidebar.button("生成演示数据（3 个批次）"):
        import make_demo_data
        make_demo_data.build_batches(DATA_DIR / "demo_batches", verbose=False)
        st.sidebar.success("已生成 data/demo_batches/，请在上方切过去")
        st.rerun()
    st.sidebar.caption("演示数据是**编造的**，只用来熟悉界面，不能写进论文。")

    return dict(folder=folder, uploads=uploads, order=order, ref_frac=ref_frac,
                metric=metric, use_qc=use_qc)


def load_prefill(folder):
    """Read concentration metadata: <data folder>/metadata.csv first, then
    <project>/metadata/metadata.csv.

    Only the folder-level file used to be read, so a metadata.csv filled in at
    the project level (metadata/metadata.csv, where the templates live) was
    silently ignored and every sample stayed "unknown".
    """
    cands = []
    if folder is not None:
        cands.append(folder / "metadata.csv")
    cands.append(PROJECT / "metadata" / "metadata.csv")
    for c in cands:
        if not c.exists():
            continue
        try:
            t = pd.read_csv(c)
        except Exception:
            continue
        if "file" not in t.columns:
            continue
        pre = {str(r["file"]): r.to_dict() for _, r in t.iterrows()}
        try:
            shown = str(c.relative_to(PROJECT))
        except Exception:
            shown = str(c)
        return pre, shown
    return {}, None


def get_items(p):
    if p["folder"] is not None:
        return read_items(p["folder"]), p["folder"]
    if p["uploads"]:
        return [(f.name, f.getvalue()) for f in p["uploads"]], None
    return None, None


def welcome():
    st.title("链霉素 DPV 检测平台")
    st.markdown("""
把电化学工作站导出的 **.cor** 文件拖进左侧，这个页面回答两个问题：

1. **这管样品里有没有链霉素？**
2. **如果有，浓度是多少？**

---
#### 开始之前
* 左侧选「上传 .cor 文件」，或选「使用本地 data/ 文件夹」。
* 想让「浓度」算出来，需要**校准数据**：至少 3 个不同浓度 × 3 支独立电极，外加 ≥3 支空白。
* 还没有校准数据？点左下角 **生成演示数据**，先用合成数据把界面走一遍。
""")
    st.info("文件名可以随意；分组和浓度在页面表格里直接改，不用准备 CSV。")


def meta_editor(df, sig):
    rows = []
    for _, r in df.iterrows():
        val, unit = to_value_unit(r.get("concentration_M", np.nan))
        # a blank cell must stay blank: a NumberColumn in Streamlit 1.66 prints
        # NaN as the word "None", which reads like a value in the table
        txt = "" if not np.isfinite(val) else ("%g" % float(val))
        row = {"文件": r["file"], "分组": r["group"], "浓度数值": txt,
               "单位": unit, "电极": r["electrode"],
               "QC": "✓" if r["qc_pass"] else "✗"}
        if "batch" in df.columns:
            row["批次"] = str(r.get("batch") or "")
        if "label" in df.columns:
            lb = r.get("label")
            row["标签"] = "" if lb is None or (isinstance(lb, float) and not np.isfinite(lb)) else str(int(lb))
        if "role" in df.columns:
            row["角色"] = str(r.get("role") or "")
        rows.append(row)
    ed = pd.DataFrame(rows)

    groups = [g for g in dict.fromkeys(list(ed["分组"]) + GROUP_ORDER) if g != "unknown"]
    if "unknown" in set(ed["分组"]):
        groups.append("unknown")

    st.markdown("##### 数据表　<span style='font-size:13px;color:#666'>"
                "分组和浓度直接在这里改；浓度留空 = 当成未知样品去预测</span>",
                unsafe_allow_html=True)
    cfg = {
        "文件": st.column_config.TextColumn("文件", disabled=True),
        "分组": st.column_config.SelectboxColumn("分组", options=groups, required=True),
        "浓度数值": st.column_config.TextColumn("浓度数值",
                                              help="填数字，单位看右边「单位」列（两者相乘）。0 = 空白对照；留空 = 未知样品"),
        "单位": st.column_config.SelectboxColumn("单位", options=list(UNITS), default="nM"),
        "电极": st.column_config.TextColumn("电极", disabled=True,
                                         help="同一支电极重复扫描必须同名，否则交叉验证会虚高"),
        "QC": st.column_config.TextColumn("QC", disabled=True, width="small",
                                       help="✓ 内参峰足够大，参与分析；✗ 电极制备不良，已剔除"),
    }
    if "batch" in ed.columns:
        cfg["批次"] = st.column_config.TextColumn(
            "批次", help="同一天做的电极填同一个批次名。按批标定靠它把批次偏移扣掉。")
    if "label" in ed.columns:
        cfg["标签"] = st.column_config.TextColumn(
            "标签", help="1 = 有链霉素，0 = 无链霉素（阴性对照），留空 = 不知道。填了就不用靠组名猜。")
    if "role" in ed.columns:
        cfg["角色"] = st.column_config.TextColumn("角色", disabled=True,
                                               help="blank / standard / sample，来自 metadata.csv")
    edited = st.data_editor(ed, key="meta_" + sig, hide_index=True, column_config=cfg)
    raw = edited["浓度数值"].astype(str).str.strip()
    num = pd.to_numeric(raw, errors="coerce")
    bad = raw.ne("") & raw.ne("nan") & num.isna()
    if bool(bad.any()):
        st.warning("这些行的浓度填的不是数字，已按「未知样品」处理：%s"
                   % ", ".join(raw[bad].unique()[:5]))
    unit = edited["单位"].map(UNITS).astype(float).fillna(1e-9)
    conc = num.astype(float) * unit

    # Show what the numbers actually became.  "1e-6" with the default unit nM is
    # 1e-15 M -- a factor of a billion off -- and nothing on screen said so.
    pos = conc[conc > 0]
    nb = int((conc == 0).sum())
    if len(pos) or nb:
        lv = np.unique(np.round(pos.values.astype(float), 20)) if len(pos) else []
        shown = ("：" + ", ".join("%.2e M" % v for v in lv[:6])
                 + (" ..." if len(lv) > 6 else "")) if len(lv) else ""
        st.caption("按现在的填法：空白 %d 支、标准点 %d 支（%d 个不同浓度%s）、待测 %d 支"
                   % (nb, len(pos), len(lv), shown, int(conc.isna().sum())))
        if len(lv) == 1 and len(pos) >= 2:
            st.warning("**所有标准点都是同一个浓度（%.2e M）。** 校准曲线要的是一串不同浓度，"
                       "把每一行填成同一个数算不出斜率 —— 至少需要 3 个不同浓度。" % lv[0])
        if len(lv) and float(np.min(lv)) < 1e-14:
            st.warning("最小浓度算出来是 %.2e M，低得不像真的。检查「单位」列："
                       "数值会和单位相乘，1e-6 配 nM 就是 1e-15 M。" % float(np.min(lv)))

    out = pd.DataFrame({"file": edited["文件"].values, "group": edited["分组"].values,
                        "electrode": edited["电极"].values, "concentration_M": conc.values})
    if "批次" in edited.columns:
        out["batch"] = edited["批次"].astype(str).str.strip().values
    if "标签" in edited.columns:
        out["label"] = pd.to_numeric(edited["标签"].astype(str).str.strip(),
                                     errors="coerce").values
    if "角色" in edited.columns:
        out["role"] = edited["角色"].astype(str).str.strip().values
    return out


def verdict_card(name, v):
    color = {"positive": "#cf222e", "negative": "#1a7f37", "unknown": "#9a6700"}[v["verdict"]]
    label = {"positive": "检出", "negative": "未检出", "unknown": "无法判定"}[v["verdict"]]
    with st.container(border=True):
        c1, c2 = st.columns([1, 3.2])
        with c1:
            st.markdown(
                "<div style='font-size:12px;color:#666;word-break:break-all'>%s</div>"
                "<div style='font-size:30px;font-weight:700;color:%s;line-height:1.15'>%s</div>"
                % (name, color, label), unsafe_allow_html=True)
        with c2:
            pr = v.get("prediction")
            big = ("<div style='font-size:26px;font-weight:600;margin-top:2px'>%s</div>"
                   % core.format_conc(pr["C"])) if pr else ""
            st.markdown("<div style='margin-top:8px;font-size:14px'>%s</div>%s"
                        % (v["detail"], big), unsafe_allow_html=True)


def missing_for_calibration(work):
    msgs = []
    if "concentration_M" not in work:
        return ["没有浓度列"]
    c = work["concentration_M"]
    nb = int((c == 0).sum())
    if nb < 3:
        msgs.append("**空白对照**：需要 ≥3 支 0 浓度电极，现在 %d 支 —— LOD 必须靠空白的 3σ 才站得住" % nb)
    lv = sorted(c[c > 0].dropna().unique())
    if len(lv) < 3:
        msgs.append("**浓度梯度**：需要 ≥3 个不同浓度，现在 %d 个%s"
                    % (len(lv), ("（%s）" % ", ".join("%.1e" % v for v in lv)) if lv else ""))
    ne = work["electrode"].nunique()
    if ne < 6:
        msgs.append("**独立电极**：现在 %d 支。少于 6 支时任何准确率都没有统计意义" % ne)
    return msgs


def explain_fit_error(err):
    e = str(err)
    if e.startswith("no row has a concentration"):
        return ("一个浓度都没读到：数据表里没填，也没在 metadata/metadata.csv 里找到。"
                "把标准点的浓度填进「浓度数值」列（空白对照填 0），未知样品留空。")
    if e.startswith("need at least 4 standards"):
        return "填了浓度的标准点不够 4 个。把每一支标液的浓度填进「浓度数值」列（空白填 0）。"
    if (e.startswith("need at least 3 different concentrations")
            or e.startswith("calibration needs at least 3 distinct")):
        m = re.search(r"have \d+ \(([^)]*)\)", e)
        got = (" —— 现在填的全是 %s" % m.group(1)) if m else ""
        return ("**浓度是填上了，但填的都是同一个值%s。** 校准曲线要的是一串"
                "「不同浓度 → 不同信号」的点，光把每一行填上数字建不出斜率。"
                "至少需要 3 个不同浓度，每个浓度 3 支独立电极，外加 ≥3 支空白。"
                "（另外看一眼表格里「单位」那一列：数值会和单位相乘，填 1e-6 而单位是 nM，"
                "实际就是 1e-15 M。）" % got)
    if e.startswith("calibration is not usable"):
        return "响应和浓度几乎没关系（拟合不出斜率），这批数据还定量不了。"
    return e


MATERIAL_HINTS = ("material", "blank", "空白", "control", "缓冲", "buffer")


def _name_hints(g):
    """Read a group name into (has target, no target, has enzyme, no enzyme).
    Chinese and English, and the negated forms win: '无靶标' contains '靶标'
    and 'noenz' contains 'enz'."""
    s = str(g).lower()
    no_t = any(h in s for h in ("no target", "notarget", "无靶标", "无靶", "无目标"))
    no_e = any(h in s for h in ("noenz", "no enz", "no-enzyme", "无酶"))
    has_t = any(h in s for h in ("target", "靶标", "有目标", "有靶"))
    has_e = any(h in s for h in ("enz", "酶"))
    return (has_t and not no_t), no_t, (has_e and not no_e), no_e


def _guess_groups(groups, label_map=None):
    """Default for the two selectboxes -- the user can always change it.

    The positive sample is the full assay (target + enzyme).  The negative
    control is a group WITHOUT the target that keeps the SAME enzyme state, so
    that the comparison isolates the target instead of confounding two things.

    An explicit label column (1 = has the analyte, 0 = does not) always wins over
    guessing from the group name -- a name can only ever be a hint."""
    if label_map:
        pos_l = [i for i, g in enumerate(groups) if label_map.get(g) == 1]
        neg_l = [i for i, g in enumerate(groups) if label_map.get(g) == 0]
        if pos_l and neg_l:
            return neg_l[0], pos_l[0]
    h = [_name_hints(g) for g in groups]
    low = [str(g).lower() for g in groups]

    pos = None
    for i, (has_t, _no_t, has_e, _no_e) in enumerate(h):
        if has_t and has_e:
            pos = i
            break
    if pos is None:
        for i, (has_t, _no_t, _has_e, _no_e) in enumerate(h):
            if has_t:
                pos = i
                break

    cand = [i for i, (_t, no_t, _e, _ne) in enumerate(h) if no_t]
    if not cand:
        cand = [i for i, g in enumerate(low) if any(k in g for k in MATERIAL_HINTS)]
    if pos is not None and cand:
        same = [i for i in cand if h[i][2] == h[pos][2]]
        pool = same or cand
    else:
        pool = cand
    neg = min(pool, key=lambda i: (len(low[i]), i)) if pool else 0
    if pos is None:
        pos = next((i for i in range(len(groups)) if i != neg), 0)
    return neg, pos


def tab_screening(work, metric, samples):
    """No calibration gradient?  Still answer the question that matters most:
    is the analyte there or not."""
    st.markdown("#### 定性筛查：这批数据能回答「有没有」")
    st.caption("没有浓度梯度也能做。拿阴性对照和阳性样品比信号，定一条截断值，"
               "新样品越过它就算检出。**只能给检出/未检出，给不出浓度。**")
    groups = [g for g in work["group"].dropna().unique().tolist()]
    if len(groups) < 2:
        st.info("这批数据只有一个分组，没有对照可比。")
        return
    label_map = {}
    if "label" in work.columns:
        for g, sub in work.groupby("group"):
            v = pd.to_numeric(sub["label"], errors="coerce").dropna()
            if len(v):
                label_map[g] = int(v.mode().iloc[0])
    gi_neg, gi_pos = _guess_groups(groups, label_map)
    if label_map:
        st.caption("分组用的是数据表「标签」列："
                   + "，".join("%s=%d" % (g, label_map[g]) for g in groups if g in label_map))
    c1, c2, c3 = st.columns([1.3, 1.3, 1])
    neg = c1.selectbox("阴性对照（不含链霉素）", groups, index=gi_neg, key="scr_neg")
    pos = c2.selectbox("阳性样品（含链霉素）", groups, index=gi_pos, key="scr_pos")
    k = c3.number_input("截断值 = 空白均值 ± k×SD", 1.0, 10.0, 3.0, 0.5, key="scr_k")
    # how many independent electrodes each group can offer -- with 2 per group
    # no test can reach p < 0.05, so show it before the user picks.
    cnt = work.dropna(subset=["group"]).groupby("group")["electrode"].nunique()
    st.caption("各组独立电极数：" + " ｜ ".join("%s %d 支" % (g, int(cnt.get(g, 0)))
                                                   for g in groups))
    if neg == pos:
        st.info("两个下拉选了同一组，换一个再比。")
        return
    sc = core.screening_test(work, neg, pos, metric=metric, k=float(k))
    if "error" in sc:
        st.warning(sc["error"])
        return

    mname = core.METRIC_CN.get(metric, metric)
    m = st.columns(4)
    m[0].metric("信号比", "%.2f×" % sc["ratio"] if np.isfinite(sc["ratio"]) else "n/a")
    m[1].metric("电极级 p 值", "%.3g" % sc["p"] if np.isfinite(sc["p"]) else "n/a")
    m[2].metric("效应量 d", "%.2f" % sc["effect_d"] if np.isfinite(sc["effect_d"]) else "n/a")
    m[3].metric("留一电极判别准确率", "%d%%" % round(sc["accuracy"] * 100) if sc.get("accuracy") is not None else "n/a")
    st.caption("%s：阴性 %s %.3g±%.3g µA（%d 支电极 / %d 条曲线）｜阳性 %s %.3g±%.3g µA"
               "（%d 支 / %d 条）｜响应方向：%s｜截断值 %.3g"
               % (mname, neg, sc["neg_mean"], sc["neg_sd"], sc["n_neg_elec"], sc["n_neg_scan"],
                  pos, sc["pos_mean"], sc["pos_sd"], sc["n_pos_elec"], sc["n_pos_scan"],
                  "信号开启" if sc["direction"] == "signal-on" else "信号关闭", sc["cutoff"]))

    if np.isfinite(sc.get("p_floor", np.nan)) and sc["p_floor"] > 0.05:
        st.info("阴性 %d 支 / 阳性 %d 支独立电极 —— 即使两组完全分开，Mann-Whitney 的"
                "最小 p 也只能到 **%.2f**，所以这里的 p 值证明不了什么。看信号比和效应量 d；"
                "要 p < 0.05，每组至少 4 支电极（5 支才稳）。"
                % (sc["n_neg_elec"], sc["n_pos_elec"], sc["p_floor"]))
    elif np.isfinite(sc["p"]) and sc["p"] > 0.05:
        st.warning("两组在统计上分不开（p = %.3g > 0.05）—— 这个指标不能用来判检出，"
                   "换一个响应指标，或者先解决信噪比问题。" % sc["p"])
    elif np.isfinite(sc["p"]):
        st.success("两组分得开（电极级 Mann-Whitney p = %.3g）。下面的截断值可以用。" % sc["p"])

    if not sc.get("separates", True):
        st.error("**这条截断值切不开两组**：%d / %d 支阴性对照被判成阳性，%d / %d 支阳性样品漏检。"
                 "空白的波动（SD %.3g）和两组之间的差（%.3g）是同一个量级，"
                 "3σ 截断值落到了 %.3g，根本没有可用的判别边界。"
                 "这不是程序问题 —— 是信噪比问题。先降噪（MCH/BSA 封闭、降低 H1/H2 浓度、"
                 "洗涤加 0.05%% Tween-20），把空白的 CV 从 40%% 压到 15%% 以下再谈判检出。"
                 % (sc["false_pos"], sc["n_neg_elec"], sc["missed"], sc["n_pos_elec"],
                    sc["neg_sd"], sc["gap"], sc["cutoff"]))
        st.caption("所以下面不列判定结果 —— 列了也是误导。换一个响应指标，或者调小 k 先看看趋势。")
        return

    if samples is not None and len(samples):
        rows = []
        for _, r in samples.iterrows():
            v = core.screen_sample(sc, r.get(metric))
            rows.append({"样品": r["file"], "判定": v["text"], "依据": v["detail"]})
        st.markdown("##### 未知样品的定性判定")
        st.dataframe(pd.DataFrame(rows), hide_index=True)
    st.caption("⚠️ 定性判定只是「有没有」，不是「多少」。要出浓度，必须有不同浓度的标准点。")


def tab_verdict(work, fit, samples, metric, fitb=None):
    st.subheader("结论")
    per_batch = bool(fitb) and not fitb.get("error")
    if fit.get("error") and not per_batch:
        st.warning("**现在还答不了「多少浓度」** —— 缺标准点，建不起校准曲线。")
        st.markdown("原因：%s" % explain_fit_error(fit["error"]))
        miss = missing_for_calibration(work)
        if miss:
            st.markdown("##### 差什么：")
            for m in miss:
                st.markdown("- " + m)
        st.divider()
        tab_screening(work, metric, samples)
        return

    if samples is not None and len(samples):
        for _, r in samples.iterrows():
            if per_batch:
                v = core.decide_batch(fitb, r[metric], r.get("batch"))
                verdict_card("%s（批次 %s）" % (r["file"], r.get("batch") or "—"), v)
            else:
                verdict_card(r["file"], core.decide(fit, r[metric]))
    else:
        st.info("数据表里没有留空浓度的行，所以没有待判定样品。"
                "把某一行的浓度清空，它就会被当成未知样品。")

    c = st.columns(4)
    if per_batch:
        lods = [b.get("LOD_M") for b in fitb["batches"] if b.get("LOD_M")]
        c[0].metric("校准 R²", "%.3f" % fitb["r2"])
        c[1].metric("检出限 LOD", core.format_conc_range(min(lods), max(lods)) if lods else "n/a")
        loqs = [b.get("LOQ_M") for b in fitb["batches"] if b.get("LOQ_M")]
        c[2].metric("定量限 LOQ", core.format_conc_range(min(loqs), max(loqs)) if loqs else "n/a")
        c[3].metric("响应方向", "信号关闭" if fitb["direction"] == "signal-off" else "信号开启")
        st.caption("按批标定：%d 个批次，每批用自己那天的标准点定截距。"
                   "把所有批次当成一条线时 R² 只有 %.3f —— 那个差就是批次偏移。"
                   % (fitb["n_batches"], fitb["pooled_r2"]))
        rl = fitb.get("rmse_log_lobo", np.nan)
        if rl is not None and np.isfinite(rl):
            st.caption("留一批次（斜率取自别的批、截距取自本批）的误差是 %.2f dex，"
                       "相当于浓度乘/除以 %.1f 倍。" % (rl, 10.0 ** float(rl)))
        if fitb.get("LOD_error"):
            st.warning("LOD 算不出来：" + fitb["LOD_error"])
    else:
        c[0].metric("校准 R²", "%.3f" % fit["r2"])
        c[1].metric("检出限 LOD", core.format_conc(fit.get("LOD_M")))
        c[2].metric("定量限 LOQ", core.format_conc(fit.get("LOQ_M")))
        c[3].metric("响应方向", "信号关闭" if fit["direction"] == "signal-off" else "信号开启")
        if fit.get("quality"):
            st.warning(fit["quality"])
        if fit.get("LOD_error"):
            st.warning("LOD 算不出来：" + fit["LOD_error"])


def tab_curves(df, curves, p, items_map, grid=None):
    st.subheader("曲线")
    show(fg.fig_traces(df, curves, grid=grid))
    show(fg.fig_mean_sd(df, curves, grid=grid))
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if "ratio" in core.metric_availability(df):
            show(fg.fig_ratio_scatter(df))
        else:
            st.info("这批数据的扫描窗口不包含 MB 峰（-0.34 V）或内参峰（+0.35 V），"
                    "比值散点画不出来。")
    with c2:
        fname = st.selectbox("看某一条曲线的原始数据", df["file"].tolist())
        raw = items_map.get(fname)
        if raw is not None:
            I, base = trace_parts(fname, raw, p["order"], tuple(grid) if grid is not None else None)
            show(fg.fig_raw_example(grid if grid is not None else GRID, I,
                                    (base - I) * 1e6, base, fname))


def tab_stats(work, metric):
    st.subheader("统计检验")
    st.caption("这里的 p 值只回答「这几组是不是不一样」，不回答「多少浓度」。")

    st.markdown("##### 各组汇总")
    st.dataframe(core.group_summary(work, "group", metric), hide_index=True)

    tab = core.group_stats(work, "group")
    if len(tab):
        st.markdown("##### 单因素 ANOVA")
        t2 = tab.copy()
        t2["p"] = t2["p"].map(lambda v: "%.2e" % v)
        t2["F"] = t2["F"].map(lambda v: "%.2f" % v)
        t2["eta2"] = t2["eta2"].map(lambda v: "%.3f" % v)
        st.dataframe(t2, hide_index=True)
        ok = tab[np.isfinite(pd.to_numeric(tab["F"], errors="coerce"))]
        if len(ok):
            best = ok.sort_values("eta2", ascending=False).iloc[0]
            st.info("组间差异最大的是 **%s**（F = %.1f, p = %.2e, η² = %.2f）。η² > 0.14 算大效应。"
                    % (core.FEATURE_LABEL.get(best["feature"], best["feature"]),
                       best["F"], best["p"], best["eta2"]))
        else:
            st.info("所有指标的组内方差都是零，ANOVA 算不出来。")

    feats = [f for f in core.FEATURES if f in work.columns]
    feat = st.selectbox("看哪个指标的组间两两比较", feats,
                        index=feats.index(metric) if metric in feats else 0,
                        format_func=lambda f: core.FEATURE_LABEL.get(f, f))
    tk = core.tukey_table(work, "group", feat)
    if len(tk):
        st.markdown("##### Tukey HSD 两两比较")
        t3 = tk.copy()
        for c in ("diff", "lo", "hi"):
            t3[c] = t3[c].map(lambda v: "%.3f" % v)
        t3["p"] = t3["p"].map(lambda v: "%.2e" % v)
        t3["显著"] = tk["p"].map(lambda v: "是" if v < 0.05 else "否")
        st.dataframe(t3, hide_index=True)
    show(fg.fig_box(work, feat))


def tab_calibration(work, fit, samples, metric, fitb=None):
    st.subheader("校准与定量")
    per_batch = bool(fitb) and not fitb.get("error")
    if per_batch:
        st.markdown("##### 按批标定：每批用自己那天的标准点")
        c = st.columns(4)
        c[0].metric("合并 R²", "%.3f" % fitb["r2"])
        c[1].metric("全局单线 R²", "%.3f" % fitb["pooled_r2"])
        rl = fitb.get("rmse_log_lobo", np.nan)
        c[2].metric("留一批次 RMSE", ("%.2f dex" % rl) if rl is not None and np.isfinite(rl) else "n/a")
        lods = [b.get("LOD_M") for b in fitb["batches"] if b.get("LOD_M")]
        c[3].metric("各批 LOD", core.format_conc_range(min(lods), max(lods)) if lods else "n/a")
        st.dataframe(core.batch_table(fitb), hide_index=True)
        if len(lods) >= 2 and max(lods) > 3 * min(lods):
            st.caption("各批 LOD 差了 %.0f 倍（%s – %s）：LOD 由空白 SD 与斜率算出来，两者每批都不同。"
                       "这不是 bug —— 所以每批都得有自己的空白，不能用别的批的 LOD。"
                       % (max(lods) / min(lods), core.format_conc(min(lods)),
                          core.format_conc(max(lods))))
        if fitb.get("LOD_error"):
            st.warning("LOD 算不出来：" + fitb["LOD_error"])
        if samples is not None and len(samples):
            st.markdown("##### 未知样品（按样品所属批次算）")
            rows = []
            for _, r in samples.iterrows():
                pr = core.predict_concentration_batch(fitb, r[metric], r.get("batch"))
                if pr.get("error"):
                    rows.append({"文件": r["file"], "批次": r.get("batch") or "—",
                                 "响应": "%.3f" % r[metric], "浓度": "—", "区间": pr["error"]})
                else:
                    rows.append({"文件": r["file"], "批次": r.get("batch") or "—",
                                 "响应": "%.3f" % r[metric],
                                 "浓度": core.format_conc(pr["C"]),
                                 "区间": "%s – %s" % (core.format_conc(pr["C_lo"]),
                                                    core.format_conc(pr["C_hi"])),
                                 "用的截距": pr.get("batch_used") or "批次平均"})
            st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.divider()
        st.markdown("##### 对照：把所有批次当成一条校准线")

    if fit.get("error"):
        st.warning("**校准曲线还建不起来**：%s" % explain_fit_error(fit["error"]))
        if not per_batch:
            for m in missing_for_calibration(work):
                st.markdown("- " + m)
        st.markdown("""
##### 要补什么样的数据
| 项目 | 最低要求 | 说明 |
|---|---|---|
| 空白 | 3 支 0 浓度 | 没有空白就没有 LOD |
| 浓度梯度 | 6 个浓度，跨 3 个数量级 | 例如 10 pM → 1 uM |
| 独立电极 | 每个浓度 ≥3 支 | 重复扫描同一支电极不算 |
| 批次 | ≥2 个批次 | 否则无法验证批次迁移 |

详细排布见 **docs/数据采集方案_ML.md**。
""")
        return

    c = st.columns(4)
    c[0].metric("R²", "%.3f" % fit["r2"])
    c[1].metric("斜率", "%.3f /decade" % fit["b"])
    c[2].metric("LOD", core.format_conc(fit.get("LOD_M")))
    c[3].metric("LOQ", core.format_conc(fit.get("LOQ_M")))
    show(fg.fig_calibration(fit, work, metric))

    if samples is not None and len(samples):
        st.markdown("##### 未知样品")
        rows = []
        for _, r in samples.iterrows():
            pr = core.predict_concentration(fit, r[metric])
            if pr.get("error"):
                rows.append({"文件": r["file"], "响应": "%.3f" % r[metric], "浓度": "—", "区间": pr["error"]})
            else:
                rows.append({"文件": r["file"], "响应": "%.3f" % r[metric],
                             "浓度": core.format_conc(pr["C"]),
                             "区间": "%s – %s" % (core.format_conc(pr["C_lo"]),
                                                core.format_conc(pr["C_hi"]))})
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        pts = [(r["file"], r[metric], fg.PALETTE[i % len(fg.PALETTE)])
               for i, (_, r) in enumerate(samples.iterrows())]
        show(fg.fig_prediction(fit, pts, metric))
    else:
        st.info("没有待测样品。把某一行的浓度清空，它就会被当成未知样品预测。")


def tab_models(work, curves, metric, grid=None):
    st.subheader("建模")
    st.caption("留一电极交叉验证：同一支电极的多次扫描被强制分在同一折，否则准确率会虚高十几个点。")
    groups = work["group"].values
    if len(set(groups)) < 2:
        st.info("只有一个分组，没法做分类。")
        return

    n_pts = np.asarray(curves).shape[1] if curves is not None and len(curves) else 0
    kind = st.radio("输入", ["整条曲线（%d 点）" % n_pts, "手工特征"], horizontal=True)
    algo = st.radio("算法", ["LDA", "随机森林"], horizontal=True)
    k = "lda" if algo == "LDA" else "rf"

    if kind.startswith("整条"):
        X, names = np.asarray(curves), ["E=%.2f" % g for g in (grid if grid is not None else GRID)]
    else:
        feats = [f for f in core.FEATURES if f in work.columns and work[f].notna().all()]
        X, names = work[feats].values.astype(float), feats

    res = core.loeo_cv(X, groups, work["electrode"].values, kind=k)
    if "error" in res:
        st.warning(res["error"])
        return

    c1, c2 = st.columns([1, 1.3])
    with c1:
        st.metric("留一电极准确率", "%.1f%%" % (res["accuracy"] * 100))
        st.caption("%d 折 / %d 条曲线" % (res["n_folds"], res["n_scans"]))
        n_groups = len(set(res["y_true"]))
        chance = 1.0 / max(1, n_groups)
        if res["accuracy"] <= chance + 0.05:
            st.warning("准确率 %.1f%% 与瞎猜（%d 类 → %.1f%%）没有区别。"
                       "分组太多、每支电极的曲线太少时，分类器学不到东西 —— "
                       "这个数字不能拿来下结论。" % (res["accuracy"] * 100, n_groups, chance * 100))
        st.dataframe(pd.DataFrame({"真值": res["y_true"], "预测": res["y_pred"]}), hide_index=True)
    with c2:
        show(fg.fig_confusion(res))

    if st.button("跑置换检验（判断这个准确率是不是碰巧）"):
        with st.spinner("重排标签中…"):
            perm = core.permutation_test(X, groups, work["electrode"].values, kind=k, n_perm=150)
        if "error" in perm:
            st.warning(perm["error"])
        else:
            st.write("观测 %.1f%% ｜ 打乱后均值 %.1f%% ｜ 打乱后 95 分位 %.1f%% ｜ p = %.3f"
                     % (perm["observed"] * 100, perm["null_mean"] * 100,
                        perm["null_p95"] * 100, perm["p_value"]))
            show(fg.fig_permutation(perm))
            if perm["observed"] <= perm["null_p95"]:
                st.error("观测值没有超过打乱标签后的 95 分位 —— 这个准确率很可能是过拟合，别信。")

    if kind.startswith("手工"):
        show(fg.fig_importance(core.feature_importance(X, groups, names)))


def tab_export(work, fit, samples, figs, tables, metric, p, items):
    st.subheader("导出报告")
    st.caption("打包成 zip：Word + HTML 报告、所有图（PNG）、所有表（CSV）。")
    if st.button("生成报告包", type="primary"):
        kpis = [("样本数", str(len(work))),
                ("独立电极", str(work["electrode"].nunique())),
                ("分组", str(work["group"].nunique()))]
        if not fit.get("error"):
            kpis += [("校准 R²", "%.3f" % fit["r2"]), ("LOD", core.format_conc(fit.get("LOD_M")))]
        sections = []
        if fit.get("error"):
            sections.append(("无法定量的原因", "<p>%s</p>" % fit["error"]))
        else:
            sections.append(("校准参数",
                             "<p>响应 = %.4f + %.4f x log10(C)；R² = %.3f；方向：%s</p>"
                             % (fit["a"], fit["b"], fit["r2"],
                                "信号关闭" if fit["direction"] == "signal-off" else "信号开启")))
        summary = {"title": "链霉素 DPV 检测分析报告",
                   "subtitle": "共 %d 条曲线 / %d 支电极" % (len(work), work["electrode"].nunique()),
                   "kpis": kpis, "sections": sections, "warning": p.get("warning")}
        blob = rp.build_zip(summary, figs, tables, raw_files=dict(items))
        st.download_button("下载 报告.zip", data=blob, file_name="dpv_report.zip",
                           mime="application/zip", type="primary")
    st.divider()
    st.markdown("##### 这次用到的数据")
    st.dataframe(work[["file", "group", "electrode", "concentration_M", metric, "qc_pass"]]
                 .rename(columns={"concentration_M": "concentration (M)"}), hide_index=True)


CLEAN_CSS = """
<style>
#MainMenu, header[data-testid="stHeader"], footer {visibility: hidden; height: 0;}
.stDeployButton, [data-testid="stAppDeployButton"] {display: none !important;}
.block-container {padding-top: 2.2rem;}
</style>
"""


def main():
    st.set_page_config(page_title="链霉素 DPV 检测平台", page_icon="🧪", layout="wide")
    st.markdown(CLEAN_CSS, unsafe_allow_html=True)
    p = sidebar()

    items, folder = get_items(p)
    if not items:
        welcome()
        return

    sig = hashlib.md5(("|".join(n for n, _ in items) + str(len(items))).encode()).hexdigest()[:10]
    p["warning"] = ("当前载入的是**演示数据（合成）**，浓度是编出来的，"
                    "只能用来熟悉界面，不能用于任何结论。"
                    if folder is not None and folder.name.startswith("demo") else "")

    df, curves, errors, grid = build_cached(tuple(items), p["order"])
    if len(df) == 0:
        st.error("这些文件里没有解析出任何数据。")
        st.dataframe(pd.DataFrame(errors))
        return

    df["group"] = df["file"].map(group_of)
    df["electrode"] = df["file"].map(electrode_of)
    df = core.add_qc(df, ref_min=0.0, ref_frac=p["ref_frac"])

    prefill, prefill_src = load_prefill(folder)
    if prefill:
        st.caption("浓度和分组来自 %s" % prefill_src)
        df["group"] = df["file"].map(lambda f: prefill.get(f, {}).get("group") or group_of(f))
        df["electrode"] = df["file"].map(lambda f: prefill.get(f, {}).get("electrode") or electrode_of(f))
        df["concentration_M"] = df["file"].map(
            lambda f: pd.to_numeric(prefill.get(f, {}).get("concentration_M"), errors="coerce"))
    else:
        df["concentration_M"] = np.nan

    # batch / label / role are optional truth columns.  Without a batch column a
    # per-batch calibration is impossible, so the folder name becomes the batch:
    # in this project one data folder is one measurement session.
    default_batch = folder.name if folder is not None else "batch"
    for col in ("batch", "label", "role"):
        df[col] = df["file"].map(
            lambda f, c=col: (prefill.get(f, {}) or {}).get(c) if prefill else None)
    b = df["batch"].astype(str).str.strip()
    df["batch"] = b.where(~b.isin(["", "None", "nan"]), default_batch)
    df["label"] = pd.to_numeric(df["label"], errors="coerce")
    df["role"] = df["role"].fillna("").astype(str).str.strip()

    st.title("链霉素 DPV 检测平台")
    if p["warning"]:
        st.error(p["warning"])

    c = st.columns(5)
    c[0].metric("曲线", len(df))
    c[1].metric("独立电极", df["electrode"].nunique())
    c[2].metric("分组", df["group"].nunique())
    c[3].metric("扫描窗口 (V)", "%.2f~%.2f" % (grid[0], grid[-1]))
    c[4].metric("QC 合格", "%d / %d" % (int(df["qc_pass"].sum()), len(df)))

    if errors:
        with st.expander("%d 个文件没参与分析（原因见下表）" % len(errors)):
            st.dataframe(pd.DataFrame(errors))

    edited = meta_editor(df, sig)
    work = df.drop(columns=["group", "electrode", "concentration_M",
                            "batch", "label", "role"], errors="ignore").merge(
        edited, on="file", how="left")
    if p["use_qc"]:
        kept_qc = work[work["qc_pass"]].reset_index(drop=True)
        if len(kept_qc) == 0:
            st.warning("按「内参中位数的 %.0f%%」这个门槛（%.2f µA）一条都留不下 ——"
                       "为了还能看图，本次没有剔除（左栏可以改 QC 下限）。"
                       % (100 * p["ref_frac"], float(df.attrs.get("ref_threshold", 0))))
        else:
            work = kept_qc
        keep = [i for i, f in enumerate(df["file"]) if f in set(work["file"])]
        curves_w = curves[keep] if len(keep) else curves
    else:
        curves_w = curves

    metric = p["metric"]
    avail = core.metric_availability(df)
    if metric not in avail:
        st.info("这个文件夹的扫描窗口是 %.2f ~ %.2f V，覆盖不到 %s 所在的电位，"
                "响应指标自动改成「%s」。"
                % (grid[0], grid[-1],
                   "MB 峰（-0.34 V）和内参峰（+0.35 V）" if metric == "ratio"
                   else "所选指标",
                   core.METRIC_CN.get(avail[0], avail[0])))
        metric = avail[0]
    if p["ref_frac"] > 0 and df.attrs.get("qc_skipped"):
        st.caption("这批数据的扫描窗口里没有内参峰（+0.35 V），内参 QC 已自动跳过。")
    elif p["ref_frac"] > 0 and np.isfinite(float(df.attrs.get("ref_median", np.nan))):
        st.caption("内参 QC 门槛：本批内参中位数 %.2f µA × %.0f%% = %.2f µA，%d / %d 条通过。"
                   % (float(df.attrs["ref_median"]), 100 * p["ref_frac"],
                      float(df.attrs["ref_threshold"]),
                      int(df["qc_pass"].sum()), len(df)))
    fit = core.fit_calibration(work, metric=metric)

    # per-batch calibration: only meaningful when there really is more than one
    # batch.  It is the one way across-batch quantification can work, because the
    # batch offset is common-mode and the same-day standards measure it.
    fitb = None
    if work["batch"].astype(str).nunique() > 1:
        if st.checkbox("按批标定：每批用自己那天的标准点定截距",
                       value=False,
                       help="批次之间的偏移是共模的，用同一天的对照扣掉。"
                            "勾上后浓度按样品所属批次算（见 docs/跨批次分析.md）。"):
            fitb = core.fit_calibration_batch(work, metric=metric)
            if fitb.get("error"):
                st.warning("按批标定没成：%s —— 本次回退到全局单条校准线。"
                           % explain_fit_error(fitb["error"]))
                fitb = None
            else:
                st.caption("按批标定：%s，%d 个批次。" % (fitb["model"], fitb["n_batches"]))

    samples = work[work["concentration_M"].isna()]
    items_map = dict(items)

    tabs = st.tabs(["结论", "曲线", "统计", "校准与定量", "建模", "导出"])
    with tabs[0]:
        tab_verdict(work, fit, samples, metric, fitb)
    with tabs[1]:
        tab_curves(work, curves_w, p, items_map, grid)
    with tabs[2]:
        tab_stats(work, metric)
    with tabs[3]:
        tab_calibration(work, fit, samples, metric, fitb)
    with tabs[4]:
        tab_models(work, curves_w, metric, grid)
    with tabs[5]:
        figs = {"曲线总览": fg.fig_traces(work, curves_w, grid=grid),
                "均值±SD": fg.fig_mean_sd(work, curves_w, grid=grid),
                **({"比值散点": fg.fig_ratio_scatter(work)}
                   if "ratio" in core.metric_availability(work) else {}),
                "箱线图": fg.fig_box(work, metric)}
        if not fit.get("error"):
            figs["校准曲线"] = fg.fig_calibration(fit, work, metric)
        tables = {"数据表": work[["file", "group", "electrode", "concentration_M", metric, "qc_pass"]],
                  "组间汇总": core.group_summary(work, "group", metric),
                  "ANOVA": core.group_stats(work, "group")}
        tab_export(work, fit, samples, figs, tables, metric, p, items)


main()
