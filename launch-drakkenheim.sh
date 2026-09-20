#!/usr/bin/env bash
set -u

APP_DIR="/home/zachw/Documents/Drakkenheim Campaign"
APP_URL="http://127.0.0.1:8765"

if curl --silent --fail --max-time 1 "$APP_URL/api/stats" >/dev/null 2>&1; then
  xdg-open "$APP_URL" >/dev/null 2>&1
  exit 0
fi

nohup python3 "$APP_DIR/app.py" >>"$APP_DIR/dashboard.log" 2>&1 &

for _attempt in {1..50}; do
  if curl --silent --fail --max-time 1 "$APP_URL/api/stats" >/dev/null 2>&1; then
    xdg-open "$APP_URL" >/dev/null 2>&1
    exit 0
  fi
  sleep 0.1
done

exit 1
