# Acceptance Verification Guide

## Required records

Before implementation, record affected feature IDs, business rules, acceptance criteria and required D1-D5 case contracts. During execution, record exact commands, environment profile, version, observed results and evidence paths. Keep results in `task.md` traceability and formal run artifacts; do not write execution state back into the case contract.

## Verification rules

- Run schema and traceability validation before product implementation.
- After product implementation, add or update fixed scripts and manifest entries for affected automated cases.
- A case passes only when all expected results and forbidden-side-effect assertions pass.
- Missing, unimplemented, skipped or expected-failure required cases remain incomplete. Required P0/P1 cases cannot be accepted that way.
- Keep product, environment, provider, asset and test-implementation failures distinguishable.
- If implementation reveals a requirement change, revise the requirement and structured case contract explicitly; never silently weaken assertions.
- Legacy UT may supply transition evidence but cannot satisfy formal D1-D5 manifest coverage.

## Choose the proof surface

| Stage | Required proof surface |
| --- | --- |
| D1 | Isolated function, SDK or component execution |
| D2 | Running API/protocol boundary and contract assertions |
| D3 | Integrated runtime/provider path with observable state and cleanup |
| D4 | Playwright browser journey and final business outcome |
| D5 | Risk-specific security, reliability, performance or deployment check |

Use all applicable stages for mixed changes. Mocks provide deterministic primary coverage. Optional real-smoke profiles prove selected real-provider integrations and remain separately identified.

## Evidence and status

- Tie each artifact to acceptance criteria and formal case IDs.
- Redact keys, authorization headers, cookies, tokens, private prompts and sensitive user data.
- Prefer textual results and local artifact paths. D4 retains screenshots/traces only for failures unless a case requires otherwise.
- Use `PENDING`, `PASS`, `FAIL` and `BLOCKED`. A completed implementation task never implies acceptance.
- A missing prerequisite is `BLOCKED`, not `N/A`. `N/A` requires an irrelevance reason.

## Model, Agent and external-provider checks

Use logical profiles instead of machine-specific values. Verify the actual Nexent runtime path, controlled input, downstream behavior, tool/provider interaction and final observable result. Record sanitized correlation or trace IDs where required. A successful HTTP status alone does not prove Agent behavior.

A2A can be proved at D2 protocol, D3 integration, D4 full journey and D5 fault/security layers as applicable. OAuth/CAS remains skipped by policy until that scope changes.

## Closeout

Run affected tests, the unified asset validator and deterministic Excel regeneration/check. Confirm every automated affected case has a valid manifest binding and that only changed/incremental entries were regenerated. Preserve historical cases and evidence unless explicitly retired with rationale.
