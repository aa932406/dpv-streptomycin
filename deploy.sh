#!/usr/bin/env bash
# ============================================================================
#  DPV 链霉素检测平台 —— 一键部署（Linux）
#
#  用法（在仓库根目录执行）：
#      sudo bash deploy.sh                       # 装到 /opt/dpv，Web 端口 3000
#      sudo bash deploy.sh --dir /srv/dpv        # 换安装目录
#      sudo bash deploy.sh --web-port 8080       # 换对外端口
#      sudo bash deploy.sh --no-systemd          # 不用 systemd，直接 nohup 起
#      sudo bash deploy.sh --no-demo             # 不生成合成演示数据
#
#  它会做这些事：
#    1. 检查/安装 python3、venv、nodejs(>=18)
#    2. 把代码同步到安装目录（排除 .venv / node_modules / out）
#    3. 建 venv、装 requirements.txt
#    4. npm install + npm run build（API_BASE 在构建时写死，所以必须现在设）
#    5. 写两个 systemd 服务：dpv-api(127.0.0.1:8000) + dpv-web(0.0.0.0:3000)
#    6. 开防火墙端口（如果有 ufw/firewalld）
#    7. 打印访问地址
#
#  两个进程的分工：浏览器只跟 Next 说话（0.0.0.0:3000），Next 把 /api/* 反代给
#  FastAPI（127.0.0.1:8000，不对外）。所以对外只需要一个端口。
# ============================================================================
set -euo pipefail

ORIG_ARGS=("$@")

APP_DIR="/opt/dpv"
WEB_PORT="3000"
API_PORT="8000"
SERVICE_USER=""
USE_SYSTEMD=1
WITH_DEMO=1

while [ $# -gt 0 ]; do
  case "$1" in
    --dir)        APP_DIR="$2"; shift 2 ;;
    --web-port)   WEB_PORT="$2"; shift 2 ;;
    --api-port)   API_PORT="$2"; shift 2 ;;
    --user)       SERVICE_USER="$2"; shift 2 ;;
    --no-systemd) USE_SYSTEMD=0; shift ;;
    --no-demo)    WITH_DEMO=0; shift ;;
    -h|--help)    sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "未知参数: $1（用 --help 看用法）" >&2; exit 1 ;;
  esac
done

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

# --- 0. root ---------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
  say "需要 root 权限，正在用 sudo 重新执行"
  exec sudo bash "$0" "${ORIG_ARGS[@]}"
fi

if [ -z "$SERVICE_USER" ]; then
  SERVICE_USER="${SUDO_USER:-}"
  if [ -z "$SERVICE_USER" ] || [ "$SERVICE_USER" = "root" ]; then
    SERVICE_USER="dpv"
  fi
fi
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  say "创建系统用户 $SERVICE_USER"
  useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# --- 1. 依赖 ---------------------------------------------------------------
say "检查系统依赖"
PKG_MGR=""
if command -v apt-get >/dev/null 2>&1; then
  PKG_MGR=apt
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv python3-pip curl ca-certificates rsync >/dev/null
elif command -v dnf >/dev/null 2>&1; then
  PKG_MGR=dnf
  dnf install -y -q python3 python3-pip curl rsync >/dev/null
elif command -v yum >/dev/null 2>&1; then
  PKG_MGR=yum
  yum install -y -q python3 python3-pip curl rsync >/dev/null
else
  warn "没找到 apt/dnf/yum，跳过系统包安装（需要已有 python3 / node / rsync）"
fi

command -v python3 >/dev/null 2>&1 || die "没有 python3，请先手动安装"
python3 -c 'import venv' 2>/dev/null || die "python3 缺少 venv 模块（apt install python3-venv）"

NODE_OK=0
if command -v node >/dev/null 2>&1; then
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
  if [ "$NODE_MAJOR" -ge 18 ]; then NODE_OK=1; fi
fi
if [ "$NODE_OK" -eq 0 ]; then
  say "安装 Node.js 20（Next.js 15 需要 >= 18.18）"
  if [ "$PKG_MGR" = "apt" ]; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null
    apt-get install -y -qq nodejs >/dev/null
  elif [ "$PKG_MGR" = "dnf" ] || [ "$PKG_MGR" = "yum" ]; then
    curl -fsSL https://rpm.nodesource.com/setup_20.x | bash - >/dev/null
    $PKG_MGR install -y -q nodejs >/dev/null
  else
    die "无法自动安装 Node.js，请手动装 node 18+ 后重跑"
  fi
fi
node -v
npm -v

# --- 2. 同步代码 -----------------------------------------------------------
mkdir -p "$APP_DIR"
if [ "$SRC_DIR" != "$APP_DIR" ]; then
  say "同步代码 $SRC_DIR -> $APP_DIR"
  rsync -a --delete \
        --exclude '.git' --exclude '.venv' --exclude 'node_modules' \
        --exclude '.next' --exclude '__pycache__' --exclude 'out' \
        --exclude '.instabox_key' --exclude 'run' \
        --filter 'P data/*/metadata.csv' \
        "$SRC_DIR"/ "$APP_DIR"/
else
  say "已经在 $APP_DIR，跳过同步"
fi
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

# --- 3. Python -------------------------------------------------------------
say "创建 venv 并安装 Python 依赖"
sudo -u "$SERVICE_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip -q
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

