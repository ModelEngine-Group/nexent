#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOYMENT_COMMON="$PROJECT_ROOT/scripts/deployment/common.sh"

DEFAULT_VERSION="latest"
DEFAULT_PLATFORM="amd64"
DEFAULT_OUTPUT_DIR="$PROJECT_ROOT/offline-package"
DEFAULT_INCLUDE_SOURCE="true"

VERSION=""
PLATFORM=""
OUTPUT_DIR=""
INCLUDE_SOURCE=""
DRY_RUN="false"
COMMON_ARGS=()

if [ -f "$DEPLOYMENT_COMMON" ]; then
  # shellcheck source=/dev/null
  source "$DEPLOYMENT_COMMON"
else
  echo "Error: shared deployment helper not found: $DEPLOYMENT_COMMON"
  exit 1
fi

show_help() {
  echo "Usage: $0 [OPTIONS]"
  echo ""
  echo "Build offline deployment package for Nexent"
  echo ""
  echo "Options:"
  echo "  --version VERSION       Nexent image version (e.g. v1.0.0 or latest)"
  echo "                           Default: $DEFAULT_VERSION"
  echo "  --platform PLATFORM     Target platform (amd64 or arm64)"
  echo "                           Default: $DEFAULT_PLATFORM"
  echo "  --output-dir DIR        Output directory for the package"
  echo "                           Default: $DEFAULT_OUTPUT_DIR"
  echo "  --include-source BOOL   Include source code (true or false)"
  echo "                           Default: $DEFAULT_INCLUDE_SOURCE"
  echo "  --components LIST       Deployment components for image selection"
  echo "  --image-source SOURCE   general, mainland, or local-latest"
  echo "  --registry-profile NAME Legacy alias for --image-source general|mainland"
  echo "  --config FILE           Deployment config with components and image source"
  echo "  --dry-run               Show execution plan without actual operations"
  echo "  --help                  Show this help message"
  echo ""
  echo "Examples:"
  echo "  $0 --version v1.0.0 --platform arm64"
  echo "  $0 --version latest --platform amd64 --include-source false"
  echo "  $0 --dry-run  # Show execution plan without actual operations"
}

parse_args() {
  local dry_run=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --version)
        VERSION="$2"
        shift 2
        ;;
      --platform)
        PLATFORM="$2"
        shift 2
        ;;
      --output-dir)
        OUTPUT_DIR="$2"
        shift 2
        ;;
      --include-source)
        INCLUDE_SOURCE="$2"
        shift 2
        ;;
      --dry-run)
        DRY_RUN="true"
        shift
        ;;
      --components|--image-source|--registry-profile|--app-version|--monitoring-provider|--port-policy|--config|--local-config)
        COMMON_ARGS+=("$1" "$2")
        shift 2
        ;;
      --use-local-config|--reconfigure)
        COMMON_ARGS+=("$1")
        shift
        ;;
      --help)
        show_help
        exit 0
        ;;
      *)
        echo "Unknown option: $1"
        show_help
        exit 1
        ;;
    esac
  done

  VERSION="${VERSION:-$DEFAULT_VERSION}"
  PLATFORM="${PLATFORM:-$DEFAULT_PLATFORM}"
  OUTPUT_DIR="${OUTPUT_DIR:-$DEFAULT_OUTPUT_DIR}"
  INCLUDE_SOURCE="${INCLUDE_SOURCE:-$DEFAULT_INCLUDE_SOURCE}"

  if [[ "$PLATFORM" != "amd64" && "$PLATFORM" != "arm64" ]]; then
    echo "Error: Platform must be 'amd64' or 'arm64'"
    exit 1
  fi
}

prepare_deployment_image_config() {
  export APP_VERSION="$VERSION"
  deployment_prepare_config "${COMMON_ARGS[@]}" --app-version "$VERSION" || exit 1

  case "$DEPLOYMENT_REGISTRY_PROFILE" in
    mainland)
      [ -f "$PROJECT_ROOT/docker/.env.mainland" ] && source "$PROJECT_ROOT/docker/.env.mainland"
      ;;
    general|local-latest)
      [ -f "$PROJECT_ROOT/docker/.env.general" ] && source "$PROJECT_ROOT/docker/.env.general"
      ;;
  esac

  deployment_apply_image_source
}

show_dry_run_plan() {
    echo "=== DRY RUN MODE ==="
    echo "Version: $VERSION"
    echo "Platform: $PLATFORM"
    echo "Output directory: $OUTPUT_DIR"
    echo "Include source: $INCLUDE_SOURCE"
    echo "Components: $DEPLOYMENT_COMPONENTS"
    echo "Image source: $DEPLOYMENT_IMAGE_SOURCE"
    echo ""
    echo "Images to pull:"
    get_nexent_images
    get_third_party_images
    echo ""
    echo "No actual operations will be performed."
    exit 0
}

