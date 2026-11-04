# Historical account migration and deployment runbook

This is the single operational guide for removing Supabase authentication from
Nexent. Run commands from the repository root. Docker and Kubernetes use the
application PostgreSQL database for accounts; ordinary deployments do not start
Supabase, GoTrue or Kong. The legacy YAML files beside this guide are recovery
assets for the original source database.

## Completion rule and execution order

`nexent.user_account_t` is the only account-migration completion marker. An existing
table, including an empty one, skips source access and credential import. Application
versions, SQL checksums, account counts and pending flags do not select migration.
A target without the legacy `user_tenant_t` relation follows fresh initialization.
A legacy target without the account table requires the original Supabase source.

**Do not apply account SQL or start the new application before the worker imports
historical accounts.** Manually applying 001 creates the completion marker without
copying passwords. Restarting deployment then skips credential import by design.
Use the automatic entry or the manual importer below, which owns the complete
schema-and-credential transaction.

| Stage | Docker | Kubernetes |
| --- | --- | --- |
| Database ready | Start selected infrastructure; PostgreSQL initializes only `deploy/sql/init.sql` on an empty data directory | Install/wait for infrastructure; its SQL ConfigMap contains only `init.sql` |
| Historical account import | Host Shell `migrate.sh --apply` runs before HTTPS/core service startup | Host Shell `migrate.sh --deployment kubernetes --apply` runs before application Secret replacement and application Helm rollout |
| Target transaction | Recheck table existence under the account-writer lock, run consolidated 001, transfer profiles and credentials, then commit | Same transaction through target PostgreSQL pod |
| Normal application SQL | Shared Workbench initialization and Config startup may run the normal SQL runner after import | Application Helm rollout runs SQL in Config or its bootstrap Job after import, then waits for business workloads |
| Administrator bootstrap | Run only after core deployment and its SQL succeed | Run only after the application bootstrap/rollout succeeds |

The infrastructure baseline `init.sql` does not create `user_account_t`. Account
SQL is kept out of infrastructure bootstrap. A migration error stops deployment
before the subsequent application/Secret rollout. Direct Compose, Helm or
`run-sql-migrations.sh` invocation bypasses this deployment sequence; complete the
manual importer first when upgrading historical accounts.

The importer keeps source rows in memory. Target schema creation, membership
email/role transfer and credential import share one transaction. Failure or
preview rolls back the new account table, its sequence and temporary import data,
and restores the original membership columns/data. Retry reads the source again.
There are no persistent credential snapshots, phase files or data checkpoints.

`v2.9.0_001_local_user_accounts.sql` creates the final schema directly, without
`account_status` or pending placeholders. Legacy status columns are converted to
`delete_flag` and dropped inside the same transaction; ordinary replay never
recreates them. Existing soft-deleted accounts, credentials and operator changes
are preserved on replay. The former 002 is consolidated into 001; existing SQL
execution history is retained. Transaction-local membership profiles supply roles
and emails to the importer without persisting unavailable ordinary identities.
Active CAS/OAuth bindings remain in the project database; provider-only accounts
have no local password login, while actual local password credentials retain it.

## Prepare the upgrade

Back up the original Supabase and target PostgreSQL data, settings and signing
keys. Freeze registration/password/provider changes during cutover. Use a matching
checkout, deployment package and backend image. Retain original storage until
acceptance completes.

The host needs Bash and Docker CLI, or Bash and kubectl with access to the original
namespace. **No host Python, pip, PostgreSQL driver or jq is required.** The selected
`NEXENT_IMAGE` must package the current Python worker, its existing psycopg2
runtime, and `v2.9.0_001_local_user_accounts.sql`. Standard deployment selects that
image automatically; preload it for offline deployment. The independent gateway
image is not the migration image.

Existing deployment settings are reused. Exported values override the selected
Shell-compatible `--env-file` (default `deploy/env/.env`). The source password
prefers `SUPABASE_POSTGRES_PASSWORD`, then the original container/pod environment;
manual interactive execution prompts only when both are unavailable.
Noninteractive missing credentials stop the upgrade. Changing an environment
password does not change an existing PostgreSQL cluster's password.

| Setting | Purpose |
| --- | --- |
| `NEXENT_IMAGE` | Version-matched backend image; set explicitly for standalone commands |
| `NEXENT_POSTGRES_PASSWORD`, `POSTGRES_USER`, `POSTGRES_DB` | Original target credentials |
| `SUPABASE_POSTGRES_PASSWORD`, `SUPABASE_POSTGRES_USER`, `SUPABASE_POSTGRES_DB` | Original source credentials |
| `SUPABASE_POSTGRES_HOST`, `SUPABASE_POSTGRES_PORT` | Explicit remote source endpoint, reachable from the worker |
| `SUPABASE_MIGRATION_DB_CONTAINER` | Explicit original Docker source when discovery is ambiguous |
| `SUPABASE_MIGRATION_AUTH_CONTAINER`, `SUPABASE_MIGRATION_KONG_CONTAINER` | Exact Docker peers reclaimed after successful apply |

