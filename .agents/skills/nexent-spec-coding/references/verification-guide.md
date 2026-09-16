# Acceptance Verification Guide

## Usage and required records

Read this guide when writing design.md's later-layer verification strategy and task.md's verification tasks, before verification, and at closeout. Use test-design-guide.md for D1 case design and the test-first gate. AC definitions and pass conditions belong in proposal.md. Record the strategies in design.md and maintain results/evidence only in task.md's Acceptance Traceability table. Evidence files may be separate; link them from that table.

| Content | Requirement |
| --- | --- |
| AC coverage, applicable proof surfaces, pass assertions and planned evidence | Required before implementation |
| One traceability row per current-change AC with baseline/delta requirement, design, code, D1 case IDs, later scenarios, evidence and result | Required throughout execution |
| Commands/scenarios, environment, data, time, version and observed result | Required for executed verification |
| API/browser/model/Agent/embedding checks | Conditional on the changed behavior below |
| Migration/rollback checks | Conditional on the approved design |
| Screenshots, videos, extended logs or extra diagrams | Optional unless an AC explicitly requires them |

An optional artifact cannot replace required assertions. A triggered proof surface is mandatory. Explain why omitted layers are irrelevant in design.md or the traceability row; never omit required verification because it is inconvenient or unavailable. Complete and execute the required D1 cases before later-layer verification, except for diagnostic runs.

## D1 execution gate

Implement designed D1 tests before their corresponding production behavior. Preserve stable case IDs in repository test metadata. Run the smallest relevant group to obtain a meaningful expected failure when feasible, implement the minimum production change, rerun that group, then run the complete affected D1 group. A passing coverage percentage cannot replace case assertions.

A D1 case passes only when every listed expected result and forbidden-side-effect assertion passes. Missing, unimplemented, skipped or expected-failure cases remain incomplete unless the approved SPEC changes. No P0/P1 case may be skipped or expected failure at acceptance. Keep product, test and environment failures distinguishable. If the implementation changes a requirement, Scenario, contract or boundary, revise and review design.md's matrix before continuing.

D1 proves isolated unit/component behavior only. Its result cannot be reused as proof for API, browser, real-model, Agent-runtime, security, reliability, migration or full-system acceptance.

## SPEC mode and baseline verification

Use [SPEC maintenance guidance](spec-maintenance-guide.md) to identify new work, refactor, direct bug-fix update, delta or baseline reconstruction. Before implementation, check baseline references, current-change ACs and any complete delta requirement blocks. Refactors verify preserved behavior; fixes verify the defect's correction and affected regression paths. When feasible, demonstrate the reproduction fails before the fix and passes after it; otherwise record why before/after execution is unavailable and retain a regression assertion.

For a missing-baseline bug, review reconstructed whole-feature coverage against concrete code/tests, including unchanged main paths and overall design. Distinguish observed implementation, intended behavior and unverified inference. This documentation review is required but does not substitute for runtime acceptance of the fix. Do not require unrelated feature changes or claim all reconstructed behavior was executed. Record the current acceptance scope and keep historical ACs/evidence intact; any baseline AC selected for this change receives all required proof.

For delta work, verify operation targets exist, MODIFIED blocks preserve unaffected scenarios, and current ACs reference the proposed requirements. At closeout, check approved/verified requirements were integrated into the baseline and affected design, with integration status and preserved delta history in task.md. Missing required integration or unresolved conflicts prevents completion.

## Choose the proof surface

| Changed behavior | Required primary proof |
| --- | --- |
| Pure business or internal logic | Unit/integration test at a stable interface |
| Backend HTTP contract | Running service and real curl/wget requests |
| Frontend interaction | Playwright in a real browser |
| Model inference | Real configured model call through Nexent and Langfuse generation/span |
| Agent runtime or tool flow | Real Agent run and step-level Langfuse trace |
| Embedding behavior | Real embedding call through Nexent, downstream assertion and corresponding Langfuse evidence |
| Data/config migration or deployment transition | Approved migration/compatibility checks and rollback validation where applicable |

