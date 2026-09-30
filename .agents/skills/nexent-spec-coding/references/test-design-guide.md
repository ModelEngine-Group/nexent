# D1-D5 Test Design Guide

Use this guide while writing or revising `design.md`. Formal Nexent acceptance assets are designed from requirements before product implementation and stored as case-local Feature and Case files. Fixed automation scripts and execution bindings are implemented after product code exposes stable interfaces, except that a focused bug reproduction may be written earlier.

## Required design content

For current-change requirements or bug acceptance, and justified regressions:

- assign or preserve a stable feature ID and observable business rules;
- select every required proving stage from D1 through D5;
- define independently verifiable cases with explicit preconditions, data, steps, expected results and forbidden side effects;
- identify mock and optional real-smoke profiles without embedding credentials or developer-local assets;
- record exclusions with a concrete reason rather than silently omitting a normally applicable stage.

Write formal assets through `nexent-test-assets`. Structured YAML/JSON files are the source of truth. Excel is a deterministic generated view and must not be edited as the source.

For bugfixes, follow the SPEC's existing Feature/rule/Case associations and check actual code impact. Without a usable SPEC, use the lightweight bugfix design's identical matrix. Search and read existing Cases before authoring. Distinguish reuse, strengthen, add, regression-only and unaffected coverage. Missing documentation or a baseline not present in this checkout is not evidence that all stages lack tests. Documentation may cover the full coherent capability while current-fix acceptance remains limited to the defect and justified regressions.

## Choose the proving stage

| Stage | Primary responsibility | Typical type |
| --- | --- | --- |
| D1 | Isolated unit or component behavior | `BE-UT`, `SDK-UT`, `FE-COMP` |
| D2 | API and protocol contracts | `API-IT`, `CONTRACT` |
| D3 | Integrated runtime and provider behavior | `AGENT-IT`, `INTEGRATION` |
| D4 | Complete browser user journeys | `E2E` |
| D5 | Security, reliability, performance and deployment risk | `SECURITY`, `RELIABILITY`, `PERFORMANCE`, `DEPLOYMENT` |

Use the lowest stage that proves a behavior, then add higher stages only when their boundary adds necessary evidence. Mixed features commonly need several stages. D1 success never establishes D2-D5 results.

No per-stage or per-bug count is required. Existing Cases may be sufficient with zero additions. Use parameterized variants when they prove the same contract; create distinct Case IDs for independent behavior or necessary independent proof. Every added layer needs a specific boundary/risk reason. Do not treat unrelated historical gaps in the functional inventory as this fix's tasks.

## Case quality rules

- One case proves one concrete behavior or coherent journey outcome.
- Assertions derive from the requirement, not current implementation quirks.
- Preconditions and test data name logical assets or profiles, never absolute paths, credentials, generated runtime IDs or SQL file locations.
- Include forbidden-side-effect checks when relevant: no unintended persistence, provider call, cross-tenant leakage, stale-state overwrite, downstream execution or sensitive-data disclosure.
- D2 defines status, schema, error and compatibility contracts. D3 identifies integration boundaries, observations and cleanup. D4 uses a full actor journey and observable business result. D5 names the risk, conditions, metrics, thresholds and recovery expectation.
- A2A is eligible at every applicable stage, including D4 journeys. OAuth/CAS remains skipped by policy until that policy changes.
- Missing, skipped, expected-failure or unimplemented required cases are not passing cases.

## Lifecycle

1. During design, confirm the Feature/Case associations and modify only changed or missing contracts.
2. Run `python test-e2e/infra/tools/validate_test_assets.py --phase design --generate` before product implementation begins.
3. Implement product behavior.
4. Implement new/strengthened scripts and update affected `execution.yaml` bindings after interfaces stabilize. Reuse correct existing scripts unchanged.
5. Run the selected Cases locally; broaden only when impact analysis warrants additional proof.
6. Run `python test-e2e/infra/tools/validate_test_assets.py --phase implementation --generate` before closeout.

Legacy implementation-oriented tests remain separate. They may continue to run during transition, but they are not formal D1-D5 assets and cannot satisfy formal Case or execution-binding coverage.
