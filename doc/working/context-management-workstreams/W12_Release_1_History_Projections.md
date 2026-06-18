# W12: Release 1 History Projections

## Objective

Build the Release 1 subset of `HistoryProjector` on top of the W5 execution event
log: `chat_projection`, `resume_projection`, and `model_context_projection`.

W12 is the implementation slice split out of P1. It gives Release 1 bounded,
purpose-specific views without waiting for Working Memory, memory-candidate, memory,
and full audit projections. W5 remains the durable source of truth; W12 projections
are rebuildable derived views.

W12 is successful when richer W5 events can be persisted without increasing active
model context unless W13/W10 explicitly select the corresponding `ContextItem`s.

## Why This Workstream Is Necessary

W5 makes execution history durable, but durability alone is not enough. If later
agent runs, lifecycle APIs, and final model requests read raw W5 events directly,
Nexent will either flood prompts with operational detail or keep relying on the old
UI transcript path that cannot support reliable resume.

W12 is the minimum projection layer needed to make W5 useful in Release 1:

- It protects prompt size. Rich W5 events can include tool calls, visible progress,
  retries, errors, snapshots, and lifecycle markers. Only a bounded model-context view
  should become eligible for W13/W10.
- It preserves chat compatibility. Current UI behavior still needs user-facing message,
  unit, source, and attachment shapes while the durable event log becomes authoritative.
- It enables restart and worker handoff. A later run needs active objectives,
  constraints, pending actions, completed tool state, and ambiguous-effect blockers,
  not just the previous assistant final answer.
- It gives W13 and W10 stable units of work. Policy selection and final fit need typed
  `ContextItem`s with source lineage, authority hints, lifecycle status, and minimum
  fidelity instead of ad hoc `{role, content}` strings.
- It contains P1 scope. The useful Release 1 slice can ship without waiting for
  Working Memory, memory-candidate, memory, and full audit projections.

Without W12, W5 risks becoming only an audit log: valuable for storage, but not
directly usable for bounded context assembly, lifecycle recovery, or model dispatch.

## Current Codebase Gap

The current codebase has several implicit, purpose-specific history paths, but no
single backend-owned projection layer.

### Current Behavior

- Chat persistence stores user prompts, assistant final answers, streamed assistant
  units, search sources, and images in conversation tables.
- The frontend sends conversation history back with each agent request.
- Backend run preparation converts that flat history into model messages and synthetic
  SDK history objects.
- The SDK reconstructs an assistant turn primarily from final-answer text rather than
  a durable sequence of typed execution events.
- Context assembly and compression operate over runtime structures and summarized
  history, not over a canonical projection from W5 events.
- Memory construction and UI history each use their own ad hoc view of the same user
  conversation.

### Gap Against W12 Target

| W12 target | Current gap |
| --- | --- |
| W5 event log is the source for chat, resume, and model-context views | Current run input still depends on caller-provided history and compatibility conversation records. |
| `chat_projection` rebuilds user-visible history from W5 events | Current chat history is stored directly as UI-oriented rows, not derived from typed execution events. |
| `resume_projection` exposes active task state after restart | Current history lacks durable run/step/tool state, pending action status, and ambiguous-effect blockers. |
| `model_context_projection` emits bounded `ContextItem`s | Current model context is assembled from flat messages, summaries, memory results, and runtime components without a stable projection contract. |
| Projection decisions are reason-coded and replayable | Current inclusion/exclusion behavior is scattered across frontend history loading, backend conversion, ContextManager strategies, and memory code. |
| Raw execution history can grow without growing prompt size | Current richer persistence would risk either being ignored by model context or being injected without a clear bounded view. |

### Practical Consequences If Not Fixed

- Restart recovery can only approximate state from visible chat history.
- Tool-call/result continuity cannot be reliably reconstructed.
- W7 lifecycle APIs have no stable derived view to inspect, restore, or reset.
- W13 cannot make deterministic policy decisions over typed context candidates.
- W10 cannot guarantee final fit from the exact set of eligible history/context items.
- Adding more W5 event detail may increase storage value but not agent reliability.

## Scope and Non-Goals

W12 owns:

- Reading authorized W5 events in session order.
- Applying active-lineage semantics for resume and model-context views.
- Producing current chat compatibility records from W5 events.
- Producing resumable state records for restart, worker handoff, and later turns.
- Producing bounded `ContextItem` candidates for W13 policy selection and W10 final fit.
- Emitting reason-coded projection decisions.

W12 does not:

- Append, mutate, or delete W5 events.
- Implement the full P1 projection suite.
- Build `working_memory_projection`, `memory_candidate_projection`,
  `memory_projection`, or full `audit_projection`.
