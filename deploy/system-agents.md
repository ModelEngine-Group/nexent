# Shared system Agent deployment

| Step | Responsibility | When to run |
| --- | --- | --- |
| SQL 001 | Consolidate legacy tenant Workbench definitions, bindings and references | Normal migrations on installation/upgrade; no legacy data means no consolidation |
| SQL 002 | Initialize public NL2Agent/NL2Skill identities, reusing existing IDs | Normal migrations on installation/upgrade, even with no history |
| SQL 003 | Add target and migrate legacy creator histories to the existing public IDs | After SQL 002; no Agent creation |
| `system_initialize` | Initialize only shared Workbench and prepare shared official resource files | Every scripted application deployment; reuse an existing draft and bindings |
| `system_release` | Publish only Workbench from its draft and persisted bindings | Every scripted application deployment; create once per product version |

Workbench has one shared draft (`version_no=0`) and published versions, with
independent Tool/Skill binding snapshots. NL2Agent and NL2Skill each have one shared v0 identity,
with no stored prompt, bindings, published versions or revision pointer. It
loads product prompt files and Python tools per run. Tenant credentials and
conversation ownership remain isolated. Startup and HTTP requests never
initialize or publish these Agents.

## First installation

Run normal deployment SQL migrations in order on the empty database:

1. `v2.8.1_001_shared_system_agents.sql` has no tenant Workbench data to merge.
2. `v2.8.1_002_shared_creator_identities.sql` creates the two public creator v0 identities.
3. `v2.8.1_003_creator_conversation_targets.sql` adds target; there are no histories to migrate.

The deployment scripts then execute these Workbench steps automatically. For
manual deployment, run them from `backend/`:

```sh
python -m management.services.agent.system_initialize
python -m management.services.agent.system_release
```

Python initialization creates only the shared Workbench draft under
ASSET_OWNER_TENANT_ID and publishes no version. SQL already owns both creator
identities. The publisher creates Workbench version 1 and selects it. Repeating
Python initialization retains the existing Workbench draft/bindings; it neither
traverses tenants nor reads/creates either creator identity.

## Upgrade from tenant-owned Workbench Agents

Stop old writers and active runs, and take a database backup. Apply normal SQL
migrations with the new image. The new immutable migration
`sql/migrations/v2.8.1_001_shared_system_agents.sql` runs after the v2.8.0 schema
consolidation, including the Agent prompt-column rename.

The SQL migration:

1. Retains one shared Agent ID and one definition/binding set per legacy version.
   Identical definitions for equal version numbers are a confirmed prerequisite.
   Existing published numbers, gaps and binding parameters are retained.
2. Maps ToolInstance/SkillInstance IDs to shared ToolInfo/SkillInfo, cloning
   missing shared catalog entries and mapping Skill-tool dependencies. Ordinary
   tenant resource definitions and bindings remain intact.
3. Rebinds relational Agent references, including soft-deleted conversation
   headers, preserving owners, timestamps, messages, attachments, citations,
   pins, activity and conversation configuration.
4. Physically deletes duplicate system definitions, metadata and bindings.
   Same-name USER Agents are excluded. Tenant MCP tools and non-official Skills
   cannot be shared implicitly; unsupported resources abort migration.

The complete SQL DO block and durable completion marker
`__once_shared_system_agents_v1` commit atomically in nexent.schema_migrations.
The existing runner also records the filename/checksum. Failure rolls back both
data and marker. Forced replay or retry after a runner interruption skips the
completed body. Do not edit the published migration.

After 001, execute 002 to initialize/reuse both public creator IDs, then 003 to
migrate creation histories to those IDs. The same order applies to fresh installs
and upgrades. Run the two Python commands above only after all three SQL scripts.
Python initialization preserves the migrated Workbench draft/bindings and prepares
shared official Skill files. It does not initialize either creator. SQL handles
database rows, not files.
Missing files for migrated Skills must be available from mounted official ZIP
packages; initialization fails if they cannot be prepared. Existing valid files
are retained. Catalog/file preparation uses existing separate service
transactions and may remain after draft-creation failure; it is retryable.

The publisher creates max(retained version_no)+1 and selects it. It neither
migrates data nor initializes/updates either creator. The first shared publication
also works when the legacy product revision matches the new revision.

