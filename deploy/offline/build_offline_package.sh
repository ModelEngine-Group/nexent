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
DEFAULT_INCLUDE_SANDBOX="true"
DEFAULT_INCLUDE_SANDBOX_FULL="false"
DEFAULT_TARGET="all"
DEFAULT_COMPRESS="false"

VERSION=""
PLATFORM=""
OUTPUT_DIR=""
INCLUDE_SOURCE=""
INCLUDE_SANDBOX=""
INCLUDE_SANDBOX_FULL=""
TARGET=""
COMPRESS=""
PACKAGE_NAME=""
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
    echo "  --include-sandbox BOOL  是否包含 Sandbox 镜像（true 或 false）"
    echo "                           默认：$DEFAULT_INCLUDE_SANDBOX"
    echo "  --include-sandbox-full BOOL"
    echo "                           是否额外生成独立的完整 Sandbox ZIP 附件（true 或 false）"
    echo "                           即使 --compress 为 false，附件仍生成 ZIP"
    echo "                           默认：$DEFAULT_INCLUDE_SANDBOX_FULL"
    echo "  --target TARGET         docker、k8s 或 all"
    echo "                           默认：$DEFAULT_TARGET"
    echo "  --compress BOOL         构建后是否创建 zip 压缩包（true 或 false）"
    echo "                           默认：$DEFAULT_COMPRESS"
    echo "  --package-name NAME     最终 zip 包名称（可省略 .zip 后缀）"
    echo "                           默认：根据目标、平台和版本自动生成"
    echo "  --components LIST       用于镜像选择的部署组件"
    echo "  --image-source SOURCE   general、mainland 或 local-latest"
    echo "  --registry-profile NAME 兼容旧参数，映射到 --image-source general|mainland"
    echo "  --image-registry-prefix PREFIX"
    echo "                           使用指定镜像仓库前缀拉取和打包镜像"
    echo "  --defaults              复用保存配置或内置默认值并跳过交互界面"
    echo "  --config                进入交互式部署配置界面"
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
  echo "  --include-sandbox BOOL  Include the Sandbox image (true or false)"
  echo "                           Default: $DEFAULT_INCLUDE_SANDBOX"
  echo "  --include-sandbox-full BOOL"
  echo "                           Create a separate full Sandbox ZIP attachment (true or false)"
  echo "                           The attachment is zipped even when --compress is false"
  echo "                           Default: $DEFAULT_INCLUDE_SANDBOX_FULL"
  echo "  --target TARGET         docker, k8s, or all"
  echo "                           Default: $DEFAULT_TARGET"
  echo "  --compress BOOL        Create zip archive after package build (true or false)"
  echo "                           Default: $DEFAULT_COMPRESS"
  echo "  --package-name NAME     Final zip package name (.zip suffix is optional)"
  echo "                           Default: generated from target, platform, and version"
  echo "  --components LIST       Deployment components for image selection"
  echo "  --image-source SOURCE   general, mainland, or local-latest"
  echo "  --registry-profile NAME Legacy alias for --image-source general|mainland"
  echo "  --image-registry-prefix PREFIX"
  echo "                           Pull and package images with this registry prefix"
  echo "  --defaults              Use saved config or built-in defaults and skip TUI"
  echo "  --config                Open the interactive deployment configuration"
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
      --include-sandbox)
        INCLUDE_SANDBOX="$2"
        shift 2
        ;;
      --include-sandbox-full)
        INCLUDE_SANDBOX_FULL="$2"
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
      --package-name)
        PACKAGE_NAME="$2"
        shift 2
        ;;
      --dry-run)
        DRY_RUN="true"
        shift
        ;;
      --components|--image-source|--registry-profile|--image-registry-prefix|--registry-prefix|--image-registry|--app-version|--monitoring-provider|--port-policy|--local-config)
        COMMON_ARGS+=("$1" "$2")
        shift 2
        ;;
      --defaults|--config|--use-local-config|--reconfigure)
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
  INCLUDE_SANDBOX="${INCLUDE_SANDBOX:-$DEFAULT_INCLUDE_SANDBOX}"
  INCLUDE_SANDBOX_FULL="${INCLUDE_SANDBOX_FULL:-$DEFAULT_INCLUDE_SANDBOX_FULL}"
  TARGET="${TARGET:-$DEFAULT_TARGET}"
  COMPRESS="${COMPRESS:-$DEFAULT_COMPRESS}"
  PACKAGE_NAME="${PACKAGE_NAME%.zip}"

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
  if [[ "$INCLUDE_SANDBOX" != "true" && "$INCLUDE_SANDBOX" != "false" ]]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "错误：Include sandbox 必须是 'true' 或 'false'"
    else
      echo "Error: Include sandbox must be 'true' or 'false'"
    fi
    exit 1
  fi
  if [[ "$INCLUDE_SANDBOX_FULL" != "true" && "$INCLUDE_SANDBOX_FULL" != "false" ]]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "错误：Include full sandbox 必须是 'true' 或 'false'"
    else
      echo "Error: Include full sandbox must be 'true' or 'false'"
    fi
    exit 1
  fi
  if [[ -n "$PACKAGE_NAME" && ! "$PACKAGE_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "错误：Package name 只能包含字母、数字、点、下划线和连字符，且必须以字母或数字开头"
    else
      echo "Error: Package name may contain only letters, numbers, dots, underscores, and hyphens, and must start with a letter or number"
    fi
    exit 1
  fi
  if [ "$INCLUDE_SANDBOX_FULL" = "true" ] && [ "$COMPRESS" = "true" ] &&
    [ "$(offline_package_name)" = "$(full_sandbox_package_name)" ]; then
    echo "Error: main package and full Sandbox attachment must have different names"
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

  # Package selection is independent of a saved runtime Sandbox preference.
  DEPLOYMENT_SANDBOX_MODE="lightweight"
  deployment_apply_image_source
}

show_dry_run_plan() {
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "=== DRY RUN 模式 ==="
    echo "版本：$VERSION"
    echo "平台：$PLATFORM"
    echo "输出目录：$OUTPUT_DIR"
    echo "包含源码：$INCLUDE_SOURCE"
    echo "包含 Sandbox 镜像：$INCLUDE_SANDBOX"
    echo "独立完整 Sandbox 附件：$INCLUDE_SANDBOX_FULL"
    echo "目标：$TARGET"
    echo "压缩：$COMPRESS"
    echo "最终包名称：$(offline_package_name).zip"
    echo "组件：$DEPLOYMENT_COMPONENTS"
    echo "镜像源：$DEPLOYMENT_IMAGE_SOURCE"
    [ -n "$DEPLOYMENT_IMAGE_REGISTRY_PREFIX" ] && echo "镜像仓库前缀：$DEPLOYMENT_IMAGE_REGISTRY_PREFIX"
    echo ""
    echo "将拉取的镜像："
    get_nexent_images
    get_third_party_images
    show_full_sandbox_attachment_plan
    echo ""
    echo "不会执行实际操作。"
    exit 0
  fi

    echo "=== DRY RUN MODE ==="
    echo "Version: $VERSION"
    echo "Platform: $PLATFORM"
    echo "Output directory: $OUTPUT_DIR"
    echo "Include source: $INCLUDE_SOURCE"
    echo "Include Sandbox image: $INCLUDE_SANDBOX"
    echo "Separate full Sandbox attachment: $INCLUDE_SANDBOX_FULL"
    echo "Target: $TARGET"
    echo "Compress: $COMPRESS"
    echo "Package name: $(offline_package_name).zip"
    echo "Components: $DEPLOYMENT_COMPONENTS"
    echo "Image source: $DEPLOYMENT_IMAGE_SOURCE"
    [ -n "$DEPLOYMENT_IMAGE_REGISTRY_PREFIX" ] && echo "Image registry prefix: $DEPLOYMENT_IMAGE_REGISTRY_PREFIX"
    echo ""
    echo "Images to pull:"
    get_nexent_images
    get_third_party_images
    show_full_sandbox_attachment_plan
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
  [ "$INCLUDE_SANDBOX" = "true" ] && echo "$NEXENT_SANDBOX_IMAGE"
  true
}

full_sandbox_package_name() {
  local safe_version="${VERSION//\//-}"
  echo "nexent-sandbox-full-${safe_version}-${PLATFORM}"
}

show_full_sandbox_attachment_plan() {
  if [ "$INCLUDE_SANDBOX_FULL" = "true" ]; then
    echo ""
    echo "Separate attachment: $(full_sandbox_package_name).zip"
    full_sandbox_image
  fi
}

full_sandbox_image() {
  local image_prefix="${NEXENT_SANDBOX_IMAGE%nexent-sandbox:*}"
  local image_tag="${NEXENT_SANDBOX_IMAGE##*:}"
  echo "${image_prefix}nexent-sandbox-full:${image_tag}"
}

get_third_party_images() {
  local image
  echo_image_ref() {
    deployment_add_image_registry_prefix "$1"
    echo ""
  }

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
    echo_image_ref "otel/opentelemetry-collector-contrib:0.151.0"
    case "$DEPLOYMENT_MONITORING_PROVIDER" in
      phoenix) echo_image_ref "arizephoenix/phoenix:15" ;;
      grafana)
        echo_image_ref "grafana/tempo:2.10.5"
        echo_image_ref "grafana/grafana:12.4"
        ;;
      zipkin) echo_image_ref "openzipkin/zipkin:latest" ;;
      langfuse)
        for image in \
          "docker.io/langfuse/langfuse-worker:3" \
          "docker.io/langfuse/langfuse:3" \
          "docker.io/clickhouse/clickhouse-server:26.3-alpine" \
          "quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z" \
          "docker.io/redis:alpine" \
          "docker.io/postgres:15-alpine"; do
          echo_image_ref "$image"
        done
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
    [ -n "$image" ] || continue
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
    [ -n "$image" ] || continue
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
    [ -n "$image" ] || continue
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
    [ -n "$image" ] || continue
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
  if [ -f "$source_dir/VERSION" ]; then
    printf '%s\n' "$VERSION" > "$source_dir/VERSION"
  fi

  local total_size
  total_size=$(du -sh "$source_dir" | cut -f1)
  echo "   Total size: $total_size"

  return 0
}

