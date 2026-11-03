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

**Do not apply account SQL or start the new application before Python imports
historical accounts.** Manually applying 001 creates the completion marker without
copying passwords. Restarting deployment then skips credential import by design.
Use the automatic entry or the manual importer below, which owns the complete
schema-and-credential transaction.

| Stage | Docker | Kubernetes |
| --- | --- | --- |
| Database ready | Start selected infrastructure; PostgreSQL initializes only `deploy/sql/init.sql` on an empty data directory | Install/wait for infrastructure; its SQL ConfigMap contains only `init.sql` |
| Historical account import | Host `migrate_docker.py --deploy --apply` runs before HTTPS/core service startup | Host `migrate_k8s.py --deploy --apply` runs before application Secret replacement and application Helm rollout |
| Target transaction | Recheck table existence under the account-writer lock, run 001 and 002, transfer profiles and credentials, then commit | Same transaction through target PostgreSQL pod |
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

001 remains immutable. New `v2.9.0_002_account_availability.sql` converts disabled
legacy accounts to `delete_flag='Y'`, removes `account_status` and clears obsolete
pending metadata. Runtime availability uses `delete_flag` alone. The normal SQL
runner temporarily supplies 001's legacy input column inside its account-pair
transaction when replaying history. It executes 002 cleanup before commit even
when both account checksums matched. A failed replay rolls back that temporary
column and preserves already completed accounts.

## Prepare the upgrade

1. Back up the original Supabase database, target PostgreSQL, application settings
   and signing keys. Retain the original data volumes until acceptance finishes.
2. Freeze registration, password changes and provider-binding changes through
   cutover. Use the intended checkout/worktree and its matching deployment assets.
3. Confirm the target still has the original membership profile fields if account
   migration has not run. Recover incomplete targets using the troubleshooting
   section instead of deleting account records.
4. The deployment host needs Python 3.8+ and `python-dotenv`. Automatic local
   container/pod migration uses psql inside the database and needs no host database
   driver. Manual host PostgreSQL connections also need `psycopg2-binary`; install
   the tool's declared dependencies with the interpreter you will run:

   ```bash
   python -m pip install -r deploy/sql/tools/supabase_to_postgres/requirements.txt
   ```

5. Populate the existing `deploy/env/.env` settings. `--env-file PATH` selects a
   different file; exported variables override it. Do not introduce migration DSN
   or `MIGRATION_SOURCE_*` / `MIGRATION_TARGET_*` variables.

| Settings | Purpose |
| --- | --- |
| `NEXENT_POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_USER` | Original target database credentials |
| `POSTGRES_HOST`, `POSTGRES_PORT` | Manual target endpoint; default `127.0.0.1:5434`. The Docker service alias `nexent-postgresql` maps to this host endpoint |
| `SUPABASE_POSTGRES_PASSWORD` | Original source password; an exported/file value takes priority |
| `SUPABASE_POSTGRES_DB`, `SUPABASE_POSTGRES_USER` | Source database/user, default `supabase` / `postgres` |
| `SUPABASE_POSTGRES_HOST`, `SUPABASE_POSTGRES_PORT` | Manual source endpoint, default `127.0.0.1:5436`; explicit remote hosts connect directly |
| `SUPABASE_MIGRATION_DB_CONTAINER` | Explicit legacy Docker DB name when discovery is ambiguous |
| `SUPABASE_MIGRATION_AUTH_CONTAINER`, `SUPABASE_MIGRATION_KONG_CONTAINER` | Exact Docker peers to reclaim, default `supabase-auth-mini` / `supabase-kong-mini` |

Automatic container/pod mode uses internal database endpoints. It can recover a
local source password from its original container/pod environment when no password
is configured. It never asks for input during deployment. Manual host mode and
legacy `up` prefer `SUPABASE_POSTGRES_PASSWORD`, then hidden interactive input.
Missing credentials fail immediately in a noninteractive terminal. Replacing an
environment password does not change an existing PostgreSQL cluster's password.

## Automatic deployment

Use the root entry point with your existing deployment options:

```bash
bash deploy.sh docker
# Or, for Kubernetes:
bash deploy.sh k8s
```

