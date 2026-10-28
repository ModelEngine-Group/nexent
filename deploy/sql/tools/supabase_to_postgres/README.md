# Supabase authentication migration on the host

Run this tool on the deployment host with Python 3.11. Activate the backend
virtual environment, or install the standalone dependencies:

```sh
python -m pip install -r deploy/sql/tools/supabase_to_postgres/requirements.txt
```

The tool loads `deploy/env/.env` by default. Exported environment variables take
precedence. `--env-file PATH` selects another deployment file. No configuration
file is rewritten. Normal backend/SDK environment configuration is unaffected.

## Default flow

1. Back up both databases and freeze account/password/provider-binding writes.
2. Apply `deploy/sql/migrations/v2.8.1_001_local_user_accounts.sql` to the existing
   application PostgreSQL if the deployment SQL runner has not done so.
3. Run the host-side preview. It never writes account rows.

```sh
python deploy/sql/tools/supabase_to_postgres/migrate.py
```

4. Review counts/conflicts, then explicitly apply:

```sh
python deploy/sql/tools/supabase_to_postgres/migrate.py --apply
```

For a default local source the tool discovers the existing Supabase database
container, including names such as `supabase_db` and `supabase-db-mini`. If it is
stopped, the tool starts that existing container and waits up to 30 seconds for
PostgreSQL. It uses the published host port reported by Docker. It never creates
an empty source, recreates containers, changes volumes or stops the source after
migration. A dry-run may start the existing source container but never imports
rows. If multiple candidates exist, select one explicitly:

```sh
python deploy/sql/tools/supabase_to_postgres/migrate.py --source-container supabase_db
```

Use `--no-start-source` to reject a stopped container and `--wait-timeout 60` to
allow a longer startup. A missing source container requires recovery of the old
container/data or reachable SUPABASE_POSTGRES_HOST/PORT settings; the tool cannot reconstruct
passwords from tenant membership alone.

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
python deploy/sql/tools/supabase_to_postgres/legacy_stack.py up
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
python deploy/sql/tools/supabase_to_postgres/legacy_stack.py up --with-auth
# Optional relocated production compatibility overlay:
python deploy/sql/tools/supabase_to_postgres/legacy_stack.py up --with-auth --production
```

GoTrue/Kong are explicit `legacy-auth` profile services. The production overlay
keeps a loopback database binding so the host-side importer can connect. HTTP(S)
ports also bind to loopback by default. Startup uses `restart: "no"`, avoiding
old auth services restarting automatically after the migration window.

Then run the host-side importer using the same source credentials and environment
file. Preserve the normal target PostgreSQL settings:

```sh
python deploy/sql/tools/supabase_to_postgres/migrate.py
python deploy/sql/tools/supabase_to_postgres/migrate.py --apply
```

After verification, manually remove legacy containers:

```sh
python deploy/sql/tools/supabase_to_postgres/legacy_stack.py down
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

`migrate.py` owns CLI orchestration, `settings.py` owns host-side configuration,
`source_container.py` handles the existing local source, and `migration.py` owns
validation and transactional import. Runtime login code does not import these
operator tools.

`--apply` imports accounts in one target transaction. Repeating
the import skips matching accounts and preserves their newer passwords/status.
Source reads use a read-only repeatable-read transaction. Provider metadata never
grants application roles; live refresh credentials are never imported. The SQL
startup runner does not execute these Python tools.

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

Apply the single `v2.8.1_001_local_user_accounts.sql` before importing. It moves
legacy role/email into `user_account_t.user_role/user_email`, removes their old
association columns and preserves the original user UUID. Disabled placeholders
created by SQL are filled by `--apply`; this appears in the `updated` counter.
Completed accounts remain `skipped`. Repeated SQL/import runs preserve newer
passwords, credential revisions and profile edits. Conflicting local metadata
aborts the SQL transaction. See the cutover runbook for details.
