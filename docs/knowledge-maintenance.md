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
Valid standard ingestion references are counted as `managed_files_not_scanned`
and excluded from legacy Redis lookup. Invalid or mismatched ingestion snapshots
remain `unreconciled_ingestion_intents`; they are not silently classified as old tasks.

Redis SCAN is not a snapshot. Duplicate observations are suppressed within one
invocation. Unattributable or corrupt Redis-only results cannot be assigned to a
tenant, so `unattributed_tasks` always remains pending. `scan_complete` means the
selected traversal ended, while `snapshot` and `migration_ready` remain false.
Runtime visibility, model dimensions and source mapping still require separate
evidence. The result revision hashes only the observed result bytes; it does not
claim an atomic revision across Redis databases or PG.
## Runtime manifest inspection

```sh
python -m management.maintenance.knowledge inspect-runtime \
  --tenant-id TENANT --user-id ACTUAL_OPERATOR --knowledge-id 123 \
  --output /tmp/kb-123-runtime.jsonl --page-size 100 --timeout 300
```

Configure `RUNTIME_SERVICE_URL` in Management and `MANAGEMENT_AGENTOS_URL` in
Runtime, with the existing shared AgentOS signing configuration. This command
requires the actual operator's current edit permission. Runtime rechecks read
authorization through the signed reverse callback on every page. Management reads
only its own resource ports; Runtime catalog and model evidence use standard
`KnowledgeBase.inspect` and `Model.get` operations.

The report records all active registered file manifests, including unpublished and
tombstoned versions. A global revision covers every manifest, including those on
other pages. Changes reject traversal; there is no automatic retry. Job reference
presence is not running-job status. This metadata scan does not read document
content or validate physical vectors, and does not invoke any provider.

Explicit MODEL_NOT_FOUND responses and missing configured dimensions remain
findings with null evidence. Other upstream failures stop the report without a
finished marker. Resources and model metadata are checked again before completion.
All requests share the command's total deadline. Existing reports are not
overwritten. `migration_ready` remains false; source mapping, legacy vectors and
legacy tasks still require the separate evidence reports and explicit migration.
## Explicit source rebuild migration

Stop and drain old data-process admission and workers before using these commands.
Upgrade every Management instance before admitting a migration snapshot. Deploy
the matching Runtime with manifest inspection and configured model dimensions
before planning, and run the inventory commands to review unsupported records. The
`--legacy-quiesced` flag records the operator's confirmation; it does not stop
containers. Use the actual operator and keep the generated plan private because
it contains the selected file's original error and audit context. Reports use
exclusive owner-only creation. Keep plans and results in a private persistent
mount such as `/maintenance`; container temporary storage is not an archival copy.

```sh
python -m management.maintenance.migration plan \
  --tenant-id TENANT --user-id ACTUAL_OPERATOR --knowledge-id 123 \
  --file-id CANONICAL_32_HEX_ID --legacy-quiesced --output /maintenance/file-plan.jsonl

python -m management.maintenance.migration execute \
  --tenant-id TENANT --user-id ACTUAL_OPERATOR --knowledge-id 123 \
  --file-id CANONICAL_32_HEX_ID --legacy-quiesced \
  --plan /maintenance/file-plan.jsonl --output /maintenance/file-execution.jsonl
```

`plan` verifies current edit DAC, the exact PG source/ledger, actual pinned object
bytes, current model configuration and absence of a Runtime manifest for the file.
Source rebuild supports canonical IDs and fully pinned sources. A proven historical
source can be pinned by the explicit planning option below. Files with no legacy
task references can be admitted directly. Referenced terminal tasks require
the private archive and live verification described below. Other records remain
blocked for explicit identity/source review. It never guesses a mapping from a filename or copies legacy vectors.

`admit` writes one immutable ingestion snapshot using the existing lifecycle CAS.
The snapshot preserves original status, errors, progress, terminal timestamps and
update audit context. The existing 16 KiB limit applies without truncation. The
source identity and original creator remain unchanged. Repeating the same plan
observes its existing receipt. Stale plans, changed actors/resources/models or
source evidence are rejected. Ordinary ingestion omits the migration field when
absent; archived state is not sent in AgentOS child requests.

`execute` admits and advances the existing ingestion coordinator once. Management
performs cleansing and Runtime receives standard AgentOS file operations. A queued
or running result is progress, not completion. Repeated execution follows the
durable child states without resubmitting reserved model/storage writes. Existing
Management lifecycle discovery can also advance an admitted record, so `admit`
is a write operation and may start processing immediately.

