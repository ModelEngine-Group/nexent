#!/usr/bin/env bash
#
# Offline (air-gapped) deployment for the Nexent FULL version.
#
# This script mirrors docker/deploy.sh and k8s/helm/deploy.sh, but replaces
# every network image pull with `docker load` + `docker tag` from a local
# directory of pre-built image tars. It then brings up the full stack:
#
#   infrastructure (elasticsearch, postgresql, redis, minio)
#   + application  (config, runtime, mcp, northbound, web)
#   + supabase     (kong, gotrue-auth, supabase-db)
#
# ...generates all runtime secrets (MinIO AK/SK, Supabase JWT set, Elasticsearch
# API key) and creates the default super admin user -- exactly what the online
# deploy.sh does, just without touching the network.
#
# Prerequisites on the server:
#   - The Nexent repo is unpacked somewhere (default /run/nexent); this script
#     uses <nexent-dir>/docker (compose files, init.sql, volumes/, scripts/,
#     create-su.sh) and never modifies the repo.
#   - Pre-built image tars live in a directory (default /run/nexent-images).
#   - Docker + docker compose (v2 preferred, v1 accepted) are installed.
#   - openssl is available (secret generation).
#
# Usage:
#   bash deploy-offline.sh [--nexent-dir DIR] [--images-dir DIR] [--root-dir DIR]
#                          [--su-password PWD] [--with-data-process]
#                          [--skip-load] [--skip-suadmin] [--list-only] [-h]
#
# Examples:
#   # Dry run: load tars and show the detected image mapping, deploy nothing.
#   bash deploy-offline.sh --list-only
#
#   # Full offline deploy with defaults (/run/nexent, /run/nexent-images).
#   bash deploy-offline.sh
#
#   # Non-interactive: set the super admin password up front.
#   bash deploy-offline.sh --su-password 'my-secret-pwd'

set -eo pipefail

# ---------------------------------------------------------------------------
# Defaults (overridable via flags or environment)
# ---------------------------------------------------------------------------
NEXENT_DIR="${NEXENT_DIR:-/run/nexent}"
IMAGES_DIR="${IMAGES_DIR:-/run/nexent-images}"
ROOT_DIR="${ROOT_DIR:-$HOME/nexent-data}"
PROJECT_NAME="nexent"
SU_PASSWORD=""
WITH_DATA_PROCESS="false"
SKIP_LOAD="false"
SKIP_SUADMIN="false"
LIST_ONLY="false"

# Canonical image references. Tars are retagged to these so the existing
# docker-compose files (which read these exact names from .env) work unchanged.
# Values mirror docker/.env.general.
declare -A CANONICAL=(
  [ELASTICSEARCH_IMAGE]="docker.elastic.co/elasticsearch/elasticsearch:8.17.4"
  [POSTGRESQL_IMAGE]="postgres:15-alpine"
  [REDIS_IMAGE]="redis:alpine"
  [MINIO_IMAGE]="quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z"
  [NEXENT_IMAGE]="nexent/nexent:latest"
  [NEXENT_WEB_IMAGE]="nexent/nexent-web:latest"
  [NEXENT_MCP_DOCKER_IMAGE]="nexent/nexent-mcp:latest"
  [NEXENT_DATA_PROCESS_IMAGE]="nexent/nexent-data-process:latest"
  [SUPABASE_KONG]="kong:2.8.1"
  [SUPABASE_GOTRUE]="supabase/gotrue:v2.170.0"
  [SUPABASE_DB]="supabase/postgres:15.8.1.060"
)

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '   \033[1;32m✓\033[0m %s\n' "$*"; }
warn() { printf '   \033[1;33m⚠\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m❌ %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
usage() {
  sed -n '14,56p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --nexent-dir)        NEXENT_DIR="$2"; shift 2 ;;
    --images-dir)        IMAGES_DIR="$2"; shift 2 ;;
    --root-dir)          ROOT_DIR="$2"; shift 2 ;;
    --su-password)       SU_PASSWORD="$2"; shift 2 ;;
    --with-data-process) WITH_DATA_PROCESS="true"; shift ;;
    --skip-load)         SKIP_LOAD="true"; shift ;;
    --skip-suadmin)      SKIP_SUADMIN="true"; shift ;;
    --list-only)         LIST_ONLY="true"; shift ;;
    -h|--help)           usage ;;
    *) die "Unknown argument: $1 (try --help)" ;;
  esac
