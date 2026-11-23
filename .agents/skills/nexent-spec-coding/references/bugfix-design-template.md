# Lightweight Bugfix Design

Use this template when a bug's owning capability has no usable SPEC. With an existing SPEC, reuse its sections and associations instead of creating a competing design. Follow the document repository and naming rules in [spec-maintenance-guide.md](spec-maintenance-guide.md).

Describe the complete coherent capability's final expected behavior, including its normal path and directly related boundaries. Keep this documentation scope separate from the current fix and execution scope. Do not create proposal.md or task.md just to fill out a document set.

Reuse the requirement design's `Traditional UT + D1-D5 Test Responsibilities` matrix and `Acceptance Traceability` columns. Link real Feature/rule/Case IDs; keep UT intentions and later selectors in their separate column. Structured assets own formal case steps/assertions. Record missing coverage without generating unrelated history. `N/A` means irrelevant with a reason; `GAP` means applicable but uncovered; `UNKNOWN` means unavailable/unconfirmed. These are annotations, not test IDs or passes. Unavailable prerequisites are BLOCKED, not N/A.

Replace placeholders and remove this usage guide in the completed document.

# Design — <Capability Name>

## Context

<Bug/Change ID, reproduction, observed behavior, SPEC search scope and results. Separately record the availability/search scope of formal test assets. Cite relevant entry points, code symbols, existing tests and user/contract evidence. Distinguish intended behavior from observed implementation.>

## Functional Scope

<Capability purpose, included normal paths, inputs/outputs and directly related boundaries. Name related Feature IDs and business rules. Explain the functional boundary without expanding to unrelated module capabilities.>

## Proposed Design

<The capability's final normal flow, responsibilities, observable outputs, business rules, failure/edge behavior and compatibility. Mark retained behavior and this fix's behavior changes. Describe the necessary implementation approach; current code alone does not prove intended requirements.>

## Current Fix and Acceptance

<Root cause, direct/transitive impact through actual callers, current-fix scope and meaningful adjacent regression paths. Record why related behavior is unaffected when that limits scope.>

### AC-001 — <Observable correction>

- Given <reproduction precondition>
- When <action>
- Then <expected result and forbidden side effects>
- Verification <required proof boundary and pass condition>

<Include only current-fix acceptance and justified regressions. Retained behavior described above is not automatically a new AC.>

## Traditional UT + D1-D5 Test Responsibilities

| Feature / rule / AC | Traditional UT | D1 | D2 | D3 | D4 | D5 | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <linked ID> | <regression behavior; reuse/strengthen/add> | <Case ID or annotation> | <Case ID or annotation> | <Case ID or annotation> | <Case ID or annotation> | <Case ID or annotation> | <impact, distinct boundary, profiles and exclusions> |

<Inventory the known coverage of the defined capability, including relevant retained behavior. Retrieve candidates through SPEC associations, Feature rules, Case steps/assertions and script/API references, then read them to confirm coverage. A shared module name alone is insufficient impact evidence. Explain why a new Case or proof layer is necessary; zero new Cases is valid. Unknown or deferred coverage does not become required work solely to fill a matrix column.>

## Test Implementation Strategy

<Assess traditional UT for every product bug, retaining a test that detects the defect (reuse is valid with evidence). State formal contracts/scripts/bindings needing changes; reuse correct regression-only scripts. Preserve all existing D1 even if unit-oriented. New D1 proves component collaboration; D3 proves runtime integration. List relevant local UT and formal execution selections separately; align formal selection with the bug record. Apply acceptance-integrity.md to changed formal obligations.>

## Acceptance Traceability

| AC | Design | Code areas | Traditional UT | Formal case IDs | Evidence | Result |
| --- | --- | --- | --- | --- | --- | --- |
| AC-001 | <section/decision> | <actual paths> | <actual selectors or justified N/A> | <selected Case IDs or justified N/A> | <separate UT/formal commands and local artifacts> | PENDING |

<Use PENDING/PASS/FAIL/BLOCKED. Update this table after execution. Link failed reproduction and rerun evidence; do not fabricate results. Existing task.md can remain the evidence owner if it already exists.>

## Limitations and Deferred Coverage

<Optional: unavailable baseline, unconfirmed peripheral behavior or unrelated historical coverage gaps, with their effect on this fix. Material uncertainty about this fix's expected behavior must be resolved.>
