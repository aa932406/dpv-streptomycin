# DPV 数据分析 · Au@SH-MIL-101(Fe) / 链霉素

差分脉冲伏安（DPV）数据的统计分析 + 建模 + 出图。

## 目录结构

```
.
├── data/                      原始数据，按测量日期分文件夹（现有 15 个日期 + 4 个演示/外部文件夹）
│   ├── 20261010/              26 个 .cor（辰华 CHI 文本格式），唯一有完整四条件对照的一批
│   ├── demo/                  合成演示数据，单批次（deploy.sh / 界面按钮生成，可删）
│   ├── demo_batches/          合成演示数据，3 个批次带批次偏移（用来演示「按批标定」）
│   ├── demo_cv/               合成 CV（4 个扫速，真实面积 0.0707 cm²，用来试电极面积那一步）
│   └── cd36_ngml/             外部数据集（miralab-ai/biosensors-AI，60 条 CD36 曲线，12 个浓度×5 重复）
├── web/                       ★ Web 前端（Next.js 15 + Tailwind 4 + recharts）
│   ├── app/(main)/            八个页面：数据 / 结论 / 曲线 / 统计 / 校准 / 建模 / 预测 / 导出
│   ├── components/            顶栏、底部 dock、图表、卡片、ModelStudio（训练/仓库/调用）
│   └── lib/                   API 客户端、类型、格式化工具
├── server/
│   └── app.py                 ★ FastAPI 后端（包 analysis_core.py），/api/analyse /api/regression /api/metadata /api/report
│                              ↳ 模型：/api/train（后台任务） /api/train/{id} /api/models /api/models/{n}/download /api/predict
├── scripts/                   所有代码
│   ├── app.py                 Streamlit 版界面（旧版，run_web_streamlit.bat 启动）
│   ├── dump_ui_json.py        把分析结果导成前端要的 JSON（API 契约）
│   ├── analysis_core.py       界面用的全部数学逻辑（不含 UI，可单独 import）
│   ├── figures.py             界面用的出图函数
│   ├── report.py              打包 zip 报告（HTML + Word + CSV + PNG）
│   ├── make_demo_data.py      生成合成演示数据（单批次 / 3 批次）
│   ├── dpv_pipeline.py        核心库 + 命令行主流程（解析/基线/特征/统计/建模/出图）
│   ├── calibration.py         单峰校准曲线 + 全程曲线 PLS
│   ├── ratiometric_calibration.py  比值法 I_MB/I_ref + LOD/LOQ  ← 推荐
│   ├── demo_ml.py             数据泄漏 / 置换检验的教学演示
│   ├── cross_batch.py         跨批次合并分析（方差来源 / 重复性 / 留一批次迁移）
│   ├── ml_models.py           ★ 定量预测模型（9 个算法 × 2 套输入，装了 xgboost 时 10 个；R²/RMSE/RPD，留一电极）
│   ├── train_model.py         ★ 训练一个能存盘的模型 → models/*.joblib + 模型卡 .json
│   ├── predict_with_model.py  ★ 加载模型，读新样品的 .cor → 检出/未检出 + 浓度 + 区间
│   ├── cv_peaks.py            读 CV 的 .cor：分扫描支、找峰、给 ipa/epc/ΔEp
│   ├── area_calc.py           工作电极有效面积（Randles–Ševčík，CV 法）
│   ├── make_demo_cv.py        生成演示 CV（4 个扫速，已知面积）
│   ├── paper_table.py         按论文表格口径输出（线性范围/灵敏度/LOD/R²/RPD/回收率）
│   │                          ↳ 「导出」页那张表就是它，API: GET /api/paper?folder=&area=
│   └── legacy/                早期 Node 版本，已弃用，留档
├── metadata/                  元数据表
│   ├── metadata.csv                   已按 2026-10-10 实测条件填好（见下）
│   ├── sample_metadata_template.csv   同 metadata.csv
│   └── metadata_示例.csv              下一批数据用的样例（3 空白 + 7 浓度 × 3 电极）
├── out/                       输出，按数据日期分文件夹
│   ├── sweep.json             全量检测报告的数据来源（每个文件夹一行，全字段）
│   └── 20261010/
│       ├── figures/           fig1..fig6 发表级图
│       ├── dpv_long.csv       长表，每扫描点一行
│       ├── dpv_features.csv   每曲线一行
│       ├── report.json        ANOVA / Tukey / PCA / LOEO 全部结果
│       ├── extra/             额外分析图（比值法、样本量）
│       └── archive/           历史版本输出
├── docs/                      分析报告与实验方案
│   ├── 分析说明.md            第一轮（Node 版）
│   ├── 分析说明_v2.md         第二轮（Python 版，完整统计）
│   ├── 分析说明_v3_机理.md    第三轮（峰归属 + 比值法 + Exo III 方向矛盾）
│   ├── 实验方案_链霉素.md     线性区侦察 / 校准 / 选择性实验设计
│   ├── 数据采集方案_ML.md     三档数据预算（30 / 60 / 150 支电极）
│   ├── CV测面积_操作卡.md     台面操作卡：配液/参数/判读/出错怎么办
│   ├── 使用说明_Web版.md      ★ 新版界面怎么用（先看这个）
│   ├── 使用说明_Streamlit版.md  旧 Streamlit 界面说明
│   ├── 数据清单.md            15 个日期文件夹各有多少条、窗口、分组、能不能用比值法
│   ├── 外部数据验证.md
│   ├── 论文对照_预测模型.md   ★ 三篇参考文献 → 实现了哪几项、差在哪、demo 实测数字
│   ├── 散点图怎么读.md        ★ 三张散点图的读法（MB vs 内参 / PCA / 真值 vs 预测）
│   ├── 全量检测报告.md        ★ 17 个文件夹全量跑一遍的结果表 + 修掉的 3 个问题
│   ├── 部署说明.md            ★ Linux 服务器一键部署（端口 / systemd / 常见问题）
│   ├── 训练与调用模型.md      ★ 怎么训练 / 模型长什么样 / 怎么调用（含两个踩过的坑）
│   └── 运行说明.md            Windows 本地运行细节
├── requirements.txt
├── run_web.bat                双击开 Web 界面（Next.js + FastAPI）← 推荐入口
├── run_web_streamlit.bat      双击开旧 Streamlit 界面
├── run_all.bat                双击跑命令行主流程
├── run_calibration.bat        双击跑校准
└── .venv/                     本地虚拟环境
```