Do not add migration DSN or `MIGRATION_SOURCE_*` / `MIGRATION_TARGET_*` variables.

## Automatic deployment

```bash
bash deploy.sh docker
# Or:
bash deploy.sh k8s
```

The shared Shell hook runs before application SQL, application Secret replacement
and business rollout. It executes psql inside the target DB container/pod to
classify the target. An existing account table skips import; absence of both
account/membership tables means fresh installation; membership without accounts
requires historical import. Missing original sources stop legacy upgrades.

Docker uses an owned one-shot container with the backend image's entrypoint
overridden to the Python worker. It attaches that container to the existing target
and source bridge networks, uses actual database internal ports/IPs and requires
no published DB ports. A source on the host can use its published port; loopback
addresses are translated to the worker network's host gateway. Host-network-only
DB containers need a reachable explicit endpoint/bridge network. The worker has
no Docker socket. An existing stopped Supabase container is started; a removed
source must first be recovered from original storage.

Kubernetes uses a separate Job before application Helm startup. The host resolves
original database endpoints/credentials and preserves source Deployment/PVC/PV
recovery definitions beside the selected env file under `backups/`, then sets
bound PV reclaim policies to `Retain`. Missing, ephemeral or unbound source storage
blocks the upgrade. A zero-replica source is scaled up and awaited. The Job receives
credentials through an owned temporary Secret, has no mounted Kubernetes API
token, uses no control CLI, and bypasses application startup SQL. It inherits
existing Config image-pull Secret references, or the namespace's default ServiceAccount
pull configuration. Configure registry access before migrating if those references
are unavailable. Network policies must allow source/target PostgreSQL access.

Python connects to both DBs inside the worker, reads a consistent read-only source
snapshot, rechecks completion under the writer lock, and applies the existing
schema/credential transaction. It never invokes Docker/kubectl. The host removes
its own worker container or Job/Secret on exit. Temporary host Secret input files
are private and removed after Job creation or on failure. No account snapshots are
written to disk. Job timeouts and migration failures stop subsequent rollout while
retaining source DB/Auth/Kong workloads. Only a committed successful apply reclaims
those source workloads, with persistent storage/backups retained. Cleanup errors
after commit are reported separately and do not erase imported credentials.

Keep the original namespace, context, Helm values, Secrets and ConfigMaps for
recovery. This operation does not convert legacy single-release Helm ownership
into the current two-release layout; resolve ownership errors first.

## Manual preview and import

Run before application/bootstrap SQL against the original business PostgreSQL.
The host uses the same Shell entry for both deployment types:

```bash
export NEXENT_IMAGE='nexent/nexent:<matching-version>'
# Docker preview, then apply:
bash deploy/sql/tools/supabase_to_postgres/migrate.sh
bash deploy/sql/tools/supabase_to_postgres/migrate.sh --apply
# Kubernetes preview, then apply:
bash deploy/sql/tools/supabase_to_postgres/migrate.sh --deployment kubernetes --namespace nexent
bash deploy/sql/tools/supabase_to_postgres/migrate.sh --deployment kubernetes --namespace nexent --apply
```

`--database-target NAME` selects the target DB container or Kubernetes workload.
`--source-container NAME` selects the original source; `--no-start-source` rejects
stopped sources. `--wait-timeout` accepts 1–300 seconds (default 300). Kubernetes
`--config-target` selects the existing Config Deployment used only for registry
pull references; no running Config is required. Preview rolls back all target
schema/data changes and retains source workloads/storage.

After success, run normal deployment. The regular SQL runner records/replays
consolidated 001 without recreating the retired status column.

## Restore or remove the legacy Docker stack

Recovery YAML, production overlay, Kong configuration and `legacy.env.example`
remain beside this guide. Use original image versions, passwords and data files.
The host Shell refuses recovery unless the data directory contains `PG_VERSION`:

```bash
export ROOT_DIR=/absolute/path/to/original/nexent-data
# Or export SUPABASE_DATA_DIR directly.
bash deploy/sql/tools/supabase_to_postgres/migrate.sh up
# Optional complete old stack/production overlay, using original auth keys:
bash deploy/sql/tools/supabase_to_postgres/migrate.sh up --with-auth --production
# Exact configured source containers only; retain volumes and data:
bash deploy/sql/tools/supabase_to_postgres/migrate.sh down
```

