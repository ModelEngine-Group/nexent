#!/usr/bin/env bash
#
# Offline k8s/helm deployment of the Nexent FULL version from pre-built image
# tars, for an air-gapped server that runs Kubernetes + Helm with containerd
# (no docker CLI).
#
# What it does:
#   1. Loads every .tar into containerd's k8s.io namespace (the only namespace
#      kubelet looks in) and tags each required image to BOTH the chart
#      reference and its docker.io normalized form. With the chart's
#      pullPolicy: Never, kubelet normalizes e.g. "redis:alpine" to
#      "docker.io/library/redis:alpine" before lookup, so both tags must exist.
#   2. Delegates the rest to the upstream k8s/helm/deploy.sh with
#      --image-source local-latest (pullPolicy: Never) and the full component
#      set (infrastructure,application,supabase). That script already handles
#      MinIO/Supabase secret generation, helm install, Elasticsearch API key
#      init and super-admin user creation.
#
# Run as root (or via sudo): the containerd socket and helm/kubectl need it.
#
# Usage:
#   bash deploy-offline-k8s.sh [--images-dir DIR] [--nexent-dir DIR]
#                              [--list-only] [-h]
#
# Examples:
#   bash deploy-offline-k8s.sh --list-only      # load tars, show mapping, do not deploy
#   bash deploy-offline-k8s.sh                  # full offline deploy (defaults below)

set -eo pipefail

# ---------------------------------------------------------------------------
# Defaults (overridable via flags or environment)
# ---------------------------------------------------------------------------
# Locate the upstream deploy script. The repo renamed k8s/helm/deploy-helm.sh
# to deploy.sh between versions; accept either name, searching this script's
# own directory first (natural placement beside the upstream script), then the
# conventional /run/nexent layout.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEXENT_DIR="${NEXENT_DIR:-/run/nexent}"
IMAGES_DIR="${IMAGES_DIR:-/run/nexent-images}"
LIST_ONLY="false"

# Canonical image references as used by the chart under --image-source local-latest
# (see scripts/deployment/common.sh deployment_apply_image_source). Tars are
# retagged to these exact names so the rendered Helm values resolve locally.
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

usage() { sed -n '20,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --images-dir)   IMAGES_DIR="$2"; shift 2 ;;
    --nexent-dir)   NEXENT_DIR="$2"; shift 2 ;;
    --deploy-script) DEPLOY_SH_OVERRIDE="$2"; shift 2 ;;
    --list-only)    LIST_ONLY="true"; shift ;;
    -h|--help)      usage ;;
    *) die "Unknown argument: $1 (try --help)" ;;
  esac
done

# Find the upstream deploy script under either of its known names.
# Prefer deploy.sh (current upstream name); fall back to the older deploy-helm.sh.
UPSTREAM_NAMES=("deploy.sh" "deploy-helm.sh")
find_upstream_deploy() {
  local d n
  for d in "$SCRIPT_DIR" "$NEXENT_DIR/k8s/helm"; do
    for n in "${UPSTREAM_NAMES[@]}"; do
      if [[ -f "$d/$n" ]]; then printf '%s/%s' "$d" "$n"; return 0; fi
    done
  done
  return 1
}

DEPLOY_SH="${DEPLOY_SH_OVERRIDE:-$(find_upstream_deploy || true)}"
HELM_DIR="$(dirname "${DEPLOY_SH:-$SCRIPT_DIR/deploy.sh}")"
if [[ -z "$DEPLOY_SH" ]] || [[ ! -f "$DEPLOY_SH" ]]; then
  cat >&2 <<EOF
❌ Upstream deploy script not found.
   Searched for deploy-helm.sh / deploy.sh in:
     $SCRIPT_DIR
     $NEXENT_DIR/k8s/helm
   This script is only the offline image-loading wrapper; it delegates the real
   deployment to the upstream nexent k8s/helm deploy script + the Helm chart +
   scripts/deployment/common.sh. They must all be present on the server.

   Check what you actually have:
     ls -la "$SCRIPT_DIR"
     find /run/nexent -maxdepth 4 -name 'deploy*helm*.sh' -o -name deploy.sh

   Fix by either:
     1. Put this script next to the real deploy script:
          cp deploy-offline-k8s.sh <dir-that-contains-deploy-helm.sh>/
     2. Point at the repo with --nexent-dir:
          bash deploy-offline-k8s.sh --nexent-dir /path/to/nexent
EOF
  exit 1
fi
ok "Using upstream deploy script: $DEPLOY_SH"

# ---------------------------------------------------------------------------
# Pre-flight: containerd tooling
# ---------------------------------------------------------------------------
command -v ctr >/dev/null 2>&1 || die "ctr not found (containerd CLI). Install containerd."
command -v helm >/dev/null 2>&1 || die "helm not found in PATH."
command -v kubectl >/dev/null 2>&1 || die "kubectl not found in PATH."

