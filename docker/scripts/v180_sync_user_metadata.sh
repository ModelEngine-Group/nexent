#!/bin/bash
#
# v1.8.0 User Metadata Sync Script
# This script executes the user data update script inside the nexent-config container.
#
# Usage:
#   ./v180_sync_user_metadata.sh [--dry-run]
#
# Options:
#   --dry-run    Show what would be updated without making changes
#

set -e

CONTAINER_NAME="nexent-config"
SCRIPT_PATH="/opt/sync_user_supabase2pg.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Clear Windows Git Bash path variables that cause path resolution issues in containers
# These variables contain Windows-style paths (e.g., C:/Program Files/Git) which break
# container execution when inherited

# Check if nexent-config container is running
DRY_RUN=false
for arg in "$@"; do
    case $arg in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            ;;
    esac
done

# Check if nexent-config container is running
log_info "Checking if container '$CONTAINER_NAME' is running..."
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log_error "Container '$CONTAINER_NAME' is not running"
    log_info "Please start the containers with: cd docker && docker compose up -d"
    exit 1
fi

log_info "Container '$CONTAINER_NAME' is running"

# Execute the script inside the container
log_info "Executing sync script inside container..."

# Use 'sh -c' wrapper to execute the command inside the container.
# This is a workaround for Windows Git Bash's execve() argument parsing issue
# where paths containing forward slashes get incorrectly interpreted.
# By wrapping the command in 'sh -c', the container's shell handles argument parsing.
if [ "$DRY_RUN" = true ]; then
    log_info "Mode: DRY-RUN (no changes will be made)"
    docker exec "$CONTAINER_NAME" sh -c "python $SCRIPT_PATH --dry-run"
else
    docker exec "$CONTAINER_NAME" sh -c "python $SCRIPT_PATH"
fi

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    log_info "Script executed successfully"
else
    log_error "Script failed with exit code: $EXIT_CODE"
    exit $EXIT_CODE
fi