## Subsequent product releases

The deployment scripts invoke the publisher automatically. For manual recovery,
from `backend/`, with the release's normal configuration:

```sh
python -m management.services.agent.system_release
```

This requires an initialized shared Workbench draft and only publishes that
Agent. It freezes the product prompt and copies existing draft Tool/Skill/child
bindings into the new version. It does not scan catalogs, install resources,
initialize identities or execute legacy consolidation. Manage any intended
draft-binding change before publication. Same-APP_VERSION retries create no
extra version and preserve an intentional rollback pointer.

## Docker Compose and Helm

The Docker and K8s deployment scripts automatically run Workbench initialization
and publication when the application/config service is selected. Infrastructure-only
or unrelated component deployments do not publish Workbench. Initialization is
idempotent: it retains the shared draft and its existing bindings. Same-APP_VERSION
publication reuses the existing release and preserves an intentional rollback pointer.
Initialization or publication failure stops deployment with a nonzero exit status.

Docker first validates Compose configuration, ensures selected business images are
available, and checks the Workbench Python files in the config image through a
temporary shell container that does not run SQL. Cached/local images are retained;
missing registry images are pulled before downtime. Missing local-latest images or
missing initialization modules fail preflight while the old business services remain running.

For a deployment selecting nexent-config, Docker then stops all running containers
in Compose project nexent for config, runtime, MCP, northbound, web and data-process.
PostgreSQL, Redis, Elasticsearch, MinIO, authentication and other infrastructure
are not stop targets. First installation needs no existing containers. Database
writers launched outside this Compose project must be stopped separately.

After business shutdown succeeds, Docker runs a one-shot config container. Its normal
SQL entrypoint completes migrations before running the two Python commands in order.
Only after migration, initialization and publication succeed does it start selected
business services. Stop failure prevents migration; migration/publication failure
leaves business services stopped, without automatically restarting old code against
the migrated schema. Retry the deployment after correcting the error. A deployment
without config (for example web only) stops only selected business services and
does not execute this shared Workbench migration/publication command.
On Windows Git Bash, that command locally excludes `/opt/` container arguments from
MSYS conversion while retaining conversion of host environment/Compose file paths.
K8s first renders both paused and active Helm manifests for validation. When the
application component is selected, it scales the six existing business Deployments
listed above to zero and waits for their Pods to disappear. Infrastructure remains
running. A first installation skips shutdown when no business Deployments exist.

K8s then applies the application release with `global.businessPaused=true`, keeping
business replicas at zero while creating a system-bootstrap Job. This Job uses the
new config image, environment, service account and resource mounts. It checks the
Workbench module files and waits while the deployment script synchronizes and
verifies official Skill ZIPs in the workspace. The script then releases the Job's
gate: the SQL entrypoint runs migrations, followed by Workbench initialization and
publication. Each command must succeed before the next runs.

Only a successful Job permits the second Helm update with
`global.businessPaused=false`, restoring configured replica counts and removing
the completed Job. The script then waits for new workloads to become ready.
Shutdown failure prevents migration. Job failure/timeout prints its logs, attempts
Job cleanup and leaves business workloads paused; fix the cause and retry the
deployment. There is no automatic restart of old writers against migrated data.
Non-application component deployments skip this migration/publication sequence.
External writers or controllers that independently restore business replicas must
be quiesced separately. Direct Helm upgrades bypass the script's ordering.

The following commands are for manual recovery or deployments that bypass these
scripts; they are no longer additional steps for a normal scripted deployment.

Use the deployment's image, environment, network and resource volumes. For
default Compose, from the repository root, initialize with a one-shot container;
its SQL entrypoint applies normal migrations before initialization:

```sh
docker compose --env-file deploy/env/.env -p nexent -f deploy/docker/compose/docker-compose.yml run --rm --no-deps --workdir /opt/backend --entrypoint /opt/nexent/scripts/start-backend.sh nexent-config python -m management.services.agent.system_initialize
```

Then run the same command with the final module changed to
`management.services.agent.system_release`. Infrastructure must already be
available. Later manual releases only need publication. Direct Compose/Helm
invocations that bypass deploy.sh must run equivalent explicit deployment commands
with matching image/configuration/mounts. These are not application startup backfills. A
nonzero exit stops rollout. APP_VERSION follows existing product configuration.