if [ "$WITH_DEMO" -eq 1 ] && [ ! -d "$APP_DIR/data/demo" ]; then
  say "生成合成演示数据（data/demo + data/demo_batches，可在界面里删掉）"
  cd "$APP_DIR"
  sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/python" scripts/make_demo_data.py --mode single >/dev/null || warn "单批次演示数据生成失败（不影响真实数据）"
  sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/python" scripts/make_demo_data.py --mode batches >/dev/null || warn "多批次演示数据生成失败（不影响真实数据）"
fi

# --- 4. 前端 ---------------------------------------------------------------
say "安装前端依赖并构建（API_BASE=http://127.0.0.1:$API_PORT，构建时写死）"
cd "$APP_DIR/web"
if [ -f package-lock.json ] && sudo -u "$SERVICE_USER" npm ci --include=dev --no-audit --no-fund; then
  :
else
  warn "package-lock.json 与 package.json 不同步（或没有 lock），改用 npm install"
  sudo -u "$SERVICE_USER" npm install --include=dev --no-audit --no-fund
fi
sudo -u "$SERVICE_USER" env API_BASE="http://127.0.0.1:$API_PORT" NODE_ENV=production npm run build

# --- 5. 服务 ---------------------------------------------------------------
if [ "$USE_SYSTEMD" -eq 1 ] && command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  say "写 systemd 服务"
  cat > /etc/systemd/system/dpv-api.service <<UNIT
[Unit]
Description=DPV analysis API (FastAPI)
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port $API_PORT
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

  cat > /etc/systemd/system/dpv-web.service <<UNIT
[Unit]
Description=DPV web UI (Next.js)
After=network.target dpv-api.service
Wants=dpv-api.service

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR/web
Environment=NODE_ENV=production
Environment=PORT=$WEB_PORT
ExecStart=$APP_DIR/web/node_modules/.bin/next start -p $WEB_PORT -H 0.0.0.0
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

  systemctl daemon-reload
  systemctl enable --now dpv-api.service dpv-web.service
  sleep 4
  systemctl --no-pager --lines=0 status dpv-api.service dpv-web.service || true
else
  say "不用 systemd，改用 start.sh / stop.sh（nohup）"
  cat > "$APP_DIR/start.sh" <<UNIT
#!/usr/bin/env bash
set -e
cd "$APP_DIR"
mkdir -p run
if [ -f run/api.pid ] && kill -0 "\$(cat run/api.pid)" 2>/dev/null; then
  echo "API 已在运行"
else
  nohup .venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port $API_PORT > run/api.log 2>&1 &
  echo \$! > run/api.pid
fi
if [ -f run/web.pid ] && kill -0 "\$(cat run/web.pid)" 2>/dev/null; then
  echo "Web 已在运行"
else
  cd web
  nohup node_modules/.bin/next start -p $WEB_PORT -H 0.0.0.0 > ../run/web.log 2>&1 &
  echo \$! > ../run/web.pid
fi
echo "已启动：http://0.0.0.0:$WEB_PORT"
UNIT
  cat > "$APP_DIR/stop.sh" <<UNIT
#!/usr/bin/env bash
cd "$APP_DIR"
for f in run/web.pid run/api.pid; do
  if [ -f "\$f" ]; then kill "\$(cat \$f)" 2>/dev/null || true; rm -f "\$f"; fi
done
pkill -f "uvicorn server.app" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true
echo "已停止"
UNIT
  chmod +x "$APP_DIR/start.sh" "$APP_DIR/stop.sh"
  chown "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR/start.sh" "$APP_DIR/stop.sh"
  sudo -u "$SERVICE_USER" bash "$APP_DIR/start.sh"
fi

# --- 6. 防火墙 -------------------------------------------------------------
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  say "放行 ufw 端口 $WEB_PORT/tcp"
  ufw allow "$WEB_PORT"/tcp >/dev/null || true
elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  say "放行 firewalld 端口 $WEB_PORT/tcp"
  firewall-cmd --permanent --add-port="$WEB_PORT"/tcp >/dev/null || true
  firewall-cmd --reload >/dev/null || true
fi

# --- 7. 自检 ---------------------------------------------------------------
say "自检"
sleep 3
API_CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$API_PORT/api/health" || true)"
WEB_CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$WEB_PORT/verdict" || true)"
echo "    API  http://127.0.0.1:$API_PORT/api/health  -> $API_CODE"
echo "    Web  http://127.0.0.1:$WEB_PORT/verdict    -> $WEB_CODE"

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -z "$IP" ] && IP="<服务器IP>"

echo ""
echo "============================================================"
echo " 部署完成"
echo "============================================================"
echo " 访问地址   http://$IP:$WEB_PORT"
echo " 安装目录   $APP_DIR"
echo " 运行用户   $SERVICE_USER"
echo " API 进程   127.0.0.1:$API_PORT（只监听本机，不对外）"
echo " Web 进程   0.0.0.0:$WEB_PORT（对外）"
echo ""
echo " 常用命令："
echo "   systemctl status dpv-web dpv-api"
echo "   journalctl -u dpv-web -f"
echo "   systemctl restart dpv-web dpv-api"
echo " （非 systemd 模式：bash $APP_DIR/start.sh / stop.sh）"
echo ""
echo " 打不开先查：云厂商安全组是否放行 $WEB_PORT"
echo "============================================================"
