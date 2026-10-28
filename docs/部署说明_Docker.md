# Docker 部署（服务器上没有 GPU 也能跑）

一个容器装两件事：FastAPI（127.0.0.1:8000，只本机）+ Next.js（0.0.0.0:3000，对外）。
对外只有一个端口，浏览器与 API 同源，没有 CORS。

**这个项目是纯 CPU 的。** 没有 CUDA、没有 torch、没有 GPU 依赖：
numpy / scipy / scikit-learn / matplotlib 全是 CPU 轮子，xgboost 用的也是 CPU 版。
你服务器上没显卡完全不影响，一张 2 核 2G 的机器就够跑（分析一次 90 支电极的批次是秒级）。

---

## 1. 最快的一条路：直接拉已经构建好的镜像

现成的镜像已经推在 GitHub 的镜像仓库（GHCR）里，服务器**不需要 git、不需要编译**：

```bash
docker pull ghcr.io/aa932406/dpv-streptomycin:latest
docker run -d --name dpv --restart unless-stopped \
  -p 3000:3000 -v dpv_data:/app/data -v dpv_models:/app/models \
  ghcr.io/aa932406/dpv-streptomycin:latest
```

浏览器打开 `http://<服务器IP>:3000` 就有界面（第一次启动自动生成演示数据）。

这个包现在是**私有**的，拉之前要先登录一次：

```bash
docker login ghcr.io -u aa932406          # 密码填 GitHub PAT，勾 read:packages 就够
```

嫌麻烦就把它改成公开：GitHub → 你的 Packages → dpv-streptomycin →
Package settings → Change visibility → Public，之后 `docker pull` 不用登录。

镜像大小 1.69 GB（amd64），解压后约 3.5 GB，拉取时间取决于带宽。

---

## 1b. 或者：服务器上自己构建

服务器只要装了 Docker（>=20.10）和 git：

```bash
git clone https://<用户名>:<token>@github.com/aa932406/dpv-streptomycin.git
cd dpv-streptomycin

docker build -t dpv-streptomycin:latest .
docker run -d --name dpv --restart unless-stopped \
  -p 3000:3000 \
  -v dpv_data:/app/data \
  -v dpv_models:/app/models \
  dpv-streptomycin:latest
```

浏览器打开 `http://<服务器IP>:3000`。

或者用 compose（同目录下的 `docker-compose.yml`）：

```bash
docker compose up -d --build
```

**构建期资源要求**：约 2 GB 内存（Next 构建）+ 约 1.5 GB 磁盘（镜像约 1.0–1.3 GB）。
构建要联网（npm ci + pip install）。构建完成后运行**不需要网络**。

---

## 2. 离线服务器：在有网的机器构建，拷过去

```bash
# 有网的机器（架构必须和目标机一致，见下面 arm64 那节）
docker build -t dpv-streptomycin:latest .
docker save dpv-streptomycin:latest | gzip > dpv-image.tar.gz

# 拷到服务器
scp dpv-image.tar.gz root@<服务器>:/root/

# 服务器上
gunzip -c /root/dpv-image.tar.gz | docker load
docker run -d --name dpv --restart unless-stopped -p 3000:3000 \
  -v dpv_data:/app/data dpv-streptomycin:latest
```

---

## 3. 推到镜像仓库，服务器只 pull

任何 registry 都行（阿里云 ACR、腾讯云 TCR、Harbor、GHCR）。以 GHCR 为例：

```bash
echo <你的PAT> | docker login ghcr.io -u aa932406 --password-stdin
docker tag dpv-streptomycin:latest ghcr.io/aa932406/dpv-streptomycin:latest
docker push ghcr.io/aa932406/dpv-streptomycin:latest

# 服务器上
docker pull ghcr.io/aa932406/dpv-streptomycin:latest
docker run -d --name dpv --restart unless-stopped -p 3000:3000 \
  -v dpv_data:/app/data ghcr.io/aa932406/dpv-streptomycin:latest
```

私有仓库记得在服务器上先 `docker login`。

