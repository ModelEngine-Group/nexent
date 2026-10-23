# Context and Prompt case repair evidence

Baseline `develop` at `33e994eacc42070e30f1bd20e0418fee294e113d`.
Worktree `C:/Project/worktree/fix-eight-e2e-cases`, branch `fix/eight-e2e-cases`.
The user authorized repairing eight existing Cases and local test preparation.
All tracked changes are test assets, shared test helpers, regressions and this report. Product source, repository SQL, package manifests, workflows and machine secret files are unchanged.

## Repairs and retained proof

| Case | Repair and retained assertions | Execution |
| --- | --- | --- |
| UT-SDK-AUTO-74430BEE8438F486 | Restore omitted explicit_sampling in the bare-model factory; retain rename, serialization, W1/W2 and override assertions | PASS |
| UT-SDK-AUTO-85A0FBE8116B9F9A | Restore explicit_sampling and diagnostic_chunks_enabled in the fake builder; retain rebuild, safety, retry exhaustion and permit release | PASS |
| AGT-010 | Remove the false ext-served http-fixture declaration; retain the runner-owned Prompt fault service, both failure modes, no-save and real recovery | PASS |
| AGT-012 | Reuse shared owned fault lifecycle and initialize/read back its required owned Prompt; classify only the exact missing-Jiuwen capability response as a dependency error | PASS |
| SEARCH-DEEPSEEK-D3-001 | Declare explicit empty preparation because the script owns its loopback provider | PASS |
| SEARCH-DEEPSEEK-D4-001 | Declare explicit empty preparation because the browser owns its API fixtures | PASS on current port-3100 frontend |
| PW-PROMPT-01 | Use current single Prompt editor, accessible description/composer and current card menu; retain real generation, unrelated-field preservation, manual save, reselection and refresh | PASS after MCP alignment |
| PW-PROMPT-02 | Use visible accessible Compare textbox instead of retired placeholders; retain two models, both rounds, separate histories and normal-mode recovery | PASS |

No new formal Cases were added. PR #4051 removed constraint/few-shot fields; the current editor also removed their tabs and the exposed expand action. PW-PROMPT-01 now expresses its generation and persistence obligations through the current single Prompt and actual unrelated fields. AC-01/02/03 map to its collected Journey. The server-read snapshot covers name, display name, author, description, models, tools, skills, children, greeting and example questions. It is compared after base save, generation, manual edit and reload.

AgentPage.select now opens Configure through More actions on the exact owned card. Its browser regression includes a similarly named neighbor. Only PW-PROMPT-02 calls the changed Compare helpers. Its fourth action now explicitly selects the configuration development step before changing Prompt, and its fifth action reopens Debug; Compare keeps its mounted histories while the configuration page is visible. The earlier script tried to edit a hidden configuration card in the full-screen Compare layout. No skip, xfail, synthetic live-model response or relaxed output oracle was introduced.

## Verification

- Design and strict implementation asset validation passed, including `--require-acceptance-case PW-PROMPT-01`.
- Targeted infrastructure regressions passed on 2026-10-23, **11 passed, 1 deselected**. The browser regression uses real Edge and transpiles the actual AgentPage helper. It covers hidden retained inputs, textarea/contenteditable composers, two independent Compare histories and the exact card menu.
- The deselected pre-existing `test_complete_draft_requires_saved_fields_not_a_completion_marker` concerns unchanged AGT-AUTO-6A6BC7594487E771 accepting tools. It is outside these eight Cases and is not counted as passing.
- Copyright checks passed for all eight changed/new source files. `git diff --check` passed.
- Product traditional UT changes are inapplicable to this test-only repair. Infrastructure regressions are reported separately from formal live acceptance.

## Local execution and environment

The supplied test-home administrator credential differs from the local deployment credential. The user explicitly authorized reading the verified existing deployment administrator credential in memory for preparation through public APIs. No credential value was logged, and no secret file or product password was rewritten. Existing preparation created/reused test tenants, accounts, groups and model anchors.

The local config/runtime images contained old v2.7.0 backend/SDK code whose ORM referenced removed prompt fields. The user authorized backing them up, replacing backend/SDK with this worktree baseline and restarting. Backups and rollback scripts are under `C:/Project/work/context-prompt-service-update/`. Existing virtual environments and runtime data were retained. A local `context_prompt_sdk.pth` selects current `/opt/sdk` instead of the image's older installed package. Original startup scripts were restored; SQL startup hooks were omitted for those controlled restarts.

The user manually aligned the local conversation schema on 2026-10-23. Read-only verification confirmed `conversation_message_t.message_source`, `conversation_record_t.last_activity_time`, `conversation_record_t.title_version` and both activity/chat indexes. The assistant did not execute the staged conversation SQL. The prior two-table pg_dump backup remains available. The unrelated missing partner_mapping_id_t table was left outside scope.

