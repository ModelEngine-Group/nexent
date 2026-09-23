# Prompt Development Guide

Nexent packages built-in prompt YAML under `sdk/nexent/core/prompts/`. Backend services collect business data and select templates. The SDK loads resources and renders fields with supplied parameters.

## Files and interfaces

- Localized resources live under `zh/` and `en/`, then in purpose-specific folders such as `agent`, `meta`, `evaluation`, and `tool`. Both languages have matching relative paths. The `meta/` folder contains prompts used to generate prompts, Agent drafts, and skill drafts.
- Agent resources live in `zh/agent/` and `en/agent/`; manager and worker roles use `agent_manager.yaml` and `agent_worker.yaml`. Chat-title generation uses `agent/generate_chat_title.yaml`. Role templates have `system_sections`, role-specific stage fields, and `final_answer`.
- Human interaction, context summary, and answer verification live in each language's `agent/human_interaction.yaml`, `agent/context_summary.yaml`, and `agent/answer_verifier.yaml`. The Chinese context-summary and verifier resources are simple translations of the English originals.
- `load_prompt(language, relative_path)` loads an independent mapping relative to the language directory, for example `load_prompt("zh", "agent/human_interaction")`. The `.yaml` suffix is optional. Use `render_prompt_text(source, parameters)` to render Jinja text with runtime values.
- Backend services call the SDK using the resource language, purpose, and filename. User-defined prompt generation templates remain in the database; their built-in defaults come from SDK YAML.

## Parameters

Callers pass current values to the SDK renderer. Agent configuration or conversation state supplies values such as `duty`, `constraint`, `few_shots`, and delegated tasks. NL2Agent, skill creation, and other workflows supply their tool names, skill drafts, document content, and related values. Missing required Jinja parameters raise an error instead of sending `{{...}}` to the model.

## Extending a template

1. Add YAML to the appropriate language and purpose folder, for example `zh/evaluation/judge.yaml`. Preserve the workflow's field names and placeholders.
2. Use the resource language and relative path at the call site. Existing Agent templates also pass SDK bundle validation. Meta prompts use `meta/nl2agent.yaml` and `meta/nl2skill.yaml`.
3. Add parameter rendering and package resource tests. SDK `pyproject.toml` declares YAML package data in the two-level subdirectories.
4. Run the consuming Backend service tests to verify final message content, language selection, and user template fallback.
