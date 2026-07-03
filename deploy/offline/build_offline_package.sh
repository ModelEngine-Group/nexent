#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY_ROOT="$PROJECT_ROOT/deploy"
DEPLOYMENT_COMMON="$DEPLOY_ROOT/common/common.sh"
VERSION_HELPER="$DEPLOY_ROOT/common/version.sh"

DEFAULT_VERSION="latest"
DEFAULT_PLATFORM="amd64"
DEFAULT_OUTPUT_DIR="$PROJECT_ROOT/offline-package"
DEFAULT_INCLUDE_SOURCE="false"
DEFAULT_TARGET="all"
DEFAULT_COMPRESS="false"

VERSION=""
PLATFORM=""
OUTPUT_DIR=""
INCLUDE_SOURCE=""
TARGET=""
COMPRESS=""
DRY_RUN="false"
COMMON_ARGS=()

if [ -f "$DEPLOYMENT_COMMON" ]; then
  # shellcheck source=/dev/null
  source "$DEPLOYMENT_COMMON"
else
  echo "Error: shared deployment helper not found: $DEPLOYMENT_COMMON"
  exit 1
fi

if [ -f "$VERSION_HELPER" ]; then
  # shellcheck source=/dev/null
  source "$VERSION_HELPER"
fi

show_help() {
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "用法：$0 [选项]"
    echo ""
    echo "构建 Nexent 离线部署包"
    echo ""
    echo "选项："
    echo "  --version VERSION       Nexent 镜像版本（例如 v1.0.0 或 latest）"
    echo "                           默认：$DEFAULT_VERSION"
    echo "  --platform PLATFORM     目标平台（amd64 或 arm64）"
    echo "                           默认：$DEFAULT_PLATFORM"
    echo "  --output-dir DIR        离线包输出目录"
    echo "                           默认：$DEFAULT_OUTPUT_DIR"
    echo "  --include-source BOOL   是否包含源码（true 或 false）"
    echo "                           默认：$DEFAULT_INCLUDE_SOURCE"
    echo "  --target TARGET         docker、k8s 或 all"
    echo "                           默认：$DEFAULT_TARGET"
    echo "  --compress BOOL         构建后是否创建 zip 压缩包（true 或 false）"
    echo "                           默认：$DEFAULT_COMPRESS"
    echo "  --components LIST       用于镜像选择的部署组件"
    echo "  --image-source SOURCE   general、mainland 或 local-latest"
    echo "  --registry-profile NAME 兼容旧参数，映射到 --image-source general|mainland"
    echo "  --config FILE           包含组件和镜像源的部署配置"
    echo "  --dry-run               只展示执行计划，不执行实际操作"
    echo "  --help                  显示帮助信息"
    echo ""
    echo "示例："
    echo "  $0 --version v1.0.0 --platform arm64"
    echo "  $0 --version latest --platform amd64 --include-source false"
    echo "  $0 --dry-run  # 只展示执行计划"
    return
  fi

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
  echo "  --target TARGET         docker, k8s, or all"
  echo "                           Default: $DEFAULT_TARGET"
  echo "  --compress BOOL        Create zip archive after package build (true or false)"
  echo "                           Default: $DEFAULT_COMPRESS"
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
      --target)
        TARGET="$2"
        shift 2
        ;;
      --compress)
        COMPRESS="$2"
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
        if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
          echo "未知选项：$1"
        else
          echo "Unknown option: $1"
        fi
        show_help
        exit 1
        ;;
    esac
  done

  if declare -F deployment_read_version >/dev/null 2>&1; then
    VERSION="${VERSION:-$(deployment_read_version "")}"
  else
    VERSION="${VERSION:-$DEFAULT_VERSION}"
  fi
  PLATFORM="${PLATFORM:-$DEFAULT_PLATFORM}"
  OUTPUT_DIR="${OUTPUT_DIR:-$DEFAULT_OUTPUT_DIR}"
  INCLUDE_SOURCE="${INCLUDE_SOURCE:-$DEFAULT_INCLUDE_SOURCE}"
  TARGET="${TARGET:-$DEFAULT_TARGET}"
  COMPRESS="${COMPRESS:-$DEFAULT_COMPRESS}"

  if [[ "$PLATFORM" != "amd64" && "$PLATFORM" != "arm64" ]]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "错误：Platform 必须是 'amd64' 或 'arm64'"
    else
      echo "Error: Platform must be 'amd64' or 'arm64'"
    fi
    exit 1
  fi
  if [[ "$TARGET" != "docker" && "$TARGET" != "k8s" && "$TARGET" != "all" ]]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "错误：Target 必须是 'docker'、'k8s' 或 'all'"
    else
      echo "Error: Target must be 'docker', 'k8s', or 'all'"
    fi
    exit 1
  fi
  if [[ "$COMPRESS" != "true" && "$COMPRESS" != "false" ]]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "错误：Compress 必须是 'true' 或 'false'"
    else
      echo "Error: Compress must be 'true' or 'false'"
    fi
    exit 1
  fi
}