# Root or sudo is required for the containerd socket.
if [[ "$(id -u)" -eq 0 ]]; then SUDO=""; else SUDO="sudo"; fi

# Wrapper that always targets the k8s.io namespace (where kubelet pulls from).
crt() { $SUDO ctr -n k8s.io "$@"; }

# Image operations prefer nerdctl when available: it lists/tags images in the
# plain docker form the Helm chart uses (e.g. "nexent/nexent:latest", not
# "docker.io/nexent/nexent:latest"), which avoids the docker.io-normalization
# mismatch that makes ctr-based existence checks and tagging fail on
# nerdctl-imported images. Fall back to ctr when nerdctl is absent.
img_list_refs() {
  if command -v nerdctl >/dev/null 2>&1; then
    $SUDO nerdctl -n k8s.io images 2>/dev/null | awk 'NR>1 && $2!="" && $2!="<none>" {print $1":"$2}'
  else
    crt images ls 2>/dev/null | awk 'NR>1 && $1!="" && $1 !~ /^sha256:/ {print $1}'
  fi
}
img_exists() { img_list_refs | grep -Fxq "$1" 2>/dev/null; }
img_tag() {
  if command -v nerdctl >/dev/null 2>&1; then $SUDO nerdctl -n k8s.io tag "$1" "$2"
  else crt images tag "$1" "$2"; fi
}

# Sanity: can we talk to containerd?
crt images ls >/dev/null 2>&1 || die "Cannot reach containerd (ctr -n k8s.io). Run as root / check the socket."

log "Nexent dir : $NEXENT_DIR"
log "Images dir : $IMAGES_DIR"
log "Helm deploy: $DEPLOY_SH"
log "ctr        : ${SUDO:+$SUDO }ctr -n k8s.io"

# ---------------------------------------------------------------------------
# Image classification helpers
# ---------------------------------------------------------------------------

# Strip any docker.io normalization prefix from a repo reference so that both
# "docker.io/library/redis" and "redis" classify the same way.
strip_dockerhub_prefix() {
  local name="$1"
  name="${name#docker.io/library/}"
  name="${name#docker.io/}"
  printf '%s' "$name"
}