After a timeout or unknown write result, use the same plan for a read-only receipt:

```sh
python -m management.maintenance.migration inspect \
  --tenant-id TENANT --user-id ACTUAL_OPERATOR --knowledge-id 123 \
  --file-id CANONICAL_32_HEX_ID \
  --plan /maintenance/file-plan.jsonl --output /maintenance/file-receipt.jsonl
```

`inspect` requires current edit DAC but not legacy quiescence. It reads only the
Management lifecycle through StorageInterface, without contacting Runtime or
revalidating the model/parser configuration. `intent_matches_plan` distinguishes
an absent receipt, an exact match and an unreadable stored intent. A receipt is
not an instruction to replay an unknown write.

Before switching a rebuilt file to Runtime retrieval, check its publication:

```sh
python -m management.maintenance.migration verify-publication \
  --tenant-id TENANT --user-id ACTUAL_OPERATOR --knowledge-id 123 \
  --file-id CANONICAL_32_HEX_ID \
  --plan /maintenance/file-plan.jsonl --output /maintenance/file-publication.jsonl
```

This read-only command checks the current Management lifecycle and asks Runtime
over signed AgentOS to confirm the exact upload job and its visible generation.
It compares the confirmed chunk counts and verifies that the writer finished.
Use the canonical ID after activating a legacy ID mapping. A successful receipt
contains `publication_verified: true`. Retrieval, physical vector counts and
legacy task disposition still require their separate checks.

`restore` accepts the same `--plan` arguments and restores the archived state only
while the row remains `INGEST_ACCEPTED` before child execution reservation. It
retains the actual operator's update audit and rejects later phases. The isolated
admission/restore rehearsal does not prove rollback after model or vector effects.
That path still requires standard execution drain/deletion and a separate cutover
rehearsal. Legacy indexes, Redis keys and source objects are not deleted here.

Reports are exclusive JSONL files with operation IDs. Incomplete plan reports
cannot be loaded; all commands share a total deadline and cancel owned resources.
`migration_complete` refers to the Management lifecycle reaching completion.
Use `publication_verified` for the corresponding Runtime publication evidence.
`retirement_complete` remains false. Historical task archival, missing/unversioned
sources, noncanonical IDs and full deployment/rollback acceptance remain pending.


## Migrate a standalone legacy chunk

After stopping and draining legacy writers, run `inspect-vectors` for the
affected knowledge base. Match the SHA-256 of the exact Elasticsearch document
ID with `document_id_hash` in the report and select a `standalone_candidate`.
Copy its document revision and the page's collection revision.

```sh
python -m management.maintenance.knowledge migrate-chunk \
  --tenant-id TENANT --user-id ACTUAL_OPERATOR --knowledge-id 123 \
  --legacy-quiesced --document-id EXACT_LEGACY_DOCUMENT_ID \
  --collection-revision INVENTORY_COLLECTION_REVISION \
  --document-revision INVENTORY_DOCUMENT_REVISION \
  --output /maintenance/chunk-migration.jsonl
```

The command requires current edit permission and a unique legacy index owner.
It copies the original body, display fields and any existing vector through the
standard Runtime chunk API. A successful receipt contains `chunk_migrated`.
The original document remains available in the legacy index. Existing Runtime
documents, changed source revisions, images and chunks with file processing
markers are rejected. After an uncertain write, inspect the Runtime key before
attempting the operation again.

## Private legacy task archive

After stopping and draining old admission and workers, export one authorized KB:

```sh
python -m management.maintenance.knowledge archive-tasks \
  --tenant-id TENANT --user-id ACTUAL_OPERATOR --knowledge-id 123 \
  --legacy-quiesced --output /maintenance/kb-123-task-archive.jsonl \
  --page-size 1 --timeout 300
```

The flag records the operator's confirmation and does not stop containers. Current
edit DAC and unique historical index ownership are checked as for `inspect-tasks`.
This command explicitly requests the private `archive` RecordStore projection.
The default task inventory stays redacted. The archive includes original backend
result bytes and Redis DUMP bytes for progress, error, cancel, chunks and part
keys. Values are Base64-encoded with SHA-256 and observed TTL in milliseconds;
`-1` means no expiry and `-2` means the key was absent when TTL was read. Missing
values have null payload/hash. Redis DUMP is an opaque Redis-format export, not
a portable interpreted record. No payload is unpickled or restored.

