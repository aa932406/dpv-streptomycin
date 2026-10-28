#!/bin/bash
cd /data/workspace/dpv/proj
pkill -f "uvicorn server.app" 2>/dev/null
pkill -f "next-server" 2>/dev/null
pkill -f "next start" 2>/dev/null
pkill -f "npx next" 2>/dev/null
sleep 2
nohup /data/workspace/dpv/.venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port 8000 > /tmp/api.log 2>&1 &
cd web
nohup npx next start -p 3100 > /tmp/next.log 2>&1 &
sleep 16
curl -s -o /dev/null -w "api %{http_code}\n" http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "web %{http_code}\n" http://127.0.0.1:3100/verdict
tail -3 /tmp/next.log
