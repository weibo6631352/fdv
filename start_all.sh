#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$ROOT_DIR/.dev-runtime"
BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
BACKEND_LOG="$RUNTIME_DIR/backend.log"
FRONTEND_LOG="$RUNTIME_DIR/frontend.log"
DATABASE_INIT_LOG="$RUNTIME_DIR/database-init.log"
BACKEND_HEALTH_URL="http://127.0.0.1:8000/health"
FRONTEND_URL="http://127.0.0.1:5173/"
LOCAL_PG_ROOT="$RUNTIME_DIR/postgres"
LOCAL_PG_DATA_DIR="$LOCAL_PG_ROOT/data"
LOCAL_PG_SOCKET_DIR="$LOCAL_PG_ROOT/socket"
LOCAL_PG_LOG="$LOCAL_PG_ROOT/postgres.log"
LOCAL_PG_PORT="${FDV_LOCAL_PG_PORT:-55432}"
LOCAL_PG_DB="${FDV_LOCAL_PG_DB:-fdv_dev}"
LOCAL_PG_USER="${FDV_LOCAL_PG_USER:-${USER:-$(id -un)}}"

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

find_pg_command() {
  local command_name="$1"
  local bin_dir

  if command -v "$command_name" >/dev/null 2>&1; then
    command -v "$command_name"
    return 0
  fi

  for bin_dir in /usr/lib/postgresql/*/bin; do
    if [[ -x "$bin_dir/$command_name" ]]; then
      printf '%s\n' "$bin_dir/$command_name"
      return 0
    fi
  done

  return 1
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

pid_is_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

stop_process() {
  local pid="$1"

  if ! pid_is_running "$pid"; then
    return 0
  fi

  kill "$pid" >/dev/null 2>&1 || true
  for _ in $(seq 1 20); do
    if ! pid_is_running "$pid"; then
      return 0
    fi
    sleep 0.5
  done

  kill -9 "$pid" >/dev/null 2>&1 || true
}

cleanup_pid_file_process() {
  local pid_file="$1"

  if [[ ! -f "$pid_file" ]]; then
    return 0
  fi

  local pid
  pid="$(<"$pid_file")"
  stop_process "$pid"
  rm -f "$pid_file"
}

listening_pid_for_port() {
  local port="$1"

  if ! command -v ss >/dev/null 2>&1; then
    return 0
  fi

  ss -ltnp "( sport = :$port )" 2>/dev/null \
    | sed -nE 's/.*pid=([0-9]+).*/\1/p' \
    | head -n 1
}

process_belongs_to_repo() {
  local pid="$1"
  local cwd

  cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  [[ -n "$cwd" && "$cwd" == "$ROOT_DIR"* ]]
}

reclaim_repo_owned_port() {
  local port="$1"
  local service_name="$2"
  local pid

  pid="$(listening_pid_for_port "$port")"
  if [[ -z "$pid" ]]; then
    return 0
  fi

  if process_belongs_to_repo "$pid"; then
    log "停止占用 $port 的旧${service_name}: pid=$pid"
    stop_process "$pid"
    return 0
  fi

  log "${service_name} 端口 $port 已被外部进程占用: pid=$pid"
  return 1
}

initialize_database_once() {
  : > "$DATABASE_INIT_LOG"
  if PYTHONPATH="$ROOT_DIR/src" python3 - <<'PY' >>"$DATABASE_INIT_LOG" 2>&1
import asyncio
from polymarket_trader.config import Settings
from polymarket_trader.infra.db import initialize_database

settings = Settings()
asyncio.run(initialize_database(settings.database_url))
PY
  then
    return 0
  fi

  return 1
}

database_config_is_default() {
  local database_url="${DATABASE_URL:-}"
  local database_driver="${DATABASE_DRIVER:-postgresql+asyncpg}"
  local database_host="${DATABASE_HOST:-localhost}"
  local database_port="${DATABASE_PORT:-5432}"
  local database_name="${DATABASE_NAME:-trader}"
  local database_user="${DATABASE_USER:-trader}"
  local database_password="${DATABASE_PASSWORD:-}"

  [[ -z "$database_url" ]] || return 1
  [[ -z "$database_password" ]] || return 1
  [[ "$database_driver" == "postgresql+asyncpg" ]] || return 1
  [[ "$database_host" == "localhost" ]] || return 1
  [[ "$database_port" == "5432" ]] || return 1
  [[ "$database_name" == "trader" ]] || return 1
  [[ "$database_user" == "trader" ]] || return 1
}

