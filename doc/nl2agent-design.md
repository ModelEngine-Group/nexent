# NL2Agent Ephemeral Agent Design

## 1. Current Flow

NL2Agent is embedded in the `/agents` creation page. Opening the generation
assistant enters create mode and starts a page-local assistant runtime.

The flow is:

1. Clarify the agent requirements through normal conversation.
2. Search the current tenant's installed and available MCP tools.
3. Render a selectable tool recommendation card.
4. Write the confirmed tool set to the current editable agent with
   `updateTools()`.
5. Send the same confirmed tool metadata to NL2Agent as the next query.
6. Generate and render an agent draft card.
7. Write the confirmed non-tool fields with `updateAgentConfig()`.
8. Save through the existing agent configuration flow.

The NL2Agent runtime and its conversation remain ephemeral. The editable agent
state is owned by the existing agent configuration store.

## 2. Runtime API

The frontend uses the existing stream adapter with NL2Agent runtime mode:

```http
POST /agent/nl2agent/run
```

```json
{
  "query": "The user's current input",
  "history": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "minio_files": []
}
```

When a recommendation is confirmed, the adapter serializes
`metadata.custom.nl2agentToolSelection` as the current query:

```json
{
  "type": "nl2agent_tool_selection",
  "tools": [
    {
      "tool_id": 10,
      "name": "weather_forecast",
      "origin_name": "weather",
      "description": "Get weather forecasts",
      "source": "mcp",
      "usage": "weather-server",
      "labels": ["weather"],
      "inputs": "{\"city\":\"string\"}"
    }
  ]
}
```

The visible user message remains a localized selection summary. The request
does not contain a persisted agent or conversation ID.

## 3. Runtime Agent and MCP Search

Every request constructs an in-memory `AgentConfig` named
`__nl2agent_runtime__` with the current tenant's default model. It binds only
the internal `search_installed_mcp_tools` and `nl2a_wrapper` Local MCP tools.

The search tool:

- Resolves the tenant from the authenticated MCP request.
- Searches only installed, available MCP tools.
- Accepts 1 to 10 normalized capability keywords.
- Returns at most five deterministic matches.
- Exposes safe display metadata and the original `inputs` schema.

The Local MCP tool only searches the catalog. Agent draft editing is performed
by the frontend configuration store.

### 3.1 Executable Action Output Contract

The localized NL2Agent prompts define three mutually exclusive response types:

1. A direct-text clarification question or post-wrapper completion message.
2. A search or wrapper action containing exactly one complete `<code>...</code>`
   block and ending immediately after `</code>`.
3. A localized direct-text generation warning when the model cannot guarantee
   a valid executable action.

Before emitting an action, the model silently verifies that the response has
one paired set of literal code tags, contains no Markdown code fence, contains
valid Python with the exact tool and keyword argument names, assigns the tool
result, prints it, and has no content after the closing tag. The model repairs
the response before submission when possible. If it still cannot guarantee the
contract, it stops the loop and returns only one of these warnings:

- Chinese: `未能生成有效的工具调用格式，请手动重新生成回复。`
- English: `Failed to generate a valid tool-call format. Please manually regenerate the response.`

Clarification, a real tool error Observation, and the completion message after
a successful wrapper call are not generation failures. Markdown fenced code
and bare Python remain non-executable; the runtime parser is intentionally not
relaxed because display-only code must never be executed as an action.

## 4. Structured NL2A Payloads

The existing `<nl2a>...</nl2a>` extraction and `nl2a` SSE type are reused.
The JSON payload is a subtype-discriminated union.

Tool recommendation success:

```json
{
  "subtype": "local_mcp_recommendation",
  "status": "success",
  "recommendation_count": 1,
  "recommendations": []
}
```

Tool recommendation error:

```json
{
  "subtype": "local_mcp_recommendation",
  "status": "error",
  "code": "tool_search_failed",
  "retryable": true
}
```

Agent draft:

```json
{
  "subtype": "agent_draft",
  "name": "weather_assistant",
  "display_name": "Weather Assistant",
  "description": "Checks weather and provides travel advice",
  "duty_prompt": "...",
  "constraint_prompt": "...",
  "few_shots_prompt": null
}
```

`GeneratedAgentDraft` contains only fields accepted by
`updateAgentConfig()`. Selected tools are not repeated in the draft payload.

## 5. Frontend State Updates

### 5.1 Tool Confirmation

Recommendation cards select all returned tools by default and allow full,
partial, or zero-tool confirmation.

On confirmation, the card:

1. Filters recommendations in their displayed order.
2. Maps the selection to `Tool[]`, using `String(tool_id)` as `id` and
   `initParams: []`.
3. Calls `updateTools()` with that exact set.
4. Stores the same selection in message metadata and starts the next run.
5. Becomes read-only.

The recommendation card selection is the source of truth for this update.

### 5.2 Draft Confirmation

The agent draft card displays the generated agent name and description without
showing the complete prompts.

On confirmation, it calls `updateAgentConfig()` with:

- `name`
- `display_name`
- `description`
- `duty_prompt`
- `constraint_prompt`
- `few_shots_prompt`

A null `few_shots_prompt` is normalized to an empty string. The previously
confirmed tool set remains unchanged.

## 6. assistant-ui Mapping

The stream adapter parses `nl2a` SSE content into
`message.metadata.custom.nl2a`. `AssistantMessage` renders after grouped
message parts:

- `local_mcp_recommendation` as `ToolRecommendations`.
- `agent_draft` as `AgentDraftCard`.

Raw MCP `execution_logs` remain attached to their tool call.

## 7. Verification

Backend tests cover the bilingual prompt contract, both subtype values, and
the reduced `GeneratedAgentDraft` schema. The prompt contract tests also verify
the mutually exclusive response types, pre-submission action validation,
localized fallback warnings, and the continued prohibition of Markdown code
fences.

Frontend verification covers:

- Full, partial, and zero-tool confirmation updates `editedAgent.tools`.
- The selection metadata sent to NL2Agent matches the stored tools.
- Draft confirmation updates only non-tool configuration fields.
- Existing agent save behavior persists the completed editable configuration.
