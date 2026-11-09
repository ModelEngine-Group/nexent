# Nexent v2.8.4 — Experimental Native Tool-Calling Agent Runtime

## 1. Mission and Scope

Implement and validate an experimental Agent Runtime based on smolagents `ToolCallingAgent`, alongside the existing Nexent `coreagent` / `CodeAgent` runtime.

This work must be performed on a dedicated feature branch based on the stable `v2.8.4` version.

**This is an architecture spike and proof of concept, not a production migration.**

The experiment has two equally important objectives:

1. **Short-term validation:** Establish a functional, testable runtime using native model tool calling and native reasoning, while preserving Nexent's existing agent capabilities.
2. **Long-term architectural learning:** Identify architectural improvements, compatibility requirements, and migration strategies that can inform a future implementation on the `develop` branch.

The implementation does not need to be directly mergeable into `develop`. However, its findings, design decisions, reusable components, and lessons learned must be documented so that the approach can later be reimplemented or migrated without repeating the investigation.

### Core Principles

- Preserve the existing CodeAgent runtime as the stable baseline.
- Make the experimental runtime independently selectable through `.env`.
- Use genuine native model tool/function calling.
- Use native model reasoning/thinking capabilities when supported.
- Remove mandatory prompt-level ReAct conventions.
- Support both **direct native tool invocation** and **optional Python code execution**.
- Preserve existing Nexent tools, harness capabilities, and Agent Definition functionality.
- Allow justified architectural experimentation and targeted refactoring.
- Optimize for rapid capability validation rather than immediate production readiness.
- Document runtime-specific components, shared capabilities, and future architectural implications.

**The objective is capability equivalence, not implementation equivalence.**

---

## 2. Phase One — Investigate the Existing v2.8.4 Architecture

Before implementation, inspect the actual Nexent codebase at `v2.8.4`.

Do not assume that upstream smolagents behavior directly describes Nexent's customized runtime.

### 2.1 Agent Runtime and ReAct Dependencies

Investigate:

- The current `coreagent` / `CodeAgent` implementation.
- Nexent-specific extensions and overrides of smolagents.
- The relationship between `CodeAgent`, `MultiStepAgent`, and Nexent's Agent Loop.
- Prompt-level ReAct conventions versus runtime-level multi-step execution.
- `<CODE>...</CODE>` generation, parsing, and execution.
- Execution result and observation handling.
- Final-answer detection and termination.
- Retry, error recovery, cancellation, and maximum-step behavior.
- Streaming and intermediate execution events.
- Conversation history and memory management.

Classify components into:

1. Runtime-independent and reusable.
2. CodeAgent-specific but adaptable.
3. Runtime-specific and better reimplemented.
4. Candidates for architectural improvement.

### 2.2 Tools and Harness Inventory

Inventory all existing capabilities, including:

- Built-in Nexent tools.
- Dynamically registered and user-configured tools.
- MCP tools and dynamic MCP container management.
- Python code execution and sandbox lifecycle.
- Tool registration, schemas, permissions, and validation.
- Managed agents and sub-agent delegation.
- Stateful execution and context persistence.
- Agent memory and context management.
- Streaming and execution events.
- Cancellation, timeouts, and resource limits.
- Multimodal capabilities, where applicable.
- Observability and tracing.
- Persisted Agent Definitions.

Determine which capabilities can be exposed directly through native tool calling and which require code execution or additional adapters.

### 2.3 Models, Providers, and Prompts

Investigate:

- Existing model/provider adapters.
- Native tool/function-calling support.
- Native reasoning/thinking configuration.
- Provider-specific reasoning, content, and tool-call handling.
- Tool-call IDs and tool-result correlation.
- Multiple tool calls per response.
- Assistant responses containing both content and tool calls.
- Tool schema compatibility.
- System prompt composition.
- CodeAgent-specific formatting instructions.
- Stored Agent Definitions and user-authored prompts.

Pay particular attention to the Qwen, DeepSeek, GLM, and MiniMax model families and their existing provider integrations.

**Native tool calling and native reasoning are independent capabilities.** Supporting one does not imply support for the other.

### Phase One Deliverable

Create a concise investigation report containing:

- Current architecture and relevant source locations.
- ReAct and CodeAgent coupling analysis.
- Tool and harness capability inventory.
- Component compatibility classification.
- Major technical risks.
- Initial architecture recommendations.

Keep the investigation focused enough to support rapid implementation.

---

## 3. Phase Two — Design the Experimental Runtime

### 3.1 Runtime Selection

Introduce an environment variable:

