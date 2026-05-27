#!/bin/bash
#
# v2.2.0 Skills Directory Migration Script
# Migrates skills from legacy location to tenant-isolated directories.
#
# Migration:
#   FROM: ${ROOT_DIR}/skills/ (flat directory, skills directly under skills/)
#   TO:   ${ROOT_DIR}/skills/{tenant_id}/
#
# The tenant_id is determined by querying user_tenant_t for the first record
# with user_role = 'ADMIN'.
#
# Usage:
#   ./v220_sync_skill_directory.sh [--dry-run]
#
# Options:
#   --dry-run    Show what would be migrated without making changes
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_PATH="${SCRIPT_DIR}/sync_skill_directory.py"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

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

if [ ! -f "$SCRIPT_PATH" ]; then
    log_error "Script not found: $SCRIPT_PATH"
    exit 1
fi

# Load environment from .env if exists
ENV_FILE="${SCRIPT_DIR}/../.env"
if [ -f "$ENV_FILE" ]; then
    log_info "Loading environment from: $ENV_FILE"
    set -a
    source "$ENV_FILE"
    set +a
fi

log_info "Executing migration script..."

if [ "$DRY_RUN" = true ]; then
    log_info "Mode: DRY-RUN (no changes will be made)"
    python "$SCRIPT_PATH" --dry-run "$@"
else
    python "$SCRIPT_PATH" "$@"
fi

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    log_info "Migration completed successfully"
else
    log_error "Migration failed with exit code: $EXIT_CODE"
    exit $EXIT_CODE
fi