Archives are exclusive owner-only JSONL files. Keep them in a private persistent
mount. Values over 16 MiB or tasks exceeding 64 MiB stop the command without
truncation or a finished marker. Original errors may contain sensitive content;
only counts and safe status fields are printed by the command. Explicit foreign
index/tenant metadata prevents raw export. Permission or PG reference changes
also stop traversal. Unattributable Redis-only tasks remain pending.

`scan_complete` covers this selected traversal. Redis SCAN, values and TTL reads
do not form a cross-database snapshot; expiration can occur during a read. The
command never changes TTLs, clears PG task references, deletes keys, invokes
Celery or replays work. A completed archive alone does not authorize source
rebuild or prove retirement. Verify the remaining mapping and cutover steps
before removing any legacy data.


## Rebuild files with archived task references

For an otherwise eligible source, pass the same complete private archive when
planning and first admitting or executing the rebuild:

```sh
python -m management.maintenance.migration plan \
  --tenant-id TENANT --user-id ACTUAL_OPERATOR --knowledge-id 123 \
  --file-id CANONICAL_32_HEX_ID --legacy-quiesced \
  --task-archive /maintenance/kb-123-task-archive.jsonl \
  --output /maintenance/file-plan.jsonl

python -m management.maintenance.migration execute \
  --tenant-id TENANT --user-id ACTUAL_OPERATOR --knowledge-id 123 \
  --file-id CANONICAL_32_HEX_ID --legacy-quiesced \
  --task-archive /maintenance/kb-123-task-archive.jsonl \
  --plan /maintenance/file-plan.jsonl --output /maintenance/file-execution.jsonl
```

The archive must belong to the same actual operator, tenant, KB and current
resource revision, contain a complete finished traversal and identify every PG
reference without ambiguity. Only SUCCESS, FAILURE and REVOKED tasks qualify.
The command compares live scoped RecordStore results and auxiliary key bytes
against the archive. Changed, expired or unknown results stop admission. TTL
countdown does not change content identity; no TTL is modified. The archive is
limited to 1 GiB with at most 128 MiB per JSONL line. Use the archive command's
default page size of one for large task exports. Invalid/oversized reports stop
without truncation or replay.

One lifecycle CAS persists the archive's exact byte SHA-256 and the three original
task references, then assigns the standard cleanse task pointer. The existing
16 KiB intent limit still applies. No local archive path or Redis payload enters
AgentOS requests. Keep the archive itself in private persistent storage.

Once this plan is admitted, repeated admission observes its existing durable
receipt without re-reading Redis or the archive. `inspect` and pre-execution
`restore` do not accept `--task-archive`; they use the persisted plan. `restore`
also restores the original task references, while old workers remain quiesced.
It still rejects any reserved child execution. Actual processing and retirement
completion require the remaining execution, cutover and rollback acceptance.


## Explicitly pin a proven historical source

If inspection reports only unpinned source fields or an unbound ledger link,
create the plan with an explicit choice:

```sh
python -m management.maintenance.migration plan \
  --tenant-id TENANT --user-id ACTUAL_OPERATOR --knowledge-id 123 \
  --file-id CANONICAL_32_HEX_ID --legacy-quiesced --bind-observed-source \
  --output /maintenance/file-plan.jsonl
```

Add `--task-archive` when old task references require it. The binding flag is
plan-only; the resulting immutable plan carries this decision into `admit` or
`execute`. Upgrade every Management writer before using it. Default planning
continues to reject unpinned records.

The inspector must prove exact ownership of an active COMMITTED ledger entry and
read the exact object version, size and independent SHA-256. The plan records the
candidate ledger ID and original six source fields. Admission reads the evidence
again and uses one lifecycle CAS to bind source, ledger link and size together
with the standard ingestion intent. It preserves file ID, source generation,
creator and source upload hash. No object is copied, quota charged or ledger
updated. A valid existing field cannot be overwritten with a different value.

Binding does not accept missing objects/ledgers, URL aliases, hash/size/version
conflicts or an unknown file identity. The existing edit DAC and file ownership
checks still apply before admission. Strict pinned-source authorization applies
after admission, including actual cleansing execution. Repeating an accepted
plan only reads its receipt. Before child reservation, `restore` restores all
six original source fields, including nulls, alongside archived task references.
After reservation it refuses SQL-only restoration. This capability does not
complete historical source recovery, actual ingestion or data-process retirement.