## Workbench rollback

```sh
python -m management.services.agent.system_release --select-workbench-version 1
```

Select an actual retained, enabled, released version. This selects its prompt
and bindings; it does not roll back Python, resource files or external services.
NL2Agent rollback deploys matching code/files. Reversing physical consolidation
requires the pre-upgrade database backup; selecting a Workbench version does
not recreate tenant copies.


## Workbench admission and memory

Workbench admission is counted by authenticated tenant ID plus workbench_main,
with the existing configured default of 50 unfinished admitted runs per tenant.
Users and published versions within a tenant share that budget. The setting
RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS remains effective, and process worker/queue
limits still apply. Accounting remains process-local; this does not introduce
a cluster-wide quota. Native Agents continue to be counted by numeric Agent ID.
Existing Workbench memory behavior is preserved. AIDP external memory plugins
are outside this revision.

## Creator conversation migration and persistence

Apply `sql/migrations/v2.8.1_002_shared_creator_identities.sql` after 001.
It always ensures one public active v0 identity for each code-backed creator,
including on empty installations. Existing public IDs and definitions are reused;
USER definitions are excluded. Missing IDs come from the database sequence.
No prompt, resource binding, publication or revision pointer is created. A partial
unique index enforces public v0 identity uniqueness, and advisory locks serialize
concurrent executions. Its own completion marker commits atomically with the seed.

Then apply `sql/migrations/v2.8.1_003_creator_conversation_targets.sql`.
It adds nullable JSONB `target` (`{"type":"agent|skill","id":123}`), and
migrates existing Workbench creation conversations in place. Their `agent_id`
becomes the shared NL2Agent/NL2Skill executor ID. Legacy Agent creation IDs
become Agent targets; Skill targets remain NULL when no reliable ID was stored.
Conversation/message IDs, owners, timestamps, attachments and configuration stay
unchanged, including soft-deleted history. Its own durable completion marker
makes replay a no-op. Both public creator IDs must already exist from 002;
a missing identity aborts 003 and rolls back its changes. Script 003 never inserts
an Agent, and Python is not a fallback for missing creator initialization.

Both Workbench creation modes and standalone creator panels call the same
creator execution/history service. Each turn stores one user and one assistant
message. Standalone panels leave `workbench_config` NULL with revision zero;
legacy `persist_history=false` no longer disables creator persistence.
The executor always has a shared ID, while runtime prompts/tools stay in code.
Agent requests use `target`; old editors' request `agent_id` is accepted as a
legacy target parameter and never written as the conversation executor.

`PATCH /conversation/{id}/target` binds a saved Skill to its conversation.
The server verifies conversation ownership, executor identity and resource edit
permission in the current tenant. Existing live targets cannot be replaced;
deleted Agent targets may be replaced without changing the executor or messages.
Retry preserves the user boundary and target. Workbench restores resource editing
from `target`, independently of executor selection. Workbench memory behavior
and external AIDP memory integration are unchanged by this work.


History detail exposes `agent_system_key`, derived from the public SYSTEM executor
identity (not inferred from target, name or tenant-owned lookalikes). Lists, pins
and Agent-chat groups use that identity to route creator history to the shared
history viewer without duplicating entries. Restoring a standalone creator derives
only transient UI state; model-control changes in that viewer do not write an
inferred Workbench configuration back to the database. Existing Workbench
configuration and its revision retain their current meaning and are read as saved.
No additional database migration or configuration-field rewrite is needed for
this separation.


## Configuration-page NL2Agent history

The NL2Agent panel has a History count/list and New conversation control.
`GET /conversation/creator_histories?kind=agent&target_id=<edited-agent-id>`
returns the authenticated user's histories for the matching public executor and
typed target, including both Workbench and standalone entrypoints. The service
checks that the target belongs to the current tenant; continuation separately
requires edit permission. Counts and pagination share the same filters.
History selection reuses the existing replay adapter and saved conversation ID;
New conversation resets only local messages/composer and saves a record on the
next send. No history is copied or saved through an additional path. Standalone
new history titles use the first question; Workbench title behavior is unchanged.