```env
NEXENT_AGENT_RUNTIME=codeagent
```

Supported values:

- `codeagent`: existing runtime, default.
- `toolcalling`: experimental runtime.

Requirements:

- Both runtimes coexist.
- CodeAgent remains the default.
- The existing runtime behavior must remain unchanged.
- Runtime selection occurs at a well-defined initialization boundary.
- Invalid values produce clear configuration errors.
- Switching runtimes does not require modifying persisted Agent Definitions.
- Runtime-specific prompts and execution behavior are selected automatically.

A frontend runtime selector is not required.

### 3.2 Agent Runtime Architecture

Use smolagents `ToolCallingAgent` as the basis of the experimental runtime.

**Do not force both runtimes to share the same Agent Loop.**

Instead:

- Reuse components when their semantics are genuinely runtime-independent.
- Adapt existing components when differences are limited and well understood.
- Implement separate components when CodeAgent-specific assumptions make reuse fragile.
- Introduce shared abstractions when they materially improve clarity or extensibility.

Architectural improvements and targeted refactoring are allowed.

Avoid:

- Unrelated changes.
- Speculative abstractions.
- Excessive indirection.
- Unnecessary duplication of business logic.
- Changes that unintentionally affect the stable CodeAgent path.

For each major Agent Loop component, document whether it is **Shared, Adapted, Reimplemented, or Not Applicable**, along with the reasoning.

### 3.3 Native Model Tool Calling

The new runtime must use genuine native tool/function-calling protocols through the model/provider adapters.

Do not simulate tool calls using:

- ReAct textual markers.
- `<CODE>...</CODE>` blocks.
- JSON embedded in assistant content.
- Prompt-specific action delimiters.

Support:

- Tool schema registration.
- Structured tool-call responses.
- Tool-call identifiers.
- Matching tool results.
- Multiple tool calls, where supported.
- Responses containing content and tool calls.
- Tool argument validation.
- Tool execution errors.
- Provider-specific protocol requirements.
- Correct conversation history across agent steps.

Ensure that the complete message history remains valid for the selected provider.

### 3.4 Native Reasoning and Prompt Design

Remove mandatory prompt-level ReAct conventions in the new runtime.

Do not require explicit:

- `Thought`
- `Action`
- `Observation`
- CodeAgent-specific code delimiters.

Instead:

- Allow models to use their native reasoning/thinking mechanisms.
- Configure reasoning through the supported model/provider interfaces.
- Keep reasoning separate from action execution.
- Handle reasoning fields independently from normal assistant content.
- Preserve compatibility with models without native reasoning support.
- Do not require models to expose private reasoning traces.

Create a dedicated system prompt suitable for native tool calling.

Preserve essential behavioral instructions, tool usage guidance, security constraints, and Agent Definition semantics.

Avoid retaining obsolete CodeAgent instructions solely for compatibility.

---

## 4. Phase Three — Hybrid Native Tool Calling and Code Execution

The experimental runtime must support a **hybrid execution model**.

Existing Nexent tools should be directly accessible through native model tool/function calling whenever technically feasible.

Python code execution must also remain available as an optional tool.

**Do not force all tool invocations through code execution.**

The model should be able to choose between:

1. Direct native tool invocation.
2. Python code execution through `code_execution`.
3. Programmatic tool orchestration from within executed Python.
4. Combining these approaches within the same agent task.

### 4.1 Direct Native Tool Exposure

Investigate whether existing Nexent tools can be registered directly with smolagents `ToolCallingAgent`.

Prefer direct exposure when a tool can be safely represented through the native tool-calling interface.

This includes, where applicable:

- Built-in Nexent tools.
- User-configured tools.
- Custom tools.
- MCP tools.
- Dynamically registered tools.
- Managed-agent delegation capabilities.

Requirements:

- Preserve existing tool implementations whenever practical.
- Reuse tool registries, schemas, authorization, and execution policies.
- Introduce adapters when needed for native tool calling.
- Preserve Agent Definition-specific tool permissions.
- Support dynamic tool registration where already required.
- Handle tool naming conflicts and schema incompatibilities.
- Avoid exposing unauthorized or internal-only tools.

Do not duplicate tool business logic between execution paths.

### 4.2 Optional `code_execution` Tool

Retain Python execution as a first-class native tool.

Suggested interface:

```python
code_execution(code: str)
```

Unlike the existing CodeAgent runtime, the new runtime must not require every action to be expressed as Python code.

The model should invoke `code_execution` when programmatic execution is useful.

Typical cases include:

