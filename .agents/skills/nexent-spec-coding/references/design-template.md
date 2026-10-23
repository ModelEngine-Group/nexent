# Design Template

## Usage guide

Create or update `design.md` according to [SPEC maintenance guidance](spec-maintenance-guide.md). Reference `proposal.md` for motivation, scope and acceptance criteria. Define formal D1-D5 case contracts before product implementation; implement fixed automation after stable interfaces exist. Use [D1-D5 test design guidance](test-design-guide.md) and the `nexent-test-assets` skill. Structured test assets, not this prose or Excel, are the executable source of truth.

# Design — <Feature Name>

## Context

<Describe the current flow, relevant code boundaries, constraints and evidence. For an undocumented bug, reconstruct the owning feature sufficiently to distinguish current behavior, intended behavior and the defect.>

## Decisions

### D-001 — <Decision>

<State the chosen approach, rationale, related acceptance criteria and meaningful alternatives.>

## Proposed Design

<Describe target control/data flow, component responsibilities, interfaces, state changes and failure handling. Preserve unaffected behavior explicitly.>

## D1-D5 Test Design

<List affected feature IDs, business rules and applicable stages. For each stage, identify case IDs and the requirement behavior proved. Put complete executable case fields in structured test assets. Explain every normally relevant stage that is N/A. Include mock and optional real-smoke profiles where applicable; never include secrets or developer-local paths.>

| Feature / rule | D1 | D2 | D3 | D4 | D5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| <ID> | <case IDs or N/A> | <case IDs or N/A> | <case IDs or N/A> | <case IDs or N/A> | <case IDs or N/A> | <reason / profile> |

## Test Implementation Strategy

<Describe intended repository boundaries and frameworks for fixed scripts. Scripts and manifest entries are implemented after product code stabilizes, except for an optional focused bug reproduction. State how IDs will be bound and how affected cases will run locally. Keep Legacy UT separate.>

## Risks / Trade-offs

<State known implementation, testing or operational risks and mitigations.>

## Interface / Data Changes

<Conditional. Describe signatures, requests/responses, events, schemas, configuration, validation and compatibility.>

## Migration / Rollback

<Conditional. Describe deployment order, migration, compatibility, rollback and irreversible limits.>

## Model / Agent Verification

<Conditional. Identify actual runtime paths, logical provider profiles, deterministic scenarios, downstream assertions and trace evidence. Never record secret values.>

## Open Questions

<Optional. Resolve questions that change behavior, scope or task breakdown before implementation.>
