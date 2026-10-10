# Task Template

## Usage guide

Create or update `task.md` according to [SPEC maintenance guidance](spec-maintenance-guide.md). The dependency order is behavior/test-responsibility design, product and traditional UT implementation, applicable formal scripts/bindings, local verification of both suites, then source/view closeout. Use numbered groups and checkboxes. Keep traditional UT permanently maintained and outside formal D1-D5 coverage; do not require artificial edits to both suites or all five layers.

This template applies to full requirement/change sets and existing task documents. A bug without a usable SPEC keeps the same Acceptance Traceability columns in its lightweight design.md and does not require a separate task.md. Reuse correct existing contracts/scripts without artificial edits. A coverage inventory is broader than the current-fix verification selection.

# Tasks — <Feature Name>

## 1. Formal Test Asset Design

- [ ] 1.1 Confirm affected feature contracts and business rules; update only changed or missing contracts. [AC-001]
- [ ] 1.2 Reuse, strengthen or add structured cases at necessary proving stages, with explicit assertions and impact reasons. Zero additions is valid. [AC-001]
- [ ] 1.2a Assess traditional UT separately: success/boundary/error/regression intentions and reuse/strengthen/add; justify non-behavior exemptions. Preserve existing D1. [AC-001]
- [ ] 1.3 Run the design-phase unified validator with --require-ut-change for the current product Change and --require-acceptance-case for added/acceptance-modified automated Cases; regenerate Excel before product implementation. [AC-001]

## 2. Product Implementation

- [ ] 2.1 Implement approved product behavior without changing the case contract to match implementation quirks. [AC-001]
- [ ] 2.2 Implement or demonstrate adequate traditional UT; keep it outside formal Case bindings. For bugs, retain regression detection and pre-fix evidence where feasible. [AC-001]

## 3. Fixed Test Implementation

- [ ] 3.1 Implement new/strengthened D1-D5 scripts after stable interfaces exist; reuse correct existing scripts for regression. [AC-001]
- [ ] 3.2 Add or update `execution.yaml` for only affected Case directories; regenerate derived hashes. [AC-001]
- [ ] 3.3 For a bug fix, retain a focused regression reproduction; an earlier reproduction script is allowed when it helps prove the defect. [AC-001]
- [ ] 3.4 Check affected formal acceptance obligations against actual collected tests and assertions, not just script presence or hashes; record completeness gaps. [AC-001]

## 4. Verification

- [ ] 4.1 Run the smallest affected case selection and record exact results. [AC-001]
- [ ] 4.1a Run relevant traditional UT locally before a product-code PR; record commands/results/blockers separately. CI reruns its configured set. [AC-001]
- [ ] 4.2 Run selected regression Cases and required profiles; broaden only for evidenced caller or risk boundaries. [AC-001]
- [ ] 4.3 Regenerate Excel and run the implementation validator with the same strict current-change flags; confirm actual UT selectors and formal test bindings. [AC-001]

## 5. Acceptance Traceability

| AC | Design | Code areas | Traditional UT | Formal case IDs | Evidence | Result |
| --- | --- | --- | --- | --- | --- | --- |
| AC-001 | <section / decision> | <actual paths> | <actual selectors or justified N/A> | <D1-D5 IDs or justified N/A> | <separate UT/formal results, artifact paths> | PENDING |

Use `PENDING`, `PASS`, `FAIL` or `BLOCKED`. `N/A` applies only to an irrelevant verification layer with a recorded reason. Preserve failed evidence and link reruns.

## 6. Completion Check

- [ ] 6.1 Every current required AC has appropriate UT and/or formal proof at its required boundary; no five-stage quota or mandatory edits to both suites.
- [ ] 6.2 Every automated affected Case has a valid case-local binding and executable fixed script.
- [ ] 6.3 No required P0/P1 case is missing, skipped, expected failure or unimplemented.
- [ ] 6.4 The generated Excel view matches structured assets and was not manually maintained.
- [ ] 6.5 Proposal, design, tasks, product behavior and formal assets agree; remaining risks are explicit.
- [ ] 6.6 Relevant traditional UT passed locally or a justified non-behavior exemption is recorded; blockers are not passes. Formal execution and acceptance completeness are distinct. No GitHub required-check setup is claimed from local evidence.

## 7. Deployment / Migration

<Conditional. Add approved rollout, compatibility and rollback tasks.>

## 8. Execution Notes

<Optional. Record blockers, deviations and sanitized evidence references.>