DB-only recovery is the default. Full auth needs original `JWT_SECRET`,
`SUPABASE_KEY`, `SERVICE_ROLE_KEY` and `DASHBOARD_PASSWORD`. Existing stopped
containers start intact. A partially present requested stack requires explicit
down/up against verified original data. Compose uses `create_host_path: false`
and never restores a backup automatically. Avoid `down -v`, volume pruning and
source-directory deletion. No recovery or migration command needs host Python.

## Identity and authentication behavior

| Identity/data | Migration behavior |
| --- | --- |
| Supabase password users | Preserve UUID, compatible bcrypt/scrypt hash, source timestamps, email confirmation and bounded provider metadata |
| Banned/deleted/anonymous users and orphans | Exclude from the new account table. Original Supabase records and membership rows remain; no role or tenant is synthesized |
| API-only batch users | Active blank-email USER/DEV membership plus historical token evidence creates a passwordless account; preserve ID, original keys and revoked key state |
| Default SPEED seed | Preserve `user_id` / `tenant_id`, mark `system_identity=speed`, keep unavailable for full-mode login. Speed mode retains its existing demo context |
| Unknown/custom identities | Exclude unrecognized identities from the local account table; retain their original records and never generate replacement IDs |
| CAS/OAuth | Existing provider bindings and CAS sessions remain in business PostgreSQL. Preserve original IDs and valid bindings. Provider-only identities stay passwordless; accounts with actual local password credentials retain password login. Import Supabase credentials only where those source identities exist |
| Audit and refresh data | Do not read/import `auth.audit_log_entries`, Supabase sessions, refresh tokens or recovery/confirmation secrets. No audit archive is created |

Canonical `user_email` and `user_role` move from `user_tenant_t` to the account;
tenant, group, key and business ownership remain unchanged. Provider metadata
never supplies an application role. `updated` counts hydrated legacy profiles,
`inserted` counts source identities absent from those profiles, and
`disabled_orphans` counts excluded source users without active tenant membership; `excluded_inactive` counts all excluded source identities. Repeat
imports skip the existing account table and preserve newer credentials/edits.

Ordinary login uses signed JWTs without a server session table. The existing
`session` response envelope stays compatible, with an empty refresh token.
Expired tokens require login; the legacy refresh endpoint rejects old credentials.
Logout clears cookies; a copied ordinary JWT remains valid until expiry unless
its credential revision or account availability changes. Password changes write
salted scrypt and increment the credential revision. CAS retains its dedicated
session table and sid revocation. Registration still requires an invitation.

Keep `JWT_SECRET` stable across application services and repeated deployments.
The new issuer and required credential revision reject legacy Supabase JWTs.
The normal SU bootstrap uses `suadmin@nexent.com`, the configured
`NEXENT_SUPER_ADMIN_PASSWORD` or the existing default. It prints credentials only
after confirming a newly created account; existing/error/manual-hidden flows do
not print them. Re-running deployment cannot recover a password from its hash.

Email reuse is checked after final account eligibility is computed. Soft-deleted,
banned, anonymous, orphaned or role-missing ordinary identities do not occupy an
email in the new account table. Temporary schema-created unavailable profiles are
removed in the same transaction, except the recognized SPEED system identity.
Only final active duplicate emails fail; logs contain the conflicting account IDs
without email values, hashes or connection details. Docker and Kubernetes preserve
the same structured conflict through psql error transport. Existing completed
account tables are still skipped, without retroactive deletion of local accounts.
Historical associations without an eligible account cannot authenticate and no
longer block SU preflight merely because the association row remains.

## Troubleshooting and recovery

Start with sanitized deployment output and database/workload readiness. Do not
paste password hashes, signing keys, DSNs or private environment files into logs.
The following query only reports schema presence:

```bash
docker exec nexent-postgresql psql -U root -d nexent -c \
  "SELECT to_regclass('nexent.user_account_t') AS accounts;"
# Kubernetes equivalent:
kubectl --namespace nexent exec deployment/nexent-postgresql -- psql -U root -d nexent -c \
  "SELECT to_regclass('nexent.user_account_t') AS accounts;"
```

Use your configured DB/user. A non-null result marks completion even when rows
were manually deleted; pending rows and SQL history never trigger re-import.

