#!/usr/bin/env bash
set -u

APP_DIR="/home/zachw/Documents/Drakkenheim Campaign"
APP_BASE_URL="http://127.0.0.1:8765"
APP_URL="$APP_BASE_URL/dm"
HEALTH_URL="$APP_BASE_URL/portal"
CONFIG_FILE="$APP_DIR/.env"

if [[ -f "$CONFIG_FILE" ]]; then
  set -a
  # This is a user-owned configuration file containing shell-style KEY=VALUE
  # assignments. It is excluded from Git.
  source "$CONFIG_FILE"
  set +a
fi

if curl --silent --fail --max-time 1 "$HEALTH_URL" >/dev/null 2>&1; then
  xdg-open "$APP_URL" >/dev/null 2>&1
  exit 0
fi

if systemctl --user cat drakkenheim-campaign.service >/dev/null 2>&1; then
  systemctl --user start drakkenheim-campaign.service
else
  nohup python3 "$APP_DIR/app.py" >>"$APP_DIR/dashboard.log" 2>&1 &
fi

for _attempt in {1..50}; do
  if curl --silent --fail --max-time 1 "$HEALTH_URL" >/dev/null 2>&1; then
    xdg-open "$APP_URL" >/dev/null 2>&1
    exit 0
  fi
  sleep 0.1
done

exit 1
