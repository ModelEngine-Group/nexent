# D1-D5 case design

Use the Case structure in `test-e2e/cases/<Case-ID>/case.yaml`. The validator checks its stage-specific contract against `test-e2e/infra/schemas/legacy/test-case.schema.json` after normalizing the single-Case wrapper; directory name and `case_id` must match.

## Case IDs and titles

New Cases use `<MODULE>-<SCENARIO>-<STAGE>-<NNN>`, for example
`AGENT-LIST-D1-003` or `MODEL-PERMISSION-D2-001`.

- Use uppercase ASCII letters/digits and hyphens. Include at least one module token and one scenario token before the stage; either label may contain more tokens. Reuse the owning capability's vocabulary rather than inventing a new prefix for each author or PR. The prefix need not literally equal the wrapper's `module` or the Feature ID.
- Use `D1` through `D5` immediately before a three-digit sequence `001` through `999`. The embedded stage must equal the Case's `stage`; select the stage by the proof boundary below, not by the existing prefix.
- Allocate an unused number within the same module/scenario/stage prefix after checking all existing Cases, including inactive history. Do not renumber to close gaps, reuse an ID for a different behavior, or put owners, dates, hash suffixes or tool-only prefixes in new IDs.
- Keep the ID globally unique and identical in the directory, `case.yaml` and `execution.yaml`. Keep IDs and existing selectors stable when repairing a Case. Do not bulk rename historical Cases to this format; a real change of proof boundary needs an explicit migration/traceability decision, not a silent rename or stage edit.
- Write a concise title as scenario/condition plus expected behavior, for example `模型不可用时禁止选择且不触发切换回调` or `Reject unavailable models without invoking the change callback`. Chinese or English is allowed; the validator rejects blank new titles but semantic clarity is a review obligation, not something a regex certifies.

`test-e2e/infra/config/case-naming-legacy.json` freezes only the historical IDs
that did not fit this format when the rule was introduced, anchored to its recorded
Git commit. A pinned content digest rejects changes even without Git history.
They retain their original IDs when edited. This is a compatibility
list, not another Case registry or an authoring output: never regenerate it from
current Cases or add new IDs to avoid the rule. Removed historical IDs may remain
reserved there. Both design and implementation validation enforce the policy,
including in a checkout without Git history or local generated views. The general
identifier Schema stays backward-compatible for Feature IDs and historical assets.

Primary script names remain framework-appropriate (`test.py`, `test.spec.ts`,
`test.test.tsx`, etc.); they do not need to repeat the Case ID. Bind the real file
and stable selector in `execution.yaml` and expose the Case ID in test metadata/title.

| Stage | Primary proof | Required boundary |
| --- | --- | --- |
| D1 (new Cases) | Component behavior and internal collaboration | Real internal policy/state/error paths; controlled external dependencies |
| D2 | API and protocol contract | Request, response, headers, schema, status, compatibility |
| D3 | Inter-component/service runtime integration | Actual runtime/configuration/protocol path and a declared external profile |
| D4 | Fixed Playwright user journey | Ordered user actions, per-step observations, final business result |
| D5 | Security, reliability, performance, deployment | Risk, condition/load, metric, threshold, recovery |

Priority expresses business and regression risk and does not select the stage. Each case proves one coherent behavior. Steps and expected results must be executable without guessing. Include forbidden side effects when failure could mutate state, leak data, invoke downstream services, or contaminate another tenant or session.

Traditional UT owns isolated function/class/domain-rule assertions under test/. Keep all existing D1 Cases, IDs, types and scripts unchanged unless an actual requirement or implementation gap is affected. BE-UT/SDK-UT remain compatible type labels for new component Cases; explain the component proof in unit_boundary rather than inventing a new type. No bulk migration or retirement is implied.

For each new layer, state the tested boundary, real execution, substituted dependencies and additional evidence. Calling functions is not a stage criterion. A direct substitute of a provider method in component code differs from calling a protocol Mock over the real product runtime. Do not mock the component's own behavior under test.

