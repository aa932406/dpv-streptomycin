# syntax=docker/dockerfile:1.7
# ============================================================================
#  DPV 链霉素检测平台 —— 单容器镜像
#
#  两个进程装在一个容器里：
#      uvicorn  FastAPI      127.0.0.1:8000   （只监听本机，不对外）
#      node     Next.js      0.0.0.0:3000     （对外唯一端口，反代 /api/*）
#
#  纯 CPU：没有 CUDA、没有 torch，服务器有没有显卡都一样跑。
#  构建：docker build -t dpv-streptomycin:latest .
#  运行：docker run -d -p 3000:3000 -v dpv_data:/app/data dpv-streptomycin:latest
# ============================================================================

# ---------- 阶段 1：构建前端（只在构建期需要 Node 和 2G 内存）----------
FROM node:22-bookworm-slim AS webbuild
WORKDIR /app/web
ENV NEXT_TELEMETRY_DISABLED=1

# 先只拷 lockfile，依赖层可以被缓存
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY web/ ./
# API_BASE 和 output:standalone 都是构建期写死的，改端口要重新构建
ENV API_BASE=http://127.0.0.1:8000 \
    NEXT_OUTPUT=standalone
RUN npm run build

# ---------- 阶段 2：运行时（Python + 一个 node 可执行文件）----------
FROM python:3.13-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production

# tini 收尸、curl 给 healthcheck、libgomp1 是 numpy/scipy/xgboost 的 OpenMP 运行时，
# fonts-dejavu 给 matplotlib（图内标签是英文，不需要中文字体）
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl tini libgomp1 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

# 从构建阶段搬一个 node 进来，省掉在运行镜像里装 NodeSource
COPY --from=webbuild /usr/local/bin/node /usr/local/bin/node

WORKDIR /app

COPY requirements.txt ./
# xgboost 从 2.x 起，PyPI 轮子会顺带拉 nvidia-nccl（300+ MB），只为 GPU 训练。
# 这里把它摘出来单独 --no-deps 装：CPU 训练完全正常，镜像少 350 MB。
RUN grep -vi '^xgboost' requirements.txt > /tmp/req-docker.txt \
 && pip install --no-cache-dir -r /tmp/req-docker.txt \
 && pip install --no-cache-dir --no-deps "xgboost>=2.0,<3"
# 预热 matplotlib 的字体缓存：第一次画图要扫描系统字体，冷启动要 20 秒，
# 放在镜像层里做掉，容器起来第一张图就是秒出。
RUN python -c "import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt; plt.figure(); plt.plot([0,1],[0,1]); plt.savefig('/tmp/_warm.png')" && rm -f /tmp/_warm.png

COPY scripts/ ./scripts/
COPY server/ ./server/
COPY metadata/ ./metadata/
COPY docs/ ./docs/
COPY README.md LICENSE NOTICE ./

# 演示数据在构建期生成，容器起来就能点（合成数据，界面有红色横幅声明）
RUN python scripts/make_demo_data.py --out data/demo \
 && python scripts/make_demo_data.py --mode batches --out data/demo_batches

# Next 的 standalone 产物 + 静态资源
COPY --from=webbuild /app/web/.next/standalone ./web/
COPY --from=webbuild /app/web/.next/static ./web/.next/static

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# 用户数据与训练好的模型放在卷里，容器重建不丢
VOLUME ["/app/data", "/app/models"]

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:3000/api/health >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/usr/local/bin/entrypoint.sh"]