- Decide final prompt membership, ranking, budgets, or representation upgrades.
  W13 and W10 own those decisions.
- Generate reduced or compressed representations. W8 and W6 own reduction and
  compaction.
- Persist long-term memories. W13 and memory services decide and execute memory
  operations.
- Implement full P2 cache validation or P5 governance.

## Dependencies

| Dependency | Required contract |
| --- | --- |
| W4 | `ContextIdentity(tenant_id, user_id, conversation_id)` authorization and ownership resolution. |
| W5 | `agent_session`, ordered `agent_event_index`, typed `agent_event_data`, canonical event reader, and `compression.snapshot` event type. |
| W7 | Consumes W12 resume/model-context projections for restore, reset, inspect, and resume behavior. |
| W13 | Consumes W12 `ContextItem`s for policy selection and memory-operation decisions. |
| W10 | Consumes W12/W13 selected context candidates for final fit and provider dispatch. |

P1 full projections remain deferred until W12 is stable and the relevant consumers
need them.

## Projection Registry

Release 1 supports exactly three projection purposes:

| Purpose | Consumer | Output |
| --- | --- | --- |
| `chat_projection` | Current conversation APIs and chat UI | User-facing message/unit/source records compatible with existing response shapes. |
| `resume_projection` | Run preparation after restart, worker handoff, or a later user turn | Active objective, constraints, pending/completed actions, tool status, lifecycle state, and ambiguous-effect blockers. |
| `model_context_projection` | W13 and W10 | Bounded `ContextItem` candidates and optional token estimates. |

Unsupported purposes fail with `unsupported_projection_purpose`; they do not fall back
to raw history.

## Projection Request and Result Contract

Trusted backend callers resolve W4 identity and W5 `agent_session_id` before invoking
the projector. Clients cannot authorize a projection by supplying internal IDs.

```text
project_release1(
  identity,
  agent_session_id,
  through_event_seq,
  purpose,
  projection_version,
  authorization_scope,
  options
) -> ProjectionResult
```

Request rules:

- `through_event_seq` is inclusive. Omitted means the latest committed event.
- `purpose` must be one of the three Release 1 registry values.
- `projection_version` identifies transformation behavior and schema.
- `authorization_scope` is resolved by backend code and cannot be widened by options.
- `options` is typed per projection and cannot bypass active-lineage or authorization
  rules.

`ProjectionResult` contains:

| Field | Meaning |
| --- | --- |
| `agent_session_id` | W5 session projected. |
| `through_event_seq` | Last source sequence considered. |
| `active_baseline_seq` | Active-state baseline after restore/reset semantics, when applicable. |
| `purpose` | Projection registry value. |
| `projection_version` | Projector implementation/schema version. |
| `records` | Ordered typed output records for chat/resume purposes. |
| `context_items` | Stable candidates for model-context purpose; empty for chat unless needed by compatibility code. |
| `source_ranges` | Source event ranges read and inactive ranges excluded. |
| `decisions` | Inclusion, exclusion, grouping, transformation, and redaction decisions with stable reason codes. |
| `token_estimates` | Optional estimates only; W10 performs final token counting. |
| `fingerprint` | Canonical digest of source ranges, relevant event content, projection version, and options. |
| `replay_status` | `complete` or `partial_after_erasure`. |

Required failures:

- `identity_not_found`
- `access_denied`
- `session_not_found`
- `invalid_event_range`
- `unsupported_event_schema`
- `unsupported_projection_purpose`
- `unsupported_projection_version`
- `invalid_projection_options`
- `artifact_unavailable`
- `projection_invariant_violation`

## Shared Projection Pipeline

Every W12 projection runs the same ordered stages:

1. Resolve W4 identity and W5 `agent_session_id`.
2. Validate `through_event_seq`.
3. Read W5 events in ascending `event_seq` through the canonical reader.
4. Apply minimal authorization and redaction status available in the current release.
5. Resolve active lineage for resume and model-context projections.
6. Transform events by purpose.
7. Build `ContextItem`s when purpose requires them.
8. Record reason-coded decisions.
9. Compute fingerprint and return the typed result.

W12 consumes only W5 canonical current-form events. Event-schema upcasting remains a
W5 responsibility.

## Active-Lineage Rules

- `chat_projection` preserves user-visible linear history by default. Restore/reset
  lifecycle markers may be exposed as metadata, but historical visible messages remain
  visible unless a later product policy explicitly hides them.
- `resume_projection` and `model_context_projection` apply active lineage.
- A `restore.applied` event makes the restored covered sequence the active baseline.
  Events between that restored sequence and the restore event remain source history
  but are excluded from active state with `inactive_after_restore`.
