# Design Template

## Usage guide

Create or update `design.md` according to [SPEC maintenance guidance](spec-maintenance-guide.md). Reference `proposal.md` for motivation, scope and acceptance criteria. Define formal D1-D5 case contracts before product implementation; implement fixed automation after stable interfaces exist. Use [D1-D5 test design guidance](test-design-guide.md) and the `nexent-test-assets` skill. Structured test assets, not this prose or Excel, are the executable source of truth.

For a bug with no usable SPEC, use [bugfix-design-template.md](bugfix-design-template.md), which shares the association matrix below. For an existing SPEC, retain its matrix and add only relevant updates. A matrix inventories coverage; it does not require every listed Case to change or run in the current change.

# Design — <Feature Name>

## Context

<Describe the current flow, relevant code boundaries, constraints and evidence. Preserve links to the current requirements and functional scope.>

## Decisions

### D-001 — <Decision>

<State the chosen approach, rationale, related acceptance criteria and meaningful alternatives.>

## Proposed Design

<Describe target control/data flow, component responsibilities, interfaces, state changes and failure handling. Preserve unaffected behavior explicitly.>

## D1-D5 Test Design

<List Feature IDs, business rules and known coverage for the defined functional scope. Link Case IDs and the behavior proved at each stage. Notes distinguish reuse, strengthen, add, regression-only and unaffected Cases, with impact reasons. Put complete executable case fields in structured test assets. N/A means irrelevant; GAP means relevant but uncovered; UNKNOWN means the baseline/association is unavailable. GAP/UNKNOWN are document annotations, not Case IDs. Distinguish coverage inventory from the current execution selection; do not fill five columns by inventing new Cases. Include profiles where applicable.>

| Feature / rule | D1 | D2 | D3 | D4 | D5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| <ID> | <case IDs or N/A> | <case IDs or N/A> | <case IDs or N/A> | <case IDs or N/A> | <case IDs or N/A> | <reason / profile> |

## Test Implementation Strategy

<Describe intended repository boundaries and frameworks for fixed scripts. Scripts and case-local execution bindings are implemented after product code stabilizes, except for an optional focused bug reproduction. State how IDs will be bound and how affected Cases will run locally. Keep Legacy UT separate.>

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