A stopped existing source DB is started and awaited. A removed source container
must be recovered from its original data before retrying; see the recovery section.
The importer refuses to substitute a new empty source for missing historical data.
Fresh installations use normal SQL initialization and create the administrator
without a historical source.

Kubernetes uses a separate migration entry sharing the same import transaction.
It starts a zero-replica source Deployment, resolves the actual PVCs from its pod
specification, saves original storage definitions under `backups/` beside the
selected environment file (`deploy/env/backups/` by default), and
sets bound PV reclaim policies to `Retain`. Missing, ephemeral or unbound source
storage blocks the upgrade. Retain the original namespace, kubeconfig context,
Helm values, Secrets and ConfigMaps for recovery. The account migration does not
convert a legacy single Helm release into the current two-release layout; resolve
that ownership error before proceeding.

## Manual preview and import

Run before new Config/Runtime containers, the application bootstrap Job, or any
manual account SQL. The target must be the original business PostgreSQL database.
Existing account tables skip the operation, including preview.

### Docker or a reachable source database

```bash
# Preview; target schema/data are rolled back.
python deploy/sql/tools/supabase_to_postgres/migrate_docker.py
# Import and commit.
python deploy/sql/tools/supabase_to_postgres/migrate_docker.py --apply
```

For local discovery, the source may be named `supabase_db` or `supabase-db-mini`.
The tool uses its actual published host binding and starts it when stopped.
`--source-container NAME` selects a source explicitly, `--no-start-source` rejects
a stopped source, and `--wait-timeout 60` extends the default 30-second readiness
window up to 300 seconds. Manual host mode requires a published PostgreSQL port.

To use internal Docker database endpoints without host PostgreSQL drivers:

```bash
python deploy/sql/tools/supabase_to_postgres/migrate_docker.py --deploy --apply
```

`--database-target` selects the target DB container. For an explicit remote source
in deployment mode, `--config-target` selects the existing Config workload whose
Python environment reads the source; it must be running. Local source/target
queries use only their database containers/pods.

### Kubernetes

```bash
python deploy/sql/tools/supabase_to_postgres/migrate_k8s.py --deploy --namespace nexent
python deploy/sql/tools/supabase_to_postgres/migrate_k8s.py --deploy --apply --namespace nexent
```

Use the original context and source Secrets. `--source-container`,
`--database-target` and `--config-target` select workload names in that namespace.
Preview can start the source and preserve its storage, but never commits accounts
or deletes source workloads. The Docker `up/down` helpers do not manage Kubernetes.

After successful manual import, run normal deployment. The regular SQL runner
records/replays its migration history; it preserves the imported credentials and
removes any transaction-scoped compatibility column before commit.

## Restore or remove the legacy Docker stack

The relocated `docker-compose-supabase.yml`, production overlay, Kong configuration
and `legacy.env.example` reside beside this guide. Standard application deployment
and offline image selection exclude retired Supabase images; retain original
images or configure their existing image variables for an accessible registry.

Point recovery at the original data directory, which must contain `PG_VERSION`:

```bash
export ROOT_DIR=/absolute/path/to/original/nexent-data
# Or set SUPABASE_DATA_DIR to the original PostgreSQL data directory directly.
python deploy/sql/tools/supabase_to_postgres/migrate_docker.py up
```

The default directory is `$ROOT_DIR/volumes/db/data`. `up` starts an existing
stopped container or recreates a removed container against those original files.
It refuses empty initialization, uses `create_host_path: false` and never restores
a backup automatically. Use the original PostgreSQL image version and credentials.
The DB binds to loopback port 5436 by default, with `restart: 'no'`.

Restore GoTrue/Kong only when the complete old stack is needed, supplying the
original `JWT_SECRET`, `SUPABASE_KEY`, `SERVICE_ROLE_KEY` and `DASHBOARD_PASSWORD`:

```bash
python deploy/sql/tools/supabase_to_postgres/migrate_docker.py up --with-auth
# Optional production compatibility overlay:
python deploy/sql/tools/supabase_to_postgres/migrate_docker.py up --with-auth --production
```

Custom names, images, ports, storage and the dedicated network/project are listed
in `legacy.env.example`. Use the same environment file for recovery and teardown.
A partially present stack requires an explicit `down` followed by `up` against the
verified original data directory. Direct Compose is also possible with these YAML
files and exported variables; the Python helper adds existing-data validation.