# Map a loaded image repo to a CANONICAL key by substring match.
classify_image() {
  local repo="$1" low
  low="$(printf '%s' "$repo" | tr '[:upper:]' '[:lower:]')"
  low="$(strip_dockerhub_prefix "$low")"
  low="${low//nexnet/nexent}"   # tolerate the common "nexnet" misspelling
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

# Compute the docker.io normalized alias of a chart image reference, so a
# pullPolicy: Never lookup succeeds. Returns empty for already-fully-qualified
# registries (anything with a dot in the first path segment, e.g. quay.io,
# docker.elastic.co) which kubelet does not re-prefix.
dockerhub_alias() {
  local ref="$1" name tag first
  name="${ref%:*}"; tag="${ref##*:}"
  first="${name%%/*}"
  if [[ "$first" == *.* ]]; then
    printf ''                      # fully-qualified registry, no alias needed
  elif [[ "$name" == */* ]]; then
    printf 'docker.io/%s:%s' "$name" "$tag"      # namespace/name
  else
    printf 'docker.io/library/%s:%s' "$name" "$tag"  # official image
  fi
}

# Tag an image reference (src) to dst if it is not already present that way.
tag_if_needed() {
  local src="$1" dst="$2" err
  [[ -n "$src" && -n "$dst" ]] || return 0
  img_exists "$dst" && return 0
  if err="$(img_tag "$src" "$dst" 2>&1)"; then
    ok "tagged $src -> $dst"
  else
    warn "tag failed: $src -> $dst ($err)"
  fi
}

# loaded_src[key] = the reference we retagged from (for the mapping report)
declare -A LOADED_SRC=()
UNMATCHED=()

# ---------------------------------------------------------------------------
# Step 1: import all tars, then scan the store and retag to canonical + alias
# ---------------------------------------------------------------------------
load_images() {
  step "Importing image tars into containerd (k8s.io namespace)"
  [[ -d "$IMAGES_DIR" ]] || die "Images directory not found: $IMAGES_DIR (use --images-dir)"

  local tars=()
  while IFS= read -r f; do tars+=("$f"); done < <(find "$IMAGES_DIR" -maxdepth 1 -type f -name '*.tar' | sort)
  [[ ${#tars[@]} -gt 0 ]] || die "No .tar files found in $IMAGES_DIR"

  # Prefer nerdctl for loading: it accepts docker-save archives that ctr's
  # importer rejects on manifest-list images ("content digest ... not found")
  # and writes straight into the k8s.io namespace. Fall back to ctr otherwise.
  local loader=()
  if command -v nerdctl >/dev/null 2>&1; then
    loader=($SUDO nerdctl -n k8s.io load -i)
    ok "loader: nerdctl (k8s.io namespace)"
  else
    loader=($SUDO ctr -n k8s.io images import --all-platforms --no-unpack)
    warn "nerdctl not found; using ctr (some docker tars may fail)"
  fi

  local tar out
  for tar in "${tars[@]}"; do
    if out="$("${loader[@]}" "$tar" 2>&1)"; then
      ok "imported $(basename "$tar")"
    else
      warn "import failed for $(basename "$tar"):"
      printf '%s\n' "$out" | sed 's/^/      /'
    fi
  done

  step "Retagging required images to chart + docker.io names"
  # Scan everything now in the store and classify. The same image may appear
  # under several names; retagging is idempotent.
  local ref key canonical alias
  while IFS= read -r ref; do
    [[ -n "$ref" ]] || continue
    key="$(classify_image "${ref%%:*}")"
    [[ -n "$key" ]] || continue
    canonical="${CANONICAL[$key]}"
    # Tag to the chart reference, then to the docker.io normalized alias.
    tag_if_needed "$ref" "$canonical"
    alias="$(dockerhub_alias "$canonical")"
    [[ -n "$alias" ]] && tag_if_needed "$ref" "$alias"
    LOADED_SRC["$key"]="$ref"
  done < <(img_list_refs | sort -u)
}

verify_required_images() {
  step "Verifying required images are present in containerd"
  local required=(ELASTICSEARCH_IMAGE POSTGRESQL_IMAGE REDIS_IMAGE MINIO_IMAGE \
                  NEXENT_IMAGE NEXENT_WEB_IMAGE SUPABASE_KONG SUPABASE_GOTRUE SUPABASE_DB)
  local missing=() k canonical alias present
  for k in "${required[@]}"; do
    canonical="${CANONICAL[$k]}"
    alias="$(dockerhub_alias "$canonical")"
    present=no
    if img_exists "$canonical"; then present=yes
    elif [[ -n "$alias" ]] && img_exists "$alias"; then present=yes; fi
    if [[ "$present" == yes ]]; then ok "$canonical"; else warn "MISSING: $canonical ($k)"; missing+=("$k"); fi
  done

  if [[ ${#missing[@]} -gt 0 ]]; then
    log ""
    log "Required image(s) not found among the loaded tars:"
    for k in "${missing[@]}"; do log "   - $k  =>  ${CANONICAL[$k]}"; done
    die "Add the missing tar(s) to $IMAGES_DIR, or retag manually with: crt images tag <src> <canonical>"
  fi
}

load_images
verify_required_images

# Show the full mapping for transparency.
step "Image mapping"
for k in ELASTICSEARCH_IMAGE POSTGRESQL_IMAGE REDIS_IMAGE MINIO_IMAGE \
         NEXENT_IMAGE NEXENT_WEB_IMAGE NEXENT_MCP_DOCKER_IMAGE \
         NEXENT_DATA_PROCESS_IMAGE SUPABASE_KONG SUPABASE_GOTRUE SUPABASE_DB; do
  if [[ -n "${LOADED_SRC[$k]:-}" ]]; then
    printf '   %-26s %-55s (from %s)\n' "$k" "${CANONICAL[$k]}" "${LOADED_SRC[$k]}"
  fi
done

# --list-only stops here so the mapping can be reviewed before a real deploy.
if [[ "$LIST_ONLY" == "true" ]]; then
  step "Dry run complete (--list-only). No helm release was created."
  exit 0
fi

# ---------------------------------------------------------------------------
# Step 2: delegate to the upstream helm deploy.sh (offline / local-latest)
# ---------------------------------------------------------------------------
step "Running upstream helm deploy.sh (local-latest, full components)"
log "   This generates secrets, runs helm install, inits Elasticsearch and"
log "   creates the super admin. It will prompt for the suadmin password."
log ""

# local-latest  -> pullPolicy: Never (use the containerd images we just loaded)
# full set      -> infrastructure + application + supabase (DEPLOYMENT_VERSION=full)
# development   -> NodePort exposure (web on 30000) for easy access
# "apply" must come first: the upstream deploy script requires an explicit
# subcommand (apply|delete|...) as the first positional argument; the options
# below are parsed afterwards by the shared common.sh.
bash "$DEPLOY_SH" apply \
  --image-source local-latest \
  --components infrastructure,application,supabase \
  --port-policy development

step "Deployment complete 🎉"
log "   Web UI (NodePort): http://<node-ip>:30000"
log "   Super admin email: suadmin@nexent.com"
log ""
log "   Pods:   kubectl -n nexent get pods"
log "   Uninstall: bash $HELM_DIR/uninstall.sh"
