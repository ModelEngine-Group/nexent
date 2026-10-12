# Acceptance Verification Guide

## Required records

Before implementation, record affected feature IDs, business rules, acceptance criteria and selected Case IDs. During execution, record exact commands, environment profile, version, observed results and evidence paths. Keep results in `task.md` traceability or the lightweight bugfix design's identical table, plus formal run artifacts; do not write execution state back into the case contract.

## Verification rules

- Run schema and traceability validation before product implementation.
- After product implementation, update scripts/bindings only when their contract, assertions or execution setup needs changes; existing regression Cases may run unchanged.
- A case passes only when all expected results and forbidden-side-effect assertions pass.
- Missing, unimplemented, skipped or expected-failure required cases remain incomplete. Required P0/P1 cases cannot be accepted that way.
- Keep product, environment, provider, asset and test-implementation failures distinguishable.
- If implementation reveals a requirement change, revise the requirement and structured case contract explicitly; never silently weaken assertions.
- Traditional UT is a permanent product-PR obligation: run relevant UT locally and record actual selectors/results; CI reruns its configured UT set. Maintain success/error/boundary and defect-regression assertions for changed unit behavior. Existing adequate tests may be reused; a non-behavior exemption needs a reason. Missing execution is BLOCKED, not an exemption.
- UT can prove a unit acceptance requirement but cannot count as formal Case execution or substitute for necessary higher-boundary proof. Report UT separately from D1-D5 and frontend coverage separately from Python coverage.

## Choose the proof surface

| Stage | Required proof surface |
| --- | --- |
| Traditional UT | Isolated unit/domain-rule behavior, boundary/error/regression assertions |
| D1 (new Cases) | Component contract with real internal collaboration and controlled external boundaries |
| D2 | Running API/protocol boundary and contract assertions |
| D3 | Integrated runtime/provider path with observable state and cleanup |
| D4 | Playwright browser journey and final business outcome |
| D5 | Risk-specific security, reliability, performance or deployment check |

Use all applicable stages for mixed changes. Mocks provide deterministic primary coverage. Optional real-smoke profiles prove selected real-provider integrations and remain separately identified.

Keep all existing D1 Cases/scripts and type labels, including unit-oriented overlap. New D1 must add necessary component evidence beyond UT; D3 proves inter-component/service/protocol runtime flow. Do not infer stages from function calls or mocks. Follow acceptance-integrity.md for affected formal obligations: script execution status, obligation mapping and semantic completeness are separate. An unreviewed legacy script PASS is not certified full acceptance.

For bugs, current-fix ACs and evidence-backed regression impact determine applicability. A full functional coverage matrix does not require all listed Cases or all five stages to execute. Global asset validation checks consistency without authorizing generation of historical coverage. Missing/unavailable baseline coverage is a limitation, not an N/A proof surface or an automatic test-generation task.

## Evidence and status

- Tie artifacts to acceptance criteria and either actual UT selectors or formal Case IDs, keeping the two result sets separate.
- Redact keys, authorization headers, cookies, tokens, private prompts and sensitive user data.
- Prefer textual results and local artifact paths. D4 retains screenshots/traces only for failures unless a case requires otherwise.
- Use `PENDING`, `PASS`, `FAIL` and `BLOCKED`. A completed implementation task never implies acceptance.
- A missing prerequisite is `BLOCKED`, not `N/A`. `N/A` requires an irrelevance reason.

## Model, Agent and external-provider checks

Use logical profiles instead of machine-specific values. Verify the actual Nexent runtime path, controlled input, downstream behavior, tool/provider interaction and final observable result. Record sanitized correlation or trace IDs where required. A successful HTTP status alone does not prove Agent behavior.

A2A can be proved at D2 protocol, D3 integration, D4 full journey and D5 fault/security layers as applicable. OAuth/CAS remains skipped by policy until that scope changes.

## Closeout

Run affected tests, the unified asset validator and deterministic Excel regeneration/check. Confirm every automated affected Case has a valid case-local binding. Regenerate derived views from the complete authoritative Case set; modify only affected source Case directories. Preserve historical Cases and evidence unless explicitly retired with rationale.
