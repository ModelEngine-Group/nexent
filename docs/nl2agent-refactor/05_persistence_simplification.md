# Persistence simplification

## Decision

PostgreSQL is the only authority. Store workflow, recommendations, Card Delivery and the immutable Session catalog in one Session aggregate. Add a durable installation-operation table because external MCP/Skill effects need checkpoints, leases and idempotent recovery. Remove all NL2Agent Redis keys, the separate workflow/cache repository and the content-addressed snapshot table.

## Final schema

### nl2agent_session_t

| Column | Type | Rule |
|---|---|---|
| session_id | bigint identity | primary key |
| tenant_id, user_id | varchar(100) | not null |
| runner_agent_id, draft_agent_id, conversation_id | int | not null |
| status | varchar(20) | active/completed/abandoned |
| workflow_schema_version | int | clean release starts at 1 |
| workflow_revision | bigint | default 0 |
| workflow_state | jsonb | strict domain payload |
| catalog_schema_version | int | default 1 |
| catalog_snapshot | jsonb | immutable normalized redacted catalog |
| audit fields | existing project types | timestamps, actors, delete flag |

Constraints: unique tenant+draft; unique tenant+conversation; owner/status/update index; status/update retention index; status check; existing partial unique tenant Runner index. The inline catalog makes start and cleanup one transaction. Cross-Session content sharing is only an optimization and is omitted.

### nl2agent_installation_operation_t

| Column | Type | Rule |
|---|---|---|
| operation_id | bigint identity | primary key |
| tenant_id, draft_agent_id | owner identity | not null |
| resource_type | varchar(16) | mcp/skill |
| installation_key | varchar(300) | stable and secret-free |
| request_fingerprint | char(64) | option + non-secret canonical structure |
| status | varchar(24) | running/connected/completed/failed/compensating |
| step | varchar(32) | durable saga checkpoint |
| attempt_count | int | default 1 |
| lease_owner | uuid | nullable |
| lease_expires_at | timestamptz | nullable |
| mcp_id, skill_id | int | nullable result references |
| public_result | jsonb | redacted IDs/status only |
| error_code, error_summary | bounded text | redacted |
| audit/completion times | timestamps/actors | project convention |

Use a unique constraint on tenant+draft+resource_type+installation_key and an index on status+lease expiry. Validate tenant/draft against an active owned Session before claim and every transition.

## Workflow JSON

It contains requirements/status/fingerprint; step completions; one recommendations map with exact ordered references and searched/presented/applying/applied/skipped/completed status; MCP review with option/operation/discovered/bound IDs; and Delivery keyed by logical Card type with message/key/status/reason/retry count.

It does not contain a catalog copy, secrets, raw configuration values or duplicated model/resource lists. Existing Agent and binding tables are truth. State response joins them and exposes only the redacted recovery projection.

## Transactions

Pure state commands use owner/status/revision conditional update. A zero-row update maps to stale, terminal or invisible ownership semantics. Commands changing Agent/binding tables lock the Session and commit resource plus workflow changes together. Finalize locks Session, re-evaluates, revalidates every model/resource by tenant, updates version-0 Draft and completes Session in one transaction.

## Installation concurrency

1. Validate owner, active Session, trusted recommendation and declared option.
2. Acquire a short `pg_advisory_xact_lock` derived from tenant/draft/type/key.
3. Insert or inspect the unique operation.
4. Replay completed result; reject another live lease; otherwise claim with random owner and expiry.
5. Release the transaction before external I/O.
6. Reacquire short lock for checkpoints/heartbeat, updating only when owner matches.
7. Retry resumes from persisted provenance/checkpoint.

This preserves token ownership without Redis or a DB connection held across network work. A recommendation-scoped claim also prevents different options installing the same recommendation concurrently.

## Compensation

- Start, model, local Apply, identity and Finalize become single transactions.
- Delete a newly created container if MCP persistence fails.
- Retain a persisted MCP when later health/discovery fails and resume it.
- Upsert all discovered Tools and checkpoint atomically.
- Bind all selected MCP Tools plus workflow resolution atomically.
- Reconcile an official Skill by canonical identity before retry; invoke existing installer rollback where supported.
- Durable compensating/failed state is never returned as success.

## Retention

Status plus update_time is sufficient. Stale active becomes abandoned; old abandoned artifacts are soft-deleted; old completed Session/operations are removed while Draft remains. A scheduled job is preferable to opportunistic start cleanup, but either is behavior-compatible. Never clean an operation with a live lease.

## Redis audit

| Key/dependency | Current purpose | Classification | Target |
|---|---|---|---|
| nl2agent:session_state | disposable workflow projection | replaceable by PostgreSQL; performance-only | remove |
| nl2agent:session_catalog | disposable catalog projection | replaceable by PostgreSQL | remove |
| nl2agent:catalog_snapshot | shared content cache | performance-only/removable | remove |
| nl2agent:mcp_installation_lock | distributed token lock | functional behavior; replaceable by advisory lock + operation lease | replace |
| Redis WATCH/MULTI | workflow/catalog CAS | replaceable by DB revision CAS | remove |
| Redis warming/fallback | optimization | removable | remove |
| fakeredis fixtures | implementation-test dependency | removable | use transactional repository fixtures |

Concurrency, idempotency, lease ownership, crash recovery and compensation remain baseline guarantees.
