#!/usr/bin/env bash

deployment_project_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$script_dir/../.." && pwd
}

deployment_read_version() {
  local explicit="${1:-}"
  if [ -n "$explicit" ]; then
    printf '%s\n' "$explicit"
    return 0
  fi

  local root version_file
  root="$(deployment_project_root)"
  version_file="$root/VERSION"
  if [ -f "$version_file" ]; then
    sed -n '1{s/[[:space:]]*$//;p;}' "$version_file"
    return 0
  fi

  local const_file="$root/backend/consts/const.py"
  if [ -f "$const_file" ]; then
    local line
    line="$(grep -E '^APP_VERSION[[:space:]]*=' "$const_file" | tail -n 1 || true)"
    line="${line##*=}"
    line="$(printf '%s' "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//;s/^["'\'']//;s/["'\'']$//')"
    [ -n "$line" ] && printf '%s\n' "$line"
    return 0
  fi

  printf 'latest\n'
}