Use all applicable surfaces for mixed changes. Add lower-level tests as needed. Source inspection, mocks or builds do not replace primary proof. Required D1 cases pass before functional verification, except diagnostic execution.

## Evidence and status rules

- Tie each artifact to AC IDs. Record exact commands or reproducible scenarios, environment shape, test data, timestamp and relevant version/commit; capture expected versus observed results and test counts where applicable.
- Redact keys, authorization headers, cookies, tokens, private prompts and sensitive user data. Keep enough sanitized detail to reproduce the check without storing secrets.
- Prefer text results and artifact paths/trace IDs. Keep failed evidence until understood and attach rerun results. Distinguish expected warnings from failures.
- Use PENDING before execution, FAIL for failed assertions and BLOCKED for missing prerequisites or mandatory evidence. PASS requires all mandatory proofs for that AC to pass. A completed implementation checkbox does not imply AC acceptance.
- N/A applies only to an irrelevant layer with a recorded reason, never to an entire required AC. Missing credentials, services or traces are BLOCKED, not N/A. Report mixed FAIL/BLOCKED checks explicitly even if the row has one summary result.
- Mark task checkboxes only after their completion checks pass. Completion requires every required AC to be PASS; report unverified criteria and remaining risks explicitly.

## Browser verification — conditional

For changed frontend interactions, start the application using discovered repository commands and exercise the actual user journey. Assert visible state, relevant requests/responses and persistence. Cover loading, empty/error, disabled, permission and refresh states where relevant. Inspect browser console errors. Screenshots, video and reports are optional unless required by an AC or needed to demonstrate the result.

## API verification — conditional

For changed HTTP behavior, call real running endpoints. Verify status codes, response schema/payload and relevant side effects. Cover authentication/permission, headers, idempotency and errors where applicable. Query a read surface or logs to confirm side effects. Use disposable or explicitly authorized data. Record sanitized requests, responses and assertions.

## Internal verification — conditional

For internal-only changes, exercise the nearest stable interface with unit/integration tests. Cover regressions, boundaries and failure paths named by ACs. Mock only unrelated external boundaries; do not mock away the behavior being accepted. API/browser checks may be N/A with an explanation.

## Model, embedding and Agent verification — conditional

1. Check applicable variable presence without displaying values. LLM uses MODEL_URL, MODEL_API_KEY, MODEL_NAME. Embedding uses EMBED_MODEL_URL, EMBED_MODEL_API_KEY, EMBED_MODEL_NAME.
2. Start the actual Nexent runtime path and execute controlled, reproducible scenarios mapped to ACs. Real-model output need not be byte-identical; assert the specified behavioral contract.
3. Locate the matching Langfuse trace using correlation IDs, session, metadata or time. Inspect inputs/assembled context, configuration, generations, tool arguments/results, intermediate states, parsing, errors and retries as relevant. Include latency/token usage when acceptance depends on them.
4. Compare relevant steps and final output with the AC. For embedding, assert the downstream use of the vectors as well as the real call.
5. Record sanitized trace IDs/links, step-level observations and pass/fail evidence in task.md. Missing, incomplete or mismatched mandatory traces block acceptance. Never count a successful HTTP response alone as proof of correct Agent behavior.

## Traceability record

Use the table from task-template.md; do not create a competing completion matrix. Every current-change AC must link its baseline/delta requirement, design, planned/actual code, D1 case IDs, later-layer scenarios, evidence and result. Preserve prior AC records separately with their original scope and results. In the case/scenario and evidence cells, identify applicable layers and their results, plus N/A reasons for omitted layers. During planning, evidence cells describe expected artifacts; during verification, replace those plans with actual references or an explicit pending/blocker explanation.

Keep proposal.md's AC definitions stable. If a criterion is invalid or requirements change, update and re-review the documents before changing implementation or acceptance expectations. Retain the approved deviation in task.md.