done

DOCKER_DIR="$NEXENT_DIR/docker"
COMPOSE_MAIN="${DOCKER_DIR}/docker-compose.yml"
COMPOSE_SUPABASE="${DOCKER_DIR}/docker-compose-supabase.yml"
ENV_FILE="${DOCKER_DIR}/.env"

# ---------------------------------------------------------------------------
# Pre-flight: tools and required files
# ---------------------------------------------------------------------------
command -v docker >/dev/null 2>&1 || die "docker not found in PATH."

detect_compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    die "docker compose (v2) or docker-compose (v1) not found."
  fi
}
detect_compose_cmd

command -v openssl >/dev/null 2>&1 || die "openssl not found (needed for secret generation)."

[[ -d "$NEXENT_DIR" ]]  || die "Nexent directory not found: $NEXENT_DIR (use --nexent-dir)"
[[ -f "$COMPOSE_MAIN" ]] || die "docker-compose.yml not found: $COMPOSE_MAIN"
[[ -f "$COMPOSE_SUPABASE" ]] || die "docker-compose-supabase.yml not found: $COMPOSE_SUPABASE"
[[ -f "${DOCKER_DIR}/init.sql" ]] || die "init.sql not found: ${DOCKER_DIR}/init.sql"
[[ -d "${DOCKER_DIR}/volumes" ]] || die "volumes/ not found: ${DOCKER_DIR}/volumes"

# All compose commands run from the docker dir so relative paths (./init.sql,
# ./.env) and the default project directory resolve correctly.
cd "$DOCKER_DIR"

log "Nexent dir  : $NEXENT_DIR"
log "Images dir  : $IMAGES_DIR"
log "Data root   : $ROOT_DIR"
log "Compose cmd : ${COMPOSE[*]}"
[[ "$WITH_DATA_PROCESS" == "true" ]] && log "Data process: enabled" || log "Data process: disabled (use --with-data-process to enable)"

# ---------------------------------------------------------------------------
# Step 1: load image tars and detect the canonical mapping
# ---------------------------------------------------------------------------
# Classify a loaded image (repo + tag) into one of the CANONICAL keys by
# substring matching on the lowercase repo. Order matters: more specific
# nexent-* and supabase/postgres patterns are checked before the catch-alls.
classify_image() {
  local repo="$1"
  local low
  low="$(printf '%s' "$repo" | tr '[:upper:]' '[:lower:]')"
  # Normalize the common "nexnet" misspelling (tars are named nexnet-*.tar and
  # the images inside may carry that prefix too) so both resolve identically.
  low="${low//nexnet/nexent}"
  case "$low" in
    *elasticsearch*)                                  echo "ELASTICSEARCH_IMAGE" ;;
    *gotrue*)                                         echo "SUPABASE_GOTRUE" ;;
    */kong|kong)                                      echo "SUPABASE_KONG" ;;
    *minio*)                                          echo "MINIO_IMAGE" ;;
    *nexent-web*|nexent-web)                          echo "NEXENT_WEB_IMAGE" ;;
    *nexent-mcp*|nexent-mcp)                          echo "NEXENT_MCP_DOCKER_IMAGE" ;;
    *nexent-data-process*|*data-process*)             echo "NEXENT_DATA_PROCESS_IMAGE" ;;
    *nexent*|nexent-core)                             echo "NEXENT_IMAGE" ;;
    *supabase*postgres*|supabase_postgres)            echo "SUPABASE_DB" ;;
    redis|*/redis)                                    echo "REDIS_IMAGE" ;;
    postgres|*/postgres)                              echo "POSTGRESQL_IMAGE" ;;
    *)                                                echo "" ;;
  esac
}

