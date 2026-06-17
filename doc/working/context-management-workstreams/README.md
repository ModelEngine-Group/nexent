# Context Management Workstream Development Specifications

This folder expands the workstreams in
[`context-management-production-plan.md`](../context-management-production-plan.md)
into implementation-ready development specifications. The production plan remains
the source of truth for roadmap priority and cross-workstream architecture.

## How to Use These Documents

- Assign one directly responsible engineer or squad per W-ID.
- Resolve open design decisions before implementation starts.
- Treat dependencies and contracts as integration requirements, not suggestions.
- Add links to ADRs, migrations, pull requests, dashboards, and test evidence as work proceeds.
- Do not mark a workstream complete until its definition of done and release evidence are satisfied.

## Implementation-Ready Standard

Every W-ID specification must make the following executable without requiring the
implementing squad to invent missing architecture:

1. State objective, ownership boundaries, dependencies, and non-goals.
2. Define typed input/output, persistence, versioning, and failure contracts.
3. Describe runtime ordering, concurrency, idempotency, authorization, and recovery.
4. Name required deliverables and concrete repository integration points.
5. Divide delivery into safe phases with compatibility, migration, and rollback behavior.
6. Define observable reason codes, metrics, and operator/debugging evidence.
7. Specify unit, integration, property, migration, security, chaos, and replay tests as applicable.
8. End with measurable completion gates that prove bypass paths and legacy authority are removed.

If a workstream delegates behavior to another W-ID, it must name the boundary and must
not duplicate or weaken the delegated contract.

## Workstream Index

### Active Workstreams (by implementation priority)

| Priority | ID | Topic | Module | Depends on | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | [W1](W1_Correct_Model_Token_Capacity_Configuration.md) | Correct Model Token-Capacity Configuration | Model Capacity and Request Safety | None | Done |
| 2 | [W2](W2_Output_and_Safety_Capacity_Reserve.md) | Output and Safety Capacity Reserve | Model Capacity and Request Safety | W1 | Done |
| 3 | [W14](W14_Prompt_Cache_Aware_Assembly.md) | Prompt-Cache-Aware Assembly | Quality and Efficiency | None | **Moved to Phase 1** |
| 4 | [W3](W3_Tenant_and_User_Isolation.md) | Tenant and User Isolation | Durable Session State and Lifecycle | None | Active |
| 5 | [W4](W4_Structured_Agent_Execution_Event_Log.md) | Structured Agent Execution Event Log | Durable Session State and Lifecycle | W3 identity contract | Bug fix first |
| 6 | [W12](W12_Reliable_Governed_Compaction.md) | Reliable Governed Compaction | Context Shaping and Compaction | W2, W15, W7 | Reliability prioritized |
| 7 | [W7](W7_Full_Session_Lifecycle_APIs.md) | Full Session Lifecycle APIs | Durable Session State and Lifecycle | W4-W5, W6 | Active |
| 8 | [W9](W9_Progressive_Component_Reduction.md) | Progressive Component Reduction | Context Shaping and Compaction | W8 | Active |
| 9 | [W13](W13_Context_Quality_and_Reliability_SLOs.md) | Context Quality and Reliability SLOs | Quality and Efficiency | Measures all workstreams | Active |
| 10 | [W15](W15_Guaranteed_Context_Fit.md) | Guaranteed Context Fit | Model Capacity and Request Safety | W1, W2; integrates W8-W10 | Active |
| 11 | [W17](W17_Capacity_Suggestion_On_Model_Add.md) | Capacity Suggestion on Model Add | Model Capacity and Request Safety | W1 catalog; resolves CM-031 | Post-acceptance |

### Tentatively Deferred Workstreams

| ID | Topic | Module | Deferral scope | Activation trigger |
| --- | --- | --- | --- | --- |
| [W5](W5_Raw_History_and_Active_Context_Separation.md) | Raw History and Active Context Separation | Durable Session State and Lifecycle | Full scope | W4 event log completion |
| [W6](W6_Complete_Cache_Validation_and_Versioning.md) | Complete Cache Validation and Versioning | Durable Session State and Lifecycle | Full version registry; minimal fix now | W4 + W5 + W8 completion |
| [W8](W8_Unified_Context_and_Memory_Policy.md) | Unified Context and Memory Policy | Context Shaping and Compaction | Full policy engine; pre-step now | W4 + W5 completion |
| [W10](W10_Context_Pollution_and_Large_Output_Control.md) | Context Pollution and Large Output Control | Context Shaping and Compaction | Artifact system; quick fixes now | W4 + W11 completion |
| [W11](W11_Trust_Provenance_Redaction_and_Retention.md) | Trust, Provenance, Redaction, and Retention | Governance and Privacy | Full governance; minimal fix now | Compliance or customer demand |

### Retired

| ID | Topic | Reason |
| --- | --- | --- |
| ~~W7~~ | ~~Durable Multi-Worker Context State~~ | Retired: merged into W4 as `compression.snapshot` events |

## Shared Engineering Rules

1. Raw execution events are durable source-of-truth records; projections and checkpoints are rebuildable.
2. Every context-state operation uses the full `ContextIdentity`.
3. Every model request passes through capacity resolution, budgeting, policy selection, and final fit.
4. Hidden chain-of-thought is neither required nor persisted.
5. All persisted payloads are redacted and governed before storage.
6. Context selection and lifecycle decisions emit stable reason codes and observable metrics.
7. Existing chat UI behavior remains compatible during migration.
8. Durable execution history is linear and branchless. Existing public APIs keep
   integer `conversation_id`; internal execution logging uses `agent_session_id`.
