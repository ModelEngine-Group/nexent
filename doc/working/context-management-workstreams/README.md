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

## Workstream Index

| ID | Topic | Module | Depends on |
| --- | --- | --- | --- |
| [W1](W1_Correct_Model_Token_Capacity_Configuration.md) | Correct Model Token-Capacity Configuration | Model Capacity and Request Safety | None |
| [W2](W2_Output_and_Safety_Capacity_Reserve.md) | Output and Safety Capacity Reserve | Model Capacity and Request Safety | W1 |
| [W3](W3_Guaranteed_Context_Fit.md) | Guaranteed Context Fit | Model Capacity and Request Safety | W1, W2; integrates W10-W12 |
| [W4](W4_Tenant_and_User_Isolation.md) | Tenant and User Isolation | Durable Session State and Lifecycle | None |
| [W5](W5_Structured_Agent_Execution_Event_Log.md) | Structured Agent Execution Event Log | Durable Session State and Lifecycle | W4 identity contract |
| [W6](W6_Raw_History_and_Active_Context_Separation.md) | Raw History and Active Context Separation | Durable Session State and Lifecycle | W5 |
| [W7](W7_Durable_Multi_Worker_Context_State.md) | Durable Multi-Worker Context State | Durable Session State and Lifecycle | W4-W6 |
| [W8](W8_Complete_Cache_Validation_and_Versioning.md) | Complete Cache Validation and Versioning | Durable Session State and Lifecycle | W5-W7 |
| [W9](W9_Full_Session_Lifecycle_APIs.md) | Full Session Lifecycle APIs | Durable Session State and Lifecycle | W5-W8 |
| [W10](W10_Unified_Context_and_Memory_Policy.md) | Unified Context and Memory Policy | Context Shaping and Compaction | W5-W6 contracts |
| [W11](W11_Progressive_Component_Reduction.md) | Progressive Component Reduction | Context Shaping and Compaction | W10 |
| [W12](W12_Context_Pollution_and_Large_Output_Control.md) | Context Pollution and Large Output Control | Context Shaping and Compaction | W5, W10, W11 |
| [W13](W13_Reliable_Governed_Compaction.md) | Reliable Governed Compaction | Context Shaping and Compaction | W2, W3, W7 |
| [W14](W14_Trust_Provenance_Redaction_and_Retention.md) | Trust, Provenance, Redaction, and Retention | Governance and Privacy | Governs W5-W12 |
| [W15](W15_Context_Quality_and_Reliability_SLOs.md) | Context Quality and Reliability SLOs | Quality and Efficiency | Measures all workstreams |
| [W16](W16_Prompt_Cache_Aware_Assembly.md) | Prompt-Cache-Aware Assembly | Quality and Efficiency | W3, W10, W11 |

## Shared Engineering Rules

1. Raw execution events are durable source-of-truth records; projections and checkpoints are rebuildable.
2. Every context-state operation uses the full `ContextIdentity`.
3. Every model request passes through capacity resolution, budgeting, policy selection, and final fit.
4. Hidden chain-of-thought is neither required nor persisted.
5. All persisted payloads are redacted and governed before storage.
6. Context selection and lifecycle decisions emit stable reason codes and observable metrics.
7. Existing chat UI behavior remains compatible during migration.

