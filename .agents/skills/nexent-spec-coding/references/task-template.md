# Task Template

## Usage guide

Create or update `task.md` (singular) according to [SPEC maintenance guidance](spec-maintenance-guide.md). Keep this fixed filename inside a SPEC directory whose name uses a registered level-1 module, an optional registered level-2 module, and a 2-to-5-word feature description. Keep prior task/evidence history when updating an existing SPEC; identify the current change and its ACs. Required sections must remain. Conditional tasks are mandatory when their trigger applies; omit irrelevant tasks rather than checking them off. Remove this guide and replace placeholders in the generated document.

| Section | Requirement | When / what to write |
| --- | --- | --- |
| D1 Tests | Required | Implement designed case IDs before corresponding production behavior |
| Implementation | Required | Dependency-ordered production tasks mapped to D1 cases and ACs |
| SPEC Maintenance Tasks | Conditional | Missing-baseline reconstruction or delta integration |
| Later-layer Verification | Required | Applicable cross-task and system verification after D1 passes |
| Acceptance Traceability | Required | One row per AC linking design, code, tests, evidence and result |
| Completion Check | Required | All required ACs pass and documents reflect delivered behavior |
| Deployment / Migration | Conditional | Design requires rollout, migration or compatibility work |
| Execution Notes | Optional | Useful blockers, deviations or execution context |

Within D1 Tests, include every case ID designed in design.md and the smallest/affected-group commands. Feature implementation follows its corresponding tests. Within Later-layer Verification, API checks are required for changed HTTP behavior, browser checks for frontend interactions, and real-service/runtime checks for model or Agent changes. See verification-guide.md; irrelevant layers require a reason for N/A.

Use numbered groups and `- [ ] X.Y` checkboxes. Each task must state how completion is verified. Reference relevant AC IDs; setup tasks can explain their supporting role. Include separate verification tasks for broader integration/system checks. Test creation remains explicit work; do not duplicate the same check merely to fill a group. Mark a checkbox only after its completion condition is met.

Before finalizing tasks, resolve questions that change scope, design or task breakdown. Keep design rationale in `design.md` and AC definitions in `proposal.md`. This adapts [OpenSpec's task guidance](https://github.com/Fission-AI/OpenSpec/blob/main/schemas/spec-driven/schema.yaml); OpenSpec itself uses `tasks.md`.

# Tasks — <Feature Name>

## 1. SPEC Maintenance Tasks

<Conditional. For a missing/incomplete baseline, add reconstruction and review tasks before implementation, checking whole-feature coverage and code/test evidence. For delta work, add a post-verification task to integrate approved changes into the named baseline and related design, check conflicts, and record integration status while retaining history. Place each task in dependency order and number it with the appropriate group. Do not convert all baseline observations into current-change test obligations or mark unrun historical checks PASS.>

## 2. D1 Tests

- [ ] 2.1 <Implement designed test case IDs before production behavior; bind IDs in test metadata and run the smallest group to confirm the expected failure when feasible> [UT-BE-area-001] [AC-001]
- [ ] 2.2 <Conditional: when a meaningful pre-implementation failure cannot be produced, record the concrete constraint and retain and implement the designed case> [UT-BE-area-001] [AC-001]

## 3. Implementation

- [ ] 3.1 <Implement the minimum approved production change and run all associated D1 case IDs; every assertion and forbidden-side-effect check must pass> [UT-BE-area-001] [AC-001]

## 4. Later-layer Verification

- [ ] 4.1 <Run the complete affected D1 group after all related implementation tasks and record case-level results> [AC-001]
- [ ] 4.2 <Run applicable API/browser/runtime or other system scenario after D1 passes; record command, assertion and evidence> [AC-001]

<Add only triggered API, browser, internal, real-model, embedding or Agent scenarios. Model/Agent verification must use the actual runtime and required Langfuse evidence.>

## 5. Acceptance Traceability

| AC | Design | Code areas | D1 case IDs / later scenarios | Evidence | Result |
| --- | --- | --- | --- | --- | --- |
| AC-001 | <section / D-ID> | <planned then actual paths> | <tests and required proof surfaces; N/A reasons> | <planned evidence then sanitized commands/results/artifact paths/trace IDs> | PENDING |

Use PENDING before execution, PASS when all required proofs pass, FAIL for a failed assertion, and BLOCKED for missing prerequisites or required evidence. N/A applies only to an irrelevant verification layer with a reason; it does not pass or remove a required AC. Keep failed evidence until understood and link rerun results. Every current-change AC in proposal.md must appear here and reference its baseline/delta requirement. Preserve older AC rows and evidence as history with their original scope/status; do not reset or claim them as rerun. Baseline observations outside current acceptance remain explicitly unverified where appropriate.

## 6. Completion Check

- [ ] 6.1 Verify every in-scope Scenario has implemented and executed D1 case IDs; no required case is missing, skipped, xfailed or failing, and no P0/P1 case is skipped or expected failure.
- [ ] 6.2 Verify every required AC is PASS with linked D1 and later-layer evidence.
- [ ] 6.3 Verify required tests and runtime checks pass and report exact commands/scenarios and counts.
- [ ] 6.4 Confirm the SPEC or change directory follows the canonical module naming rule, then review changed files for scope and verify proposal.md, design.md and task.md match the delivered implementation.
- [ ] 6.5 Record approval or authorized self-review and any approved deviations; report remaining risks and unverified checks explicitly.
- [ ] 6.6 Verify the selected SPEC maintenance mode is complete; for reconstruction review whole-feature coverage and evidence, and for deltas confirm baseline/design integration and retained delta history.

## 7. Deployment / Migration

<Conditional. Add numbered checkboxes from the approved migration/rollback plan, with completion checks. Place this group before any tasks that depend on it and renumber groups accordingly.>

## 8. Execution Notes

<Optional. Blockers, approved deviations and supporting context. Reference existing decisions and evidence rather than copying them.>
