#!/usr/bin/env bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

set -euo pipefail

if [ "$#" -ne 2 ] && [ "$#" -ne 3 ]; then
  echo "Usage: $0 MANAGEMENT_IMAGE RUNTIME_IMAGE [OPS_IMAGE]" >&2
  exit 2
fi

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
if [[ "$OSTYPE" == msys* ]]; then
  repo="$(cd "$repo" && pwd -W)"
  export MSYS2_ARG_CONV_EXCL='*'
fi
prefix="nexent-image-smoke-$$"
password="$(openssl rand -hex 16)"
signing_key="$(openssl rand -hex 32)"
containers=("$prefix-management" "$prefix-runtime" "$prefix-postgres" "$prefix-redis")
containers+=("$prefix-mcp")
if [ "$#" -eq 3 ]; then
  containers+=("$prefix-ops")
fi

cleanup() {
  local status=$?
  local name
  if ((status != 0)); then
    for name in "${containers[@]}"; do
      docker logs "$name" >&2 || true
    done
  fi
  docker rm -fv "${containers[@]}" >/dev/null 2>&1 || true
  docker network rm "$prefix" >/dev/null 2>&1 || true
  return "$status"
}

docker network create "$prefix" >/dev/null
trap cleanup EXIT

for image in "$@"; do
  ports="$(docker image inspect "$image" --format '{{json .Config.ExposedPorts}}')"
  if [ "$ports" != "null" ] && [ "$ports" != "{}" ]; then
    echo "$image declares exposed ports: $ports" >&2
    exit 1
  fi
done

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
  local container=$1 port=$2 path=${3:-/health/ready}
  for ((attempt = 1; attempt <= 90; attempt++)); do
    if docker exec "$container" python -c '
import sys
from urllib.request import ProxyHandler, build_opener
with build_opener(ProxyHandler({})).open(sys.argv[1], timeout=2) as response:
    print(response.read(4096).decode())
' "http://127.0.0.1:$port$path" 2>/dev/null; then
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
docker exec "$prefix-management" sh -ec '
  test ! -d /opt/backend/runtime
  test ! -d /opt/backend/ops
  test ! -d /opt/backend/data_process
  test ! -d /opt/backend/services
'

docker run -d --name "$prefix-runtime" --network "$prefix" --network-alias runtime \
  "${env_args[@]}" --entrypoint /opt/nexent/scripts/start-backend.sh "$2" python -m backend.http.runtime_service >/dev/null
wait_ready "$prefix-runtime" 5014
docker exec "$prefix-runtime" sh -ec '
  test ! -d /opt/backend/management
  test ! -d /opt/backend/ops
  test ! -d /opt/backend/data_process
  test ! -e /opt/nexent/scripts/run-sql-migrations.sh
'

docker run -d --name "$prefix-mcp" --network "$prefix" "${env_args[@]}" \
  -e "NEXENT_MCP_INTERNAL_TOKEN=$signing_key" -e NEXENT_SQL_STARTUP_MODE=off -e PYTHON_DOTENV_DISABLED=1 \
  --entrypoint /opt/nexent/scripts/start-backend.sh "$1" python -m backend.http.mcp_service >/dev/null
wait_ready "$prefix-mcp" 5015 /tools/outer_api

if [ "$#" -eq 3 ]; then
  docker run -d --name "$prefix-ops" --network "$prefix" "${env_args[@]}" \
    -e GATEWAY_AUTH_ENABLED=true -e TRAJECTORY_READ_ENABLED=true \
    -e REDIS_BACKEND_URL=redis://redis:6379/0 \
    --tmpfs /tmp/nexent-trajectory -e TRAJECTORY_ROOT_DIR=/tmp/nexent-trajectory "$3" >/dev/null
  wait_ready "$prefix-ops" 5016
  docker exec -i "$prefix-ops" python - <<'PY'
import json
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from contracts.constants.environment import TRAJECTORY_ROOT_DIR
from gateway.identity.downstream import IDENTITY_HEADER, sign_identity
from infrastructure.rdb.client import get_db_session
from infrastructure.trace.trajectory_store import TrajectoryFileStore
from management.db.identity.models import UserAccount, UserTenant

