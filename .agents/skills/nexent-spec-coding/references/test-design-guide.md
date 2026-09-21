# D1-D5 Test Design Guide

Use this guide while writing or revising `design.md`. Formal Nexent acceptance assets are designed from requirements before product implementation and stored as structured feature and case files. Fixed automation scripts and manifest entries are implemented after product code exposes stable interfaces, except that a focused bug reproduction may be written earlier.

## Required design content

For every in-scope requirement or bug contract:

- assign or preserve a stable feature ID and observable business rules;
- select every required proving stage from D1 through D5;
- define independently verifiable cases with explicit preconditions, data, steps, expected results and forbidden side effects;
- identify mock and optional real-smoke profiles without embedding credentials or developer-local assets;
- record exclusions with a concrete reason rather than silently omitting a normally applicable stage.

Write formal assets through `nexent-test-assets`. Structured YAML/JSON files are the source of truth. Excel is a deterministic generated view and must not be edited as the source.

## Choose the proving stage

| Stage | Primary responsibility | Typical type |
| --- | --- | --- |
| D1 | Isolated unit or component behavior | `BE-UT`, `SDK-UT`, `FE-COMP` |
| D2 | API and protocol contracts | `API-IT`, `CONTRACT` |
| D3 | Integrated runtime and provider behavior | `AGENT-IT`, `INTEGRATION` |
| D4 | Complete browser user journeys | `E2E` |
| D5 | Security, reliability, performance and deployment risk | `SECURITY`, `RELIABILITY`, `PERFORMANCE`, `DEPLOYMENT` |

Use the lowest stage that proves a behavior, then add higher stages only when their boundary adds necessary evidence. Mixed features commonly need several stages. D1 success never establishes D2-D5 results.

## Case quality rules

- One case proves one concrete behavior or coherent journey outcome.
- Assertions derive from the requirement, not current implementation quirks.
- Preconditions and test data name logical assets or profiles, never absolute paths, credentials, generated runtime IDs or SQL file locations.
- Include forbidden-side-effect checks when relevant: no unintended persistence, provider call, cross-tenant leakage, stale-state overwrite, downstream execution or sensitive-data disclosure.
- D2 defines status, schema, error and compatibility contracts. D3 identifies integration boundaries, observations and cleanup. D4 uses a full actor journey and observable business result. D5 names the risk, conditions, metrics, thresholds and recovery expectation.
- A2A is eligible at every applicable stage, including D4 journeys. OAuth/CAS remains skipped by policy until that policy changes.
- Missing, skipped, expected-failure or unimplemented required cases are not passing cases.

## Lifecycle

1. During requirement or bug design, update the feature inventory and formal D1-D5 case contracts.
2. Run `python test/tools/validate_test_assets.py --phase design --generate-excel` before product implementation begins.
3. Implement product behavior.
4. Implement fixed scripts and manifest entries after interfaces stabilize. Bind every automated case ID to its implementation.
5. Run affected cases locally, then the applicable broader stage groups.
6. Run `python test/tools/validate_test_assets.py --phase implementation --generate-excel` before closeout.

Legacy implementation-oriented tests remain separate. They may continue to run during transition, but they are not formal D1-D5 assets and cannot satisfy formal case or manifest coverage.