| Symptom | Checks and recovery |
| --- | --- |
| Account table exists but historical passwords were never imported | Check whether 001 or the new application was started manually first. Stop identity writes and restore the target's pre-upgrade backup containing the original membership role/email fields, then run the Shell migration entry before normal deployment. An old incomplete draft is not detected automatically |
| SU bootstrap reports an existing SU membership or missing account profile | Verify original ID and membership/account consistency. Deleting only account rows leaves tenant ownership behind. Restore the matching target backup; do not replace the owner with a new UUID or delete memberships to bypass preflight |
| Original Supabase database required / configured source missing | Recover the original stopped/removed container or restore its original data/backup, then use `up`. Verify explicit container name or remote endpoint. Never create an empty source to make migration pass |
| Source stopped, no published port, or readiness timeout | The Shell coordinator starts an existing source and the worker uses internal endpoints. Check source readiness, both Docker bridge networks or Kubernetes services/network policies, and adjust `--wait-timeout` within its supported range |
| Password unavailable or PostgreSQL authentication fails | Use the original `SUPABASE_POSTGRES_PASSWORD` and target credentials. Check the selected environment file and exported values; automatic local mode can read original container/pod settings. Changing a new container environment does not reset the old DB password |
| Target account/role/email conflict, ambiguous source IDs, unsupported date or hash | Resolve the actual conflicting legacy metadata or recover its backup. Import must preserve stable IDs and supported hashes; do not invent UUIDs, roles or replacement passwords. Failure leaves the original target schema/data available for a clean retry |
| `ModuleNotFoundError` for dotenv or psycopg2 | Rebuild/select the matching backend image. The worker requires its packaged database driver; installing packages on the host does not fix the image |
| Python path contains `C:/c/...` or `/opt/C:/Program Files/Git/...` | Use the current `migrate.sh` entry, which never launches host Python. Docker/kubectl container paths retain scoped exclusions; host filenames passed to native kubectl are converted explicitly |
| Missing `migration.py`, `migrate.py`, `legacy_stack.py`, or old version/pending-account errors | Use a consistent checkout/package. Current host entry is `migrate.sh`; the image contains its Python worker; remove stale launch commands instead of restoring deleted migration environment variables or phase files |
| SQL bootstrap or application startup fails | Inspect Config/bootstrap Job logs and the normal SQL runner output. Fix the failing schema/service prerequisite and retry deployment. A failed new credential transaction rolls back its table/profile changes; an existing completed table is preserved |
| Cleanup incomplete after migration committed | Accounts are already committed. Correct Docker/kubectl access and finish exact-resource cleanup, retaining volumes/backups. Do not drop the account table or rerun a source restore to undo a cleanup warning |
| Kubernetes source has missing/unbound/ephemeral storage | Verify the source Deployment and actual PVC/PV bindings. Preserve original storage definitions and restore its original bound storage before retrying; never substitute a new empty claim |
| Kubernetes rejects a legacy single Helm release | Resolve infrastructure/application resource ownership and the two-release layout first. Account import does not migrate Helm ownership; keep original values, Secrets and storage for that operation |
| Helm reports `secrets.jwtSecret is required for local authentication` | Supply the original signing key through private `nexent-common.secrets.jwtSecret` values. The deployment script generates/reuses it; a shell variable alone does not populate direct Helm values |

Do not delete `user_account_t` after a completed migration to force another import.
Its role/email fields may now be the only canonical copies. A partially upgraded
older target requires backup recovery or an explicit, reviewed data repair.

## Acceptance and application rollback

Verify original password login, wrong/unconfirmed/unavailable user rejection,
original UUID/tenant/role/group and business ownership, password-change JWT
revocation, existing API keys and revoked keys, and fresh/rerun SU bootstrap.
Verify provider bindings and CAS sid/single logout against actual providers before
production cutover. Local mocks do not establish external-provider acceptance.

Before new identity/password writes, application rollback requires restoring the
target PostgreSQL backup and original application configuration together against
the preserved source. The old application needs membership email/role columns;
rolling back only its image is insufficient. After cutover writes, reconcile new
accounts, password and profile changes before restoring an older backup. SQL
replay is a forward upgrade and cannot recover intentionally deleted account data.

Local verification uses `AUTH-LOCAL-D5-001` for real PostgreSQL schema/credential
atomicity, SQL replay and source lifecycle, and `AUTH-LOCAL-D2-001`, `API-005`,
`API-006` for native HTTP/authentication behavior. `deploy/tests/test_common.sh`
guards Shell-worker-before-application execution order and failure propagation.
`NEXENT_AUTH_TEST_DSN` must identify an isolated instance allowed to create/drop
test databases. Kubernetes command/storage unit tests and Shell checks are separate from actual
cluster Job verification; report the executed cluster/context and fixture scope.