bootstrap_local_postgres() {
  local initdb_bin
  local pg_ctl_bin
  local createdb_bin
  local pg_isready_bin
  local psql_bin

  initdb_bin="$(find_pg_command initdb)" || {
    log "未找到 initdb，无法自动拉起本地 PostgreSQL"
    return 1
  }
  pg_ctl_bin="$(find_pg_command pg_ctl)" || {
    log "未找到 pg_ctl，无法自动拉起本地 PostgreSQL"
    return 1
  }
  createdb_bin="$(find_pg_command createdb)" || {
    log "未找到 createdb，无法自动创建本地开发库"
    return 1
  }
  pg_isready_bin="$(find_pg_command pg_isready)" || {
    log "未找到 pg_isready，无法探测本地 PostgreSQL 状态"
    return 1
  }
  psql_bin="$(find_pg_command psql)" || {
    log "未找到 psql，无法校验本地开发库"
    return 1
  }

  mkdir -p "$LOCAL_PG_ROOT" "$LOCAL_PG_SOCKET_DIR"

  if [[ ! -f "$LOCAL_PG_DATA_DIR/PG_VERSION" ]]; then
    log "初始化仓库内 PostgreSQL 数据目录"
    "$initdb_bin" \
      -D "$LOCAL_PG_DATA_DIR" \
      -U "$LOCAL_PG_USER" \
      -A trust \
      --auth-host=trust \
      --auth-local=trust \
      >/dev/null
  fi

  if "$pg_isready_bin" -h 127.0.0.1 -p "$LOCAL_PG_PORT" >/dev/null 2>&1; then
    log "复用本地 PostgreSQL: 127.0.0.1:$LOCAL_PG_PORT"
  else
    log "启动仓库内 PostgreSQL: 127.0.0.1:$LOCAL_PG_PORT"
    "$pg_ctl_bin" \
      -D "$LOCAL_PG_DATA_DIR" \
      -l "$LOCAL_PG_LOG" \
      -o "-p $LOCAL_PG_PORT -h 127.0.0.1 -k '$LOCAL_PG_SOCKET_DIR'" \
      start \
      >/dev/null
  fi

  if ! "$pg_isready_bin" -h 127.0.0.1 -p "$LOCAL_PG_PORT" >/dev/null 2>&1; then
    log "本地 PostgreSQL 未就绪，日志见 $LOCAL_PG_LOG"
    return 1
  fi

  if [[ "$("$psql_bin" -h 127.0.0.1 -p "$LOCAL_PG_PORT" -U "$LOCAL_PG_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$LOCAL_PG_DB'")" != "1" ]]; then
    log "创建本地开发库: $LOCAL_PG_DB"
    "$createdb_bin" -h 127.0.0.1 -p "$LOCAL_PG_PORT" -U "$LOCAL_PG_USER" "$LOCAL_PG_DB"
  fi

  export DATABASE_URL="postgresql+asyncpg://${LOCAL_PG_USER}@127.0.0.1:${LOCAL_PG_PORT}/${LOCAL_PG_DB}"
}

ensure_database() {
  if initialize_database_once; then
    log "数据库 schema 已就绪"
    return 0
  fi

  if database_config_is_default; then
    log "默认数据库配置不可用，切换到仓库内 PostgreSQL 开发库"
    bootstrap_local_postgres || return 1
    initialize_database_once || {
      log "本地 PostgreSQL 已启动，但 schema 初始化失败，日志见 $DATABASE_INIT_LOG"
      return 1
    }
    log "数据库 schema 已就绪"
    log "当前 DATABASE_URL: ${DATABASE_URL}"
    return 0
  fi

  log "数据库初始化失败，请检查 .env 中 DATABASE_URL / DATABASE_* 配置，日志见 $DATABASE_INIT_LOG"
  return 1
}

ensure_backend() {
  if http_ready "$BACKEND_HEALTH_URL"; then
    log "后端已在运行: $BACKEND_HEALTH_URL"
    return 0
  fi

  cleanup_pid_file_process "$BACKEND_PID_FILE"
  reclaim_repo_owned_port 8000 "后端服务" || return 1
  ensure_database

  log "启动后端服务"
  start_background_process \
    "export PYTHONPATH=src && python3 -m uvicorn polymarket_trader.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload" \
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

  cleanup_pid_file_process "$FRONTEND_PID_FILE"
  reclaim_repo_owned_port 5173 "前端服务" || return 1

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

  load_repo_env
  ensure_backend
  ensure_frontend
  open_browser "$FRONTEND_URL"

  log "全部服务已就绪"
  log "前端地址: $FRONTEND_URL"
  log "后端文档: http://127.0.0.1:8000/docs"
  log "日志目录: $RUNTIME_DIR"
}

main "$@"
