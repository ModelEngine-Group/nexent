# W6: Raw History and Active Context Separation

## Objective

Build versioned, purpose-specific projections from W5 execution events so durable
history can become richer without increasing the active model prompt by default.

## Projection Contract

Create a `HistoryProjector` interface:

```text
project(identity, branch_head_seq, purpose, policy_version) -> ProjectionResult
```

`ProjectionResult` contains ordered typed records, source event ranges, projection
version, token estimates where relevant, exclusions with reason codes, and a
deterministic fingerprint. Projectors are pure/rebuildable except for explicitly
versioned materialized-view caches.

## Required Projections

| Projection | Consumer and content |
| --- | --- |
| `chat_projection` | UI-facing user messages and final answers |
| `resume_projection` | Unresolved tasks, actions, decisions, and tool state |
| `model_context_projection` | Budgeted summaries and recent complete steps |
| `memory_projection` | Policy-approved stable facts/preferences |
| `working_memory_projection` | Current goals, constraints, decisions, open work, entities, tool state |
| `memory_candidate_projection` | Sanitized facts/corrections/verified evidence for policy review |
| `audit_projection` | Complete authorized event record |

## ContextItem Model

Project executable state into stable `ContextItem` records. Each item includes identity,
type, scope, source event IDs, provenance, authority tier, lifecycle status, dirty
state, recompute cost, and minimum-fidelity requirements. Representations are separate
records so W11 can select full, compressed, structured, or pointer forms without
changing source truth.

Working Memory is authoritative only for active-task state confirmed by policy. It is
derived and rebuildable, may be explicitly edited through W9, and records edits as new
events rather than mutating history.

## Implementation Plan

1. Define projector and `ContextItem` schemas plus versioning rules.
2. Implement shared event reader, authorization filter, and canonical ordering.
3. Implement chat projection first and compare it with the current UI transcript.
4. Implement resume, model-context, Working Memory, memory-candidate, and audit views.
5. Add materialization only where profiling proves it necessary.
6. Emit selection/exclusion decisions and projection latency metrics.
7. Ensure policy-version changes can rebuild projections from raw events.

## Repository Touchpoints

- New backend projection/context-item modules
- W5 event-log repository
- `backend/services/conversation_management_service.py`
- `backend/agents/create_agent_info.py`
- `sdk/nexent/core/agents/agent_context.py`
- `sdk/nexent/core/agents/summary_cache.py`
- `sdk/nexent/memory/`

## Tests and Definition of Done

- Golden-event fixtures validate every projection.
- Increasing raw tool/event detail does not increase model-context size unless selected.
- Rebuild tests reproduce materialized projections from the event log.
- Working Memory survives restart and preserves explicit constraints and open work.
- Authorization tests prove audit and shared-state projections do not leak data.
- W6 is done when backend-owned projections serve UI, resume, model context, memory,
  Working Memory, and audit consumers without deleting or rewriting source events.

