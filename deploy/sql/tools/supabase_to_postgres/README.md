# Supabase authentication upgrade

## Automatic deployment

Run the normal `deploy.sh`. Docker invokes `migrate_docker.py`; Kubernetes invokes the
dedicated `migrate_k8s.py`, sharing account import logic. Users do not run a separate migration
command or install host database packages. The deployment host requires Python
3.8+, Docker or kubectl, and access to the original source data.

Before replacing the application, deployment checks the account SQL version and
SHA-256 in `nexent.schema_migrations`, together with data-import and cleanup
checkpoints. An incomplete upgrade snapshots only `auth.users` and
`auth.identities` into a private file under `deploy/env/.migration-state/`.
Stopped existing Docker source databases are started automatically. Exported
`SUPABASE_POSTGRES_PASSWORD` takes precedence; otherwise the original source
container's password is reused without prompting. Source reads are read-only.

Config then runs the normal versioned SQL migration runner. After it records
`v2.9.0_001_local_user_accounts.sql` at the expected checksum, deployment runs
`migrate_docker.py` with `--apply` using Config's existing Python/database dependencies.
Account import and its data checkpoint commit in one transaction. Deployment
then removes the selected source DB/Auth/Kong containers and records cleanup,
before creating/checking the super admin. Data volumes and backups remain.
Kubernetes snapshots the source PVC/PV definitions and sets the PV reclaim
policy to `Retain` before Helm replaces the legacy resources.

A fresh installation with no historical identities needs no source. A completed
upgrade skips source access. An import failure leaves the source and private
snapshot available; a cleanup failure retains the snapshot and committed data
checkpoint. Fix the reported prerequisite and rerun `deploy.sh`. SQL completion
alone never skips an unfinished credential import. The snapshot is deleted only
after both import and cleanup succeed; protect retained files as credentials.
Infrastructure-only and data-process-only deployments do not invoke this flow.

Back up both databases and freeze account/password/provider-binding writes
during cutover. If the original source containers were deleted, recover them
from their existing data using the manual recovery commands below; automatic
deployment refuses to create an empty source for historical login identities.

## Manual recovery and preview

### Kubernetes entry point

Kubernetes `deploy.sh` automatically uses `migrate_k8s.py`. It shares account
mapping/import and checkpoints with `migrate_docker.py`, while handling Kubernetes
source startup and actual PVC/PV bindings separately. A source Deployment scaled
to zero is scaled to one and awaited. Custom existing claims are discovered from
the pod template; every bound PV is archived and protected with `Retain` before
Helm removes legacy resources. Missing/unbound persistent storage blocks rollout.
Retry snapshots are checked against the namespace, target database and API server.

For recovery, use the same kubeconfig context, namespace and state directory:

```sh
python deploy/sql/tools/supabase_to_postgres/migrate_k8s.py --deploy-phase prepare --namespace nexent
# Deploy the application so Config executes the versioned SQL migrations.
python deploy/sql/tools/supabase_to_postgres/migrate_k8s.py --deploy-phase apply --apply --namespace nexent
```

Optional `--source-container`, `--database-target` and `--config-target` select
Deployment names in this namespace. `up/down` commands are Docker-only. Keep
private state files and source storage for recovery. Helm may remove old source
workloads during rollout; the read-only account snapshot remains available even
when a later import fails. Recovery of the complete old authentication stack
also requires the original Helm values, Secrets and ConfigMaps and a business
database backup; a retained PV alone does not restore that stack.

Run this tool on the deployment host with Python 3.11. Activate the backend
virtual environment, or install the standalone dependencies:

```sh
python -m pip install -r deploy/sql/tools/supabase_to_postgres/requirements.txt
```

The tool loads `deploy/env/.env` by default. Exported environment variables take
precedence. `--env-file PATH` selects another deployment file. No configuration
file is rewritten. Normal backend/SDK environment configuration is unaffected.

### Manual flow

1. Back up both databases and freeze account/password/provider-binding writes.
2. Apply `deploy/sql/migrations/v2.9.0_001_local_user_accounts.sql` to the existing
   application PostgreSQL if the deployment SQL runner has not done so.
3. Run the host-side preview. It never writes account rows.

```sh
python deploy/sql/tools/supabase_to_postgres/migrate_docker.py
```

4. Review counts/conflicts, then explicitly apply:

```sh
python deploy/sql/tools/supabase_to_postgres/migrate_docker.py --apply
```

For a default local source the tool discovers the existing Supabase database
container, including names such as `supabase_db` and `supabase-db-mini`. If it is
stopped, the tool starts that existing container and waits up to 30 seconds for
PostgreSQL. It uses the published host port reported by Docker. It never creates
an empty source or changes data volumes. After a successful local `--apply`
commits, it stops and removes the selected source DB plus the configured legacy
Auth/Kong containers. A preview or failed import retains the stack for inspection
and retry. A dry-run may start the existing source container but never imports
rows or removes containers. If multiple candidates exist, select one explicitly:

```sh
python deploy/sql/tools/supabase_to_postgres/migrate_docker.py --source-container supabase_db
```

Use `--no-start-source` to reject a stopped container and `--wait-timeout 60` to
allow a longer startup. A missing source container requires recovery of the old
container/data or reachable SUPABASE_POSTGRES_HOST/PORT settings; the tool cannot reconstruct
passwords from tenant membership alone.

The selected DB name is used for cleanup. Auth/Kong default to
`supabase-auth-mini` and `supabase-kong-mini`; set
`SUPABASE_MIGRATION_AUTH_CONTAINER` / `SUPABASE_MIGRATION_KONG_CONTAINER` in the
existing deployment environment if the source stack uses different names. Cleanup
uses exact names, never application-wide Compose down, and does not delete data
volumes or backups. A remote source selected only by HOST/PORT does not cause
local container removal. If cleanup fails after commit, the command reports
`Account migration committed; source cleanup failed`; the accounts remain
migrated. Correct Docker access/configuration and use `migrate_docker.py down` with
the original source names to finish cleanup; repeating the importer is safe.

## Historical API-only identities

The historical fixed `user_id` / `tenant_id` / `SPEED` demo identity is a system
identity. Its untouched migration placeholder is marked `system_identity=speed`,
kept disabled with password login off, and removed from credential-pending state.
Speed-mode authentication retains its existing default context; full-mode
authentication does not gain access. Replays preserve operator changes. Custom
SPEED identities and unknown blank-email users are not automatically activated.
Deployment preparation recognizes this repairable seed before Config reruns SQL,
so an old pending seed alone does not require a Supabase database.

CAS/OAuth provider bindings and CAS sessions already reside in application
PostgreSQL and are retained. Historical registration code also created project
identities in Supabase: these identity records still require import under their
original UUIDs. Provider bindings alone do not prove account activation eligibility
or reconstruct passwords/disabled status. CAS-created random passwords remain
ineligible for password login; OAuth/password accounts retain their original rules.

API-only users created by the batch endpoint have no Supabase `auth.users` row.
The 2.9.0 SQL recognizes an active USER/DEV membership with an empty email and
historical token evidence, retains the original UUID and API Key, and makes the
account active with password login disabled. A revoked key stays revoked. A
normal login identity, deleted membership, or identity without this evidence stays
disabled until its normal credential migration completes.

The same SQL repairs untouched pending placeholders created by the earlier draft
migration, even when the old membership columns have already been removed. It
does not reactivate an account subsequently disabled/deleted or modified by an
operator. Batch creation now writes the passwordless account, membership, group
link and key in one transaction, so a later failure rolls back the entire batch.

## Restore a stopped or removed legacy stack manually

The original Compose definitions now live beside the migration tools:
`docker-compose-supabase.yml`, `docker-compose-supabase.prod.yml`, and `kong.yml`.
They are excluded from normal Nexent deployment. Historical SQL files remain at
`deploy/sql/supabase`; the relocated YAML references them without modifying them.

If the old containers have been removed, the importer cannot start them by name.
Recover them explicitly from their original bind data before importing. Prepare
an environment file outside Git based on `legacy.env.example`, or export the
original values. `ROOT_DIR` is the original deployment storage root whose
`volumes/db/data/PG_VERSION` already exists. `SUPABASE_DATA_DIR` may specify the
exact existing PostgreSQL directory instead. The normal Nexent image/offline selection does not include these retired images;
keep the old local images or configure their registry mirrors explicitly.
Use the original PostgreSQL image version and password; a different environment password does not reset an existing
PostgreSQL cluster's credentials.

```sh
# Environment may instead come from --env-file /private/path/legacy.env.
export ROOT_DIR=/absolute/path/to/original/nexent-data
# If already exported, SUPABASE_POSTGRES_PASSWORD is reused; otherwise up prompts.
python deploy/sql/tools/supabase_to_postgres/migrate_docker.py up
```

Default `up` selects only the legacy database, publishing PostgreSQL on loopback
port 5436. It refuses to initialize an empty source: `PG_VERSION` must exist and
the data bind uses `create_host_path: false`. If the DB container is merely
stopped, it starts that existing container without changing its settings. If it
was removed, Compose recreates the container against the same data directory.
It never auto-restores a backup or runs `initdb` on a new directory.

To restore old GoTrue and Kong as well, provide the original `JWT_SECRET`,
`SUPABASE_KEY`, `SERVICE_ROLE_KEY`, and Kong `DASHBOARD_PASSWORD` through the environment/file:

