# Nexent operations backend

The operations backend runs in its own process and container using the shared
backend image. It owns historical trajectory queries, retrieval, administrator
cleanup settings and background summary/statistics maintenance. Runtime retains
Agent execution, capture identity, file writing and conversation-deletion hooks.

Authenticated operations also expose scope and resource inventory metadata using the existing PostgreSQL identity and permission tables.

## Local startup

Use the existing Python 3.11 backend environment. From the repository root,
with both the root and `backend/` on `PYTHONPATH`:

```shell
bash deploy/common/start-backend.sh python -m backend.http.ops_service
```

Compose and Helm use this module command through `start-backend.sh`, which
initializes Ops storage before launching the service. Running
`backend/http/ops_service.py` as a script places its directory first on Python's
import path, where the shared `logging.py` shadows the standard library.

The listener binds to `0.0.0.0`; `OPS_PORT` defaults to `5016`. Configuration
reads remain centralized in `contracts/constants/environment.py`. Set
`PYTHON_DOTENV_DISABLED=1` to disable nearby dotenv loading.

With trajectory reading and model monitoring disabled and a provider other than
`local_file`, Ops serves health and documentation without initializing their
storage clients.
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

Web sends trajectory and system configuration requests through Gateway. Gateway
uses `GATEWAY_OPS_URL` to reach Ops and attaches a request-bound identity signature.
Conversation directory requests go to Ops only with `view=trajectory`; ordinary
history and execution keep their existing routing. Roles, tenant ownership, private-cache headers,
response envelopes and opaque references retain their existing contracts.
References are process-local; multi-replica deployments need affinity or must
restart a query when its reference is unavailable.

When model monitoring is enabled, startup prepares its Elasticsearch mappings
before reporting ready.
`GET /ops/authorization`, `/ops/resources` and `/ops/scope` require a valid session.
OPS is restricted to its tenant; SU can select any tenant or all tenants. The
System configuration endpoints enforce the shared read and update grants in Ops.
Model monitoring is exposed under `/ops/v1/monitoring/models` when enabled.
The Gateway forwards `/api/ops/v1/monitoring/` to Ops with a signed session identity.

## Model monitoring setup

Monitoring is enabled by default. Normal Compose and Helm deployment creates
the independent Ops database and applies its versioned migrations automatically;
no separate database or SQL command is required. Ops uses the existing
`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER` and `NEXENT_POSTGRES_PASSWORD`
directly. Only the database name differs: the default is `POSTGRES_DB` plus
`_ops` (`nexent_ops` with the standard configuration). `OPS_POSTGRES_DB` can
override the name; no separate Ops server or credentials are configured.

The shared launcher applies business migrations first in `migrate` mode, then
creates and migrates Ops storage. `wait` consumers wait for both schemas; the
Ops process keeps business SQL off and initializes only its own database.
Concurrent initializers serialize database creation and reuse the migration
ledger and lock. Existing data is preserved. Initialization failure prevents
application startup. Names equal to the business database or longer than 63
UTF-8 bytes are rejected before Ops SQL runs.

The deployment role needs database creation permission when the target does not
exist and schema creation permission for migration. Existing databases can be
managed by a role without database creation permission. Set
`OPS_MONITORING_ENABLED=false` to skip Ops initialization and collection;
explicit false remains effective during upgrades. Producers stage sanitized
batches in the Ops database. Ops owns the
Elasticsearch mappings, writer and publisher. Give its Elasticsearch identity
template management and monitoring-index permissions, including document
deletion on `monitoring-daily-*`. The service uses the
configured Elasticsearch endpoint and `OPS_MONITORING_TIMEZONE` for statistic
dates.

Model monitoring shares the existing SDK request and response observations.
Legacy records keep their existing defaults, while Ops preserves missing provider
usage so coverage can be measured. ModelService and the monitored legacy OpenAI
chat client share physical attempt measurements with local Trace. A recorded
attempt span and its ES fact carry the same fact identity. Facts can include the
native `trace_id` and `span_id`, and publish even when local Trace is disabled.

Model trends include every requested day. Dates without a publication return null
metrics. Refresh returns HTTP 409 with `message.code=MONITORING_DATES_UNCOVERED`
and `message.missing_dates` when the requested scope has no confirmed source for
those dates.
Unconfirmed failed Elasticsearch batches mark affected query scopes stale until
they recover and the replacement statistics are published.

Define a `MonitoringKind` with the typed fact and Elasticsearch fields. Supply
a reducer when daily publication is available. Add the kind to `MONITORING_KINDS` in
`ops.monitoring.runtime`. Ops installs the compatible mappings on its shared
indices at startup. The two monitoring tables are shared, with date state and
publication tracked per tenant and kind. SDK callers submit sanitized events
through `nexent.monitor.facts.emit_fact`; the backend producer owns transport
and retries. Readers use `Monitoring.publication_snapshot` to pin the published
documents for the duration of a query.