prepare_deployment_image_config() {
  export APP_VERSION="$VERSION"
  deployment_prepare_config "${COMMON_ARGS[@]}" --app-version "$VERSION" || exit 1

  case "$DEPLOYMENT_REGISTRY_PROFILE" in
    mainland)
      [ -f "$DEPLOY_ROOT/env/image-source.mainland.env" ] && source "$DEPLOY_ROOT/env/image-source.mainland.env"
      ;;
    general|local-latest)
      [ -f "$DEPLOY_ROOT/env/image-source.general.env" ] && source "$DEPLOY_ROOT/env/image-source.general.env"
      ;;
  esac

  deployment_apply_image_source
}

show_dry_run_plan() {
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "=== DRY RUN 模式 ==="
    echo "版本：$VERSION"
    echo "平台：$PLATFORM"
    echo "输出目录：$OUTPUT_DIR"
    echo "包含源码：$INCLUDE_SOURCE"
    echo "目标：$TARGET"
    echo "压缩：$COMPRESS"
    echo "组件：$DEPLOYMENT_COMPONENTS"
    echo "镜像源：$DEPLOYMENT_IMAGE_SOURCE"
    echo ""
    echo "将拉取的镜像："
    get_nexent_images
    get_third_party_images
    echo ""
    echo "不会执行实际操作。"
    exit 0
  fi

    echo "=== DRY RUN MODE ==="
    echo "Version: $VERSION"
    echo "Platform: $PLATFORM"
    echo "Output directory: $OUTPUT_DIR"
    echo "Include source: $INCLUDE_SOURCE"
    echo "Target: $TARGET"
    echo "Compress: $COMPRESS"
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

uses_latest_tag() {
  local image="$1"
  local tag="${image##*:}"
  [[ "$tag" == "latest" ]]
}

image_exists_locally() {
  local image="$1"
  docker image inspect "$image" >/dev/null 2>&1
}

should_skip_pull() {
  local image="$1"

  if image_exists_locally "$image"; then
    echo "Using existing local image without pulling: $image"
    return 0
  fi

  if uses_latest_tag "$image"; then
    echo "Skipping pull for latest image; expecting local image: $image"
    return 0
  fi

  return 1
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
    if should_skip_pull "$image"; then
      continue
    fi

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
    if should_skip_pull "$image"; then
      continue
    fi

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

copy_deployment_bundle() {
  echo ""
  echo "========================================"
  echo "Copying deployment bundle..."
  echo "========================================"

  cp "$PROJECT_ROOT/deploy.sh" "$OUTPUT_DIR/deploy.sh"
  cp "$PROJECT_ROOT/uninstall.sh" "$OUTPUT_DIR/uninstall.sh"
  cp "$PROJECT_ROOT/VERSION" "$OUTPUT_DIR/VERSION"

  if command -v rsync >/dev/null 2>&1; then
    rsync -a \
      --exclude='.DS_Store' \
      --exclude='deploy.options' \
      --exclude='env/.env' \
      --exclude='env/.env.bak' \
      --exclude='env/monitoring.env' \
      --exclude='docker/.env.generated' \
      --exclude='k8s/helm/nexent/generated-values.yaml' \
      --exclude='k8s/helm/nexent/generated-runtime-values.yaml' \
      --exclude='k8s/helm/nexent/generated-secrets-values.yaml' \
      --exclude='k8s/helm/nexent/generated-persistence-values.yaml' \
      "$DEPLOY_ROOT/" "$OUTPUT_DIR/deploy/"
  else
    cp -R "$DEPLOY_ROOT" "$OUTPUT_DIR/deploy"
    find "$OUTPUT_DIR" -name '.DS_Store' -type f -delete 2>/dev/null || true
  fi

  rm -f "$OUTPUT_DIR/deploy/env/.env" "$OUTPUT_DIR/deploy/env/.env.bak" "$OUTPUT_DIR/deploy/env/monitoring.env" "$OUTPUT_DIR/deploy/docker/.env.generated" "$OUTPUT_DIR/deploy/docker/deploy.options" "$OUTPUT_DIR/deploy/k8s/deploy.options"
  rm -f "$OUTPUT_DIR/deploy/k8s/helm/nexent/generated-values.yaml" "$OUTPUT_DIR/deploy/k8s/helm/nexent/generated-runtime-values.yaml" "$OUTPUT_DIR/deploy/k8s/helm/nexent/generated-secrets-values.yaml" "$OUTPUT_DIR/deploy/k8s/helm/nexent/generated-persistence-values.yaml"
  case "$TARGET" in
    docker) rm -rf "$OUTPUT_DIR/deploy/k8s" ;;
    k8s) rm -rf "$OUTPUT_DIR/deploy/docker" ;;
  esac

  find "$OUTPUT_DIR" -name '.git' -type d -prune -exec rm -rf {} + 2>/dev/null || true
  chmod +x "$OUTPUT_DIR/deploy.sh" "$OUTPUT_DIR/uninstall.sh" "$OUTPUT_DIR/load-images.sh" 2>/dev/null || true
  find "$OUTPUT_DIR/deploy" -type f -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true

  echo "✅ Deployment bundle copied"
}