```sh
python deploy/sql/tools/supabase_to_postgres/migrate_docker.py up --with-auth
# Optional relocated production compatibility overlay:
python deploy/sql/tools/supabase_to_postgres/migrate_docker.py up --with-auth --production
```

GoTrue/Kong are explicit `legacy-auth` profile services. The production overlay
keeps a loopback database binding so the host-side importer can connect. HTTP(S)
ports also bind to loopback by default. Startup uses `restart: "no"`, avoiding
old auth services restarting automatically after the migration window.

Then run the host-side importer using the same source credentials and environment
file. Preserve the normal target PostgreSQL settings:

```sh
python deploy/sql/tools/supabase_to_postgres/migrate_docker.py
python deploy/sql/tools/supabase_to_postgres/migrate_docker.py --apply
```

After verification, manually remove legacy containers:

```sh
python deploy/sql/tools/supabase_to_postgres/migrate_docker.py down
```

`down` stops/removes only the three configured Supabase container names. It
retains bind directories and named volumes, and removes only a dedicated network
owned by the migration Compose project. It never downs the application Compose
project, deletes `nexent_network`, or calls volume deletion. It also handles old
containers created under the former deployment project. If only part of the
requested stack exists, `up` asks for an explicit `down` then `up` to avoid name
or project conflicts. Verify the original data path before that sequence.

The helper defaults to `deploy/env/.env`; both `up` and `down` accept `--env-file`.
Use the same environment file for teardown when custom container/network names
were used. Available overrides are listed in `legacy.env.example`, including
image tags, container names, published ports and the dedicated project/network.
Direct Docker Compose use is also possible with these YAML files and exported
variables, but the helper additionally validates the existing `PG_VERSION` and
handles containers retained from the previous Compose project. Avoid `down -v`,
volume pruning and deleting the original data directory.

## Connections and password priority

| Setting | Default behavior |
| --- | --- |
| Source host/port | `127.0.0.1:5436`, replaced by the existing container's actual published binding |
| Source database/user | `SUPABASE_POSTGRES_DB` / `SUPABASE_POSTGRES_USER`, default `supabase` / `postgres` |
| Source password | `SUPABASE_POSTGRES_PASSWORD`, then hidden interactive input |
| Target host/port | `127.0.0.1:5434`; Docker service hostname `nexent-postgresql` maps to that published host endpoint |
| Target database/user/password | Existing `POSTGRES_DB`, `POSTGRES_USER`, `NEXENT_POSTGRES_PASSWORD` |

If a source password is exported or present in the
deployment file, the tool does not prompt. Missing passwords use `getpass` in an
interactive terminal. Noninteractive runs fail with a clear prerequisite message
instead of waiting for input. Neither Docker stderr nor connection details are
printed on errors. Set connection secrets through environment variables rather
than command-line arguments or committed configuration.

## Data contract and layout

`migrate_docker.py` contains deployment orchestration, manual CLI, configuration, source
container handling, validation and transactional import. Runtime login code does
not import this operator tool.

`--apply` imports accounts in one target transaction. Repeating
the import skips matching accounts and preserves their newer passwords/status.
Source reads use a read-only repeatable-read transaction. Provider metadata never
grants application roles; live refresh credentials are never imported. The SQL
startup runner owns SQL order; `deploy.sh` invokes this tool around that runner.

See the [cutover and verification runbook](../../../../docs/local-authentication-migration.md)
for excluded source fields and acceptance checks. Keep source backups until
original passwords, UUID/ownership and provider bindings have been verified.

Source `auth.audit_log_entries` is excluded entirely: the tool never reads it,
creates no audit archive, and returns only account counters. Existing application
business/security auditing is independent and unchanged.

Connections use only the existing SUPABASE_POSTGRES_HOST/PORT/DB/USER/PASSWORD
and POSTGRES_HOST/PORT/DB/USER plus NEXENT_POSTGRES_PASSWORD fields. An explicit
source host address connects directly; default settings and Docker service
aliases retain automatic discovery/startup. --source-container explicitly selects
a local container when needed. No migration-specific DSN or endpoint variables
are read.

## Canonical account profile upgrade

Apply the single `v2.9.0_001_local_user_accounts.sql` before importing. It moves
legacy role/email into `user_account_t.user_role/user_email`, removes their old
association columns and preserves the original user UUID. Disabled placeholders
created by SQL are filled by `--apply`; this appears in the `updated` counter.
Completed accounts remain `skipped`. Repeated SQL/import runs preserve newer
passwords, credential revisions and profile edits. Conflicting local metadata
aborts the SQL transaction. See the cutover runbook for details.
