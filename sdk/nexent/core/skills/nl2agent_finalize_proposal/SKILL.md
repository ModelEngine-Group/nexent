---
name: nl2agent_finalize_proposal
description: Synthesize the nl2agent conversation into a complete draft agent specification. Use when the user indicates they are satisfied with the design: "finalize", "publish", "done", "looks good", etc. Produces a full agent spec JSON covering identity, LLM models, prompts, greeting, example questions, runtime options, and selected tools/skills.
tags:
  - nl2agent
  - agent-builder
  - finalize
---

# nl2agent_finalize_proposal

Synthesize the conversation into a complete draft agent specification.

## When to call

Use this skill when the user signals they are satisfied with the design:
- "finalize", "publish", "done", "looks good", "that's everything", etc.
- The user has selected the tools, skills, and LLM models they want and wants to preview the agent.

Do NOT call proactively. Only call when the user explicitly indicates they are done configuring the agent.

## What to produce

Output exactly one fenced JSON block tagged `nl2agent-finalize` containing every
field the agent detail UI needs. Extract each value from the conversation so far.
If a field was never discussed, infer a sensible default (see defaults below).

## JSON schema (all fields required unless marked optional)

```nl2agent-finalize
{
  // ── Identity (required) ──────────────────────────────────────────
  "agent_id": 123,                    // internal draft agent ID — MUST be present
  "name": "customer_support_agent",  // programmatic, snake_case, max 50 chars
  "display_name": "Customer Support Agent", // user-facing, max 50 chars

  // ── LLM models (required) ──────────────────────────────────────
  "business_logic_model_id": 7,      // model used to generate prompts (user must have selected)
  "model_ids": [5, 8],               // up to 5 runtime LLM models (user selections from conversation)

  // ── Task & template (required) ─────────────────────────────────
  "business_description": "A support agent that answers product FAQs...",
  "prompt_template_id": 1,           // 1 = General, 2 = Tool-calling, etc.
  "prompt_template_name": "General", // display name for the template

  // ── Prompt sections (required — derive from conversation) ──────
  "duty_prompt": "You are a helpful customer support agent...",  // role description
  "constraint_prompt": "Only answer questions about our products...", // constraints
  "few_shots_prompt": "Example:\nUser: How do I reset my password?\nAgent: ..." // optional, "" if unused

  // ── UI greeting (required) ──────────────────────────────────────
  "greeting_message": "Hi! I'm your support assistant. What can I help with today?",
  "example_questions": [              // up to 6 starter questions
    "How do I reset my password?",
    "How can I upgrade my plan?",
    "Where can I find my billing history?"
  ],

  // ── Runtime behaviour (use defaults if not discussed) ─────────────
  "max_steps": 15,                   // default 15; override if discussed
  "requested_output_tokens": 2048,   // default 2048; override if discussed
  "provide_run_summary": false,       // default false; set true if user wants summary
  "verification_config": {            // default disabled; enable if discussed
    "enabled": false,
    "mode": "basic"
  },
  "enable_context_manager": true,     // default true

  // ── Resources (required — come from nl2agent_search_* calls) ─
  "selected_tools": [101, 203, 307],  // tool_ids from conversation
  "selected_skills": [5],            // skill_ids from conversation
  "sub_agent_ids": [],               // sub-agent IDs if discussed, else []

  // ── Resource configs (required — per-agent param overrides) ──────────────
  // MCP tools especially need their server_url, api_key, index_names, etc.
  // Shape: { tool_id (int): { param_name: value, ... }, ... }
  "tool_configs": {
    "101": { "server_url": "https://api.example.com", "api_key": "sk-..." },
    "203": { "index_names": ["kb_prod", "kb_faq"] }
  },
  // Shape: { skill_id (int): { config_key: value, ... }, ... }
  "skill_configs": {
    "5": {}
  },

  // ── Meta ──────────────────────────────────────────────────────────
  "description": "A customer support agent for product FAQs and billing questions.",
  "author": ""                        // leave empty; frontend fills from session user
}
```

## How to derive each field

| Field | Source in conversation |
|-------|----------------------|
| `agent_id` | Always pass through from the session context (`draft_agent_id`). |
| `name` | snake_case version of `display_name`. Validate: `/^[a-zA-Z_][a-zA-Z0-9_]*$/`. |
| `display_name` | Extract from any mention of the agent's intended name; default to a sensible title derived from `business_description`. |
| `business_description` | Synthesise from the user's task description in the conversation. |
| `duty_prompt` | What the agent's role is — extract from conversation topic. |
| `constraint_prompt` | What the agent must NOT do — infer from task scope. |
| `few_shots_prompt` | Include only if the user discussed or demonstrated example interactions. Empty string `""` is valid. |
| `greeting_message` | Extract a greeting the user mentioned, or generate one consistent with the agent's role. |
| `example_questions` | Up to 6 follow-up questions the agent might be asked. Derive from the conversation topic. |
| `model_ids` | Look for mentions of "use model X" or LLM selections in the conversation. |
| `business_logic_model_id` | The model used for prompt generation — same as the primary runtime model if not specified separately. |
| `selected_tools` / `selected_skills` | IDs returned by prior `nl2agent_search_*` tool calls in this session. |
| `sub_agent_ids` | Any sub-agent the user explicitly discussed. |
| `tool_configs` | **Critical for MCP tools.** Look for any MCP tool config params the user discussed or set during the session: `server_url`, `api_key`, `index_names`, `rerank_model_name`, `collection_name`, `dataset_ids`, `kds_list`, etc. Each entry is `{ tool_id: { param_name: value, ... } }`. If the user configured a tool via the `ToolConfigModal` during the session, include those values. If not discussed, use an empty object `{}` — the tool will use its catalog defaults. |
| `skill_configs` | Any per-skill runtime config the user discussed: e.g., a skill's custom instruction override. Shape: `{ skill_id: { config_key: value } }`. If nothing discussed, use `{}`. |
| `verification_config`, `enable_context_manager`, `provide_run_summary`, `max_steps`, `requested_output_tokens` | Infer from the complexity of the task: simple FAQ agents get defaults; complex agents may benefit from `verification_config.enabled=true`. |

## Output rules

- Output exactly one fenced JSON block with the tag `nl2agent-finalize`.
- After the block, add one short sentence: "The agent will be published as [display_name]."
- Do NOT call any backend services. All data comes from the conversation.
- If a required field cannot be derived, use a sensible default (documented above).
- `example_questions` must have ≤ 6 items; never more.
- For `tool_configs` and `skill_configs`, use string keys for tool/skill IDs in the JSON (e.g. `"101"` not `101`).
