# Historical KB source inspection

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