copy_load_script() {
  local load_script="$OUTPUT_DIR/load-images.sh"
  local template_script="$SCRIPT_DIR/load-images.sh"

  echo ""
  echo "========================================"
  echo "Copying load-images.sh script..."
  echo "========================================"

  if [ ! -f "$template_script" ]; then
    echo "❌ load-images.sh template not found: $template_script"
    return 1
  fi

  cp "$template_script" "$load_script" || return 1
  chmod +x "$load_script" || return 1

  echo "✅ Created: $load_script"
}

copy_push_script() {
  local push_script="$OUTPUT_DIR/push-images.sh"
  local template_script="$SCRIPT_DIR/push-images.sh"

  echo ""
  echo "========================================"
  echo "Copying push-images.sh script..."
  echo "========================================"

  if [ ! -f "$template_script" ]; then
    echo "❌ push-images.sh template not found: $template_script"
    return 1
  fi

  cp "$template_script" "$push_script" || return 1
  chmod +x "$push_script" || return 1

  echo "✅ Created: $push_script"
}

create_offline_deploy_entrypoint() {
  local deploy_script="$OUTPUT_DIR/deploy.sh"

  if [ ! -f "$deploy_script" ]; then
    echo "❌ deploy.sh not found in offline package: $deploy_script"
    return 1
  fi
  if ! grep -q '^DEPLOY_WRAPPER_DEFAULT_CONFIG_MODE=""$' "$deploy_script"; then
    echo "❌ deploy.sh does not contain the offline mode marker: $deploy_script"
    return 1
  fi

  local tmp_script="${deploy_script}.tmp"
  sed 's/^DEPLOY_WRAPPER_DEFAULT_CONFIG_MODE=""$/DEPLOY_WRAPPER_DEFAULT_CONFIG_MODE="defaults"/' "$deploy_script" > "$tmp_script"
  mv "$tmp_script" "$deploy_script"
}