## 快速开始

**双击 `run_web.bat`** —— 打开傻瓜式网页界面，浏览器自动跳到 <http://127.0.0.1:3000/verdict>。
首次启动要装依赖 + 构建前端（几分钟），之后几十秒。
在「数据」页填浓度 / 批次 / 标签并保存，其余六页立刻重算。
详细用法见 [docs/使用说明_Web版.md](docs/使用说明_Web版.md)。

技术栈：前端 Next.js 15（App Router）+ Tailwind 4 + recharts，
后端 FastAPI 包住 `scripts/analysis_core.py`，Next 用 rewrites 把 `/api/*` 反代过去，
所以浏览器只跟一个端口说话，云端部署只改 `API_BASE`。

界面里能做的（都已用演示数据跑通）：

- 自动出图、ANOVA/Tukey、PCA、留一电极交叉验证 + 置换检验
- 校准曲线 + LOD/LOQ + 逆回归置信区间（需要浓度梯度）
- **按批标定**：数据表里出现 2 个以上批次时自动启用，每批用自己那天的标准点定截距（见使用说明第 7 节）
- 数据表可填 **批次 / 标签（0/1）**，标签优先于组名正则
- 「数据」页可直接编辑浓度 / 批次 / 标签并保存回 `data/<文件夹>/metadata.csv`
- 一键导出 zip（HTML + JSON + CSV + PNG + 原始 .cor）

想要命令行批处理、不要界面：

**双击 `run_all.bat`** —— 自动装依赖、跑主流程、出图。

或者手动：

```bash
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
python scripts/dpv_pipeline.py
```

默认行为：自动找 `data/` 下**最新的日期文件夹**，输出到 `out/<同名日期>/`。
不用传任何参数。

## 部署到 Linux 服务器

