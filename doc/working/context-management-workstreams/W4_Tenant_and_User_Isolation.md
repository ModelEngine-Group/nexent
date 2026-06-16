# W4: Tenant and User Isolation

## Objective

Eliminate bare-conversation context state and require a fully qualified identity for
caches, compression snapshots, locks, metrics, lifecycle operations, and authorization.

## Current State and Threat Model

`backend/agents/agent_run_manager.py` qualifies active runs by user and conversation,
but keys reusable `ContextManager` instances and run counts only by `conversation_id`.
Identical IDs across tenants or users can therefore collide. Durable sessions,
compression snapshots, and artifacts would multiply the impact unless identity is fixed first.

## Identity Contract

W4 owns identity resolution, authorization, and identity-qualified keying. It does not
define event schemas, compression snapshot contents, or lifecycle behavior; W5 and W9 consume
the authorized identity contract.

Introduce immutable branchless `ContextIdentity`:

```text
tenant_id, user_id, conversation_id
```

All fields are required for conversation/session-state mutation. Agent identity is a
run property, not a session-ownership field, because a conversation may execute
different agents over time. Stable serialization is used for database uniqueness,
cache keys, distributed locks, and metric labels. Public APIs derive tenant/user
identity from authenticated request context and must not trust caller-supplied
ownership fields.

### Subagent Identity Contract

A subagent runs under its own `agent_session_id` (UUID) but inherits the parent's
`conversation_id`. The `agent_session` table records `parent_session_id` (UUID,
nullable) and `delegation_type` (enum: `'subagent'` or NULL) to capture the
delegation relationship.

The subagent's W4 `ContextIdentity` uses the same `tenant_id` and `user_id` as
the parent session. Subagent authorization follows the same rules as ordinary
agents, determined by its agent configuration.

Recursive delegation is prohibited: a subagent cannot create sub-subagents.

**Finding:** CM-025.

### Initial Single-Owner Contract

The initial release supports exactly one immutable owning `tenant_id` and `user_id` for
each conversation and its W5 `agent_session`. It does not support conversation
membership, shared-session access, or ownership transfer. A future product request to
give another user an independent copy creates a new conversation/session; it does not
change the original owner's durable identity.

Shared agents, tenant-shared memories, and other independently governed resources do
not grant access to a conversation, session, event, compression snapshot, artifact, projection,
or lifecycle operation. Explicit administrator/operator privileges, when separately
defined, are audited policy exceptions and never change session ownership.

## Authorization Rules

- Ordinary conversation/session read and write requires the authenticated user to
  match the immutable owner resolved by trusted backend code.
- Requests to share a conversation or transfer ownership return
  `shared_conversation_unsupported` or `ownership_transfer_unsupported`.
- Ordinary unauthorized resource access returns the existing non-disclosing
  `access_denied`/`not_found` behavior rather than revealing whether another user's
  resource exists.
- Shared-agent and tenant-shared-memory state use their own explicit policy and scope,
  not omitted user IDs or inherited conversation access.
- Cross-tenant operations are denied before storage lookup.
- Metrics must avoid unbounded raw identity labels; use scoped hashes or aggregate labels.
- Deletion and cleanup operate on the same identity contract.

## Identity Resolution Contract

```text
resolve_context_identity(authenticated_request, conversation_id) -> ContextIdentity
authorize_context_operation(identity, operation, resource) -> AuthorizationDecision
```

The immutable identity is canonically serialized. Decisions contain allow/deny, policy
version, reason code, and audit metadata. Tenant/user ownership is always derived and
verified server-side. Required denials include `identity_not_found`, `tenant_mismatch`,
`user_not_authorized`, `conversation_not_owned`, and `resource_scope_mismatch`.
Caller-supplied identity fields or authorization decisions are untrusted. Model
dispatch and governed persistence require a current server-issued allow decision bound
to the operation and resource being executed.

## Keying, Deliverables, and Phases

- Caches, durable uniqueness constraints, locks, and cleanup selectors use the complete
  identity or a collision-resistant canonical hash; raw identities are not metric labels.
- Deliver the shared identity model, resolver, authorization matrix/service, migrated
  runtime/storage keys, collision report, and denied-access audit events.
- Phase through shadow dual-key comparison, cache/run/lock migration, full enforcement,
  then removal of bare internal mutation APIs and legacy keys.

## Implementation Plan

1. Add `ContextIdentity` to backend and SDK boundary models.
2. Replace string key construction in `AgentRunManager`.
3. Require identity in context-manager creation, cleanup, and run registration.
4. Verify W5 persistence schemas include identity columns and composite indexes;
   coordinate with W5 implementation to ensure alignment.
5. Add an authorization service used by compression snapshot, artifact, and lifecycle operations.
6. Mark internal mutation APIs that accept only `conversation_id` as deprecated
   with a notice that they will be removed in the next version. Public conversation
   APIs may retain `conversation_id` as a parameter but must resolve and authorize
   the full identity from request context.
7. Add structured security audit events for denied access.
8. Require model dispatch and governed persistence boundaries to reject missing, stale,
   mismatched, or caller-supplied authorization decisions.

## Repository Touchpoints

- `backend/agents/agent_run_manager.py`
- `backend/agents/create_agent_info.py`
- `backend/apps/agent_app.py`
- `backend/apps/conversation_management_app.py`
- `backend/services/conversation_management_service.py`
- `backend/database/conversation_db.py`
- New event-log, artifact, and lifecycle modules from W5-W9

## Tests

- Collision tests use identical conversation IDs across tenants and users.
- Authorization tests cover reads, writes, deletes, restore, and artifact access.
- Single-owner tests reject sharing and ownership-transfer requests, prove shared-agent
  or tenant-shared-memory access does not grant session access, and prove audited
  operator privileges do not mutate the session owner.
- Concurrency tests prove locks are identity-qualified.
- Cleanup tests prove deleting one identity leaves all colliding identities untouched.
- Static checks or targeted repository tests reject new bare-ID context mutation APIs.
- Negative integration tests prove SDK/client identity and authorization assertions
  cannot authorize model dispatch or governed persistence.
- Subagent identity tests prove subagent sessions inherit parent tenant/user and
  conversation_id.
- Recursive delegation tests prove subagents cannot create sub-subagents.
- Subagent authorization tests prove subagent permissions are determined by its own
  agent configuration.

## Rollout and Definition of Done

Dual-key in-memory state briefly while logging mismatches, then switch to the full
identity and remove legacy keys. Existing conversations receive an internal W5 session
during migration. W4 is done when every context-state mutation requires authorized
`ContextIdentity`, unsupported sharing/transfer fails explicitly, and collision/security
suites pass.