# loaded_refs[key] = "repo:tag" that we retagged FROM (for reporting)
declare -A LOADED_REFS=()
UNMATCHED=()

load_and_map_images() {
  step "Loading image tars from $IMAGES_DIR"
  [[ -d "$IMAGES_DIR" ]] || die "Images directory not found: $IMAGES_DIR (use --images-dir)"

  local tars=()
  while IFS= read -r f; do tars+=("$f"); done < <(find "$IMAGES_DIR" -maxdepth 1 -type f -name '*.tar' | sort)
  [[ ${#tars[@]} -gt 0 ]] || die "No .tar files found in $IMAGES_DIR"

  local tar loaded_line ref repo key
  for tar in "${tars[@]}"; do
    # `docker load` prints "Loaded image: repo:tag" (or "Loaded image ID: ...").
    loaded_line="$(docker load -i "$tar" 2>&1 | tail -n 1)"
    ref="$(printf '%s' "$loaded_line" | sed -n 's/^Loaded image: //p')"
    if [[ -z "$ref" ]]; then
      warn "$(basename "$tar"): $loaded_line (no taggable ref, skipped)"
      continue
    fi
    repo="${ref%%:*}"
    key="$(classify_image "$repo")"
    if [[ -z "$key" ]]; then
      warn "$(basename "$tar") -> $ref (unmatched, ignored)"
      UNMATCHED+=("$(basename "$tar") -> $ref")
      continue
    fi
    # Retag to the canonical reference so the compose .env resolves locally.
    if [[ "$ref" != "${CANONICAL[$key]}" ]]; then
      docker tag "$ref" "${CANONICAL[$key]}" >/dev/null
    fi
    LOADED_REFS["$key"]="$ref"
    ok "$(basename "$tar") -> $ref  [=$key]"
  done
}

verify_required_images() {
  step "Verifying required images are available locally"
  local required=(ELASTICSEARCH_IMAGE POSTGRESQL_IMAGE REDIS_IMAGE MINIO_IMAGE \
                  NEXENT_IMAGE NEXENT_WEB_IMAGE SUPABASE_KONG SUPABASE_GOTRUE SUPABASE_DB)
  [[ "$WITH_DATA_PROCESS" == "true" ]] && required+=(NEXENT_DATA_PROCESS_IMAGE)

  local missing=()
  local k
  for k in "${required[@]}"; do
    if docker image inspect "${CANONICAL[$k]}" >/dev/null 2>&1; then
      ok "${CANONICAL[$k]}"
    else
      warn "MISSING: ${CANONICAL[$k]}  ($k)"
      missing+=("$k")
    fi
  done

  if [[ ${#missing[@]} -gt 0 ]]; then
    log ""
    log "The following required images were not found among the loaded tars:"
    for k in "${missing[@]}"; do log "   - $k  =>  ${CANONICAL[$k]}"; done
    log ""
    log "Either add the missing tar(s) to $IMAGES_DIR, or if a tar was named"
    log "differently, retag it manually, e.g.:"
    log "   docker load -i /path/to/that.tar"
    log "   docker tag <loaded-repo:tag> ${CANONICAL[${missing[0]}]}"
    die "Cannot proceed: ${#missing[@]} required image(s) missing."
  fi
}

if [[ "$SKIP_LOAD" == "true" ]]; then
  step "Skipping image load (--skip-load); assuming images already present"
else
  load_and_map_images
fi

verify_required_images

if [[ ${#UNMATCHED[@]} -gt 0 ]]; then
  log ""
  log "Note: these loaded images were not mapped to any service (ignored):"
  for u in "${UNMATCHED[@]}"; do log "   - $u"; done
fi

# --list-only stops here: user inspects the mapping before a real deploy.
if [[ "$LIST_ONLY" == "true" ]]; then
  step "Dry run complete (--list-only). No services were started."
  log "Resolved image mapping:"
  for k in ELASTICSEARCH_IMAGE POSTGRESQL_IMAGE REDIS_IMAGE MINIO_IMAGE \
           NEXENT_IMAGE NEXENT_WEB_IMAGE NEXENT_MCP_DOCKER_IMAGE \
           NEXENT_DATA_PROCESS_IMAGE SUPABASE_KONG SUPABASE_GOTRUE SUPABASE_DB; do
    if [[ -n "${LOADED_REFS[$k]:-}" ]]; then
      printf '   %-26s %s  (from %s)\n' "$k" "${CANONICAL[$k]}" "${LOADED_REFS[$k]}"
    fi
  done
  exit 0
fi

# ---------------------------------------------------------------------------
# Step 2: prepare .env (copy from example, then force-set deploy-time vars)
# ---------------------------------------------------------------------------
set_env_var() {
  # Update KEY if present, else append. Escapes backslashes and ampersands for sed.
  local key="$1" value="$2"
  local escaped
  escaped="$(printf '%s' "$value" | sed -e 's/\\/\\\\/g' -e 's/&/\\&/g')"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i.bak "s~^${key}=.*~${key}=\"${escaped}\"~" "$ENV_FILE"
  else
    printf '%s="%s"\n' "$key" "$value" >> "$ENV_FILE"
  fi
  rm -f "${ENV_FILE}.bak"
}

generate_jwt() {
  # HS256 JWT for a Supabase role, signed with $1=JWT_SECRET, $2=role.
  local secret="$1" role="$2"
  local now exp header header_b64 payload payload_b64 sig
  now="$(date +%s)"
  exp=$((now + 157680000))
  header='{"alg":"HS256","typ":"JWT"}'
  header_b64="$(printf '%s' "$header" | base64 | tr -d '\n=' | tr '/+' '_-')"
  payload="{\"role\":\"$role\",\"iss\":\"supabase\",\"iat\":$now,\"exp\":$exp}"
  payload_b64="$(printf '%s' "$payload" | base64 | tr -d '\n=' | tr '/+' '_-')"
  sig="$(printf '%s' "$header_b64.$payload_b64" | openssl dgst -sha256 -hmac "$secret" -binary | base64 | tr -d '\n=' | tr '/+' '_-')"
  printf '%s.%s.%s' "$header_b64" "$payload_b64" "$sig"
}

prepare_env() {
  step "Preparing $ENV_FILE"
  if [[ ! -f "$ENV_FILE" ]] && [[ -f "${DOCKER_DIR}/.env.example" ]]; then
    cp "${DOCKER_DIR}/.env.example" "$ENV_FILE"
    ok "Created .env from .env.example"
  fi
  [[ -f "$ENV_FILE" ]] || die ".env not found and no .env.example to copy."

  # Layout / version / paths.
  set_env_var "ROOT_DIR" "$ROOT_DIR"
  set_env_var "DEPLOYMENT_VERSION" "full"
  set_env_var "DEPLOYMENT_MODE" "development"
  set_env_var "NEXENT_USER_DIR" "$HOME/nexent"

  # Image references -> canonical names (now present locally after the load step).
  local k
  for k in "${!CANONICAL[@]}"; do
    set_env_var "$k" "${CANONICAL[$k]}"
  done

  # MinIO access keys (generate if absent).
  if ! grep -q "^MINIO_ACCESS_KEY=." "$ENV_FILE" || ! grep -q "^MINIO_SECRET_KEY=." "$ENV_FILE"; then
    local ak sk
    ak="$(openssl rand -hex 12 | sed 's/[^a-zA-Z0-9]//g')"
    sk="$(openssl rand -base64 32 | tr -d '\r\n' | sed 's/[^a-zA-Z0-9+/=]//g')"
    set_env_var "MINIO_ACCESS_KEY" "$ak"
    set_env_var "MINIO_SECRET_KEY" "$sk"
    ok "Generated MinIO access keys (AK: $ak)"
  else
    ok "Reusing existing MinIO access keys"
  fi

  # Supabase secret set (generate fresh every run, like deploy.sh).
  local jwt_secret anon_key service_role_key
  jwt_secret="$(openssl rand -base64 32 | tr -d '[:space:]')"
  anon_key="$(generate_jwt "$jwt_secret" "anon")"
  service_role_key="$(generate_jwt "$jwt_secret" "service_role")"
  set_env_var "JWT_SECRET" "$jwt_secret"
  set_env_var "SECRET_KEY_BASE" "$(openssl rand -base64 64 | tr -d '[:space:]')"
  set_env_var "VAULT_ENC_KEY" "$(openssl rand -base64 32 | tr -d '[:space:]')"
  set_env_var "SUPABASE_KEY" "$anon_key"
  set_env_var "SERVICE_ROLE_KEY" "$service_role_key"
  ok "Generated Supabase JWT secret + anon/service_role keys"

  # Re-source so this shell sees the new values.
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
}

prepare_directories() {
  step "Preparing data directories under $ROOT_DIR"
  mkdir -p "$ROOT_DIR/elasticsearch" "$ROOT_DIR/postgresql" "$ROOT_DIR/minio/data" "$ROOT_DIR/redis" "$ROOT_DIR/skills"
  mkdir -p "$ROOT_DIR/openssh-server/ssh-keys"
  chmod -R 775 "$ROOT_DIR/elasticsearch" "$ROOT_DIR/postgresql" "$ROOT_DIR/minio" "$ROOT_DIR/redis" 2>/dev/null || true

  # supabase compose mounts $ROOT_DIR/volumes/db/*.sql and kong.yml; copy once.
  if [[ ! -d "$ROOT_DIR/volumes" ]]; then
    cp -rn "${DOCKER_DIR}/volumes" "$ROOT_DIR"
    chmod -R 775 "$ROOT_DIR/volumes"
    ok "Copied volumes/ -> $ROOT_DIR/volumes"
  fi
  # nexent-config mounts $ROOT_DIR/scripts/sync_user_supabase2pg.py.
  if [[ ! -d "$ROOT_DIR/scripts" ]]; then
    cp -rn "${DOCKER_DIR}/scripts" "$ROOT_DIR"
    ok "Copied scripts/ -> $ROOT_DIR/scripts"
  fi

  # Nexent user workspace (mounted to /mnt/nexent). Optional skills bundle.
  mkdir -p "$HOME/nexent"
  if [[ -d "${DOCKER_DIR}/official-skills-zip" ]] && [[ ! -d "$HOME/nexent/official-skills-zip" ]]; then
    cp -rn "${DOCKER_DIR}/official-skills-zip" "$HOME/nexent/"
    chmod -R 775 "$HOME/nexent/official-skills-zip"
    ok "Copied official-skills-zip -> $HOME/nexent/official-skills-zip"
  fi
  ok "Directories ready"
}

# ---------------------------------------------------------------------------
# Step 3: bring up services in dependency order
# ---------------------------------------------------------------------------
COMPOSE_UP_PREFIX=("${COMPOSE[@]}" -p "$PROJECT_NAME")

up_infrastructure() {
  step "Starting infrastructure (elasticsearch, postgresql, redis, minio)"
  "${COMPOSE_UP_PREFIX[@]}" -f "$COMPOSE_MAIN" up -d nexent-elasticsearch nexent-postgresql redis nexent-minio
  ok "Infrastructure services started"
}

wait_elasticsearch_healthy() {
  step "Waiting for Elasticsearch to become healthy"
  local retries=0 max=60
  while ! "${COMPOSE_UP_PREFIX[@]}" -f "$COMPOSE_MAIN" ps nexent-elasticsearch 2>/dev/null | grep -q "healthy" && [[ $retries -lt $max ]]; do
    printf '   ⏳ waiting... (%d/%d)\n' "$((retries + 1))" "$max"
    sleep 10
    retries=$((retries + 1))
  done
  [[ $retries -ge $max ]] && { warn "Elasticsearch did not report healthy in time; continuing anyway."; return 0; }
  ok "Elasticsearch is healthy"
}

generate_elasticsearch_api_key() {
  step "Generating Elasticsearch API key"
  local api_json encoded
  api_json="$(docker exec nexent-elasticsearch curl -s -u "elastic:${ELASTIC_PASSWORD}" \
    "http://localhost:9200/_security/api_key" -H "Content-Type: application/json" \
    -d '{"name":"nexent_api_key","role_descriptors":{"nexent_role":{"cluster":["all"],"index":[{"names":["*"],"privileges":["all"]}]}}}')"
  encoded="$(printf '%s' "$api_json" | sed -n 's/.*"encoded":"\([^"]*\)".*/\1/p')"
  if [[ -z "$encoded" ]] || [[ "$encoded" == "$api_json" ]]; then
    warn "Failed to extract Elasticsearch API key. Response: $api_json"
    return 0
  fi
  set_env_var "ELASTICSEARCH_API_KEY" "$encoded"
  ELASTICSEARCH_API_KEY="$encoded"
  ok "ELASTICSEARCH_API_KEY generated and written to .env"
}

up_supabase() {
  step "Starting Supabase (kong, auth, db)"
  "${COMPOSE_UP_PREFIX[@]}" -f "$COMPOSE_SUPABASE" up -d
  ok "Supabase services started"
}

up_core() {
  step "Starting application services (config, runtime, mcp, northbound, web)"
  local core=(nexent-config nexent-runtime nexent-mcp nexent-northbound nexent-web)
  "${COMPOSE_UP_PREFIX[@]}" -f "$COMPOSE_MAIN" up -d "${core[@]}"
  if [[ "$WITH_DATA_PROCESS" == "true" ]]; then
    "${COMPOSE_UP_PREFIX[@]}" -f "$COMPOSE_MAIN" up -d nexent-data-process
    ok "data-process started"
  fi
  ok "Application services started"
}

create_super_admin() {
  step "Creating default super admin user (suadmin@nexent.com)"
  local script="${DOCKER_DIR}/create-su.sh"
  [[ -f "$script" ]] || { warn "create-su.sh not found at $script; skipping."; return 0; }
  chmod +x "$script"

  local password="$SU_PASSWORD"
  if [[ -z "$password" ]]; then
    log "   No --su-password given; create-su.sh will prompt interactively."
    log "   (Email: suadmin@nexent.com)"
  fi

  # create-su.sh sources .env and uses docker exec, so the vars above are enough.
  if bash "$script" "$password"; then
    ok "Super admin user ready"
  else
    warn "Super admin creation reported an error (deployment otherwise complete)."
  fi
}

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
prepare_env
prepare_directories

up_infrastructure
wait_elasticsearch_healthy
# ES API key MUST be written before core services start, since they read it
# from .env at container start.
generate_elasticsearch_api_key

up_supabase
up_core

[[ "$SKIP_SUADMIN" == "true" ]] || create_super_admin

step "Deployment complete 🎉"
log "   Web UI        : http://localhost:3000"
log "   Northbound API: http://localhost:5013/api"
log "   MinIO console : http://localhost:9011"
log "   Supabase (kong): http://localhost:8000"
log ""
log "   Manage with:  cd $DOCKER_DIR && ${COMPOSE[*]} -p $PROJECT_NAME ps"
log "   Logs:         ${COMPOSE[*]} -p $PROJECT_NAME -f docker-compose.yml logs -f <service>"
log "   Stop:         ${COMPOSE[*]} -p $PROJECT_NAME -f docker-compose.yml -f docker-compose-supabase.yml down"