copy_deployment_bundle() {
  echo ""
  echo "========================================"
  echo "Copying deployment bundle..."
  echo "========================================"

  cp "$PROJECT_ROOT/deploy.sh" "$OUTPUT_DIR/deploy.sh"
  cp "$PROJECT_ROOT/uninstall.sh" "$OUTPUT_DIR/uninstall.sh"
  printf '%s\n' "$VERSION" > "$OUTPUT_DIR/VERSION"

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
      --exclude='k8s/helm/nexent-infrastructure/generated-values.yaml' \
      --exclude='k8s/helm/nexent-infrastructure/generated-runtime-values.yaml' \
      --exclude='k8s/helm/nexent-infrastructure/generated-secrets-values.yaml' \
      --exclude='k8s/helm/nexent-infrastructure/generated-persistence-values.yaml' \
      "$DEPLOY_ROOT/" "$OUTPUT_DIR/deploy/"
  else
    cp -R "$DEPLOY_ROOT" "$OUTPUT_DIR/deploy"
    find "$OUTPUT_DIR" -name '.DS_Store' -type f -delete 2>/dev/null || true
  fi

  rm -f "$OUTPUT_DIR/deploy/env/.env" "$OUTPUT_DIR/deploy/env/.env.bak" "$OUTPUT_DIR/deploy/env/monitoring.env" "$OUTPUT_DIR/deploy/docker/.env.generated" "$OUTPUT_DIR/deploy/docker/deploy.options" "$OUTPUT_DIR/deploy/k8s/deploy.options"
  rm -f "$OUTPUT_DIR/deploy/k8s/helm/nexent/generated-values.yaml" "$OUTPUT_DIR/deploy/k8s/helm/nexent/generated-runtime-values.yaml" "$OUTPUT_DIR/deploy/k8s/helm/nexent/generated-secrets-values.yaml" "$OUTPUT_DIR/deploy/k8s/helm/nexent/generated-persistence-values.yaml"
  rm -f "$OUTPUT_DIR/deploy/k8s/helm/nexent-infrastructure/generated-values.yaml" "$OUTPUT_DIR/deploy/k8s/helm/nexent-infrastructure/generated-runtime-values.yaml" "$OUTPUT_DIR/deploy/k8s/helm/nexent-infrastructure/generated-secrets-values.yaml" "$OUTPUT_DIR/deploy/k8s/helm/nexent-infrastructure/generated-persistence-values.yaml"
  case "$TARGET" in
    docker) rm -rf "$OUTPUT_DIR/deploy/k8s" ;;
    k8s)
      rm -rf "$OUTPUT_DIR/deploy/docker"
      if [ ! -d "$DEPLOY_ROOT/docker/assets/official-skills-zip" ]; then
        echo "❌ Required K8s official skill assets not found: $DEPLOY_ROOT/docker/assets/official-skills-zip"
        return 1
      fi
      mkdir -p "$OUTPUT_DIR/deploy/docker/assets"
      cp -R "$DEPLOY_ROOT/docker/assets/official-skills-zip" "$OUTPUT_DIR/deploy/docker/assets/"
      ;;
  esac

  create_offline_deploy_entrypoint
  find "$OUTPUT_DIR" -name '.git' -type d -prune -exec rm -rf {} + 2>/dev/null || true
  chmod +x "$OUTPUT_DIR/deploy.sh" "$OUTPUT_DIR/uninstall.sh" "$OUTPUT_DIR/load-images.sh" "$OUTPUT_DIR/push-images.sh" 2>/dev/null || true
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
    echo "includeSandbox: \"$INCLUDE_SANDBOX\""
    echo 'includeFullSandbox: "false"'
    echo "imageSource: \"$DEPLOYMENT_IMAGE_SOURCE\""
    echo "imageRegistryPrefix: \"$DEPLOYMENT_IMAGE_REGISTRY_PREFIX\""
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
      set -o pipefail
      cd "$OUTPUT_DIR" || exit 1
      find . -type f ! -name checksums.txt -print | LC_ALL=C sort | while IFS= read -r file; do
        sha256sum "$file" || exit 1
      done
    ) > "$checksum_file" || return 1
  elif command -v shasum >/dev/null 2>&1; then
    (
      set -o pipefail
      cd "$OUTPUT_DIR" || exit 1
      find . -type f ! -name checksums.txt -print | LC_ALL=C sort | while IFS= read -r file; do
        shasum -a 256 "$file" || exit 1
      done
    ) > "$checksum_file" || return 1
  else
    echo "❌ sha256sum or shasum is required to create checksums"
    return 1
  fi

  echo "✅ Created: $checksum_file"
}