The Ops worker starts an hourly sweep of superseded daily aggregation documents.
It keeps the current PostgreSQL publication for each tenant, kind and date, and
skips dates that have no publication. In-flight queries hold an Elasticsearch
snapshot through the read. Fact documents are outside this cleanup.

The first implementation starts each tenant's coverage at its first observed fact.
It uses a single source generation and page-number queries. Configure fact
retention and coordinate PostgreSQL and Elasticsearch snapshots at deployment.
Snapshot-bound pagination is follow-up work.

## Main Agent fact sample

The main Agent worker collects facts when Ops monitoring is enabled. It emits
the start revision before the core adapter runs and measures that call with a
monotonic clock. The terminal revision uses those timestamps and is offered
after worker cleanup. Trajectory capture can be disabled independently.

With the monitoring producer configured, submit an execution's revisions through
the same SDK entry point. Keep the execution ID, start timestamp, initiating
groups and resource identity stable across revisions. This sample crosses a UTC
month boundary, so both revisions belong in the October facts index.

```python
from uuid import uuid4

from nexent.monitor.facts import emit_fact

run_id = str(uuid4())
started = {
    "tenant_id": "sample-tenant",
    "fact_kind": "agent",
    "fact_id": run_id,
    "call_context_id": run_id,
    "root_run_id": run_id,
    "agent_run_id": run_id,
    "agent_id": 21,
    "agent_version_no": 3,
    "is_root": True,
    "initiator_group_ids": [12, 13],
    "started_at": "2026-10-31T23:59:59.800Z",
    "record_revision": 1,
    "outcome": "started",
}
finished = dict(
    started, record_revision=2, outcome="succeeded",
    ended_at="2026-11-01T00:00:00.150Z", duration_ms=350,
)
emit_fact(started)
emit_fact(finished)
emit_fact(finished)
```

The fixed case `OPS-AGENT-FACTS-D3-001` sends these revisions in separate
batches and reads back the same ES document after each write. The shared
publisher groups Agent executions by start day, tenant, initiating groups
and Agent ID. It writes the execution count, exact duration sum and number of
ended executions with a measured duration. A measured zero is a valid sample.

## Agent summary query

Use `GET /ops/v1/monitoring/agents/summary` directly on Ops or
`/api/ops/v1/monitoring/agents/summary` through the Web proxy. Supply a session
bearer token with `ops.dashboard:read`. Ops operators are scoped to their own
tenant. Super Admin can select a tenant or omit `tenant_id` for all tenants.

`start_date` and `end_date` are inclusive dates in the Ops monitoring timezone.
The range can cover up to 366 days. Repeat `group_ids` to match any of those
initiating groups. A record matching multiple groups contributes once.
`agent_id` selects a single Agent.

```http
GET /ops/v1/monitoring/agents/summary?tenant_id=example&start_date=2026-11-18&end_date=2026-11-18&group_ids=12&group_ids=13&agent_id=21
Authorization: Bearer <session-token>
```

```json
{
  "data": {"execution_count": 2, "avg_duration_ms": 250.0, "duration_sample_count": 2},
  "data_as_of": "2026-11-18T08:40:00+00:00",
  "coverage_state": "covered",
  "is_stale": false
}
```

The endpoint reads the latest published version and averages the total duration
over all selected duration samples. A covered selection with zero matches
returns zero executions and samples and a null average. An uncovered
selection returns null metrics. Partial coverage can report the published
subset, and `is_stale` indicates that source changes or failed writes are pending.

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
logs and trajectory directories, and publishes `${OPS_PORT:-5016}`. Gateway
uses the corresponding `GATEWAY_OPS_URL`.

```shell
docker compose --env-file deploy/env/.env -p nexent -f deploy/docker/compose/docker-compose-ops.yml up -d nexent-ops
```

Standalone Compose joins the existing external `nexent_network`. The shared
network and environment files must already exist. Kubernetes mounts the logs
PVC and, when trajectories are enabled, the trajectory PVC plus existing shared
configuration/secrets. Ops reads its database and signature settings from the
shared ConfigMap and Secret in both modes. The normal deployment generator
sets Gateway `opsUrl` from `OPS_PORT`; direct Helm overrides must set that
address consistently with the Ops Service port. SQL startup stays disabled in ops.

Application, Uvicorn and access logs use `infrastructure.logging`, console and
rotating persistent files. The file path is `LOG_DIR/ops/nexent_ops.log`; Kubernetes
uses a per-pod log directory to avoid concurrent rotation.

## Code boundaries

- `backend/http/ops_service.py`: launcher.
- `ops/api/`: HTTP routes and application composition.
- `ops/services/trajectory/`: query parsing, file retrieval and maintenance orchestration.
- `ops/db/trajectory/`: authorized catalogs, list/statistics SQL and cleanup configuration.
- `ops/concurrency.py`, `ops/lifespan.py`: process-owned resources.
- `management/db/trajectory/`: shared ORM and transactional capture/projection writes.
- `infrastructure/trace/`: shared file primitives and Runtime capture wiring.

Database identity and permission access is reused from management. Resource inventory
selects metadata fields explicitly and excludes credentials and content.
