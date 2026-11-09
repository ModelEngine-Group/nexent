# Develop migration roadmap

## Validated observations

The SDK and deployed application experiments demonstrate that an existing Nexent tool can execute through native model APIs and return a correlated result used by the next generation. This does not establish full harness equivalence. The source contains CodeAgent-specific wrapper checks, prompt policies and textual history assumptions beyond the agent constructor. Upgrading to inspected smolagents 1.26.0 alone does not remove textual history rendering.

## Recommendations

1. Define a small runtime lifecycle contract around construction, invocation, cancellation, state/context input and observer output. Keep CodeAgent and ToolCallingAgent loops independent.
2. Keep definition-specific authorized tool construction and business implementations shared. Make validation/execution context and result identity explicit so native and sandbox bridge calls agree.
3. Use a first-class code_execution tool backed by the existing sandbox lifecycle. Preserve per-invocation kernels, bridge permissions and limits. Do not infer full compatibility from arithmetic execution alone.
4. Represent native assistant calls and per-ID results as indivisible context groups. Add budget accounting and group-level compaction before production rollout; request-tail preservation with fail-on-overflow is an experimental shortcut.
5. Separate semantic instructions from runtime formatting at prompt composition. Retain authored text, replace only platform-owned CodeAgent conventions, and surface incompatible definitions explicitly.
6. Specify provider capabilities independently for tool calling, streaming, reasoning parameters and continuation metadata. Validate representative Qwen, DeepSeek, GLM and MiniMax configurations rather than assuming family equivalence.
7. Port the tested planning, verification/guardrails and clarification adapters and add live policy/form journeys before claiming parity. Never turn explicit experimental rejection into silent production bypass.
8. Maintain native event IDs across model, executor, nested bridge and observer/tracing boundaries; reconcile persisted message-unit projection and frontend replay.

## Suggested implementation sequence on develop

Prerequisites: retain this experiment's hybrid/sandbox/provider/MCP/delegation evidence and stable regressions, then close the explicitly unverified harness boundaries. Reconcile develop's newer backend configuration layout before implementation; do not copy v2.8.4 const.py paths blindly.

Introduce lifecycle/configuration contract with stable-default tests; native wire model adapter; direct tool registry; sandbox code tool/bridge; protocol-preserving context; observer/history persistence; managed agents/MCP; planning/verification/clarification; provider capability coverage. Keep each stage selectable and independently testable.

Use unit checks for schemas/IDs/configuration/error/cancellation branches, real provider and sandbox D3 cases for actual protocol exchanges, existing definition API/browser journeys, and branch-built deployment/rollback D5 checks. Retain source/image identities and sanitized Phoenix span evidence per acceptance scenario.

Rollout remains opt-in. Rollback selects codeagent and restarts application without database migration. Avoid production migration until all required harness and compatibility checks pass.

## Unresolved questions

Native current-run compaction and overflow recovery; model tool limits/schema portability and provider continuation metadata; sandbox bridge equivalence for dynamic MCP containers; concurrent managed-agent lifetime; multimodal native messages/results; live planning/verifier/clarification journeys; statistically meaningful token/latency comparisons. These are open work, not validated improvements.

## Concrete migration lessons

- Retain the independent loops, native wire adapter and shared authorized tool construction; do not copy CoreAgent parsing or its textual history.
- Make executor registration and per-execution context explicit lifecycle operations. Upstream automatic registration is unsafe for the optional code tool.
- Preserve callback context across the Python bridge, including tool-call identity, permissions and trace parentage. The final Docker evidence shows the programmatic existing-tool span beneath code_execution.
- Model thinking toggles and effort independently. DeepSeek required an explicit thinking object in the tested gateway, while DeepSeek/MiniMax reasoning fields varied across gateway runs. Native tool support is a separate observation.
- Use capability-based adapters for plan/verification/clarification and authoring helpers; the spike's borrowed CoreAgent plan methods are a temporary coupling to replace.
- Define atomic native exchange groups for context compaction and a multimodal message algebra before production rollout.
- Preserve default CodeAgent as the rollback path. Both selected runtimes completed the same persisted-definition workloads; the isolated timing observations are not a performance benchmark.

## Standalone branch follow-up — 2026-11-09

This v2.8.4 branch is a standalone hotfix-like experiment and is not intended for merge into main/develop. The feature-introduction branch is feature/native-toolcalling-runtime (PR4315), based on develop and its model service. Historical evidence above refers to earlier source snapshots.

The follow-up implements validated finish reasons: normal nonempty content-only stop or standalone final_answer can terminate; content accompanying ordinary tool calls is intermediate. Length/filter/refusal/missing/inconsistent completion cannot authorize tool execution or successful completion. Public content now bypasses the legacy thinking parser, is retained around tools, rolls back per attempt, and persists/reloads without duplicating the accepted final step. No progress tool is added. Current sanitized verification is retained separately from historical evidence.