create_manifest() {
  local manifest="$OUTPUT_DIR/manifest.yaml"
  local image

  echo ""
  echo "========================================"
  echo "Creating manifest.yaml..."
  echo "========================================"

  {
    echo "version: \"$VERSION\""
    echo "platform: \"$PLATFORM\""
    echo "target: \"$TARGET\""
    echo "components: \"$DEPLOYMENT_COMPONENTS\""
    echo "imageSource: \"$DEPLOYMENT_IMAGE_SOURCE\""
    echo "images:"
    while IFS= read -r image; do
      [ -n "$image" ] && echo "  - \"$image\""
    done < <(get_nexent_images; get_third_party_images)
  } > "$manifest"

  echo "✅ Created: $manifest"
}

create_checksums() {
  local checksum_file="$OUTPUT_DIR/checksums.txt"
  echo ""
  echo "========================================"
  echo "Creating checksums.txt..."
  echo "========================================"

  if command -v sha256sum >/dev/null 2>&1; then
    (
      cd "$OUTPUT_DIR"
      find . -type f ! -name checksums.txt -print | LC_ALL=C sort | while IFS= read -r file; do
        sha256sum "$file"
      done
    ) > "$checksum_file"
  elif command -v shasum >/dev/null 2>&1; then
    (
      cd "$OUTPUT_DIR"
      find . -type f ! -name checksums.txt -print | LC_ALL=C sort | while IFS= read -r file; do
        shasum -a 256 "$file"
      done
    ) > "$checksum_file"
  else
    echo "❌ sha256sum or shasum is required to create checksums"
    return 1
  fi

  echo "✅ Created: $checksum_file"
}

offline_package_name() {
  local safe_version="${VERSION//\//-}"
  echo "nexent-offline-${TARGET}-${PLATFORM}-${safe_version}"
}

create_zip_package() {
  if [[ "$COMPRESS" != "true" ]]; then
    echo "Skipping zip archive creation (compress=false)"
    return 0
  fi

  if ! command -v zip >/dev/null 2>&1; then
    echo "❌ zip is required to create compressed package"
    return 1
  fi

  local output_parent
  local archive_file

  output_parent="$(cd "$(dirname "$OUTPUT_DIR")" && pwd)"
  archive_file="$output_parent/$(offline_package_name).zip"

  echo ""
  echo "========================================"
  echo "Creating zip package..."
  echo "========================================"

  rm -f "$archive_file"
  (cd "$OUTPUT_DIR" && zip -r "$archive_file" .)

  echo "✅ Created: $archive_file"
  ls -lh "$archive_file"
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
  echo "Target: $TARGET"
  echo "Compress: $COMPRESS"
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

  copy_deployment_bundle || {
    echo "❌ Deployment bundle copy failed, aborting"
    exit 1
  }

  create_manifest || {
    echo "❌ Manifest creation failed, aborting"
    exit 1
  }

  create_checksums || {
    echo "❌ Checksum creation failed, aborting"
    exit 1
  }

  create_zip_package || {
    echo "❌ Zip package creation failed, aborting"
    exit 1
  }

  echo ""
  echo "========================================"
  echo "✅ Offline package build completed"
  echo "========================================"
  echo "Package contents available at: $OUTPUT_DIR"
  if [[ "$COMPRESS" == "true" ]]; then
    echo "Compressed package available at: $(cd "$(dirname "$OUTPUT_DIR")" && pwd)/$(offline_package_name).zip"
  fi
  echo ""
}

main "$@"
