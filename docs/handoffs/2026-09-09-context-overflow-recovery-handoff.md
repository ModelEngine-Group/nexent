# Context Overflow Recovery Handoff

- Status: `summary-quality and WebUI revision verified at 16K; deterministic Langfuse overflow trace pending`
- Branch: `fix-context-overflow-recovery`
- Base: `origin/develop@48349d4fb82f7156a444b6e1d854d1e399d0904b`
- SPEC: `nexent/model-runtime-governance/context-overflow-recovery/`

## Goal and boundary

Stack this branch on `perf-context-proactive-compaction` and respond only to explicit Provider context overflow. Safe requests may use the remaining portion of the shared three-attempt compression allowance and perform at most two recovery dispatches. Possible or confirmed external side effects forbid replay. Unknown Effective Input Limit still permits Provider-driven recovery. Generic retry and length continuation are out of scope.

Recovery reuses the proactive branch's canonical Effective Input Limit, Compaction Trigger Threshold, and Compaction Target state. It must not introduce aliases or a second threshold model.

The stacked proactive revision must stop recompressing target-sized history when the remaining complete-request excess is non-history, validate exactly seven canonical summary sections, chain later attempts from the prior in-memory candidate, and emit only a non-streaming compacting status until a valid persisted result exists. Token-estimator calibration is out of scope.

## Reference only

Review donor overflow classification, context event, monitoring, OpenAI adapter, and Agent tests. Do not carry over retry logic without proving the side-effect ledger boundary.

## Verification

- Branch is stacked on proactive commit `4d9d40bce`.
- `77 passed` for the complete OpenAI adapter test module.
- `168 passed` for ContextManager and CoreAgent tests.
- A real Provider smoke call returned the expected marker with response diagnostics.
- A deterministic real Provider overflow and Langfuse trace were not available in this environment; mock tests are not presented as substitutes.
- The summary-quality revision adds a canonical `HistorySummaryInput`, exact seven-section parsing, dynamic output limits, a 5%/32-token minimum reduction gate, and an achievable-history stop condition.
- Internal summary model streaming is isolated from the Agent observer. The stream emits `compacting`, then either removes that transient state or publishes one validated `accepted` summary.
- `210 passed` for the focused ContextManager, context-runtime, and CoreAgent suite locally.
- The revised main and web images were built and deployed to `nexent-context-recovery-20260910`; the Web endpoint returns HTTP 200 and all application containers are running.
- The dedicated test model `Context Compaction E2E LLM` now uses a 16,384-token context window with a 512-token output reserve. Expected canonical budgets are Effective Input Limit 15,872, Compaction Trigger Threshold 12,697, and Compaction Target 9,523 tokens.
- Real WebUI replay triggered compaction at a raw estimate of 20,667 tokens. One valid summary reduced compressible history from 9,218 to 2,248 tokens, stopped with `history_target_reached`, persisted unit `83`, and retained the Fact-118/119/120 markers.
- The summary Provider request used the dynamic 2,539-token output allowance with Qwen thinking disabled. An earlier candidate was safely rejected as `invalid_candidate`; it was neither displayed nor persisted.
- The new `/newchat` UI now renders transient `compacting` and accepted `history-summary` data parts. Persisted accepted summaries reappear after page reload; legacy `/chat` handling remains supported.
- After runtime restart, the Agent loaded persisted summary unit `83` and correctly returned `validation-seed-001`. A subsequent accepted incremental snapshot was loaded as unit `93`.
- With a 14,141-token complete request above Trigger but only 2,411 compressible-history tokens, the feasible-history guard stopped repeated compression: `compaction_attempts=0`, `compression_attempted=false`, `compaction_stop_reason=history_target_reached`; the Agent still returned Fact-117 marker `M117`.
- The final main and web images were rebuilt from current worktree source and deployed to `nexent-context-recovery-20260910`.
- Deterministic Provider overflow recovery plus Langfuse trace remains pending because this environment has no configured Langfuse endpoint and the real Provider did not emit a context-window overflow during the bounded replay.
- This HANDOFF remains intentionally uncommitted.
