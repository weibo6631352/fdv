#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
DIST_DIR="$FRONTEND_DIR/dist"
PACKAGE_DIR="$ROOT_DIR/.dist-packages"
ARCHIVE_NAME="frontend-dist.tar.gz"
CREATE_ARCHIVE=0

log() {
  printf '[build_dist] %s\n' "$*"
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf '[build_dist] 缺少命令: %s\n' "$command_name" >&2
    exit 1
  fi
}

show_help() {
  cat <<'EOF'
用法:
  ./build_dist.sh [--archive]

说明:
  默认执行前端 typecheck、lint、build，并产出 frontend/dist。
  传入 --archive 后，额外生成 .dist-packages/frontend-dist.tar.gz。
EOF
}

ensure_frontend_dependencies() {
  if [[ -d "$FRONTEND_DIR/node_modules" ]]; then
    return 0
  fi

  log "安装前端依赖"
  npm --prefix "$FRONTEND_DIR" install
}

build_frontend_dist() {
  log "执行前端类型检查"
  npm --prefix "$FRONTEND_DIR" run typecheck

  log "执行前端静态检查"
  npm --prefix "$FRONTEND_DIR" run lint

  log "构建前端 dist"
  rm -rf "$DIST_DIR"
  npm --prefix "$FRONTEND_DIR" run build

  if [[ ! -d "$DIST_DIR" ]]; then
    log "构建结束后未找到 $DIST_DIR"
    exit 1
  fi

  log "dist 已生成: $DIST_DIR"
}

create_archive() {
  require_command tar
  mkdir -p "$PACKAGE_DIR"
  rm -f "$PACKAGE_DIR/$ARCHIVE_NAME"
  tar -C "$FRONTEND_DIR" -czf "$PACKAGE_DIR/$ARCHIVE_NAME" dist
  log "归档已生成: $PACKAGE_DIR/$ARCHIVE_NAME"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --archive)
        CREATE_ARCHIVE=1
        ;;
      -h|--help)
        show_help
        exit 0
        ;;
      *)
        printf '[build_dist] 未知参数: %s\n' "$1" >&2
        show_help >&2
        exit 1
        ;;
    esac
    shift
  done
}

main() {
  parse_args "$@"
  require_command npm
  ensure_frontend_dependencies
  build_frontend_dist
  if [[ "$CREATE_ARCHIVE" -eq 1 ]]; then
    create_archive
  fi
}

main "$@"