**这个仓库已经推过了**：`ghcr.io/aa932406/dpv-streptomycin:latest`，
digest `sha256:7f69faea824a28a7708ed0133a486e47760625cbe287667c62e316451eaa863e`。
以后改了代码只要重新 `docker build` + `docker push` 同一个 tag，服务器 `docker pull` 就更新了。

---

## 4. 数据放哪

容器里两个卷：

| 容器路径 | 内容 | 要不要备份 |
|---|---|---|
| `/app/data` | `data/<日期>/*.cor`、每个文件夹的 `metadata.csv` | **要**，这是你的实验数据 |
| `/app/models` | 界面里训练出来的 .joblib / .pkl | 建议 |

**第一次启动**如果 `/app/data` 是空的，entrypoint 会自动生成演示数据（合成数据，界面顶部有红色横幅声明），所以镜像起来就能点，不会白屏。

放真实数据两种方式：

```bash
# 方式 A：拷进卷（推荐）
docker cp ./20261101 dpv:/app/data/20261101

# 方式 B：直接把宿主机目录挂进去（注意 uid 权限）
docker run ... -v /srv/dpv-data:/app/data ...
```

界面里改完浓度、点「保存并重新分析」写的就是 `/app/data/<文件夹>/metadata.csv`。

---

## 5. 常用运维

```bash
docker ps --filter name=dpv                 # 状态（healthy 才算真起来）
docker logs -f dpv                          # 两个进程的日志都在这里
curl -fsS http://127.0.0.1:3000/api/health  # 一条命令测前后端通不通

docker restart dpv                          # 重启
docker rm -f dpv                            # 删容器（卷里的数据还在）

# 更新到新代码
git pull && docker build -t dpv-streptomycin:latest . && docker rm -f dpv && docker run ...
```

镜像自带 HEALTHCHECK（每 30 秒打一次 `/api/health`，40 秒宽限期）。

---

## 6. 没有 GPU —— 具体说清楚

| 问题 | 答案 |
|---|---|
| 需要 CUDA / cuDNN 吗 | 不需要。Dockerfile 里一个 GPU 相关包都没有 |
| 需要装 nvidia-container-toolkit 吗 | 不需要，`docker run` 不用加 `--gpus` |
| 训练会不会很慢 | 不会。最大的一次训练是 90 支电极 × 16 特征，sklearn 在单核上是毫秒到秒级 |
| xgboost 呢 | 装的是 CPU 版；预测页会自动列出它，没有 GPU 只是训练慢一点点 |
| 以后想用深度学习怎么办 | 那是另一个量级的问题：需要 150+ 支电极的数据，且要单独建 GPU 镜像（`FROM pytorch/pytorch:...-cuda12`）。现在用不着 |
| 内存要多少 | 2 GB 够（`docker-compose.yml` 里 `mem_limit: 2g`）。构建期需要 2 GB |

---

## 7. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `docker build` 卡在 `npm ci` 或被杀 | 内存不足 2 GB | 加 swap，或 `docker build --memory=3g`，或换台机器构建后 `docker save` 过去 |
| 页面能开、数据全空 | `/app/data` 里没有 `.cor` | `docker cp` 数据进去，或点「生成演示数据」 |
| `/api/*` 全 502 | API 进程没起来 | `docker logs dpv` 看 uvicorn 报错；多半是 pip 没装完（构建时网络断了，重建） |
| 端口占用 | 3000 被别的服务占了 | `-p 8080:3000`，容器内部端口不用改 |
| 服务器是 arm64（鲲鹏/飞腾/树莓派/Apple Silicon） | 在 x86 上构建的镜像不能跑 | 在 arm64 机器上构建；或用 `docker buildx build --platform linux/arm64 -t ... --load .` |
| 想换对外端口又不想重新构建 | `API_BASE` 是**构建期**写进 `routes-manifest.json` 的 | 换宿主机端口用 `-p`；换容器内端口要重建（内部始终 127.0.0.1:8000 → 3000） |
| 卷权限 | bind mount 时容器内是 root | `-v /srv/dpv-data:/app/data` 前先 `chown -R 1000:1000` 或直接用命名卷 |
