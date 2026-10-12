# D1-D5 case design

Use the Case structure in `test-e2e/cases/<Case-ID>/case.yaml`. The validator checks its stage-specific contract against `test-e2e/infra/schemas/legacy/test-case.schema.json` after normalizing the single-Case wrapper; directory name and `case_id` must match.

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
