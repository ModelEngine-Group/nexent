# Historical KB inspection

The server-side maintenance command inspects one tenant and KB. It checks the
operator's current membership and edit permission before reading source objects.
Use the actual operator's user ID. The command never chooses a creator or task
owner automatically and does not expose a public HTTP route.

Run it from `backend/`, or inside the Management image with the same Python
environment as the service.

Use the service's existing PG and MinIO configuration. No new environment flags
are required.

```bash
python -m management.maintenance.knowledge inspect \
  --tenant-id tenant-id \
  --user-id actual-operator-id \
  --knowledge-id 42 \
  --page-size 100 \
  --timeout 300 \
  --output /tmp/kb-42-source-inventory.jsonl
```

The output directory must already exist. The command creates a new JSONL file
and refuses to overwrite an existing report. Paths refer to the filesystem where
the command runs. Copy reports out of a container explicitly when needed.

Each page contains active lifecycle records selected by KB and tenant, the
actual operator, issues and observed source evidence. A source is read only when
its exact object identity has a committed ledger entry in the selected KB. Reads
use a fixed object revision and calculate SHA256 from actual bytes. ETags are
object revisions and are never used as content hashes. Missing source pins can
produce a `candidate_source`; this observation does not change stored records.

Issues distinguish noncanonical file IDs, unpinned source identities, mismatched
hashes or sizes, unresolved aliases, missing or inactive ledger entries, pending
deletions and unverified tasks. The report omits raw source URLs, local paths,
task payloads and credentials. Authorization or record changes during a page
discard that page with a conflict. There are no automatic retries.

Exit code 0 means the selected **source inventory** finished. A successful report
ends with `source_inventory_finished` and `scan_complete=true`. It always retains
`migration_ready=false` and unfinished checks for old vectors, legacy tasks,
Runtime visibility and model dimensions. It cannot authorize cutover or perform
a migration. There is no `apply` mode.

Exit code 1 indicates a failure; 2 indicates invalid arguments; interruption uses
130. A partial report has no finished marker. Earlier pages are observations at
their individual read times, not a transaction across the whole KB. Future
migration execution must revalidate their resource, file, ledger and source
versions before writing. Repeating inspection is safe because it never modifies
PG, objects, vectors or queues.

Source inspection is the first part of the data-process retirement maintenance
work. Legacy ES inventory, Redis-only task handling, explicit ingestion into the
new visible manifests, rollback and cutover rehearsal remain separate required
steps. Keep old data and queues until those checks are complete.

## Legacy vector inventory

Run this separate command with the Management PG configuration and the existing
Elasticsearch endpoint. The ES driver loads when this command runs; the source
inspection command does not require that driver.

```bash
python -m management.maintenance.knowledge inspect-vectors \
  --tenant-id tenant-id \
  --user-id actual-operator-id \
  --knowledge-id 42 \
  --page-size 100 \
  --timeout 300 \
  --output /tmp/kb-42-legacy-vectors.jsonl
```

The operator needs current edit permission. Infrastructure also verifies that
the physical index belongs to exactly this KB across known PG ownership history,
including soft-deleted rows. Shared indexes, aliases and ambiguous ownership are
rejected before document scanning. The command reads the old physical index
through StorageInterface and leaves its data intact. It creates no new index.

One PIT supplies the count and all pages. The command checks vector values and
dimensions against the stored mapping, records unresolved file identities and
tenant conflicts, then closes the PIT and clients. The report contains document
ID and source-reference hashes, storage revisions and confirmed canonical file
IDs. It omits raw URLs, credentials, content and vectors.

The `legacy_vector_inventory_finished` record confirms that this snapshot scan
completed. The report retains `migration_ready=false` and pending source mapping,
legacy task, Runtime visibility and model dimension checks. Model compatibility
requires Runtime evidence through AgentOS; the stored index dimensions alone do
not establish it. Explicit migration must revalidate these observations before
writing. This command has no execution or retry mode and adds no public route.

## Legacy task inspection

Run the explicit `inspect-tasks` subcommand from the Management image with both
`REDIS_BACKEND_URL` (legacy Celery result database) and `REDIS_URL` (auxiliary database)
configured. It uses the same required `--tenant-id`, `--user-id`, `--knowledge-id`,
`--output`, `--page-size` and total `--timeout` options as the source inspector.

```sh
python -m management.maintenance.knowledge inspect-tasks \
  --tenant-id TENANT --user-id ACTUAL_OPERATOR --knowledge-id 123 \
  --output /tmp/kb-123-tasks.jsonl --page-size 100 --timeout 300
```

Current edit DAC and one unique historical index owner are required before Redis
access. PG-linked process, forward and parent task references are checked even if
the result has expired. Redis-only results are included only when their metadata
names the selected exact index. Missing results remain UNKNOWN. The report hashes
task IDs, allows only known status codes and canonical file IDs, and reports key
presence for progress, errors, cancellation, chunks and parts without reading those
values. It never invokes Celery, resumes jobs, sets TTLs or deletes keys.

Redis SCAN is not a snapshot. Duplicate observations are suppressed within one
invocation. Unattributable or corrupt Redis-only results cannot be assigned to a
tenant, so `unattributed_tasks` always remains pending. `scan_complete` means the
selected traversal ended, while `snapshot` and `migration_ready` remain false.
Runtime visibility, model dimensions and source mapping still require separate
evidence. The result revision hashes only the observed result bytes; it does not
claim an atomic revision across Redis databases or PG.
