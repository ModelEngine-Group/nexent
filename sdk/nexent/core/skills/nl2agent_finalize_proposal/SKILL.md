---
name: nl2agent_finalize_proposal
description: Synthesize a confirmed NL2AGENT conversation into a publishable draft-agent preview.
tags:
  - nl2agent
  - agent-builder
  - finalize
---

# NL2AGENT Finalize Proposal

Produce a final preview only after the user explicitly asks to finish.

## Entry conditions

All conditions are required:

- The exact `draft_agent_id` is present in session context.
- A primary platform LLM has been saved.
- At least one local-resource recommendation batch is registered.
- Every registered recommendation batch is `applied` or `skipped`.
- The identity card confirms that the user-facing display name was saved.
- Every installed MCP is either `tools_bound` or `binding_skipped`; a
  `connected` MCP still requires an explicit user decision.

If any condition is missing, do not emit a finalize card. Ask the user to complete the corresponding platform card.

## Authoritative state

Persisted backend state is authoritative for models, tools, skills, MCP bindings, and their configuration. Recommended IDs are not selected IDs. Never copy IDs from search results, invent IDs, reconstruct secrets, or claim that a resource is installed or bound based on conversation text. Never include MCP configuration or MCP IDs in the finalize proposal.

The backend owns both persisted identity and the generated internal variable name. Never ask for, derive, or output `name` or `display_name`.

## Output

Output exactly one `nl2agent-finalize` fenced JSON block, followed by one short sentence. Use this schema:

```nl2agent-finalize
{
  "agent_id": 123,
  "description": "A concise user-facing description.",
  "business_description": "The confirmed task and scope.",
  "prompt_template_id": 1,
  "prompt_template_name": "General",
  "duty_prompt": "The agent role and responsibilities.",
  "constraint_prompt": "Confirmed scope and safety constraints.",
  "few_shots_prompt": "",
  "greeting_message": "A role-appropriate greeting.",
  "example_questions": [],
  "max_steps": 15,
  "requested_output_tokens": 2048,
  "provide_run_summary": false,
  "verification_config": {"enabled": false, "mode": "basic"},
  "enable_context_manager": true,
  "sub_agent_ids": [],
  "author": ""
}
```

Do not include `name`, `display_name`, model IDs, selected tool or skill IDs, `tool_configs`, or `skill_configs`. The review card loads identity, models, and resources from the read-only session-state endpoint.

Use at most six example questions. Do not call backend services from this skill.
