# Lightweight Bugfix Design

Use this template when a bug's owning capability has no usable SPEC. With an existing SPEC, reuse its sections and associations instead of creating a competing design. Follow the document repository and naming rules in [spec-maintenance-guide.md](spec-maintenance-guide.md).

Describe the complete coherent capability's final expected behavior, including its normal path and directly related boundaries. Keep this documentation scope separate from the current fix and execution scope. Do not create proposal.md or task.md just to fill out a document set.

Reuse the requirement design's `D1-D5 Test Design` matrix and `Acceptance Traceability` columns. Link real Feature, rule and Case IDs. Structured assets own the complete case steps and assertions; this document summarizes their relationships. Record relevant missing coverage without automatically generating it. `N/A` means a stage is irrelevant; `GAP` means a relevant behavior has no known Case; `UNKNOWN` means the baseline is unavailable or the association is unconfirmed. GAP/UNKNOWN are document annotations, not Case IDs or passing results.

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

## D1-D5 Test Design

| Feature / rule | D1 | D2 | D3 | D4 | D5 | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| <linked Feature/rule ID> | <linked Case ID or annotation> | <Case ID or annotation> | <Case ID or annotation> | <Case ID or annotation> | <Case ID or annotation> | <per-Case reuse/strengthen/add/regression-only/unaffected; evidence and profiles> |

<Inventory the known coverage of the defined capability, including relevant retained behavior. Retrieve candidates through SPEC associations, Feature rules, Case steps/assertions and script/API references, then read them to confirm coverage. A shared module name alone is insufficient impact evidence. Explain why a new Case or proof layer is necessary; zero new Cases is valid. Unknown or deferred coverage does not become required work solely to fill a matrix column.>

## Test Implementation Strategy

<Which Case contracts, primary scripts and execution.yaml bindings need changes and why. Reuse correct existing scripts unchanged for regression-only Cases. Preserve IDs and use existing machine configuration/asset helpers. List the current-fix execution selection separately from the full coverage inventory; synchronize it with the bug change record.>

## Acceptance Traceability

| AC | Design | Code areas | Formal case IDs | Evidence | Result |
| --- | --- | --- | --- | --- | --- |
| AC-001 | <section/decision> | <actual paths> | <selected Case IDs> | <sanitized commands and local artifacts> | PENDING |

<Use PENDING/PASS/FAIL/BLOCKED. Update this table after execution. Link failed reproduction and rerun evidence; do not fabricate results. Existing task.md can remain the evidence owner if it already exists.>

## Limitations and Deferred Coverage

<Optional: unavailable baseline, unconfirmed peripheral behavior or unrelated historical coverage gaps, with their effect on this fix. Material uncertainty about this fix's expected behavior must be resolved.>
