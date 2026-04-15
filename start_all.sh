#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$ROOT_DIR/.dev-runtime"
BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
BACKEND_LOG="$RUNTIME_DIR/backend.log"
FRONTEND_LOG="$RUNTIME_DIR/frontend.log"
BACKEND_HEALTH_URL="http://127.0.0.1:8000/health"
FRONTEND_URL="http://127.0.0.1:5173/"

mkdir -p "$RUNTIME_DIR"

log() {
  printf '[start_all] %s\n' "$*"
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf '[start_all] 缺少命令: %s\n' "$command_name" >&2
    exit 1
  fi
}

load_repo_env() {
  if [[ -f "$ROOT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.env"
    set +a
  fi
}

http_ready() {
  local url="$1"
  python3 - "$url" <<'PY'
import sys
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=1.5) as response:
        sys.exit(0 if 200 <= response.status < 500 else 1)
except Exception:
    sys.exit(1)
PY
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local timeout_seconds="${3:-30}"
  local attempts=$((timeout_seconds * 2))

  for _ in $(seq 1 "$attempts"); do
    if http_ready "$url"; then
      return 0
    fi
    sleep 0.5
  done

  log "$name 启动失败，日志见 $RUNTIME_DIR"
  return 1
}

start_background_process() {
  local command_text="$1"
  local pid_file="$2"
  local log_file="$3"

  : > "$log_file"
  setsid bash -lc "cd '$ROOT_DIR' && $command_text" </dev/null >>"$log_file" 2>&1 &
  echo "$!" > "$pid_file"
}

initialize_database() {
  if PYTHONPATH="$ROOT_DIR/src" python3 - <<'PY'
import asyncio
from polymarket_trader.config import Settings
from polymarket_trader.infra.db import initialize_database

settings = Settings()
asyncio.run(initialize_database(settings.database_url))
PY
  then
    log "数据库 schema 已就绪"
    return 0
  fi

  if command -v systemctl >/dev/null 2>&1; then
    log "数据库初始化失败，尝试启动系统 PostgreSQL 服务"
    sudo systemctl start postgresql
    PYTHONPATH="$ROOT_DIR/src" python3 - <<'PY'
import asyncio
from polymarket_trader.config import Settings
from polymarket_trader.infra.db import initialize_database

settings = Settings()
asyncio.run(initialize_database(settings.database_url))
PY
    log "数据库 schema 已就绪"
    return 0
  fi

  log "数据库初始化失败，且无法自动启动 PostgreSQL"
  return 1
}

ensure_backend() {
  if http_ready "$BACKEND_HEALTH_URL"; then
    log "后端已在运行: $BACKEND_HEALTH_URL"
    return 0
  fi

  log "启动后端服务"
  start_background_process \
    "export PYTHONPATH=src && uvicorn polymarket_trader.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload" \
    "$BACKEND_PID_FILE" \
    "$BACKEND_LOG"

  wait_for_http "后端服务" "$BACKEND_HEALTH_URL" 30
  log "后端已启动: $BACKEND_HEALTH_URL"
}

ensure_frontend_dependencies() {
  if [[ -d "$ROOT_DIR/frontend/node_modules" ]]; then
    return 0
  fi

  log "安装前端依赖"
  npm --prefix "$ROOT_DIR/frontend" install
}

ensure_frontend() {
  if http_ready "$FRONTEND_URL"; then
    log "前端已在运行: $FRONTEND_URL"
    return 0
  fi

  ensure_frontend_dependencies

  log "启动前端服务"
  start_background_process \
    "npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173" \
    "$FRONTEND_PID_FILE" \
    "$FRONTEND_LOG"

  wait_for_http "前端服务" "$FRONTEND_URL" 30
  log "前端已启动: $FRONTEND_URL"
}

open_browser() {
  local url="$1"

  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 || true
    return 0
  fi

  if command -v gio >/dev/null 2>&1; then
    gio open "$url" >/dev/null 2>&1 || true
    return 0
  fi

  python3 -m webbrowser "$url" >/dev/null 2>&1 || true
}

main() {
  require_command python3
  require_command npm
  require_command uvicorn

  load_repo_env
  initialize_database
  ensure_backend
  ensure_frontend
  open_browser "$FRONTEND_URL"

  log "全部服务已就绪"
  log "前端地址: $FRONTEND_URL"
  log "后端文档: http://127.0.0.1:8000/docs"
  log "日志目录: $RUNTIME_DIR"
}

main "$@"