get_nexent_images() {
  deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "application" && echo "$NEXENT_IMAGE"
  deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "application" && echo "$NEXENT_WEB_IMAGE"
  deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "application" && echo "$NEXENT_MCP_DOCKER_IMAGE"
  deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "data-process" && echo "$NEXENT_DATA_PROCESS_IMAGE"
  deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "terminal" && echo "$OPENSSH_SERVER_IMAGE"
  true
}

get_third_party_images() {
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "infrastructure"; then
    echo "$ELASTICSEARCH_IMAGE"
    echo "$POSTGRESQL_IMAGE"
    echo "$REDIS_IMAGE"
    echo "$MINIO_IMAGE"
  fi
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "supabase"; then
    echo "$SUPABASE_KONG"
    echo "$SUPABASE_GOTRUE"
    echo "$SUPABASE_DB"
  fi
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "monitoring"; then
    echo "otel/opentelemetry-collector-contrib:0.151.0"
    case "$DEPLOYMENT_MONITORING_PROVIDER" in
      phoenix) echo "arizephoenix/phoenix:15" ;;
      grafana)
        echo "grafana/tempo:2.10.5"
        echo "grafana/grafana:12.4"
        ;;
      zipkin) echo "openzipkin/zipkin:latest" ;;
      langfuse)
        echo "docker.io/langfuse/langfuse-worker:3"
        echo "docker.io/langfuse/langfuse:3"
        echo "docker.io/clickhouse/clickhouse-server:26.3-alpine"
        echo "docker.io/minio/minio:RELEASE.2023-12-20T01-00-02Z"
        echo "docker.io/redis:alpine"
        echo "docker.io/postgres:15-alpine"
        ;;
    esac
  fi
  true
}

pull_with_retry() {
  local image="$1"
  local platform="$2"
  local max_retries=3
  local retry=0
  local wait_time=5

  echo "Pulling image: $image (platform: $platform)"

  while [[ $retry -lt $max_retries ]]; do
    if docker pull --platform "linux/$platform" "$image"; then
      echo "✅ Successfully pulled: $image"
      return 0
    fi

    retry=$((retry + 1))
    echo "⚠️  Pull failed (attempt $retry/$max_retries), retrying in $wait_time seconds..."
    sleep $wait_time
  done

  echo "❌ Failed to pull image after $max_retries attempts: $image"
  return 1
}

pull_all_images() {
  echo ""
  echo "========================================"
  echo "Pulling Nexent images..."
  echo "========================================"

  local nexent_images_str
  nexent_images_str=$(get_nexent_images)

  while IFS= read -r image; do
    pull_with_retry "$image" "$PLATFORM" || {
      echo "❌ Failed to pull Nexent image: $image"
      return 1
    }
  done <<< "$nexent_images_str"

  echo ""
  echo "========================================"
  echo "Pulling third-party images..."
  echo "========================================"

  local third_party_images_str
  third_party_images_str=$(get_third_party_images)

  while IFS= read -r image; do
    pull_with_retry "$image" "$PLATFORM" || {
      echo "❌ Failed to pull third-party image: $image"
      return 1
    }
  done <<< "$third_party_images_str"

  echo ""
  echo "✅ All images pulled successfully"
}

save_image_to_tar() {
  local image="$1"
  local output_file="$2"

  echo "Saving image to tar: $output_file"

  if docker save -o "$output_file" "$image"; then
    echo "✅ Saved: $output_file"
    return 0
  else
    echo "❌ Failed to save image: $image"
    return 1
  fi
}

save_all_images() {
  local images_dir="$OUTPUT_DIR/images"

  mkdir -p "$images_dir"

  echo ""
  echo "========================================"
  echo "Saving images to tar files..."
  echo "========================================"

  local nexent_images_str
  nexent_images_str=$(get_nexent_images)

  while IFS= read -r image; do
    local image_name
    image_name=$(echo "$image" | sed 's/.*\///' | sed 's/:.*//')
    local image_tag
    image_tag=$(echo "$image" | sed 's/.*://' | sed 's/\./-/g')
    local tar_file="$images_dir/${image_name}-${image_tag}.tar"

    save_image_to_tar "$image" "$tar_file" || return 1
  done <<< "$nexent_images_str"

  local third_party_images_str
  third_party_images_str=$(get_third_party_images)

  while IFS= read -r image; do
    local image_name
    image_name=$(echo "$image" | sed 's/.*\///' | sed 's/:.*//')
    local image_tag
    image_tag=$(echo "$image" | sed 's/.*://' | sed 's/RELEASE\.//' | sed 's/\./-/g')
    local tar_file="$images_dir/${image_name}-${image_tag}.tar"

    save_image_to_tar "$image" "$tar_file" || return 1
  done <<< "$third_party_images_str"

  echo ""
  echo "✅ All images saved successfully"
}