```bash
git clone https://<用户名>:<token>@github.com/aa932406/dpv-streptomycin.git
cd dpv-streptomycin
sudo bash deploy.sh                    # 装到 /opt/dpv，对外 3000，监听 0.0.0.0
```

脚本自动装依赖（python3 / Node 20）、建 venv、`npm run build`、写两个 systemd 服务并启动，
最后打印访问地址。API 只听 127.0.0.1:8000，浏览器只跟 Next 的 3000 说话，**对外只需开一个端口**。

常用参数：`--dir /srv/dpv`、`--web-port 8080`、`--no-systemd`（容器里用 start.sh/stop.sh）、`--no-demo`。
完整说明（防火墙、常见报错、更新代码、数据目录）见 [docs/部署说明.md](docs/部署说明.md)。

## 换一批数据

把新的 `.cor` 放进 `data/20261105/`，再跑一次 `run_all.bat`。
脚本会自动选最新的日期文件夹，输出进 `out/20261105/`，不会覆盖旧的。

界面上直接在下拉框里切日期文件夹即可，不用改代码。
**不同日期的扫描窗口不一样**（0.09→-0.50、0.19→-0.20、0.60→-0.59 …），
窗口盖不到 MB 峰（-0.34 V）或内参峰（+0.35 V）时，
界面会自动换响应指标、自动跳过内参 QC，并在页面上说明原因 —— 不会静默给出假峰高。
每个文件夹的窗口见 [docs/数据清单.md](docs/数据清单.md)。

指定日期：

```bash
python scripts/dpv_pipeline.py --data 20261010
```

## 跑校准

```bash
copy metadata\sample_metadata_template.csv metadata\metadata.csv
:: 用 Excel 填 concentration_M 列（单位 M，空白填 0，不参与的留空）
python scripts/ratiometric_calibration.py --meta metadata/metadata.csv

# 跨批次：所有 data/<日期>/ 一起看（方差来源、重复性、留一批次迁移）
python scripts/cross_batch.py
```

需要**至少 3 条空白**（`concentration_M = 0`）才能算 LOD。

## 数据格式

辰华 CHI 的 `.cor` 文件。扩展名像二进制，实际是纯文本：

```
CORRW ASCII
...
ID_DiffPulseVA
Data:2026-10-10 Time:20:01:42
ExpParmas:...&-&InitialE=0.8&-&FinalE=-0.8&-&IncE=0.02&-&...
...
E(V)		i(A/cm^2)		T(s)
...
End Comments
-0.800000	-1.234e-05	1.2      <- 数据在 "End Comments" 之后
```

解析注意两点：数据行在 `End Comments` **之后**；文件用 `latin1` 解码
（里面的路径字段是 GBK 字节）。

## 2026-10-10 这批的实测条件

| 组 | 链霉素 | Exo III | MB 载量 |
|---|---|---|---|
| material | 无 | 无 | 无 |
| material+MB | 无 | 无 | 10 µM |
| target_noEnz | 1 µM | 无 | 10 µM |
| target+Enz | 1 µM | 0.025 U/mL | 10 µM |

已写进 `metadata/metadata.csv`。

## 已知问题

- 26 个文件里只有 **9 支独立电极**（`_ReStart` 是同一支电极重复扫描），
  所以留一电极交叉验证的置信区间很宽，见 `docs/数据采集方案_ML.md`。
- 链霉素只有一个浓度（1 µM），**做不出校准曲线**，需要补浓度梯度。
  现在跑 `calibration.py` 会明确报：
  `calibration needs at least 3 distinct concentration levels, found 1 (1.00e-06 M)`
- 缺 3 个对照：无靶标+无酶（空白）、**无靶标+有酶**、非特异性靶标。
  其中"无靶标+有酶"最关键 —— 没有它无法判断 0.30 的信号是靶标特异还是酶的本底。
- `data/` 里 15 个日期文件夹**全部没有浓度梯度**，所以目前哪个文件夹都算不出浓度，
  界面会如实说"现在还答不了多少浓度"，并列出缺什么。
- 老文件夹分组很碎（20260927 有 13 组 / 26 支电极），建模页准确率会接近瞎猜，
  界面会直接警告"这个数字不能拿来下结论"，不要当成模型失效。
