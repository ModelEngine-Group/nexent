#!/usr/bin/env bash

# Deploy official Agent bundles after Nexent is already installed.
# The source may be an Agent Hub Git repository, an unpacked local directory,
# or an archive. All sources use the same scan/copy/sync path.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO="${OFFICIAL_AGENTS_REPO_URL:-https://gitcode.com/ModelEngine/AgentsHub}"
DEFAULT_REF="${OFFICIAL_AGENTS_REPO_REF:-main}"
NEXENT_USER_DIR_EXPLICIT="${NEXENT_USER_DIR:-}"
NEXENT_USER_DIR="${NEXENT_USER_DIR:-$HOME/nexent}"
TARGET_DIR="$NEXENT_USER_DIR/official-agents"
TARGET_CONTAINER="nexent-config"
TARGET_CONTAINER_DIR="/mnt/nexent/official-agents"
SOURCE_MODE=""
SOURCE_PATH=""
PROFILES=""
PROFILE_ROOT=""
REF="$DEFAULT_REF"
NAMESPACE="nexent"

usage() {
  cat <<'EOF'
Usage: deploy-official-agents.sh [options]

Options:
  --source hub|local        Resource source (default: interactive)
  --path PATH               Local directory/archive or Git checkout path
  --profile-root PATH       Directory under the source that contains profiles
  --profiles LIST           Comma-separated profiles (default: interactive)
  --ref REF                 Git ref when using Agent Hub
  --kubernetes               Sync through kubectl instead of Docker
  --namespace NAME          Kubernetes namespace (default: nexent)
  -h, --help                Show this help
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

validate_directory_name() {
  local name="$1"
  case "$name" in
    ""|"."|".."|*"/"*|*"\\"*) die "invalid directory name: $name" ;;
  esac
}