- A `reset.applied` event resets declared derived-state categories. Later events
  rebuild those categories; unaffected categories remain active.
- A session marked `partial_after_erasure` must surface that replay status in every
  projection.

## Event-to-Projection Mapping

Release 1 must cover at least these W5 event families:

| Event family | Chat projection | Resume projection | Model-context projection |
| --- | --- | --- | --- |
| `user.input` | User message | Active objective and explicit constraints | Recent user-turn candidate |
| `run.started` | Usually hidden | Run/config state | Agent/config metadata only when needed |
| model visible progress | User-visible unit when supported by UI policy | Action status | Recent complete-step candidate |
| `tool.call.*` | Hidden by default | Pending/completed tool action | Paired with result when relevant |
| `tool.result.*` | Optional visible source/unit | Result status and pointer/summary | Paired result summary or pointer |
| `run.failed`, cancellation, retry | Optional status | Recovery/retry state and blockers | Include only when relevant |
| `final.answer` | Assistant final answer | Completed outcome | Recent-turn candidate |
| `compression.snapshot` | Hidden by default | Recovery acceleration reference | Bounded summary candidate |
| `restore.applied`, `reset.applied` | Optional lifecycle marker | Active-lineage change | Active-lineage change |

Unknown registered event types must never be silently ignored. A projector must handle
the type, explicitly exclude it with a registered reason, or fail with
`unsupported_event_schema`.

## ContextItem Contract

`model_context_projection` emits `ContextItem`s, not final prompt messages.

Each `ContextItem` contains:

- Stable item ID.
- Item type and source event references or contiguous source range.
- Ownership scope and authorization tags.
- Authority tier hint for W13.
- Recency and lifecycle status.
- Minimum-fidelity requirement.
- Optional recompute cost and token estimate.
- Optional pointer or summary reference.

W12 may estimate token counts for planning, but W10 remains the final source of token
truth for provider dispatch.

## Migration and Compatibility

- Existing conversation APIs continue returning the current chat response shapes while
  W12 is introduced.
- Compatibility projection writes are idempotent by W5 `event_id`.
- Caller-provided `AgentRequest.history` is treated as migration compatibility input,
  not resumable source truth.
- During rollout, W12 can run in shadow mode and compare generated chat projection
  output with current conversation tables.
- If W12 is disabled, existing chat persistence remains available but W7 restart and
  W10 model-context reconstruction claims cannot be enabled.

## Required Deliverables and Phases

- Deliver projection registry, request/response schemas, shared projector pipeline,
  three Release 1 projectors, reason-code registry, compatibility adapters, metrics,
  and inspection hooks.
- Phase through shadow `chat_projection`, enforced `chat_projection`, `resume_projection`,
  and then `model_context_projection` integration with W13/W10.

## Implementation Plan

1. Define Release 1 projection schemas and reason codes.
2. Implement shared W5 event reader adapter and active-lineage resolver.
3. Implement `chat_projection` in shadow mode and compare against current UI history.
4. Make chat compatibility output idempotent from W5 events.
5. Implement `resume_projection` including ambiguous-effect blockers.
6. Implement `model_context_projection` and `ContextItem` emission.
7. Wire W7 resume/restore/inspect flows to W12 projections.
8. Wire W13/W10 to consume W12 `ContextItem`s.
9. Add metrics for projection latency, event count, output size, exclusion reasons,
   and shadow mismatch rate.

## Repository Touchpoints

- W5 event-log repository and canonical reader.
- New history projection service/module.
- `backend/services/conversation_management_service.py`
- Existing conversation API compatibility code.
- `backend/agents/create_agent_info.py`
- `sdk/nexent/core/agents/agent_context.py`
- W7 lifecycle service.
- W13 policy service and W10 fit pipeline integration points.

## Tests and Definition of Done

- `chat_projection` preserves current UI behavior from W5 events.
- `resume_projection` reconstructs active continuation state after restart.
- `model_context_projection` emits bounded `ContextItem` candidates for W13/W10.
- Restore/reset lineage tests prove inactive events are excluded from active views but
  remain available to authorized audit paths.
- Unknown event tests prove no event is silently ignored.
- Idempotency tests prove compatibility projection writes do not duplicate records.
- Authorization tests prove non-owner reads are denied without leaking session existence.
- Shadow-mode tests compare W12 chat output against existing conversation history.
- Performance tests measure projection latency by event count and output size.
- W12 is done when W7 can resume from W5 events and W10 can receive bounded model
  context candidates without reading raw history directly.