- Data transformation.
- Iteration and conditional logic.
- Complex calculations.
- Batch operations.
- Programmatic tool orchestration.
- Workflows where code reduces unnecessary model round trips.

For ordinary tool operations, direct native tool calls should generally be preferred.

The system prompt may provide concise guidance, but must not enforce a rigid execution strategy.

### 4.3 Code Execution Backend

The new runtime may use:

- The existing Nexent Python execution environment.
- An existing sandbox environment.
- An adapted combination of existing execution infrastructure.

**The execution backend does not need to be identical to the original CodeAgent implementation.**

Choose an approach that balances:

- Feature compatibility.
- Security and isolation.
- Implementation complexity.
- Reliability.
- Speed of experimentation.
- Long-term architectural value.

Preserve, where applicable:

- Python execution capabilities.
- Stateful execution across agent steps.
- Tool access within executed Python.
- Output and error capture.
- Timeouts and cancellation.
- Resource limits.
- Sandbox lifecycle.
- Authorized dependencies and imports.
- Execution context propagation.

Do not introduce unrestricted host execution or weaken existing security boundaries.

### 4.4 Programmatic Tool Orchestration

The following workflow should remain possible through `code_execution`:

```python
results = search_tool(query="...")
filtered = [item for item in results if item["score"] > 0.8]
print(filtered)
```

If Python execution takes place in a sandbox, investigate whether existing Nexent tools can be accessed through an appropriate bridge or adapter.

Preserve:

- Tool identity and permissions.
- Argument validation.
- Execution context.
- Error handling.
- Cancellation and timeouts.
- Observability.
- Sandbox isolation.

Do not assume that exposing `code_execution` alone provides full CodeAgent compatibility.

### 4.5 Shared Tool Execution Layer

Ideally, direct native tool calls and programmatic tool invocations should converge on a shared execution abstraction.

Conceptually:

```text
Native Tool Call ────────────┐
                             ├── Tool Execution Layer
Python Sandbox → Tool Bridge ┘
```

This is an architectural direction, not a mandatory implementation requirement for the experiment.

If the existing architecture supports a shared execution layer with reasonable changes, implement or adapt it.

If not, separate execution paths are acceptable, provided the differences and future consolidation opportunities are documented.

The two paths should preserve consistent semantics for:

- Tool identity.
- Authorization.
- Input validation.
- Execution errors.
- Timeouts and cancellation.
- Execution context.
- Tracing and observability.

### 4.6 Tool Exposure Strategy

Investigate the trade-offs between exposing all authorized tools directly and exposing a smaller subset.

Consider:

- Tool schema compatibility.
- Model/provider tool-count limitations.
- Tool selection accuracy.
- Context and token consumption.
- Dynamic tool discovery.
- Execution reliability.

For this experiment, prioritize direct native exposure of existing authorized tools whenever practical.

Do not introduce sophisticated tool routing, selection, or discovery systems unless required by the existing architecture.

Record observed limitations and possible solutions for the future `develop` implementation.

### 4.7 Hybrid Execution Validation

Validate these execution paths independently:

1. **Direct invocation:** The model invokes an existing Nexent tool through native tool calling.
2. **Code execution:** The model invokes `code_execution` to execute Python.
3. **Programmatic orchestration:** Python executed through `code_execution` invokes Nexent tools.
4. **Hybrid workflow:** Direct tool calls and code execution are both used within the same task.
5. **Multi-step workflow:** Results from either execution path are correctly returned to the model and used in subsequent steps.

All execution paths should be observable through tracing.

A successful `code_execution` call alone is not sufficient evidence that direct native exposure works.

---

## 5. Phase Four — Agent Definition Compatibility

Existing Agent Definitions must remain usable with both runtimes.

Investigate:

- System prompts.
- User-authored instructions.
- Tool configurations.
- Managed-agent configurations.
- Model configurations.
- Execution settings.
- Runtime-specific assumptions.

### Compatibility Strategy

Prefer runtime-specific interpretation and prompt composition over modifying persisted definitions.

The experimental runtime should:

- Preserve the semantic intent of existing agent instructions.
- Remove or adapt CodeAgent-specific formatting requirements.
- Retain existing tool permissions and behavior.
- Avoid destructive database migrations.
- Allow switching back to CodeAgent without data loss.

If instructions cannot be safely transformed automatically, identify and document the limitation.

Do not silently discard meaningful user-authored instructions.

Distinguish between temporary compatibility mechanisms suitable for the experiment and architectural approaches recommended for `develop`.

---

## 6. Phase Five — Implementation

Implement the new runtime on the feature branch based on `v2.8.4`.

