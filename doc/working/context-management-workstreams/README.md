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
| 3 | [W3](W3_Prompt_Cache_Aware_Assembly.md) | Prompt-Cache-Aware Assembly | Quality and Efficiency | None | **Moved to Phase 1** |
| 4 | [W4](W4_Tenant_and_User_Isolation.md) | Tenant and User Isolation | Durable Session State and Lifecycle | None | Active |
| 5 | [W5](W5_Structured_Agent_Execution_Event_Log.md) | Structured Agent Execution Event Log | Durable Session State and Lifecycle | W4 identity contract | Bug fix first |
| 6 | [W12](W12_Release_1_History_Projections.md) | Release 1 History Projections | Durable Session State and Lifecycle | W5 event log | New W after W5 |
| 7 | [W13](W13_Unified_Context_and_Memory_Policy.md) | Unified Context and Memory Policy | Context Shaping and Compaction | W5, W12 | New W before W8/W10 |
| 8 | [W6](W6_Reliable_Governed_Compaction.md) | Reliable Governed Compaction | Context Shaping and Compaction | W2, W10, W7 | Reliability prioritized |
| 9 | [W7](W7_Full_Session_Lifecycle_APIs.md) | Full Session Lifecycle APIs | Durable Session State and Lifecycle | W4, W5, W12 | Active |
| 10 | [W8](W8_Progressive_Component_Reduction.md) | Progressive Component Reduction | Context Shaping and Compaction | W13 | Active |
| 11 | [W9](W9_Context_Quality_and_Reliability_SLOs.md) | Context Quality and Reliability SLOs | Quality and Efficiency | Measures all workstreams | Active |
| 12 | [W10](W10_Guaranteed_Context_Fit.md) | Guaranteed Context Fit | Model Capacity and Request Safety | W1, W2; integrates W8, W13 | Active |
| 13 | [W11](W11_Capacity_Suggestion_On_Model_Add.md) | Capacity Suggestion on Model Add | Model Capacity and Request Safety | W1 catalog; resolves CM-031 | Post-acceptance |

### Tentatively Deferred Workstreams (P-Series)

P-series workstreams are Plan/Proposed documents that remain deferred until their dependencies complete. They use P-numbering to distinguish them from implementation-ready W-series specifications.

| ID | Topic | Module | Deferral scope | Activation trigger |
| --- | --- | --- | --- | --- |
| [P1](P1_Raw_History_and_Active_Context_Separation.md) | Raw History and Active Context Separation | Durable Session State and Lifecycle | Full projection suite beyond W12 | W12 completion plus consumer demand |
| [P2](P2_Complete_Cache_Validation_and_Versioning.md) | Complete Cache Validation and Versioning | Durable Session State and Lifecycle | Full version registry | W5 + W12 + W13 + P5 completion |
| [P3](P3_Unified_Context_and_Memory_Policy.md) | Unified Context and Memory Policy Extensions | Context Shaping and Compaction | Extensions beyond W13 | W13 completion plus advanced policy demand |
| [P4](P4_Context_Pollution_and_Large_Output_Control.md) | Context Pollution and Large Output Control | Context Shaping and Compaction | Artifact system and output-limit quick fixes | Customer demand, large-output incidents, or W5 + P5 completion |
| [P5](P5_Trust_Provenance_Redaction_and_Retention.md) | Trust, Provenance, Redaction, and Retention | Governance and Privacy | Full governance stack | Compliance, legal, or customer demand |

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
