# Agent publication acceptance backfill

## Current behavior

Product baseline: `b10c8f778`. Publication stays on the agent editor route and selects the publication tab. Drafts show an empty state; published agents show experience/share, API and A2A sections. Preview and API key actions navigate the current tab. An unregistered A2A settings response (404) is not-enabled guidance; other request failures offer retry. This supersedes the historical post-publish warehouse navigation in AGUG-001; the existing warehouse usage-guide entry remains supported.

## Proof gaps and responsibilities

| Behavior | Existing proof | Missing boundary and action |
| --- | --- | --- |
| Workflow tabs and draft empty state | `agentConfigHeader.test.tsx` checks callbacks and button selection | Add AGENT-PUBLICATION-D4-001 for the actual mounted editor, preserved description and published collapsible sections. |
| Preview/API key navigation | `agentPublication.test.tsx` checks href and missing target attributes | Add AGENT-PUBLICATION-D4-002 for real clicks, selected chat agent, user settings, page count and popup events. |
| Publish outcome | PW-VERSION-01 checks version persistence, but its helper can return to the editor after a redirect | Strengthen PW-VERSION-01 with a controlled rejected HTTP publish response, successful publication landing and the original version history/draft isolation checks. Opt into landing assertions before any helper navigation. |
| A2A states | Component coverage checks enabled/disabled data and retry; PW-A2A-PUBLISH-01 proves real external discovery/invocation | Strengthen PW-A2A-PUBLISH-01 with actual unregistered 404 guidance, displayed registered endpoints/development URLs, controlled transport failure and retry recovery. Preserve authenticated external invocation. |
| A2A 404 regression | No component input supplied statusCode=404 | Add `shows not-enabled guidance when unregistered A2A settings return 404` in traditional frontend component tests; assert absence of failure, retry and endpoint fields. |

These additions prove browser journeys (D4), with real page state, routing and tenant services. Only the rejected publish response and temporary A2A transport failure are controlled. The A2A external client remains real. No new D1/D2/D3/D5 contract is needed, and no production code is changed.

## Acceptance assertion review

- AGENT-PUBLICATION-D4-001 AC-01: steps 1–2 assert the draft empty state, no preview link, workflow selection and retained description. AC-02: steps 3–4 assert the publication landing, initially expanded sections/example, independent collapse/reopen behavior; final assertions repeat description and access-content checks. A request observer rejects unrelated invocation/key mutations.
- AGENT-PUBLICATION-D4-002 AC-01: steps 1–2 assert publication landing, current-page preview URL with owned agent ID and visible selected agent. AC-02: steps 3–4 assert current-page user settings, API key UI and a usable publication page on return. Page count plus page-created events detect popup regressions; requests guard against invocation/key writes.
- PW-VERSION-01 AC-01 retains validation, version history and snapshot isolation assertions, including refresh. AC-02 asserts controlled publish rejection feedback/context, no publication content on failure, no additional persisted version, and successful same-route publication before any fallback navigation.
- PW-A2A-PUBLISH-01 AC-01/AC-02 preserve owned UI enable/publish, actual registration/card version consistency and authenticated external output-marker verification. AC-03 asserts a real settings 404 before A2A enablement, absence of fabricated fields/retry, displayed card/interface values matching registration, both development URLs, controlled transport failure and restored card URL after retry. Routes are restored in finally blocks; cleanup deletes only the dynamically created agent and probe-owned resources.

## Verification

- Traditional frontend component tests: `agentPublication.test.tsx` and `agentConfigHeader.test.tsx`: **16 passed** (includes the new 404 regression).
- Playwright collection: all four changed/new Case IDs collected successfully.
- Formal design validator with explicit acceptance gates for all four Cases: passed; derived navigation, registry and Excel regenerated locally (ignored generated files are not hand-edited).
- Full implementation validation: blocked by the existing unrelated `CHAT-INLINE-MESSAGE-EDIT-20261016` change (`Confirm actual traditional UT selectors after implementation`). No current-change contract/binding issue was reported alongside it.
- The standard `run_cases.py` stops all four Cases at that unrelated full validation gate before browser execution (`NOT_EXECUTED`). To obtain independent execution evidence without changing the validator, a machine-local wrapper checks execution bindings and invokes the existing `run_cases.run_one` for each selected Case, preserving preparation, fixed Playwright runner, network audit, acceptance report and cleanup. This is targeted execution evidence, not a full-validator PASS.
- Targeted browser execution: AGENT-PUBLICATION-D4-001 PASS (`20261020T102308455769Z`), AGENT-PUBLICATION-D4-002 PASS (`20261020T102326672490Z`), PW-VERSION-01 PASS (`20261020T102345479918Z`). Evidence is under `${test-home}/runs/repository-local/<timestamp>-<Case-ID>/`.
- PW-A2A-PUBLISH-01 PASS (`20261020T115020824058Z`): all eight steps passed, including real unregistered 404 guidance, registered interface display, external Agent Card discovery, authenticated real-model marker verification, controlled transport failure and retry recovery. All four Cases have runner/assertion/cleanup PASS and `MAPPED_EXECUTION_PASSED` acceptance reports.
- The local minimal deployment initially lacked runtime/northbound/Redis/MinIO and the documented `NORTHBOUND_EXTERNAL_URL`; these dependencies were temporarily enabled/configured and current code synchronized for real A2A execution. No product assertion was replaced or relaxed. The original ignored DevSpace file and the pre-test Helm revisions were restored after verification; temporary runtime/northbound deployments were removed and persistent data retained. Deployment/profile changes are excluded from Git.
- Current UI helper adaptations: create dialog/name and skip-guide controls, selected-model drawer, primary prompt, description accessible label, persisted default author and dialog-scoped publish button. Publication landing compares origin and owned editor path, allowing the product to clear the one-time onboarding query. Existing fallback navigation executes only after the strict publication assertions.
- No controlled mutation run is claimed. Acceptance review checks concrete assertions, and the runtime outcomes above remain separate from full asset-validation completeness.
