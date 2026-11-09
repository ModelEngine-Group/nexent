# v2.8.4 runtime investigation

Architecture spike based on the inspected release, with implementation and evidence indexed in runtime-validation.md.

Source: remote tag `v2.8.4`, commit `c43d2d995b15c9005c0d736cd60200a22305de74`.
Branch: `feature/v284-native-toolcalling`; draft PR #4310 targeting main.
Bootstrap: `a6ba04a312938242d27824921beb2e7212b36c74` (empty product diff).

## Observed source boundaries

- `sdk/pyproject.toml`: smolagents[mcp] pinned to 1.23.0; Python >=3.11,<3.12.
- `sdk/nexent/core/agents/core_agent.py`: imports CodeAgent, custom action classification, code extraction, protocol repairs, verification, context runtime and cancellation. Explicit format reminders require code and final-answer tags. These must not enter the native loop.
- `sdk/nexent/core/agents/nexent_agent.py`: create_single_agent constructs CoreAgent after building authorized tools and optional sandbox executor. Candidate factory boundary. Subagent invocation constructs independent NexentAgent runtimes. Monitoring wrappers already surround tools.
- Same file: add_history_to_agent explicitly checks isinstance(CoreAgent); this is a compatibility boundary that a factory alone cannot solve. Plan tools depend on runtime attributes and callbacks.
- `sdk/nexent/core/agents/run_agent.py`: concurrency, cancellation, managed MCP collection and terminal model/protocol failures surround runtime construction and execution.
- `sdk/nexent/core/models/openai_llm.py`: existing native-tool and provider reasoning controls require detailed protocol inspection; their presence is not evidence of correct native history support.
- `sdk/nexent/core/agents/sandbox.py` and tool_fastpath.py: existing executor construction, lifecycle and deferred tool execution should be investigated before selecting the bridge. No host-execution fallback is authorized by this experiment.

## Initial classification (source inspection only)

| Component | Candidate treatment | Remaining proof |
|---|---|---|
| Authorized tool construction and monitoring wrappers | Shared | Permission/schema parity and native invocation |
| Sandbox creation, workspace and cleanup | Adapted | Stateful bridge, cancellation and isolation |
| CodeAgent textual output parsing and loop | Reimplemented via ToolCallingAgent | Genuine structured exchanges and termination |
| History loading and context projection | Adapted | Valid IDs, results, multi-call provider history |
| Agent Definition storage | Shared | Runtime-specific interpretation without data writes |
| Prompt composition and observer events | Adapted | Preserve instructions and streaming contract |
| Reasoning/provider controls | Shared where valid | Independent native thinking and tool-call evidence |

## Findings from implementation and live verification

The constructor alone is insufficient. Legacy type checks also govern history restoration, metadata trees, observer invocation and child construction. These boundaries now recognize both supported runtime types; the legacy constructor lookup remains unchanged for default-path compatibility.

Nexent's existing OpenAIModel assembles textual output and diagnostics for CoreAgent; it does not supply the required native conversation transcript. NativeModel reuses its configured client, capacity dispatcher, retry classifications, concurrency limiter and reasoning controls while assembling native stream fragments separately. smolagents 1.23.0's ActionStep.to_messages renders calls/results as text; inspected 1.26.0 retains that assumption. An upgrade alone does not solve history correctness, so this spike retains 1.23.0.

MultiStepAgent.run automatically calls python_executor.send_tools with every tool. That would inject recursive code_execution and terminal tools into Nexent's remote executor. The native runtime owns a separate executor attribute and registers only authorized programmatic functions once. The existing sandbox helper _execute_with_tool_context must surround each code call: registering proxy functions alone leaves their execution token unset and loses authenticated callback/context propagation.

## Capability inventory and classification

| Area | Existing ownership | Native treatment / limits |
|---|---|---|
| Builtin/local and configured tools | NexentAgent.create_tool, definition-specific ToolConfig | Shared instances, schemas and permission scope; direct and Python paths verified |
| MCP tools | ManagedMCPToolCollection, mcpadapt, create_mcp_tool | Same session lifetime and adapter; actual stdio MCP protocol verified; dynamic container management unchanged and unverified |
| Python | sandbox.py, LocalPythonExecutor, deferred executor, workspace manager | Same restricted interpreter or configured Docker executor; state, bridge and image paths verified |
| Managed agents | NexentAgent child factory; smolagents agent-as-tool | Selection propagates; actual native parent -> child -> Python verified |
| Memory/context | ManagedContextRuntime, context items, historical projection | Reuse instruction selection/budgeting; native current-run transcript remains atomic; current-run compaction unsupported |
| Planning | PlanRepo and existing plan tools/callbacks | Adapt callbacks without CodeAgent loop; focused unit proof |
| Verification/guardrails | VerificationController, GuardrailEngine | Input/argument/output checks, programmatic argument checks and final repair; focused unit proof |
| Clarification | ClarificationForm and HUMAN_INTERACTION observer contract | Native structured terminal tool, existing schema; unit proof, full browser form round trip unverified |
| Streaming/lifecycle | MessageObserver, RunCancellationScope, ThreadManager | Existing stream contract and typed cancellation; actual provider-stream cancellation and limits tested |
| Definitions | Existing backend/storage model | No runtime field or database migration; same persisted definition tested across both selections |
| Multimodal | Existing attachments/model paths | Not validated; initial native memory projection currently retains text only |
| Tracing | Existing Nexent monitoring/OpenTelemetry | Phoenix root/LLM/tool spans and nested bridge context inspected |

## Environment

Multipass's snap launcher cannot acquire its required capability in this agent process; verified SSH initially enabled VM development. The user subsequently stopped the resource-limited VM and explicitly selected the host for final deployment. The VM remains stopped. All host task files, caches and deployment data are within the PR4310 worktree. A separate task Phoenix instance runs on the host; historical VM traces are identified separately. Phoenix MCP is available for final trace inspection; no Phoenix CLI was installed.

## Architectural risks

Unbounded native history, provider-specific continuation metadata beyond reasoning/reasoning_content, multimodal blocks/results, dynamic MCP containers, prompt compatibility for authored CodeAgent directives and concurrent child/kernel lifetime need further work before production migration. Empty model output can result from an incorrectly configured output budget: the initial host model record defaulted to one effective output token; configuring the tested 2048-token operational budget resolved it. This was test configuration, not native protocol success.
