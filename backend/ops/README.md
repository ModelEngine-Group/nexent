# Nexent operations backend

The operations backend runs in its own process and container using the existing
backend image. It currently exposes only process health and API documentation.
It does not initialize databases, Redis, MinIO, Elasticsearch, telemetry, Agent
executors or schedulers.

## Local startup

Use the existing Python 3.11 backend environment. From `backend/`:

```shell
python ops_service.py
```

The listener binds to `0.0.0.0`. Defaults: port `5016`, log level `info`. Configure
`OPS_PORT` and `LOG_LEVEL` through the process environment or
the existing `.env` workflow. Reads remain centralized in
`contracts/constants/environment.py`. For a clean environment without loading
a nearby `.env`, set `PYTHON_DOTENV_DISABLED=1` before starting Python.

| Endpoint | Contract |
| --- | --- |
| `/health/live` | HTTP 200 with `{"status":"alive"}` |
| `/health/ready` | HTTP 200 with `{"status":"ready"}` after startup; otherwise HTTP 503 with `{"status":"not_ready"}` |
| `/docs` | OpenAPI UI; health endpoints are omitted from the schema |

Health checks describe only the operations process. Business monitoring APIs
and their authentication will be added together in a later change.

## Container startup

Build the normal backend image with this source, then set `NEXENT_IMAGE` to that
image. Docker deployment starts ops whenever the `application` component is
selected, including the default full deployment. Development and production
Compose files extend the same operations service definition. Infrastructure-only
deployment does not start ops. Kubernetes also includes ops in the application component.

Run the normal deployment entry point from the repository root:

```shell
bash deploy/deploy.sh --defaults docker
```

To start only ops against an existing deployment, use the same Compose project:

```shell
docker compose --env-file deploy/env/.env -p nexent -f deploy/docker/compose/docker-compose-ops.yml up -d nexent-ops
```

The Compose file defines only `nexent-ops` and joins the existing shared
`nexent_network`, matching the optional monitoring deployment. The main stack
normally creates this network. If running ops before the main stack, create the
network once with `docker network create nexent_network`.

The default published port is `5016:5016`. Containers on the shared network can
resolve `nexent-ops` and reach `http://nexent-ops:5016`; host access uses
`http://localhost:5016`. If `OPS_PORT` is changed, both ports change together.

The service has no business-service `depends_on` entries. The environment file
supplies Compose substitutions; it is not injected wholesale into the container.
Only the existing logs directory is mounted; no business data volumes are required. Set
`ROOT_DIR` in the deployment environment for this mount. SQL startup is explicitly disabled. The container listens on
`0.0.0.0`. There is no operations destination URL configured in business services.
The listener address is not an access policy: the published port remains reachable
according to host networking and firewall rules. Preventing business services from
accessing operations requires an explicit ingress or network policy.

The shared backend image retains its existing installed dependencies. This
change reduces runtime service dependencies, not image size. No image build or
container rollout is performed by the bootstrap code.

## Code boundaries

- `ops_service.py`: process launcher.
- `ops/api/`: HTTP parsing, responses and application composition.
- `ops/services/`: future business rules and orchestration.
- `ops/lifespan.py`: process resources and readiness lifecycle.

Introduce database access and integration adapters only when a feature needs
them. Simple process health does not require a forwarding service class.

## Kubernetes

The existing `bash deploy/deploy.sh --defaults k8s` entry point enables the
`nexent-ops` subchart whenever `application` is selected and waits for its
Deployment to become ready. It reuses the selected backend image and does not
mount business configuration, credentials, SQL or business storage. Only explicit
ops settings and SQL-startup-off are passed to its container; the Kubernetes API
service-account token is not mounted.

The only storage mount is the logs PVC, using `global.sharedStorage.logs.existingClaim`
or the subchart's `logs.existingClaim` (default `nexent-logs`). The parent chart
creates the standard logs claim; a standalone ops chart needs an existing claim.

The Service and container port default to `5016` (`OPS_PORT` overrides both).
The default external address is `<node-ip>:30016`; in the same namespace,
use `http://nexent-ops:5016`. For direct Helm use, configure
`nexent-ops.service.type=ClusterIP` to keep it internal, or change
`nexent-ops.service.nodePort` when the default NodePort conflicts. Log level
uses `LOG_LEVEL`, default `info`.

Health probes use `/health/live` and `/health/ready`. Image and ops configuration
checksums participate in rollouts. Resource requests and limits are configurable
chart defaults, not measured memory or CPU consumption. Helm rendering verifies
manifest composition; it does not prove an actual cluster deployment.

## Persistent logs

Console output remains available. Application, Uvicorn server and HTTP access
records also use the existing rotating file handler:

- Local: `LOG_DIR/ops/nexent_ops.log`, default `logs/ops/nexent_ops.log`.
- Docker host: `${ROOT_DIR}/logs/ops/nexent_ops.log`.
- Kubernetes logs PVC: `<pod-name>/ops/nexent_ops.log`.

Kubernetes assigns `LOG_DIR` per pod so replicas and rolling updates do not rotate
the same file concurrently. Replacing a pod keeps its previous directory on the
PVC; old pod directories need cleanup under the deployment's retention policy.
Shared `LOG_LEVEL`, `IS_DEBUG`, `LOG_MAX_BYTES`, `LOG_ROTATION_INTERVAL` and
`LOG_BACKUP_COUNT` settings apply. Defaults rotate at 50 MiB or daily and retain
30 backups per file. No Elasticsearch client or log collection service is required.
