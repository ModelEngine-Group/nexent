# Gateway service

Gateway listens on 5013 and handles both ordinary backend forwarding to Management5010/Runtime5014 and Northbound APIs. From the repository root, set `PYTHONPATH` to the absolute `backend/` directory and run `python -m backend.http.gateway_service`. The Dockerfile declares no application ENTRYPOINT/CMD; Compose and Helm provide the Python command.

## Authentication and source boundary

External session JWTs and API keys are verified in Gateway. `security/credentials.py` parses credentials and enforces their purpose; `security/database_provider.py` applies identity policy to a snapshot read by `infrastructure/rdb/identity.py`. The default provider queries PostgreSQL directly and never falls back to Management HTTP lookup. The older signed Management identity endpoint remains for explicit compatibility callers and regression tests.

The repository selects only user identity, canonical account role/email, token version, active membership, API-key ownership and CAS status/expiry/ownership. Existing SU and ASSET_OWNER session defaults are preserved. Membership selection preserves the established first-active-relation behavior, ordered by its primary key. Missing or ambiguous accounts and revoked credentials fail before business execution. Database faults return a sanitized503; invalid credentials return401. Logout keeps its idempotent anonymous failure behavior. MCP credential delegation uses the same database provider.

Every lookup uses a read-only repeatable-read transaction with finite acquire/query/connect timeouts and no cross-request identity cache. Lifespan owns the connection pool and closes it on shutdown. A broken or cancelled connection is terminated rather than reused or retried. Ordinary request resource authorization remains in each downstream service.

The image packages Gateway, its launcher, the shared security protocol, and the read-only RDB identity adapter. Its six direct dependencies are FastAPI, Uvicorn, HTTPX, websockets, PyJWT and asyncpg. Gateway configuration reads injected environment only and never loads .env.

Gateway owns request signing, path normalization, the public-entry policy, and MCP credential delegation. The MCP process binds the Gateway-owned tenant router to its local app registry and supplies its own Gateway URL and signing key. Downstream apps use the adapters in `gateway/downstream/` to load backend configuration and verify signatures. The standalone Gateway image packages only the edge modules and pure protocol code.

## Database configuration

Gateway reads the existing PostgreSQL configuration directly. Compose passes only these connection values; Helm references the existing shared ConfigMap and Secret. No separate database account, password, override layer or bootstrap SQL is needed.

| Variable | Default |
| --- | --- |
| POSTGRES_HOST | localhost for direct launches; nexent-postgresql in deployment |
| POSTGRES_PORT | 5432 |
| POSTGRES_DB | nexent |
| POSTGRES_USER | root |
| NEXENT_POSTGRES_PASSWORD | Required when authentication is enabled; redacted from settings repr |

The connection pool defaults to8 connections per replica and a5-second timeout. Every identity lookup uses a read-only transaction. Effective database permissions belong to the existing PostgreSQL account. Gateway runs no migrations or create_all; Management retains schema ownership.

The Kubernetes deployment script updates global.rolloutChecksums.postgresSecret when the existing password changes, restarting Gateway to replace its pool credentials. For direct Helm installs configure nexent-common.config.postgres and nexent-common.secrets.postgresPassword. On direct Helm rotations, update the postgresSecret rollout digest or restart deployment/nexent-gateway.

Keep TZ identical to Management because CAS expiration uses naive local timestamps. JWT_SECRET, JWT_ISSUER and optional GATEWAY_SIGNING_SECRET must match downstream services. Authentication defaults enabled; missing keys or database credentials fail startup. Explicitly disabled diagnostic mode creates no database pool. Health reports local process readiness.

## Exposure and transports

`exposure/registry.json` is the explicit method/path/transport snapshot, including existing public aliases. Adding a downstream route does not publish it automatically. Unlisted requests and method/transport mismatches return404 (WebSocket1008) before authentication or upstream work. CORS preflight is admitted only for a declared HTTP operation. Manifest revision/digest are available on app.state. Direct API-key aliases need a coordinated service identity policy change.

Gateway owns a shared HTTP client without a user-cookie jar. SSE/WS responses close on completion, failure and disconnect; streaming execution is never retried implicitly. Northbound protocol/business currently remains in Management behind the fixed Northbound upstream. Moving that adaptation layer is the next batch; durable task recovery remains with the business owner.

## Build, upgrade and rollback

Build with `bash deploy/images/build.sh --gateway --version <release-tag> --load` and rebuild the backend from the same revision. Configure the existing PostgreSQL account/password before startup. Compose/Helm now create `nexent-gateway:5013`; frontend and MCP references use that service. No independent northbound image exists, and no image is deleted by this change.

Docker deployment checks the old `nexent-northbound` container's Compose project/service labels, disables its restart policy, stops it gracefully and removes only that container before starting the new Gateway. Images and volumes are preserved. A mismatched owner stops the upgrade for inspection. Do not keep running an older Compose file that recreates the old service. Helm upgrades within the same release remove the old chart resources and create the new Gateway deployment/service. Audit custom NetworkPolicies and external service references during rollout.

Verify login/session/API-key, revocation, ordinary backend forwarding, incremental SSE, Northbound and WS. Roll back image revisions and deployment resource names together, ensuring only one public Gateway and one durable recovery owner are active. This repository change does not execute an existing business deployment.
