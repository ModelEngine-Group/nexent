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

A2A coverage can include discovery, registration or publishing, binding, invocation, and failure recovery at their necessary proving stages. A bug affecting one A2A behavior does not require generating Cases for all capabilities or all five stages. OAuth and CAS journeys remain policy-skipped.
