#!/usr/bin/env bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 MANAGEMENT_IMAGE RUNTIME_IMAGE" >&2
  exit 2
fi

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
prefix="nexent-image-smoke-$$"
password="$(openssl rand -hex 16)"
signing_key="$(openssl rand -hex 32)"

cleanup() {
  local status=$?
  if ((status != 0)); then
    docker logs "$prefix-management" >&2 || true
    docker logs "$prefix-runtime" >&2 || true
    docker logs "$prefix-postgres" >&2 || true
  fi
  docker rm -fv "$prefix-management" "$prefix-runtime" "$prefix-postgres" "$prefix-redis" >/dev/null 2>&1 || true
  docker network rm "$prefix" >/dev/null 2>&1 || true
  return "$status"
}

docker network create "$prefix" >/dev/null
trap cleanup EXIT

docker run -d --name "$prefix-postgres" --network "$prefix" --network-alias postgres \
  -e POSTGRES_USER=root -e POSTGRES_DB=nexent -e "POSTGRES_PASSWORD=$password" postgres:15-alpine >/dev/null
docker run -d --name "$prefix-redis" --network "$prefix" --network-alias redis redis:7-alpine >/dev/null

env_args=(
  -e POSTGRES_HOST=postgres -e POSTGRES_USER=root -e POSTGRES_DB=nexent
  -e "NEXENT_POSTGRES_PASSWORD=$password" -e REDIS_URL=redis://redis:6379/0
  -e "JWT_SECRET=$signing_key" -e GATEWAY_AUTH_ENABLED=false -e LANGFUSE_ENABLED=false
  -e MINIO_ENDPOINT=http://minio:9000
  -e MINIO_ACCESS_KEY=smoke -e "MINIO_SECRET_KEY=$password"
  -e RUNTIME_SERVICE_URL=http://runtime:5014 -e MANAGEMENT_AGENTOS_URL=http://management:5010
)

wait_ready() {
  local container=$1 port=$2
  for ((attempt = 1; attempt <= 90; attempt++)); do
    if docker exec "$container" curl --fail --silent --max-time 2 "http://127.0.0.1:$port/health/ready"; then
      printf '\n%s is ready\n' "$container"
      return 0
    fi
    [ "$(docker inspect --format '{{.State.Running}}' "$container")" = true ] || break
    sleep 2
  done
  echo "$container did not become ready" >&2
  return 1
}

docker run -d --name "$prefix-management" --network "$prefix" --network-alias management \
  "${env_args[@]}" --mount "type=bind,source=$repo/deploy/sql,target=/opt/nexent/sql,readonly" \
  --entrypoint /opt/nexent/scripts/start-backend.sh "$1" python -m backend.http.config_service >/dev/null
wait_ready "$prefix-management" 5010
docker exec "$prefix-management" sh -ec 'test ! -d /opt/backend/runtime'

docker run -d --name "$prefix-runtime" --network "$prefix" --network-alias runtime \
  "${env_args[@]}" --entrypoint /opt/nexent/scripts/start-backend.sh "$2" python -m backend.http.runtime_service >/dev/null
wait_ready "$prefix-runtime" 5014
docker exec "$prefix-runtime" sh -ec 'test ! -d /opt/backend/management'
