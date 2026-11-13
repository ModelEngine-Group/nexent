# Nexent operations backend

The operations backend runs in its own process and container using the shared
backend image. It owns historical trajectory queries, retrieval, administrator
cleanup settings and background summary/statistics maintenance. Runtime retains
Agent execution, capture identity, file writing and conversation-deletion hooks.

## Local startup

Use the existing Python 3.11 backend environment. From `backend/`:

```shell
python ops_service.py
```

The listener binds to `0.0.0.0`; `OPS_PORT` defaults to `5016`. Configuration
reads remain centralized in `contracts/constants/environment.py`. Set
`PYTHON_DOTENV_DISABLED=1` to disable nearby dotenv loading.

With trajectory reading disabled and a provider other than `local_file`, ops
serves health and documentation without importing business clients or the SDK.
Setting `TRAJECTORY_READ_ENABLED=true` or selecting `MONITORING_PROVIDER=local_file`
enables trajectory routes and managed maintenance. Query reads still require
`TRAJECTORY_READ_ENABLED=true`. Enabled operations uses the existing PostgreSQL
configuration and JWT authentication. It does not initialize telemetry exporters
or execute Agent calls or SQL migrations.

| Endpoint | Contract |
| --- | --- |
| `/health/live` | HTTP 200 with `{"status":"alive"}` |
| `/health/ready` | HTTP 200 after local startup; HTTP 503 before startup and during shutdown |
| `/docs` | OpenAPI UI |
| `/trajectory/records` | PG-only lists, filter candidates and saved statistics |
| `/trajectory/conversations/{id}` | Conversation execution list |
| `/trajectory/conversations/{id}/snapshot` | File-backed nodes and metrics |
| `/trajectory/conversations/{id}/contents/{content_id}` | Bounded body chunks |
| `/trajectory/cleanup` | Administrator cleanup batches |
| `/trajectory/cleanup/schedule` | Read or update tenant cleanup intervals |
| `/conversation/agent_groups` and its conversations subresource | Administrator directory with `view=trajectory` |

The existing Web origin accepts `/api/trajectory/` and forwards it to ops through
`OPS_HTTP_BACKEND` (local default `http://localhost:5016`). Conversation directory
requests go to ops only with `view=trajectory`; ordinary history and execution
requests remain on Runtime. Roles, tenant ownership, private-cache headers,
response envelopes and opaque references retain their existing contracts.
References are process-local; multi-replica deployments need affinity or must
restart a query when its reference is unavailable.

## Storage and process resources

Both Runtime and ops must see the same `TRAJECTORY_ROOT_DIR`, default
`/mnt/nexent-data/trajectory`. Runtime provisions and writes archives. Ops reads
those files, updates PG projections and performs retention cleanup using the
existing per-tenant intervals and cross-process file locks. Multi-node deployments
require the existing `shared_directory` storage mode and a shared filesystem
supporting the required lock/atomic-replace behavior.

Ops owns its ThreadManager query/cleanup lanes and three managed background
services: maintenance, summary compensation and statistics refresh. Capture
publication occurs in another process, so summary compensation discovers durable
archives through its bounded scan, restarting a completed scan after 60 seconds.
Readiness describes local resource startup; it does not poll PostgreSQL on each
health request. Shutdown stops owned services and releases process-local query
references.

Historical summary backfill is now:

```shell
python -m ops.scripts.backfill_trajectory_summaries
```

## Deployment

Normal Docker and Kubernetes application selection includes ops. Docker ops
loads both `deploy/env/.env` and `deploy/env/monitoring.env`, mounts the shared
logs and trajectory directories, and publishes `${OPS_PORT:-5016}`. Its Web
container receives the corresponding `OPS_HTTP_BACKEND`.

```shell
docker compose --env-file deploy/env/.env -p nexent -f deploy/docker/compose/docker-compose-ops.yml up -d nexent-ops
```

Standalone Compose joins the existing external `nexent_network`. The shared
network and environment files must already exist. Kubernetes mounts the logs
PVC and, when trajectories are enabled, the trajectory PVC plus existing shared
configuration/secrets. Default health mode keeps its minimal configuration and
logs-only mount. The normal deployment generator sets Web `config.opsHttpBackend`
from `OPS_PORT`; direct Helm overrides must set that address consistently with
the ops Service port. SQL startup stays disabled in ops.

Application, Uvicorn and access logs use `infrastructure.logging`, console and
rotating persistent files. The file path is `LOG_DIR/ops/nexent_ops.log`; Kubernetes
uses a per-pod log directory to avoid concurrent rotation.

## Code boundaries

- `ops_service.py`: launcher.
- `ops/api/`: HTTP routes and application composition.
- `ops/services/trajectory/`: query parsing, file retrieval and maintenance orchestration.
- `ops/db/trajectory/`: authorized catalogs, list/statistics SQL and cleanup configuration.
- `ops/concurrency.py`, `ops/lifespan.py`: process-owned resources.
- `management/db/trajectory/`: shared ORM and transactional capture/projection writes.
- `infrastructure/observability/`: shared file primitives and Runtime capture wiring.
