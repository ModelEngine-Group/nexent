# W9: Full Session Lifecycle APIs

## Objective

Expose durable, authorized, auditable session operations for compact, checkpoint,
restore, fork, reset, and context inspection over immutable execution history.

## API Surface

Provide backend APIs and matching SDK methods:

| Operation | Required behavior |
| --- | --- |
| `compact` | Create a governed compacted representation, optionally using focused instructions |
| `checkpoint` | Flush and persist a named recovery boundary |
| `restore` | Create a new branch head whose active view matches a checkpoint |
| `fork` | Create a child branch referencing a parent event sequence |
| `reset_context` | Reset selected derived state without deleting source history |
| `inspect_context` | Return authorized items, representations, budgets, and decision reasons |

Add authorized Working Memory inspect/edit and memory-decision inspect operations.
Edits append events; they do not rewrite source history. Every operation is idempotent
when supplied an idempotency key and emits pre/post lifecycle events.

## Behavioral Rules

- Restore and reset cannot silently destroy dirty state; W7 writeback completes first.
- Fork inherits source events by reference and diverges through new branch events.
- Manual compaction instructions are untrusted user input governed by W10/W14.
- Inspect responses redact sensitive payloads and reveal no hidden chain-of-thought.
- Lifecycle hooks have deadlines and cannot leave operations half-committed.

## Implementation Plan

1. Define request/response/error schemas and authorization matrix.
2. Add lifecycle service orchestrating W5 events, W7 checkpoints, and W8 validation.
3. Implement checkpoint and inspect first, then fork/restore/reset, then compact.
4. Add Working Memory edit operations with optimistic version checks.
5. Add pre/post hooks and typed lifecycle events.
6. Add frontend/operator controls only after API contracts stabilize.
7. Publish SDK examples and operational runbooks.

## Repository Touchpoints

- New session lifecycle service and database modules
- `backend/apps/conversation_management_app.py`
- `backend/services/conversation_management_service.py`
- `backend/agents/agent_run_manager.py`
- New SDK session client methods
- Monitoring/operator UI

## Tests and Definition of Done

- Forked branches diverge without changing the parent.
- Restore reproduces the checkpoint's effective active-context view.
- Reset preserves immutable events and handles dirty-state writeback.
- Authorization, redaction, idempotency, concurrency, and hook-failure tests pass.
- Inspection explains inclusion, exclusion, reduction, budget, and provenance decisions.
- W9 is done when all lifecycle operations are durable, authorized, replayable,
  observable, and usable through backend API plus SDK.

