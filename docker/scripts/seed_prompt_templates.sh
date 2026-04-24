#!/bin/bash
# Seed builtin prompt templates by reading YAML files and writing to PostgreSQL.
# Usage:
#   ./seed_prompt_templates.sh [--dry-run] [--tenant-id <tenant_id>]

set -e

CONTAINER_NAME="nexent-config"
SCRIPT_PATH="/opt/seed_prompt_templates.py"

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

ARGS="$*"

log_info "Checking if container '$CONTAINER_NAME' is running..."
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log_warn "Container '$CONTAINER_NAME' is not running, skipping prompt template seeding"
    exit 0
fi

log_info "Running prompt template seed script inside container..."
if ! docker exec "$CONTAINER_NAME" sh -c "python $SCRIPT_PATH $ARGS"; then
    log_error "Prompt template seed script failed"
    exit 1
fi

log_info "Prompt template seed script completed successfully"