TrajectoryFileStore.provision(TRAJECTORY_ROOT_DIR)
opener = build_opener(ProxyHandler({}))
base = "http://127.0.0.1:5016"
actor = {"kind": "session", "user_id": "smoke", "tenant_id": "smoke", "role": "SU", "roles": ["SU"]}
with get_db_session() as session:
    session.add_all([
        UserAccount(user_id=actor["user_id"], user_roles=actor["roles"]),
        UserTenant(user_id=actor["user_id"], tenant_id=actor["tenant_id"]),
    ])


def request(path, method="GET", payload=None):
    headers = {IDENTITY_HEADER: sign_identity(actor, "ops", method, path, b"")}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    with opener.open(Request(base + path, data=data, headers=headers, method=method), timeout=10) as response:
        return json.load(response)


paths = request("/openapi.json")["paths"]
assert "patch" in paths["/system_configurations"]
assert "get" in paths["/trajectory/records"]
try:
    opener.open(base + "/system_configurations", timeout=5)
except HTTPError as error:
    assert error.code in (401, 403)
else:
    raise AssertionError("Ops accepted a configuration request without credentials")

items = {item["key"]: item["value"] for item in request("/system_configurations")["items"]}
key = "LLM_INCLUDE_LOGPROBS"
value = not items[key]
result = request("/system_configurations", "PATCH", {"changes": {key: value}})
assert result["saved"] and result["notification"] == "published"
saved = {item["key"]: item["value"] for item in request("/system_configurations")["items"]}
assert saved[key] is value
assert isinstance(request("/trajectory/records"), dict)
print("Ops signed configuration read/write and trajectory query passed")
PY
  docker exec "$prefix-ops" python -m ops.scripts.backfill_trajectory_summaries
fi

docker exec "$prefix-mcp" sh -ec '
  test -s /opt/backend/configs/model_catalog.json
  test -s /opt/backend/configs/models_dev_catalog.json
  test -s /opt/nexent/litellm_models.json
  test -f /opt/backend/tool_collection/langchain/compute_tool.py
  python -c "from nexent.core.model_service.profiles.resolver import load_profile_catalog; load_profile_catalog()"
'
docker exec -i "$prefix-mcp" python - <<'PY'
import asyncio
import os
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

from fastmcp import Client
from fastmcp.client.transports import SSETransport
from backend.http.mcp_service import get_registered_openapi_services, register_openapi_service

opener = build_opener(ProxyHandler({}))
url = "http://127.0.0.1:5011/mcp/smoke/sse"
try:
    opener.open(url, timeout=5)
except HTTPError as error:
    assert error.code == 403
else:
    raise AssertionError("MCP accepted a request without tenant credentials")

headers = {
    "Accept": "text/event-stream",
    "X-Tenant-ID": "smoke",
    "X-Nexent-Internal-Token": os.environ["NEXENT_MCP_INTERNAL_TOKEN"],
}

async def verify_tools():
    async with asyncio.timeout(15):
        async with Client(SSETransport(url, headers=headers)) as client:
            tools = await client.list_tools()
            demo, = [tool.name for tool in tools if tool.name.endswith("test_tool_name")]
            result = await client.call_tool(demo, {"para_1": "smoke", "para_2": 1})
            assert not result.is_error
            assert any(part.text == "success" for part in result.content)

asyncio.run(verify_tools())
print("MCP tenant tool listing and invocation passed")

spec = {
    "openapi": "3.0.3",
    "info": {"title": "Smoke API", "version": "1.0"},
    "paths": {"/ping": {"get": {"operationId": "ping", "responses": {"200": {"description": "OK"}}}}},
}
assert register_openapi_service("smoke_api", spec, "http://127.0.0.1:5015", {})
assert {service["service_name"] for service in get_registered_openapi_services()} == {"smoke_api"}
assert not get_registered_openapi_services("other-tenant")
print("MCP OpenAPI registration passed")
PY
docker exec "$prefix-mcp" test ! -d /opt/backend/ops
if [ "$#" -eq 3 ]; then
  docker exec "$prefix-ops" sh -ec '
    test ! -e /opt/backend/http/config_service.py
    test ! -e /opt/backend/http/runtime_service.py
    test ! -e /opt/backend/management/api/application.py
    test ! -d /opt/backend/data_process
    test ! -d /opt/deploy/sql
    test ! -d /opt/sdk
  '
  docker exec "$prefix-ops" test ! -e /opt/backend/http/mcp_service.py
fi
