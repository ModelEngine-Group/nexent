# W5: Structured Agent Execution Event Log

## Objective

Create an append-only, typed, replayable execution event log that becomes the durable
source of truth for agent runs while preserving the current conversation UI through a
compatibility projection.

## Scope and Non-Goals

W5 stores what happened: runs, model actions, tool calls/results, artifacts, errors,
answers, context-item lifecycle, Working Memory updates, and memory decisions. W6
decides what each consumer sees. W7 persists recovery checkpoints. Hidden/private
chain-of-thought is explicitly not required and is not persisted by default.

## Core Entities

| Entity | Required responsibility |
| --- | --- |
| `agent_session` | Context identity, status, root branch, lifecycle metadata |
| `agent_run` | User-triggered execution and immutable model/config snapshots |
| `agent_event` | Ordered typed event with schema-versioned payload |
| `agent_artifact` | Large or binary output stored outside inline events |
| `context_checkpoint` | Event-boundary recovery record, implemented with W7 |

Every event includes `tenant_id`, `user_id`, `session_id`, `run_id`, `branch_id`,
`event_seq`, `event_type`, optional `step_id`, optional `parent_event_id`, timestamps,
schema version, redaction status, and policy version. Ordering is monotonic within a
branch; event IDs are globally unique and idempotency keys prevent duplicate appends.

## Event Taxonomy

Define a stable registry for user input, run lifecycle, model action, tool call, tool
result, artifact, error/retry/cancellation, final answer, Working Memory update,
memory candidate/write/conflict decision, context-item creation/representation/recall/
eviction/restoration, writeback stage/validation/commit/rejection, checkpoint, and
lifecycle boundary. Payload schemas use typed models and stable reason codes.

## Write Path

The backend owns event creation. A transaction appends the event and advances the
branch sequence using optimistic concurrency. Large payloads are redacted, written to
artifact storage, and referenced by events. User-facing conversation tables continue
to be populated by an idempotent compatibility projector, not by frontend authority.
Failed projection never loses the source event and is retriable.

## Implementation Plan

1. Approve event taxonomy, schemas, ordering, idempotency, and evolution ADRs.
2. Add database entities, indexes, payload-size limits, and append repository.
3. Add an event writer to agent execution, tool, error, cancellation, and answer paths.
4. Add context/memory lifecycle event APIs for W6-W14.
5. Implement redaction-before-persistence and artifact-reference behavior with W14.
6. Build compatibility projection into current conversation tables.
7. Implement replay tooling that reconstructs a run after process restart.

## Repository Touchpoints

- `backend/database/db_models.py` and new event-log database module
- `backend/agents/create_agent_info.py`
- `backend/apps/agent_app.py`
- `backend/services/conversation_management_service.py`
- `backend/database/conversation_db.py`
- `sdk/nexent/core/agents/nexent_agent.py`
- `sdk/nexent/core/agents/agent_context.py`
- Tool execution and observer/monitoring paths

## Tests and Definition of Done

- Schema contract and backward/forward event-version tests.
- Atomic ordering, idempotent append, retry, and concurrent-writer tests.
- Replay test reconstructs a completed and interrupted run after restart.
- Compatibility projection matches existing UI behavior.
- Redaction fixtures prove secrets and hidden reasoning are absent.
- W5 is done when all production run paths emit typed events, replay is deterministic
  enough to rebuild state, and no UI transcript is treated as the execution source of truth.