Keep the experiment isolated from `develop`.

### Implementation Priorities

1. Establish an end-to-end native tool-calling Agent Loop.
2. Expose existing authorized tools through native tool calling.
3. Implement optional `code_execution`.
4. Restore programmatic tool orchestration.
5. Support hybrid execution workflows.
6. Integrate existing Agent Definitions.
7. Restore streaming, tracing, and operational capabilities.
8. Validate representative workloads.
9. Document architectural findings and unresolved limitations.

Architectural improvements and targeted refactoring are allowed when technically justified.

Do not optimize solely for the smallest diff.

However, avoid turning the experiment into a broad Nexent architecture rewrite.

Favor clear component boundaries, testability, and rapid validation.

### Architecture Decision Records

For significant decisions, document:

- Problem.
- Alternatives.
- Selected approach.
- Technical justification.
- Trade-offs.
- Impact on the stable runtime.
- Implications for future development.

---

## 7. Phase Six — Verification and Runtime Comparison

Validation is a primary deliverable.

### 7.1 Functional Compatibility

Compare the original CodeAgent and new ToolCallingAgent using representative scenarios:

- Direct answers without tools.
- Direct native tool calls.
- Multiple native tool calls.
- Multi-step workflows.
- Python execution.
- Programmatic tool orchestration.
- Hybrid workflows.
- MCP tools.
- Tool errors and recovery.
- Stateful execution.
- Existing Agent Definitions.
- Managed/sub-agent execution.
- Streaming and final answers.
- Cancellation and execution limits.

Validate the original CodeAgent for regressions.

Distinguish between:

- Implemented.
- Tested.
- Verified working.
- Unverified.
- Unsupported.

Do not claim feature parity without evidence.

### 7.2 Native Tool-Calling Verification

Use actual model requests and traces to verify:

- Tool schemas are passed through native model APIs.
- Models return structured tool calls.
- Tool-call IDs and results are correctly correlated.
- Conversation history contains valid tool-call exchanges.
- No CodeAgent-specific action parsing is required.
- Mixed assistant content and tool calls are handled correctly.

### 7.3 Native Reasoning Verification

Inspect actual execution traces through Phoenix, Langfuse, or existing OpenTelemetry integration.

Verify:

- Reasoning configuration is passed correctly.
- Native thinking works with tool calling when supported.
- Reasoning fields are handled appropriately.
- Models without native reasoning remain usable.
- Provider limitations are explicitly documented.

Distinguish reasoning being configured from reasoning being observable.

Do not fabricate or infer hidden reasoning traces.

### 7.4 Comparative Evaluation

Where practical, run equivalent tasks through both runtimes with comparable model configurations.

Compare:

- Task completion success.
- Tool invocation correctness.
- Agent step count.
- Direct tool-call versus code-execution usage.
- Token consumption.
- End-to-end latency.
- Tool execution errors.
- Recovery behavior.

The goal is useful experimental evidence, not necessarily a statistically significant benchmark.

Document evaluation limitations.

---

## 8. Phase Seven — Architectural Learnings for `develop`

This phase is mandatory.

The experiment should produce actionable architectural insights even if the implementation is never merged.

### 8.1 Component Reuse Matrix

For every major component, document:

- Existing CodeAgent implementation.
- Experimental ToolCallingAgent implementation.
- Shared, Adapted, Reimplemented, or Not Applicable.
- Reason for the implementation choice.
- Whether the approach should be retained on `develop`.
- Recommended future improvements.

### 8.2 Architectural Findings

Investigate and document:

- CodeAgent-specific coupling.
- Prompt-format dependencies.
- Model/provider abstraction limitations.
- Tool registry and execution architecture.
- Native tool-calling integration.
- Code execution and sandbox abstraction.
- Shared tool execution opportunities.
- Agent Loop extensibility.
- Prompt composition.
- Conversation and tool-call history.
- Streaming and tracing contracts.
- Agent Definition compatibility.

Classify findings as:

- **Validated improvements**
- **Promising hypotheses**
- **Rejected approaches**
- **Unresolved questions**

### 8.3 Recommended Future Architecture

Based on actual experimental evidence, propose an architecture for `develop`.

Consider:

- Runtime interfaces and lifecycle.
- Independent Agent Loop implementations.
- Shared tools and execution abstractions.
- Direct native tool exposure.
- Optional code execution.
- Sandbox and Tool Bridge.
- Provider capability negotiation.
- Runtime-specific prompts.
- Agent Definition compatibility.
- Conversation history.
- Observability and tracing.

Do not assume that experimental code should be copied directly into `develop`.

