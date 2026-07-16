#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_FILE="$SCRIPT_DIR/manifest.yaml"
LOAD_SCRIPT="$SCRIPT_DIR/load-images.sh"

IMAGE_REGISTRY_PREFIX="${IMAGE_REGISTRY_PREFIX:-}"
REGISTRY_USERNAME="${REGISTRY_USERNAME:-}"
REGISTRY_PASSWORD="${REGISTRY_PASSWORD:-}"
LOAD_IMAGES="false"
PROMPT_FOR_MISSING="true"
OUTPUT_ENV_FILE=""

usage() {
  cat <<'USAGE'
Usage:
  bash push-images.sh [--image-registry-prefix registry.example.com/nexent] [options]

Options:
  --image-registry-prefix PREFIX  Registry prefix used for pushed image tags. Prompts when omitted.
  --registry-username USER        Username for docker login. Prompts when omitted.
  --registry-password PASSWORD    Password for docker login. REGISTRY_PASSWORD is also supported.
  --registry-password-stdin       Read docker login password from standard input.
  --load-images                   Load images from ./images before pushing.
  --no-prompt                     Fail instead of prompting for missing values.
  --output-env-file FILE          Write selected image registry prefix to FILE.
  --help                          Show this help message.
USAGE
}

normalize_image_registry_prefix() {
  local prefix="$1"
  prefix="${prefix#"${prefix%%[![:space:]]*}"}"
  prefix="${prefix%"${prefix##*[![:space:]]}"}"
  prefix="${prefix#http://}"
  prefix="${prefix#https://}"
  while [[ "$prefix" == */ ]]; do
    prefix="${prefix%/}"
  done
  printf '%s' "$prefix"
}

prefixed_image_ref() {
  local image="$1"
  local prefix="$2"
  if [ -z "$prefix" ]; then
    printf '%s' "$image"
    return 0
  fi
  case "$image" in
    "$prefix"/*) printf '%s' "$image" ;;
    *) printf '%s/%s' "$prefix" "$image" ;;
  esac
}

registry_host_from_prefix() {
  local prefix="$1"
  printf '%s' "${prefix%%/*}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --image-registry-prefix|--registry-prefix|--image-registry)
      if [ $# -lt 2 ]; then
        echo "Error: $1 requires a value." >&2
        exit 1
      fi
      IMAGE_REGISTRY_PREFIX="$2"
      shift 2
      ;;
    --registry-username)
      if [ $# -lt 2 ]; then
        echo "Error: $1 requires a value." >&2
        exit 1
      fi
      REGISTRY_USERNAME="$2"
      shift 2
      ;;
    --registry-password)
      if [ $# -lt 2 ]; then
        echo "Error: $1 requires a value." >&2
        exit 1
      fi
      REGISTRY_PASSWORD="$2"
      shift 2
      ;;
    --registry-password-stdin)
      REGISTRY_PASSWORD="$(cat)"
      shift
      ;;
    --load-images)
      LOAD_IMAGES="true"
      shift
      ;;
    --no-prompt)
      PROMPT_FOR_MISSING="false"
      shift
      ;;
    --output-env-file)
      if [ $# -lt 2 ]; then
        echo "Error: $1 requires a value." >&2
        exit 1
      fi
      OUTPUT_ENV_FILE="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [ -z "$IMAGE_REGISTRY_PREFIX" ]; then
  if [ -t 0 ]; then
    if [ "$PROMPT_FOR_MISSING" = "true" ]; then
      read -r -p "Enter image registry prefix (e.g. registry.example.com/nexent): " IMAGE_REGISTRY_PREFIX
    else
      echo "Error: --image-registry-prefix is required." >&2
      exit 1
    fi
  else
    echo "Error: --image-registry-prefix is required." >&2
    exit 1
  fi
fi

IMAGE_REGISTRY_PREFIX="$(normalize_image_registry_prefix "$IMAGE_REGISTRY_PREFIX")"
if [ -z "$IMAGE_REGISTRY_PREFIX" ]; then
  echo "Error: image registry prefix cannot be empty." >&2
  exit 1
fi

if [ -z "$REGISTRY_USERNAME" ]; then
  if [ -t 0 ]; then
    if [ "$PROMPT_FOR_MISSING" = "true" ]; then
      read -r -p "Registry username: " REGISTRY_USERNAME
    else
      echo "Error: --registry-username is required when pushing images." >&2
      exit 1
    fi
  else
    echo "Error: --registry-username is required when pushing images." >&2
    exit 1
  fi
fi

if [ -z "$REGISTRY_USERNAME" ]; then
  echo "Error: registry username cannot be empty." >&2
  exit 1
fi

if [ -z "$REGISTRY_PASSWORD" ]; then
  if [ -t 0 ]; then
    if [ "$PROMPT_FOR_MISSING" = "true" ]; then
      read -r -s -p "Registry password: " REGISTRY_PASSWORD
      echo ""
    else
      echo "Error: registry password is required when pushing images." >&2
      exit 1
    fi
  else
    echo "Error: registry password is required when pushing images." >&2
    exit 1
  fi
fi

if [ -z "$REGISTRY_PASSWORD" ]; then
  echo "Error: registry password cannot be empty." >&2
  exit 1
fi

if [ ! -f "$MANIFEST_FILE" ]; then
  echo "Error: manifest not found: $MANIFEST_FILE" >&2
  exit 1
fi

registry_host="$(registry_host_from_prefix "$IMAGE_REGISTRY_PREFIX")"
printf '%s' "$REGISTRY_PASSWORD" | docker login "$registry_host" --username "$REGISTRY_USERNAME" --password-stdin

if [ -n "$OUTPUT_ENV_FILE" ]; then
  mkdir -p "$(dirname "$OUTPUT_ENV_FILE")"
  printf 'IMAGE_REGISTRY_PREFIX=%q\n' "$IMAGE_REGISTRY_PREFIX" > "$OUTPUT_ENV_FILE"
fi

if [ "$LOAD_IMAGES" = "true" ]; then
  if [ ! -f "$LOAD_SCRIPT" ]; then
    echo "Error: --load-images requires $LOAD_SCRIPT" >&2
    exit 1
  fi
  bash "$LOAD_SCRIPT"
fi

echo "Pushing images with prefix: $IMAGE_REGISTRY_PREFIX"

awk -F'"' '/^[[:space:]]*-[[:space:]]*"/ { print $2 }' "$MANIFEST_FILE" | while IFS= read -r image; do
  [ -n "$image" ] || continue
  target_image="$(prefixed_image_ref "$image" "$IMAGE_REGISTRY_PREFIX")"

  if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "Error: image is not loaded locally: $image" >&2
    echo "Run bash load-images.sh first, or use --load-images." >&2
    exit 1
  fi

  if [ "$target_image" != "$image" ]; then
    echo "Tagging: $image -> $target_image"
    docker tag "$image" "$target_image"
  fi

  echo "Pushing: $target_image"
  docker push "$target_image"
done

echo ""
echo "✅ All images pushed successfully"