offline_package_name() {
  if [[ -n "$PACKAGE_NAME" ]]; then
    echo "$PACKAGE_NAME"
    return
  fi

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
  (cd "$OUTPUT_DIR" && zip -r "$archive_file" .) || return 1

  echo "✅ Created: $archive_file"
  ls -lh "$archive_file"
}

create_full_sandbox_attachment() (
  [ "$INCLUDE_SANDBOX_FULL" = "true" ] || return 0
  if ! command -v zip >/dev/null 2>&1; then
    echo "Error: zip is required for the full Sandbox attachment"
    return 1
  fi

  # Isolate temporary output and publish the ZIP only after every step succeeds.
  local output_parent staging_dir archive_file image image_tag local_platform
  output_parent="$(cd "$(dirname "$OUTPUT_DIR")" && pwd)" || return 1
  archive_file="$output_parent/$(full_sandbox_package_name).zip"
  staging_dir="$(mktemp -d "$output_parent/.nexent-full-sandbox.XXXXXX")" || return 1
  trap 'rm -rf "$staging_dir"' EXIT
  image="$(full_sandbox_image)"
  image_tag="${image##*:}"
  local_platform="$(docker image inspect "$image" --format '{{.Os}}/{{.Architecture}}' 2>/dev/null || true)"
  if [ "$local_platform" != "linux/$PLATFORM" ]; then
    pull_with_retry "$image" "$PLATFORM" || return 1
  else
    echo "Using existing local image for linux/$PLATFORM: $image"
  fi

  OUTPUT_DIR="$staging_dir/package"
  mkdir -p "$OUTPUT_DIR/images" || return 1
  save_image_to_tar "$image" "$OUTPUT_DIR/images/nexent-sandbox-full-${image_tag//./-}.tar" || return 1
  copy_load_script || return 1
  copy_push_script || return 1
  {
    echo "version: \"$VERSION\""
    echo "platform: \"$PLATFORM\""
    echo 'target: "all"'
    echo 'components: "sandbox-full"'
    echo 'includeSandbox: "false"'
    echo 'includeFullSandbox: "true"'
    echo "imageSource: \"$DEPLOYMENT_IMAGE_SOURCE\""
    echo "imageRegistryPrefix: \"$DEPLOYMENT_IMAGE_REGISTRY_PREFIX\""
    echo 'images:'
    echo "  - \"$image\""
  } > "$OUTPUT_DIR/manifest.yaml" || return 1
  cat > "$OUTPUT_DIR/README.md" <<'README' || return 1
# Full Sandbox offline attachment

Extract this ZIP into its own directory, separately from the main offline package.
Match its version, architecture and image source to the main package.

1. Verify integrity: `sha256sum -c checksums.txt` (macOS: `shasum -a 256 -c checksums.txt`).
2. Load with `bash load-images.sh docker`, or `bash load-images.sh k8s` on every
   relevant Kubernetes node. The latter uses containerd's `k8s.io` namespace.
3. Alternatively, push to an internal registry with
   `bash push-images.sh --load-images --image-registry-prefix registry.example.com/nexent`.
   Use the same prefix when deploying the main package.
4. From the main package, deploy with `bash deploy.sh docker --sandbox-mode full`
   or `bash deploy.sh k8s --sandbox-mode full`, using the matching application version
   and image source. Load the main package images separately as usual.

The main package keeps the lightweight sandbox. Loading this attachment does not
switch the runtime sandbox mode. No deployment scripts or service data are included.
README
  create_checksums || return 1
  (cd "$OUTPUT_DIR" && zip -r "$staging_dir/attachment.zip" .) || return 1
  mv "$staging_dir/attachment.zip" "$archive_file" || return 1
  echo "Full Sandbox attachment available at: $archive_file"
)

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
  echo "Include Sandbox image: $INCLUDE_SANDBOX"
  echo "Separate full Sandbox attachment: $INCLUDE_SANDBOX_FULL"
  echo "Target: $TARGET"
  echo "Compress: $COMPRESS"
  echo "Package name: $(offline_package_name).zip"
  echo "Components: $DEPLOYMENT_COMPONENTS"
  echo "Image source: $DEPLOYMENT_IMAGE_SOURCE"
  [ -n "$DEPLOYMENT_IMAGE_REGISTRY_PREFIX" ] && echo "Image registry prefix: $DEPLOYMENT_IMAGE_REGISTRY_PREFIX"
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

  copy_load_script || {
    echo "❌ Load script creation failed, aborting"
    exit 1
  }

  copy_push_script || {
    echo "❌ Push script creation failed, aborting"
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

  create_full_sandbox_attachment || {
    echo "❌ Full Sandbox attachment creation failed, aborting"
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
