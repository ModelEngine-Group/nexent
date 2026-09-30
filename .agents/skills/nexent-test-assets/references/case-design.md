# D1-D5 case design

Use `test/schemas/test-case.schema.json` as the exact file contract.

| Stage | Primary proof | Required boundary |
| --- | --- | --- |
| D1 | Backend unit, SDK unit, frontend component | Isolated behavior; no real external service |
| D2 | API and protocol contract | Request, response, headers, schema, status, compatibility |
| D3 | Runtime integration | Real local Nexent services and a declared external profile |
| D4 | Fixed Playwright user journey | Ordered user actions, per-step observations, final business result |
| D5 | Security, reliability, performance, deployment | Risk, condition/load, metric, threshold, recovery |

Priority expresses business and regression risk and does not select the stage. Each case proves one coherent behavior. Steps and expected results must be executable without guessing. Include forbidden side effects when failure could mutate state, leak data, invoke downstream services, or contaminate another tenant or session.

A2A requires applicable cases at D1-D5, including discovery, registration or publishing, binding, invocation, and failure recovery journeys. OAuth and CAS journeys remain policy-skipped.
