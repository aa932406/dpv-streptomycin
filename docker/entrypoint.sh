#!/bin/bash
# 两个进程一个容器：FastAPI 在 127.0.0.1:8000，Next 在 0.0.0.0:3000。
# 任何一个挂了都让容器退出（交给 docker restart 策略处理），不要留半死的状态。
# 注意用 bash：dash 的 wait 没有 -n。
set -uo pipefail

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"

# 数据卷第一次挂上来是空的：塞一份演示数据，界面至少能用
if [ -d /app/data ] && [ -z "$(ls -A /app/data 2>/dev/null)" ]; then
  echo "[entrypoint] /app/data 是空的，生成演示数据"
  python /app/scripts/make_demo_data.py --out /app/data/demo || true
  python /app/scripts/make_demo_data.py --mode batches --out /app/data/demo_batches || true
fi
mkdir -p /app/data /app/models

echo "[entrypoint] 启动 API 127.0.0.1:${API_PORT}"
uvicorn server.app:app --host 127.0.0.1 --port "${API_PORT}" --app-dir /app &
API_PID=$!

echo "[entrypoint] 启动 Web 0.0.0.0:${WEB_PORT}"
cd /app/web
PORT="${WEB_PORT}" HOSTNAME=0.0.0.0 node server.js &
WEB_PID=$!

cleanup() {
  kill "$API_PID" "$WEB_PID" 2>/dev/null || true
  wait "$API_PID" "$WEB_PID" 2>/dev/null || true
}
trap 'echo "[entrypoint] 收到停止信号"; cleanup; exit 0' TERM INT

# 两个都活着就一直等；谁先死，收掉另一个并以失败退出
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
  sleep 2
done

if ! kill -0 "$API_PID" 2>/dev/null; then
  echo "[entrypoint] API 进程已退出"
  wait "$API_PID" || true
else
  echo "[entrypoint] Web 进程已退出"
  wait "$WEB_PID" || true
fi
cleanup
exit 1
