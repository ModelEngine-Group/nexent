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
