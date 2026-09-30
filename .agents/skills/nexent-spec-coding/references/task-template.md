# Task Template

## Usage guide

Create or update `task.md` according to [SPEC maintenance guidance](spec-maintenance-guide.md). The dependency order is formal test design, product implementation, fixed test implementation and case-local binding, local verification, then source/view closeout. Use numbered groups and checkboxes. Do not merge Legacy UT obligations into formal D1-D5 coverage.

This template applies to full requirement/change sets and existing task documents. A bug without a usable SPEC keeps the same Acceptance Traceability columns in its lightweight design.md and does not require a separate task.md. Reuse correct existing contracts/scripts without artificial edits. A coverage inventory is broader than the current-fix verification selection.

# Tasks — <Feature Name>

## 1. Formal Test Asset Design

- [ ] 1.1 Confirm affected feature contracts and business rules; update only changed or missing contracts. [AC-001]
- [ ] 1.2 Reuse, strengthen or add structured cases at necessary proving stages, with explicit assertions and impact reasons. Zero additions is valid. [AC-001]
- [ ] 1.3 Run the design-phase unified validator and regenerate Excel before product implementation. [AC-001]

## 2. Product Implementation

- [ ] 2.1 Implement approved product behavior without changing the case contract to match implementation quirks. [AC-001]

## 3. Fixed Test Implementation

- [ ] 3.1 Implement new/strengthened D1-D5 scripts after stable interfaces exist; reuse correct existing scripts for regression. [AC-001]
- [ ] 3.2 Add or update `execution.yaml` for only affected Case directories; regenerate derived hashes. [AC-001]
- [ ] 3.3 For a bug fix, retain a focused regression reproduction; an earlier reproduction script is allowed when it helps prove the defect. [AC-001]

## 4. Verification

- [ ] 4.1 Run the smallest affected case selection and record exact results. [AC-001]
- [ ] 4.2 Run selected regression Cases and required profiles; broaden only for evidenced caller or risk boundaries. [AC-001]
- [ ] 4.3 Regenerate the Excel view and run the unified test-asset validator. [AC-001]

## 5. Acceptance Traceability

| AC | Design | Code areas | Formal case IDs | Evidence | Result |
| --- | --- | --- | --- | --- | --- |
| AC-001 | <section / decision> | <actual paths> | <D1-D5 IDs> | <commands, counts, artifact paths> | PENDING |

Use `PENDING`, `PASS`, `FAIL` or `BLOCKED`. `N/A` applies only to an irrelevant verification layer with a recorded reason. Preserve failed evidence and link reruns.

## 6. Completion Check

- [ ] 6.1 Every affected requirement and business rule has validated structured cases at every required stage.
- [ ] 6.2 Every automated affected Case has a valid case-local binding and executable fixed script.
- [ ] 6.3 No required P0/P1 case is missing, skipped, expected failure or unimplemented.
- [ ] 6.4 The generated Excel view matches structured assets and was not manually maintained.
- [ ] 6.5 Proposal, design, tasks, product behavior and formal assets agree; remaining risks are explicit.

## 7. Deployment / Migration

<Conditional. Add approved rollout, compatibility and rollback tasks.>

## 8. Execution Notes

<Optional. Record blockers, deviations and sanitized evidence references.>
