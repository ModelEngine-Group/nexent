# Gateway service

Gateway listens on 5013 and handles both ordinary backend forwarding to Management5010/Runtime5014 and Northbound APIs. Run `python backend/gateway_service.py` from the repository root. The Dockerfile declares no application ENTRYPOINT/CMD; Compose and Helm provide the Python command.

## Authentication and source boundary

External session JWTs and API keys are verified in Gateway. `security/credentials.py` parses credentials and enforces their purpose; `security/database_provider.py` applies identity policy to a snapshot read by `infrastructure/database/identity.py`. The default provider queries PostgreSQL directly and never falls back to Management HTTP lookup. The older signed Management identity endpoint remains for explicit compatibility callers and regression tests.

The repository selects only user identity, canonical account role/email, token version, active membership, API-key ownership and CAS status/expiry/ownership. Existing SU and ASSET_OWNER session defaults are preserved. Membership selection preserves the established first-active-relation behavior, ordered by its primary key. Missing or ambiguous accounts and revoked credentials fail before business execution. Database faults return a sanitized503; invalid credentials return401. Logout keeps its idempotent anonymous failure behavior. MCP credential delegation uses the same database provider.

Every lookup uses a read-only repeatable-read transaction with finite acquire/query/connect timeouts and no cross-request identity cache. Lifespan owns the connection pool and closes it on shutdown. A broken or cancelled connection is terminated rather than reused or retried. Ordinary request resource authorization remains in each downstream service.

The image contains Gateway, its launcher, and only the side-effect-free infrastructure initializer/database subpackage. It contains no Management/Runtime implementation, SDK, ORM, MinIO factory or global backend environment. Seven direct dependencies are FastAPI, Uvicorn, HTTPX, websockets, PyJWT, bcrypt and asyncpg. Gateway configuration reads injected environment only and never loads .env.

## Database configuration

Configure these values through deployment secrets/environment, not inside the image.

| Variable | Default |
| --- | --- |
| GATEWAY_DB_HOST | POSTGRES_HOST; localhost for direct launches, nexent-postgresql in Compose |
| GATEWAY_DB_PORT | POSTGRES_PORT, otherwise 5432 |
| GATEWAY_DB_NAME | POSTGRES_DB, otherwise nexent |
| GATEWAY_DB_USER | POSTGRES_USER, otherwise root |
| GATEWAY_DB_PASSWORD | NEXENT_POSTGRES_PASSWORD; an effective password is required with authentication enabled and redacted from settings repr |
| GATEWAY_DB_POOL_SIZE | 8, valid range1..64 per replica |
| GATEWAY_DB_TIMEOUT | 5 seconds, finite range greater than0 through60 |

Keep `TZ` identical to Management because the current CAS schema stores naive local expiration timestamps. Shipped Compose/Helm propagate the deployment timezone to Gateway. JWT_SECRET, JWT_ISSUER and optional GATEWAY_SIGNING_SECRET must match downstream services. GATEWAY_HOST defaults0.0.0.0 and GATEWAY_PORT defaults5013. Authentication defaults enabled; missing keys or database credentials fail startup. Explicitly disabled diagnostic mode creates no database pool. Health reports local process readiness, not continuous database/business/model availability.

Gateway reuses the existing PostgreSQL account and password by default. No extra role or password is required. Leave connection overrides empty in deploy/env/.env.example to inherit PostgreSQL settings; each nonempty GATEWAY_DB_HOST/PORT/NAME/USER/PASSWORD takes precedence independently. When upgrading from the previous dedicated-login defaults, clear an existing GATEWAY_DB_USER=nexent_gateway and its password override if you want to reuse PostgreSQL credentials; existing nonempty overrides remain intentional and are not overwritten. For a separate account, set both GATEWAY_DB_USER and GATEWAY_DB_PASSWORD to that account's credentials. Gateway still uses read-only transactions; its effective database permissions are those of the selected account.

Optionally provision a dedicated login with only the required grants. Connect as a database administrator to the configured identity database and use a secure password prompt or the site's secret manager. The following is an optional operator example for the nexent database and a separate nexent_gateway role. It is not an automatic schema migration.

```sql
CREATE ROLE nexent_gateway LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
-- In psql, set the password through its secure prompt.
\password nexent_gateway
GRANT CONNECT ON DATABASE nexent TO nexent_gateway;
GRANT USAGE ON SCHEMA nexent TO nexent_gateway;
GRANT SELECT (user_id,user_email,user_role,token_version,delete_flag)
  ON nexent.user_account_t TO nexent_gateway;
GRANT SELECT (user_tenant_id,user_id,tenant_id,delete_flag)
  ON nexent.user_tenant_t TO nexent_gateway;
GRANT SELECT (user_id,token_id,access_key,delete_flag)
  ON nexent.user_token_info_t TO nexent_gateway;
GRANT SELECT (session_id,user_id,status,expires_at,delete_flag)
  ON nexent.user_cas_session_t TO nexent_gateway;
```

For the optional restricted login, verify that it cannot write identities or read password_hash and does not inherit owner privileges. No SQL migration/create_all/bootstrap runs in Gateway. Main Management retains schema migration ownership. Compose maps the effective PostgreSQL connection settings into Gateway's explicit environment without loading the whole backend env file. Direct Helm defaults to `nexent-common.config.postgres` and `nexent-common.secrets.postgresPassword`; optional nonempty `config.gatewayIdentity` fields and `secrets.gatewayDatabasePassword` override them. The Kubernetes deployment script hashes the effective password in the Pod template, so password rotations roll Gateway to replace its connection pool. When applying Helm values directly, also change global.rolloutChecksums.gatewayDatabase to a digest of the effective password, or run kubectl rollout restart deployment/nexent-gateway after rotating credentials.

## Exposure and transports

`exposure/registry.json` is the explicit method/path/transport snapshot, including existing public aliases. Adding a downstream route does not publish it automatically. Unlisted requests and method/transport mismatches return404 (WebSocket1008) before authentication or upstream work. CORS preflight is admitted only for a declared HTTP operation. Manifest revision/digest are available on app.state. Direct API-key aliases need a coordinated service identity policy change.

Gateway owns a shared HTTP client without a user-cookie jar. SSE/WS responses close on completion, failure and disconnect; streaming execution is never retried implicitly. Northbound protocol/business currently remains in Management behind the fixed Northbound upstream. Moving that adaptation layer is the next batch; durable task recovery remains with the business owner.

## Build, upgrade and rollback

Build with `bash deploy/images/build.sh --gateway --version <release-tag> --load` and rebuild the backend from the same revision. Configure the existing PostgreSQL account/password before startup; a dedicated reader is optional. Compose/Helm now create `nexent-gateway:5013`; frontend and MCP references use that service. No independent northbound image exists, and no image is deleted by this change.

Docker deployment checks the old `nexent-northbound` container's Compose project/service labels, disables its restart policy, stops it gracefully and removes only that container before starting the new Gateway. Images and volumes are preserved. A mismatched owner stops the upgrade for inspection. Do not keep running an older Compose file that recreates the old service. Helm upgrades within the same release remove the old chart resources and create the new Gateway deployment/service. Audit custom NetworkPolicies and external service references during rollout.

Verify login/session/API-key, revocation, ordinary backend forwarding, incremental SSE, Northbound and WS. Roll back image revisions and deployment resource names together, ensuring only one public Gateway and one durable recovery owner are active. This repository change does not execute an existing business deployment.