Example: quota UT proves unit conversion and threshold arithmetic; D1 executes the quota component's real ledger/strategy/error collaboration with a controlled storage adapter; D2 proves HTTP status/response/authentication; D3 proves the actual upload/storage/quota runtime integration. Agent tool D1 tests the invocation component's internal handling; D3 proves actual Agent/provider/tool message flow. Do not add D1 merely to repeat UT or D3 assertions.

## New D1 admission and overlap review

Before creating a new D1, read relevant UT and existing formal assertions and record:

1. The observable component contract, not a list of functions needing coverage.
2. Which internal collaborators and policy/state/error paths execute for real, and which external boundaries are controlled. Keep the collaboration under test real; do not mock every internal step into predefined returns.
3. The specific evidence missing from existing UT/formal tests. If existing tests sufficiently prove the required behavior at the same boundary, reuse them or add missing variants there rather than creating another Case.
4. Why this is component proof rather than a running API contract (D2) or inter-component/service/protocol runtime path (D3). Do not classify by language, framework, type label or mock count.

No Feature is required to have D1. UT plus necessary D2-D5 proof can be sufficient. Unit validation, arithmetic, isolated branches and error conversion belong primarily in traditional UT. Do not copy UT into a Case directory, invoke it through a formal wrapper or reproduce its assertions solely to increase functional Case counts.

Compare behavior/rule, input conditions, expected assertions and execution boundary. Matching all four with no additional necessary evidence is probable duplication. Matching the first three at a distinct required boundary is legitimate defense: UT can prove a permission helper while D2 proves the real endpoint enforces it. Names, files and overlapping code coverage alone cannot decide this. Record deliberate cross-layer overlap with its boundary/risk reason; do not remove essential API/runtime proof to reduce counts.

| Proposed test | Decision |
| --- | --- |
| Mock every internal step and repeat UT's empty-name rejection or helper call count | Reuse/strengthen UT; do not create D1 |
| Execute real configuration parsing, validation and merge to assert preservation of user settings through the component | D1 only if that contract needs additional proof |
| Call a deployed endpoint to verify status, authorization and payload | D2 |
| Run Agent configuration through actual provider/tool protocols and verify the runtime result | D3 |

Missing existing test access is UNKNOWN, not proof of a gap. For already-developed code, use test-backfill.md. Apply admission to new D1 only; retain existing D1 contracts/scripts and repair genuine gaps within the authorized scope rather than bulk deduplicating the baseline.

A2A coverage can include discovery, registration or publishing, binding, invocation, and failure recovery at their necessary proving stages. A bug affecting one A2A behavior does not require generating Cases for all capabilities or all five stages. OAuth and CAS journeys remain policy-skipped.

## Responsibility routing

Confirm the primary business domain when designing a Feature, before execution. Reuse the central `domains` and `feature_overrides` in `test-e2e/infra/config/report-ownership.yaml`; do not add owner names to each `case.yaml` or infer ownership from Git authors, stage, incidental keywords or a provider name.

For example, an editor workflow Feature can declare `AGENT-EDITOR-WORKFLOWS: agent_config` under `feature_overrides`; every associated Case inherits the domain's maintained contact. Use `case_overrides` when a specific Case proves another boundary (for example an AIDP retrieval journey or a real Gateway kernel isolation test). State the rationale in the test-fix/change record. Keep one primary contact; collaboration does not make ambiguous routing acceptable.

Active/planned Features and non-retired Cases must resolve uniquely during both validation phases. An unmapped new Feature fails even before it has Cases. Unknown domains, ambiguous rules and placeholder contacts are errors. Update central contacts for staff changes; do not rewrite historical `report-ownership.json` or journal/checkpoint results. The dashboard shows one contact from the versioned map while retaining original execution evidence internally.

Design checklist: identify the Feature; confirm its domain and primary proving boundary; reuse or add the central mapping; document any Case exception; run `python test-e2e/infra/tools/ownership_catalog.py --root .` and the normal design validator. The validator checks coverage, not the correctness of a human business-domain decision.