copy_source_code() {
  if [[ "$INCLUDE_SOURCE" != "true" ]]; then
    echo "Skipping source code copy (include-source=false)"
    return 0
  fi

  local source_dir="$OUTPUT_DIR/nexent"

  echo ""
  echo "========================================"
  echo "Copying git-managed source code..."
  echo "========================================"

  echo "Source: $PROJECT_ROOT"
  echo "Destination: $source_dir"

  rm -rf "$source_dir"

  mkdir -p "$source_dir"

  if ! git -C "$PROJECT_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "⚠️  Warning: Project root is not a git repository"
    echo "   Falling back to copying all files (excluding .git and .github)"

    local cp_result=0
    if command -v rsync >/dev/null 2>&1; then
      rsync -a --exclude='.git' --exclude='.github' "$PROJECT_ROOT/" "$source_dir/" || cp_result=$?
    else
      shopt -s dotglob nullglob
      cp -r "$PROJECT_ROOT"/* "$source_dir/" 2>&1 || cp_result=$?
      shopt -u dotglob nullglob
      rm -rf "$source_dir/.git" "$source_dir/.github"
    fi

    if [[ $cp_result -ne 0 ]]; then
      echo "❌ Failed to copy source code"
      return 1
    fi

    echo "✅ Source code copied to: $source_dir"
    return 0
  fi

  echo "   Using git ls-files to get managed file list..."

  local git_files
  git_files=$(git -C "$PROJECT_ROOT" ls-files)

  if [[ -z "$git_files" ]]; then
    echo "❌ No git-managed files found"
    return 1
  fi

  local file_count
  file_count=$(echo "$git_files" | wc -l | tr -d ' ')
  echo "   Found $file_count git-managed files"

  local file
  while IFS= read -r file; do
    local src_file="$PROJECT_ROOT/$file"
    local dst_file="$source_dir/$file"
    local dst_dir

    dst_dir=$(dirname "$dst_file")

    if [[ -f "$src_file" ]]; then
      mkdir -p "$dst_dir"
      cp "$src_file" "$dst_file"
    fi
  done <<< "$git_files"

  echo "✅ Git-managed source code copied to: $source_dir"

  local total_size
  total_size=$(du -sh "$source_dir" | cut -f1)
  echo "   Total size: $total_size"

  return 0
}

create_load_script() {
  local load_script="$OUTPUT_DIR/load-images.sh"

  echo ""
  echo "========================================"
  echo "Creating load-images.sh script..."
  echo "========================================"

  cat > "$load_script" << 'LOADSCRIPT'
#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGES_DIR="$SCRIPT_DIR/images"

echo "Loading Docker images from $IMAGES_DIR..."

for tar_file in "$IMAGES_DIR"/*.tar; do
  if [[ -f "$tar_file" ]]; then
    echo "Loading: $tar_file"
    docker load -i "$tar_file"
  fi
done

echo ""
echo "✅ All images loaded successfully"
LOADSCRIPT

  chmod +x "$load_script"

  echo "✅ Created: $load_script"
}

main() {
  parse_args "$@"
  prepare_deployment_image_config

  if [[ "$DRY_RUN" == "true" ]]; then
    show_dry_run_plan
  fi

  echo ""
  echo "========================================"
  echo "Building Offline Deployment Package"
  echo "========================================"
  echo "Version: $VERSION"
  echo "Platform: $PLATFORM"
  echo "Output directory: $OUTPUT_DIR"
  echo "Include source: $INCLUDE_SOURCE"
  echo "Components: $DEPLOYMENT_COMPONENTS"
  echo "Image source: $DEPLOYMENT_IMAGE_SOURCE"
  echo "========================================"

  rm -rf "$OUTPUT_DIR"
  mkdir -p "$OUTPUT_DIR"

  pull_all_images || {
    echo "❌ Image pull failed, aborting"
    exit 1
  }

  save_all_images || {
    echo "❌ Image save failed, aborting"
    exit 1
  }

  copy_source_code || {
    echo "❌ Source code copy failed, aborting"
    exit 1
  }

  create_load_script || {
    echo "❌ Load script creation failed, aborting"
    exit 1
  }

  echo ""
  echo "========================================"
  echo "✅ Offline package build completed"
  echo "========================================"
  echo "Package contents available at: $OUTPUT_DIR"
  echo ""
}

main "$@"