Identify any experimental shortcuts that should be replaced in a production implementation.

### 8.4 Migration Roadmap

Provide a concrete implementation roadmap for `develop`, including:

- Prerequisites.
- Recommended implementation sequence.
- Reusable components.
- Components requiring redesign.
- Compatibility strategy.
- Testing approach.
- Rollback strategy.
- Risks and unresolved questions.

The roadmap should enable future developers or Codex sessions to implement the validated approach without repeating the investigation.

---

## 9. Acceptance Criteria

### Runtime Functionality

- [ ] Experiment implemented on a feature branch based on `v2.8.4`.
- [ ] Both runtimes selectable through `.env`.
- [ ] Existing CodeAgent remains the default and continues working.
- [ ] Experimental runtime uses smolagents `ToolCallingAgent`.
- [ ] Existing authorized Nexent tools can be exposed directly through native tool calling.
- [ ] Native tool calls replace CodeAgent-specific textual action parsing.
- [ ] Prompt-level ReAct requirements are removed.
- [ ] Native reasoning is configured and handled correctly where supported.
- [ ] `code_execution` remains available as an optional native tool.
- [ ] Python execution can invoke existing Nexent tools where required.
- [ ] Direct tool invocation and code execution can coexist in the same task.
- [ ] Existing MCP and harness capabilities are preserved.
- [ ] Existing Agent Definitions remain compatible without destructive migration.

### Validation

- [ ] Real model execution confirms native tool-calling behavior.
- [ ] Direct tool invocation is independently verified.
- [ ] Code execution is independently verified.
- [ ] Programmatic tool orchestration is independently verified.
- [ ] Hybrid execution is independently verified.
- [ ] Native thinking is verified to the extent supported by providers.
- [ ] Representative end-to-end scenarios pass.
- [ ] Existing CodeAgent regression tests pass.
- [ ] Functional gaps and unverified capabilities are explicitly documented.

### Architectural Learning

- [ ] ReAct and CodeAgent coupling is documented.
- [ ] Shared and runtime-specific components are identified.
- [ ] Major design decisions and trade-offs are recorded.
- [ ] Tool execution architecture findings are documented.
- [ ] Experimental conclusions are supported by evidence.
- [ ] A future architecture for `develop` is proposed.
- [ ] A concrete migration roadmap is provided.

These are acceptance targets, not permission to claim success without evidence.

Unmet criteria must be explicitly reported.

---

## 10. Final Deliverables

Produce five documentation artifacts:

1. **`runtime-investigation.md`** — v2.8.4 architecture, ReAct dependencies, tool/harness inventory, and compatibility risks.
2. **`runtime-design.md`** — Experimental runtime architecture, hybrid execution design, component boundaries, and architectural decisions.
3. **`runtime-compatibility-matrix.md`** — Feature-by-feature comparison of both runtimes, including direct tool calling, code execution, and hybrid workflows.
4. **`runtime-validation.md`** — Tests, actual trace evidence, comparative results, and known limitations.
5. **`develop-migration-roadmap.md`** — Architectural lessons, recommendations, and a practical migration plan for `develop`.

Place these documents together in an appropriate repository directory.

Include relevant source paths, commits, test commands, and trace references to make findings reproducible.

Do not include credentials, secrets, or sensitive reasoning traces.

---

## 11. Execution Instructions

Proceed autonomously through investigation, design, implementation, validation, and documentation.

Do not stop after investigation or planning unless a fundamental blocker prevents progress.

Use the actual v2.8.4 codebase, installed smolagents version, existing infrastructure, and runtime behavior as the source of truth.

**Execution order should prioritize obtaining a working end-to-end native tool-calling trace early**, followed by progressively restoring the existing capabilities.

Do not let difficult compatibility work prevent initial validation of the core technical approach.

You may introduce justified architectural improvements, but document significant deviations and their consequences.

Keep the implementation isolated to the experimental feature branch. Do not modify or merge into `develop`.

Before completion:

1. Execute relevant automated and end-to-end tests.
2. Review the implementation for regressions, compatibility, security, and unnecessary complexity.
3. Fix actionable findings.
4. Update documentation to reflect observed results rather than assumptions.
5. Summarize what was validated, what remains uncertain, and what should eventually be implemented on `develop`.

**Central Research Question**

Can Nexent adopt a hybrid, model-native Agent Runtime based on smolagents `ToolCallingAgent`—supporting direct native tool invocation, optional programmatic code execution, and native reasoning—while preserving existing capabilities, and what architectural lessons should guide its eventual implementation on `develop`?