The first resumed PW-PROMPT-01 reached real generation but its MCP save returned draft_save_failed. MCP logs identified the old ORM querying removed constraint_prompt. The user separately authorized updating nexent-mcp. Its backend/SDK was archived to nexent-mcp-backup.tar (22,691,840 bytes, 1,514 entries), then aligned to the same baseline. The management OpenAPI on port 5015 returned 200; SDK imports current /opt/sdk, and the original startup script was restored. The update helper initially probed the config-service readiness path, which MCP does not implement; its timeout was checked against the actual management API and corrected in the local script.

A separate worktree frontend runs on port 3100 against the local config/runtime services. The original port-3000 frontend and main checkout remain untouched. Its isolated dependencies contain Next 16.3.5 and TypeScript 5.8.3. The declared AI-SDK-6-compatible react-ai-sdk 1.3.33 was installed locally without saving manifest or lockfile changes. The original shared Next 15 dependencies ignored proxy.ts; replacing the worktree dependency junction with an isolated installation fixed locale routing.

The local wrapper calls standard suite.worker, retaining declared preparation, audited D4 queue/contracts and cleanup. It uses the existing shared backend Python because the test-home dedicated test-venv is absent, and adapts only the in-memory preparation credential and frontend base URL. It is outside Git and does not change Daily workflows.

## Formal execution evidence

Receipts are under `C:/Project/nexent-test-suite/runs/repository-local/`.

| Case | Successful evidence directory |
| --- | --- |
| UT-SDK-AUTO-74430BEE8438F486 | 20261022T121114362765Z-UT-SDK-AUTO-74430BEE8438F486 |
| UT-SDK-AUTO-85A0FBE8116B9F9A | 20261022T121117883429Z-UT-SDK-AUTO-85A0FBE8116B9F9A |
| SEARCH-DEEPSEEK-D3-001 | 20261022T121120998340Z-SEARCH-DEEPSEEK-D3-001 |
| SEARCH-DEEPSEEK-D4-001 | 20261023T014628Z-context-prompt-SEARCH-DEEPSEEK-D4-001 |
| AGT-010 | 20261022T122651Z-context-prompt-AGT-010 |
| AGT-012 | 20261022T122920Z-context-prompt-AGT-012 |
| PW-PROMPT-01 | 20261023T014815Z-context-prompt-PW-PROMPT-01 |
| PW-PROMPT-02 | 20261023T014937Z-context-prompt-PW-PROMPT-02 |

D3 fault receipts record exactly one actual Provider request for each unavailable/timeout variant, exact HTTP status (AGT-010 400; AGT-012 500), unchanged draft and zero cleanup errors. Both Cases also passed real-model recovery and nonempty Jiuwen-source assertions.

Earlier failures remain as historical evidence, including the original port-3000/Next-15 attempts, stale direct Configure selector, missing conversation columns and old MCP ORM. They are not relabeled as passes. PW-PROMPT-01 passed after MCP alignment; PW-PROMPT-02 passed after restoring the configuration/Debug navigation. All eight selected Cases passed.

Final 2026-10-23 acceptance is **8/8 PASS**. PW-PROMPT-01 completed all 3 preconditions, 8 actions and 3 final assertions. PW-PROMPT-02 completed the same contract shape, including two old outputs, two new outputs, retained histories and one normal-mode answer. Both formal receipts have zero cleanup errors. Strict implementation validation was repeated after the final Compare fix and passed. The repair is committed for PR review.

## Latest develop integration

Merged `origin/develop` at `75906a319` on 2026-10-23. The only conflicted file was AgentPage. The resolution retains the upstream debugComposer abstraction and uses one visible accessible textbox for normal and Compare modes, including panes that stay mounted while hidden. The exact-card Configure menu repair remains in place.

After the merge, all 11 selected infrastructure regressions passed again (one unrelated pre-existing test deselected). Strict implementation asset validation and copyright checks passed. All three affected browser Cases passed against the merged frontend, with zero cleanup errors.

The first post-merge PW-PROMPT-01 request reached the real Provider but exhausted its 4096 completion-token limit using reasoning-only chunks (4093 reasoning chunks, zero content chunks). It produced no save-tool call. This attempt is retained as failure evidence in 20261023T020049Z-context-prompt-PW-PROMPT-01. An independent rerun uses the same script, model configuration and assertions; no automatic retry or alternate oracle was added to the Case.

The unchanged PW-PROMPT-01 rerun passed all obligations at `20261023T020356Z-context-prompt-PW-PROMPT-01`. This confirms a passing execution after the conflict resolution while retaining the Provider exhaustion as a known run-time limitation.

Post-merge successful receipts are `20261023T020356Z-context-prompt-PW-PROMPT-01`, `20261023T020708Z-context-prompt-PW-PROMPT-02` and `20261023T020801Z-context-prompt-SEARCH-DEEPSEEK-D4-001`. The remote develop tip was confirmed unchanged at `75906a3191feda4f09810540165382189ed8cd96` before PR creation.
