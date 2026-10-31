#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGES_DIR="$SCRIPT_DIR/images"

TARGET="${1:-docker}"

if [[ "$TARGET" != "docker" && "$TARGET" != "k8s" ]]; then
  echo "Error: target must be 'docker' or 'k8s': $TARGET" >&2
  exit 1
fi

loader=(docker load -i)
loader_name="Docker"
if [ "$TARGET" = "k8s" ]; then
  if command -v ctr >/dev/null 2>&1; then
    loader=(ctr -n k8s.io images import)
    if [ "$(id -u)" -ne 0 ]; then
      if command -v sudo >/dev/null 2>&1 && sudo -n ctr -n k8s.io namespaces list >/dev/null 2>&1; then
        loader=(sudo -n ctr -n k8s.io images import)
      elif ! ctr -n k8s.io namespaces list >/dev/null 2>&1; then
        echo "Error: ctr is installed but the containerd socket is not accessible." >&2
        echo "Run this command as root or grant non-interactive sudo access to ctr." >&2
        exit 1
      fi
    fi
    loader_name="containerd (k8s.io namespace)"
  else
    echo "Warning: ctr is unavailable; falling back to Docker image loading." >&2
    echo "Warning: verify that the Kubernetes container runtime can access Docker-loaded images." >&2
  fi
fi

echo "Loading images into $loader_name from $IMAGES_DIR..."

for tar_file in "$IMAGES_DIR"/*.tar; do
  if [[ -f "$tar_file" ]]; then
    echo "Loading: $tar_file"
    "${loader[@]}" "$tar_file"
  fi
done

echo ""
echo "✅ All images loaded successfully"