validate_archive_paths() {
  local archive="$1" entry
  shift
  while IFS= read -r entry; do
    entry="${entry#./}"
    case "$entry" in
      /*|../*|*/../*|..|*\\..\\*) die "archive contains an unsafe path: $entry" ;;
    esac
  done < <("$@" "$archive")
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --source) SOURCE_MODE="${2:?missing value for --source}"; shift 2 ;;
    --path) SOURCE_PATH="${2:?missing value for --path}"; shift 2 ;;
    --profile-root) PROFILE_ROOT="${2:?missing value for --profile-root}"; shift 2 ;;
    --profiles) PROFILES="${2:?missing value for --profiles}"; shift 2 ;;
    --ref) REF="${2:?missing value for --ref}"; shift 2 ;;
    --kubernetes) DEPLOY_OFFICIAL_K8S=true; shift ;;
    --namespace) NAMESPACE="${2:?missing value for --namespace}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/nexent-official-agents.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

prepare_source() {
  case "$SOURCE_MODE" in
    hub)
      command -v git >/dev/null 2>&1 || die "git is required for Agent Hub deployment"
      SOURCE_PATH="$TMP_ROOT/source"
      # Do not checkout the whole Hub: unrelated profiles may contain Git LFS
      # objects that are unavailable or are not needed for this deployment.
      GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 --no-checkout --branch "$REF" "$DEFAULT_REPO" "$SOURCE_PATH"
      ;;
    local)
      [ -n "$SOURCE_PATH" ] || read -r -p "Local directory/archive path: " SOURCE_PATH
      [ -e "$SOURCE_PATH" ] || die "local source does not exist: $SOURCE_PATH"
      if [ -f "$SOURCE_PATH" ]; then
        SOURCE_ROOT="$TMP_ROOT/unpacked"
        mkdir -p "$SOURCE_ROOT"
        if tar -tf "$SOURCE_PATH" >/dev/null 2>&1; then
          validate_archive_paths "$SOURCE_PATH" tar -tf
          tar -xf "$SOURCE_PATH" -C "$SOURCE_ROOT"
        else
          command -v unzip >/dev/null 2>&1 || die "archive requires tar or unzip"
          validate_archive_paths "$SOURCE_PATH" unzip -Z1
          unzip -q "$SOURCE_PATH" -d "$SOURCE_ROOT"
        fi
        SOURCE_PATH="$SOURCE_ROOT"
      fi
      ;;
    *)
      printf '%s\n' "Official Agent source:" "  1) Agent Hub" "  2) Local directory/archive"
      read -r -p "Choose source [1/2]: " source_choice
      [ "$source_choice" = "1" ] && SOURCE_MODE=hub || SOURCE_MODE=local
      prepare_source
      return
      ;;
  esac
  SOURCE_ROOT="$SOURCE_PATH"
  if [ -n "$PROFILE_ROOT" ]; then
    validate_directory_name "$PROFILE_ROOT"
    SOURCE_ROOT="$SOURCE_PATH/$PROFILE_ROOT"
  fi
}

prepare_hub_checkout() {
  [ "$SOURCE_MODE" = "hub" ] || return 0

  local profile path include_paths lfs_files
  local -a sparse_paths=()
  IFS=',' read -r -a selected <<< "$PROFILES"
  for profile in "${selected[@]}"; do
    profile="$(printf '%s' "$profile" | xargs)"
    [ -n "$profile" ] || continue
    validate_directory_name "$profile"
    path="$profile"
    [ -n "$PROFILE_ROOT" ] && path="$PROFILE_ROOT/$profile"
    sparse_paths+=("$path")
  done
  [ "${#sparse_paths[@]}" -gt 0 ] || die "no profiles selected"

  GIT_LFS_SKIP_SMUDGE=1 git -C "$SOURCE_PATH" sparse-checkout init --cone
  GIT_LFS_SKIP_SMUDGE=1 git -C "$SOURCE_PATH" sparse-checkout set "${sparse_paths[@]}"
  # A no-checkout clone may leave the worktree empty after sparse rules are
  # written. Materialize the selected paths explicitly before scanning them.
  GIT_LFS_SKIP_SMUDGE=1 git -C "$SOURCE_PATH" read-tree -mu HEAD

  # Fetch LFS objects only when the selected paths actually contain them.
  # Unrelated profiles remain neither checked out nor downloaded.
  if lfs_files="$(git -C "$SOURCE_PATH" lfs ls-files -n 2>/dev/null)" && [ -n "$lfs_files" ]; then
    include_paths="$(IFS=,; printf '%s' "${sparse_paths[*]}")"
    git -C "$SOURCE_PATH" lfs pull --include="$include_paths" \
      || die "failed to download Git LFS objects for selected official agent profiles"
  fi
}

select_profiles() {
  if [ -z "$PROFILES" ]; then
    if [ "$SOURCE_MODE" = "hub" ]; then
      if [ -n "$PROFILE_ROOT" ]; then
        mapfile -t available < <(git -C "$SOURCE_PATH" ls-tree -d --name-only "HEAD:$PROFILE_ROOT" | sort)
      else
        mapfile -t available < <(git -C "$SOURCE_PATH" ls-tree -d --name-only HEAD | sort)
      fi
    else
      mapfile -t available < <(find "$SOURCE_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
    fi
    [ "${#available[@]}" -gt 0 ] || die "no official Agent profiles found in $SOURCE_ROOT"
    printf 'Available profiles: %s\n' "${available[*]}"
    read -r -p "Select profiles (comma-separated): " PROFILES
  fi
  [ -n "$PROFILES" ] || die "no profiles selected"
}

copy_profiles() {
  local profile source target staged_root
  staged_root="$TMP_ROOT/staged"
  mkdir -p "$staged_root"
  IFS=',' read -r -a selected <<< "$PROFILES"
  for profile in "${selected[@]}"; do
    profile="$(printf '%s' "$profile" | xargs)"
    [ -n "$profile" ] || continue
    # Profile names may contain Unicode characters (for example, Chinese).
    # Keep only the path-safety restrictions here: a profile must be a single
    # directory name and must not escape SOURCE_ROOT.
    validate_directory_name "$profile"
    source="$SOURCE_ROOT/$profile"
    [ -d "$source" ] || die "profile not found: $profile"
    find "$source" -type f -name agent.json -print -quit | grep -q . || die "profile has no agent.json: $profile"
    target="$staged_root/$profile"
    rm -rf "$target"
    mkdir -p "$target"
    cp -R "$source/." "$target/"
    if [ -n "$NEXENT_USER_DIR_EXPLICIT" ] || [ "${DEPLOY_OFFICIAL_K8S:-false}" = true ]; then
      mkdir -p "$TARGET_DIR"
      cp -R "$target" "$TARGET_DIR/"
    else
      command -v docker >/dev/null 2>&1 || die "docker is required for Docker deployment"
      docker inspect "$TARGET_CONTAINER" >/dev/null 2>&1 || die "container not found: $TARGET_CONTAINER"
      docker exec "$TARGET_CONTAINER" mkdir -p "$TARGET_CONTAINER_DIR"
      docker cp "$target" "$TARGET_CONTAINER:$TARGET_CONTAINER_DIR/"
    fi
  done
}

sync_repository() {
  if [ "${DEPLOY_OFFICIAL_K8S:-false}" = true ]; then
    MSYS_NO_PATHCONV=1 kubectl exec deployment/nexent-config -n "$NAMESPACE" -- \
      python backend/scripts/sync_official_agents.py \
      --base-dir "$TARGET_CONTAINER_DIR" --profiles "$PROFILES"
  else
    MSYS_NO_PATHCONV=1 docker exec -e "OFFICIAL_AGENT_PROFILES=$PROFILES" nexent-config \
      python backend/scripts/sync_official_agents.py \
      --base-dir "$TARGET_CONTAINER_DIR" --profiles "$PROFILES"
  fi
}

prepare_source
select_profiles
prepare_hub_checkout
copy_profiles
sync_repository
printf 'Official Agent deployment completed for profiles: %s\n' "$PROFILES"