A successful local apply reclaims only the selected source DB/Auth/Kong resources.
Volumes, bind directories and backups are retained. Remote-source imports never
remove local containers. To finish cleanup manually:

```bash
python deploy/sql/tools/supabase_to_postgres/migrate_docker.py down
```

This stops/removes exact configured container names and an empty dedicated network
owned by the migration project. It does not down the application project or delete
`nexent_network`. Avoid `down -v`, volume pruning and source-directory deletion.
Kubernetes apply removes captured source DB/Auth/Kong Deployments/Services while
retaining source storage and storage-definition backups.

## Identity and authentication behavior

| Identity/data | Migration behavior |
| --- | --- |
| Supabase password users | Preserve UUID, compatible bcrypt/scrypt hash, source timestamps, email confirmation and bounded provider metadata |
| Banned/deleted/anonymous users and orphans | Exclude from the new account table. Original Supabase records and membership rows remain; no role or tenant is synthesized |
| API-only batch users | Active blank-email USER/DEV membership plus historical token evidence creates a passwordless account; preserve ID, original keys and revoked key state |
| Default SPEED seed | Preserve `user_id` / `tenant_id`, mark `system_identity=speed`, keep unavailable for full-mode login. Speed mode retains its existing demo context |
| Unknown/custom identities | Preserve without automatic activation when no recognized eligibility exists |
| CAS/OAuth | Existing provider bindings and CAS sessions remain in business PostgreSQL. Historical registration also created Supabase project identities; import those original UUIDs. CAS-generated random passwords remain password-login disabled |
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
| Account table exists but historical passwords were never imported | Check whether 001 or the new application was started manually first. Stop identity writes and restore the target's pre-upgrade backup containing the original membership role/email fields, then run Python before normal deployment. An old incomplete draft is not detected automatically |
| SU bootstrap reports an existing SU membership or missing account profile | Verify original ID and membership/account consistency. Deleting only account rows leaves tenant ownership behind. Restore the matching target backup; do not replace the owner with a new UUID or delete memberships to bypass preflight |
| Original Supabase database required / configured source missing | Recover the original stopped/removed container or restore its original data/backup, then use `up`. Verify explicit container name or remote endpoint. Never create an empty source to make migration pass |
| Source stopped, no published port, or readiness timeout | Automatic container/pod mode can start an existing source. Manual host mode needs a published port. Check source readiness/image compatibility; select the original container and adjust `--wait-timeout` within its supported range |
| Password unavailable or PostgreSQL authentication fails | Use the original `SUPABASE_POSTGRES_PASSWORD` and target credentials. Check the selected environment file and exported values; automatic local mode can read original container/pod settings. Changing a new container environment does not reset the old DB password |
| Target account/role/email conflict, ambiguous source IDs, unsupported date or hash | Resolve the actual conflicting legacy metadata or recover its backup. Import must preserve stable IDs and supported hashes; do not invent UUIDs, roles or replacement passwords. Failure leaves the original target schema/data available for a clean retry |
| `ModuleNotFoundError` for dotenv or psycopg2 | Install the declared requirements with the exact host interpreter being used. Automatic local mode needs python-dotenv; direct host DB mode also needs psycopg2-binary |
| Python path contains `C:/c/...` or `/opt/C:/Program Files/Git/...` | Confirm the current checkout contains `migrate_docker.py`. Do not globally export `MSYS_NO_PATHCONV=1` or `MSYS2_ARG_CONV_EXCL='*'` for host Python; allow Git Bash path conversion. Docker/kubectl container calls retain their scoped exclusions |
| Missing `migration.py`, `migrate.py`, `legacy_stack.py`, or old version/pending-account errors | Use a consistent checkout/package. Current entries are `migrate_docker.py` and `migrate_k8s.py`; remove stale launch commands instead of restoring deleted migration environment variables or phase files |
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
guards Python-before-application execution order and failure propagation.
`NEXENT_AUTH_TEST_DSN` must identify an isolated instance allowed to create/drop
test databases. Kubernetes command/storage unit tests and shell checks do not
constitute a live Kubernetes upgrade.
