# Post-development test backfill

Use when product code already exists and the request is to add or complete tests. Do not restart product development, generate a Case per function, or assume every Feature needs D1. This route supplies missing proof; it does not excuse inadequate requirements or treat current code as the expected contract.

## Establish scope and ownership

1. Confirm the requested behavior and code version. Read available requirements/SPEC, API contracts, Feature rules and bug history; inspect code to understand actual interfaces and collaborators. Resolve material intent conflicts before writing assertions. If intent cannot be established, record the uncertainty instead of certifying the implementation as correct.
2. Search existing Features and formal Cases. Reuse the owning Feature ID; update its definition only when the contract is missing/incomplete or genuinely changes. Create a Feature only for a distinct capability not already cataloged. Every new formal Case needs a valid owning Feature; tests do not live only in changes/.
3. Read relevant traditional UT and formal scripts, including actual inputs, assertions, parameter variants and mocked boundaries. A matching filename, coverage percentage or test title is not sufficient proof. Distinguish verified gaps from an unavailable baseline.

## Decide what to add

Record a compact proof-gap table in an existing SPEC design/task document or the Change's notes; no new schema or full proposal/design/task set is required for test-only backfill:

| Behavior / AC | Existing proof and actual selector | Boundary and remaining gap | Action and reason |
| --- | --- | --- | --- |
| Empty model name is rejected | Existing UT asserts the rejection | Isolated validation; no gap | Reuse UT; no new D1 |
| Configuration merge preserves user settings | UT covers only individual helpers | Component collaboration is unproved | Add D1 with real parsing/validation/merge |
| Cross-tenant model updates are rejected | No API-boundary assertion found | Running API authorization | Add D2, not a D1 copy of a permission helper |
| Saved model can be invoked by an Agent | Existing D3 proves the runtime path | No identified new gap | Execute existing D3 |

Choose reuse, strengthen, add or justified irrelevance for each required proof boundary. Missing prerequisites are blockers, not irrelevance. Put isolated validation, arithmetic, local branches and error conversion in traditional UT through nexent-python-tests. Zero new D1 or zero new formal Cases is valid when UT and existing formal proof are sufficient. Necessary API/runtime/journey/risk evidence cannot be replaced by UT.

For every proposed new D1, apply the admission questions and overlap comparison in case-design.md. Record the component contract, real internal collaborators, substituted boundaries, additional evidence beyond existing UT, and why D2/D3 is not the intended proof surface. If the only benefit is another directory, Case ID or functional report entry, do not add it. Preserve all existing D1; this is not authority to delete, retire or relabel overlapping baseline Cases.

## Record, implement and verify

- Pure test backfill uses a schema-valid `change_type: test-fix` under `test-e2e/changes/test-fixes/`. Keep an existing requirement/bug record when completing that delivery; genuine product behavior changes or fixes follow their corresponding lifecycle. Do not fabricate a requirement or bug merely to add coverage.
- Record only affected Feature/Case IDs. If all work belongs to traditional UT, empty formal Case changes are valid with `no_case_change_reason`; UT is never bound in execution.yaml. Use existing traditional_ut fields where applicable and put proof-gap/admission rationale in notes or SPEC prose, not invented schema keys.
- Define formal contracts before writing their fixed scripts, even though product code already exists. Add acceptance obligations for every new or acceptance-modified automated Case. Run the design validator with `--require-acceptance-case <ID>` for those Cases; include `--require-ut-change <Change-ID>` when the current Change also changes product code. Do not invent selectors or passing evidence.
- Implement only the missing assertions and necessary execution bindings. Reuse sufficient tests unchanged; collect and execute actual selectors. Follow test-implementation.md and acceptance-integrity.md for formal Cases, and nexent-python-tests for UT. A newly found product defect is not permission to silently change the product or weaken expectations; report it and route an authorized fix through bugfix mode.
- Run the implementation validator with the same applicable strict flags, regenerate derived views when formal assets change, and execute affected formal Cases plus relevant UT. Report results separately with local evidence and unresolved blockers. If no formal assets changed, do not generate artificial Case/Feature edits or formal runs.

Structural validation does not decide whether tests are semantically duplicated or complete. The implementing workflow must inspect actual assertions and retain the proof-gap decisions; no new human approval, CI or Daily mutation is implied.
