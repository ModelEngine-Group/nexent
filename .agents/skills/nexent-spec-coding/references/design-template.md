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

## Traditional UT + D1-D5 Test Responsibilities

<List Feature IDs, business rules and known coverage for the defined functional scope. Link Case IDs and the behavior proved at each stage. Notes distinguish reuse, strengthen, add, regression-only and unaffected Cases, with impact reasons. Put complete executable case fields in structured test assets. N/A means irrelevant; GAP means relevant but uncovered; UNKNOWN means the baseline/association is unavailable. GAP/UNKNOWN are document annotations, not Case IDs. Distinguish coverage inventory from the current execution selection; do not fill five columns by inventing new Cases. Include profiles where applicable.>

| Feature / rule / AC | Traditional UT | D1 | D2 | D3 | D4 | D5 | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <ID> | <unit behavior + reuse/strengthen/add> | <case IDs or N/A> | <case IDs or N/A> | <case IDs or N/A> | <case IDs or N/A> | <case IDs or N/A> | <distinct proof boundary / profile / exclusion reason> |

<Assess UT for every product change. Do not require all stages or edits to both suites. UT remains outside the formal registry. Preserve existing D1; new D1 proves component collaboration beyond UT, D3 proves actual runtime integration. State real versus substituted dependencies. A unit-only AC can be proved by UT; higher-boundary ACs require their selected formal evidence.>

## Test Implementation Strategy

<Describe traditional UT success/error/boundary/regression obligations and applicable formal scripts separately. UT selectors are confirmed after implementation; formal scripts/bindings follow stable interfaces except focused bug reproduction. For each changed formal acceptance obligation, explain actual tests/assertions and collection/execution checks, not just file/ID existence. State relevant local UT commands and affected Case execution. Existing D1 stays; completeness gaps are reported separately from script PASS.>

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
