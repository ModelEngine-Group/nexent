# W4: Tenant and User Isolation

## Objective

Eliminate bare-conversation context state and require a fully qualified identity for
caches, checkpoints, locks, metrics, lifecycle operations, and authorization.

## Current State and Threat Model

`backend/agents/agent_run_manager.py` qualifies active runs by user and conversation,
but keys reusable `ContextManager` instances and run counts only by `conversation_id`.
Identical IDs across tenants or users can therefore collide. Future branches,
checkpoints, and artifacts would multiply the impact unless identity is fixed first.

## Identity Contract

Introduce immutable `ContextIdentity`:

```text
tenant_id, user_id, conversation_id, agent_id, branch_id
```

All fields are required for context-state mutation. `branch_id` defaults to an explicit
root branch, never null. Stable serialization is used for database uniqueness, cache
keys, distributed locks, and metric labels. Public APIs derive tenant/user identity
from authenticated request context and must not trust caller-supplied ownership fields.

## Authorization Rules

- Read/write requires tenant and user authorization plus conversation access.
- Shared-agent state uses an explicit policy and distinct scope, not omitted user IDs.
- Cross-tenant operations are denied before storage lookup.
- Metrics must avoid unbounded raw identity labels; use scoped hashes or aggregate labels.
- Deletion and cleanup operate on the same identity contract.

## Implementation Plan

1. Add `ContextIdentity` to backend and SDK boundary models.
2. Replace string key construction in `AgentRunManager`.
3. Require identity in context-manager creation, cleanup, and run registration.
4. Add identity columns and composite indexes to W5/W7 persistence schemas.
5. Add an authorization service used by checkpoint, artifact, and lifecycle operations.
6. Remove or deprecate mutation APIs that accept only `conversation_id`.
7. Add structured security audit events for denied access.

## Repository Touchpoints

- `backend/agents/agent_run_manager.py`
- `backend/agents/create_agent_info.py`
- `backend/apps/agent_app.py`
- `backend/apps/conversation_management_app.py`
- `backend/services/conversation_management_service.py`
- `backend/database/conversation_db.py`
- New event-log, checkpoint, artifact, and lifecycle modules from W5-W9

## Tests

- Collision tests use identical conversation and branch IDs across tenants and users.
- Authorization tests cover reads, writes, deletes, restore, fork, and artifact access.
- Concurrency tests prove locks are identity-qualified.
- Cleanup tests prove deleting one identity leaves all colliding identities untouched.
- Static checks or targeted repository tests reject new bare-ID context mutation APIs.

## Rollout and Definition of Done

Dual-key in-memory state briefly while logging mismatches, then switch to the full
identity and remove legacy keys. Existing sessions receive an explicit root branch and
agent identity during migration. W4 is done when every context-state mutation requires
authorized `ContextIdentity` and collision/security suites pass.

