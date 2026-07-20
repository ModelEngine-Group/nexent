# Removal candidates

Only parity-preserving removals are listed. User-visible behavior, correctness/isolation, idempotency, concurrency and recovery are not candidates.

## High confidence

- All NL2Agent Redis state/catalog/snapshot keys and cache warming/fallback code, after PostgreSQL-only tests pass.
- Redis installation lock after the durable operation lease and PostgreSQL advisory-lock claim is proven under concurrency/failure injection.
- `nl2agent_catalog_snapshot_t` and content-addressed sharing; inline the immutable normalized catalog in Session.
- Five unreleased prototype migrations and their backfills; replace with one final migration.
- `repair_nl2agent_tables.py` and migration-ID-specific local repair/guard behavior.
- Facade aliases removed by the current history and any remaining pass-through methods in `nl2agent_service.py` that only assemble dependency bundles.
- Function-valued dependency dataclasses used solely to make large services mockable; replace with narrow repository/provider protocols and real boundary fixtures.
- Separate trusted-search and recommendation-batch maps; one exact recommendation aggregate retains proof and lifecycle.
- Model/resource lists duplicated into workflow state; authoritative Agent/binding tables plus redacted state projection suffice.
- Handwritten frontend API response interfaces duplicated by generated `nl2agent-api.ts`.
- Handwritten Card payload aliases duplicated by the canonical Card schema's generated types.
- SDK normalization of MCP provider payload after Backend catalog adapters emit the same canonical install options.
- fakeredis fixtures and Redis behavior tests whose behavior is replaced by PostgreSQL CAS/lease tests.
- Tests asserting only wrapper/dependency mock calls rather than owner-scoped persisted effects.
- Prototype action Tool compatibility: only the three read-only search Tools remain.
- Automatic migration of old workflow schema versions; there is no released state to support.

## Medium confidence

- Separate summary service: most methods can become query/projection functions within Finalize/state read models, but preserving one testable projection module may improve clarity.
- Separate workflow service: commands can live beside the aggregate/repository, but routes still need an application boundary.
- Separate seed service: provisioner can be small, but startup and tenant-on-demand readiness may still justify a focused service.
- Separate Card delivery helper files in Frontend: consolidate into lifecycle coordinator if final-message streaming remains readable.
- Per-status retention environment variables: one documented policy may suffice, but operations may require independent tuning.
- Opportunistic cleanup at Session start: replace with existing scheduled maintenance if a dependable scheduler is present on the clean branch.
- Single-card Markdown fallback parser: remove if repository evidence proves all NL2Agent Cards traverse final-message validation; otherwise retain inert parsing without side effects.
- Name-prefix filtering for internal Agents: an explicit existing visibility/status field would be cleaner if one is already reliable.
- Exact marketplace byte/page values: retain finite normal-operation bounds while deferring security-tuned ceilings.

## Investigate

- Whether official Skill installation has a supported rollback API for partially written files and DB rows. If not, retain reconciliation checkpoints rather than pretending transactionality.
- Whether existing MCP service methods can accept caller-owned DB sessions across create/health/discovery without behavior changes.
- Whether a repository-wide scheduler exists and is enabled in every deployment topology for retention/expired-operation cleanup.
- Whether the final clean branch uses `deploy/sql/init.sql`, `docker/init.sql`, the K8s chart copy, or generated schema synchronization; update every authoritative fresh path.
- Whether generated TypeScript can be produced directly from the Card schema with the current toolchain, avoiding cardPayloadTypes without adding a dependency.
- Whether ordinary shared HTTP transport disables redirects/proxies in the deployment; this affects the minimum advanced-security fallback, not feature parity.
