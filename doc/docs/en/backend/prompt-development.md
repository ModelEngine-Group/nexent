# Prompt Development Guide

This guide explains how Nexent prompt templates are organized under `backend/prompts/` and how to extend them for new agents.

## 📂 File Layout & Naming

- Core templates live in `backend/prompts/`, split by language into paired `{name}_zh.yaml` and `{name}_en.yaml` files (e.g., `manager_system_prompt_template_zh.yaml` / `manager_system_prompt_template_en.yaml`). The mapping from template type to file is centralized in `backend/utils/prompt_template_utils.py`.
- Utility templates are under `backend/prompts/utils/` for meta generation (e.g., titles, prompt generation, greetings, regex guardrails).
- Evaluation-related templates live in `backend/prompts/evaluation/` (evaluator generation, case generation, judging, report analysis, etc.).

## 🧩 Template Structure

Common top-level fields for agent templates (manager/managed):
- `managed_agent`: `task` and `report` prompts for sub-agents.
- `planning`: `initial_plan`, `update_plan_pre_messages`, `update_plan_post_messages`.
- `final_answer`: `pre_messages` / `post_messages` (summary prompts when the maximum number of steps is reached).
- `verification`: `pre_messages` / `post_messages` for answer verification.

The agent's role/constraint/few-shot content (`duty`, `constraint`, `few_shots`) is injected into the template as variables by the backend at render time, rather than kept in separate files (see `render_kwargs` in `backend/agents/create_agent_info.py`).

## 🔄 Variables

Common placeholders in templates:
- `{{name}}`, `{{task}}`, `{{final_answer}}`
- Render variables: `tools`, `managed_agents`, `skills`, `external_a2a_agents`
- Render variables: `duty`, `constraint`, `few_shots`
- Render variables: `memory_list`, `knowledge_base_summary`, `APP_NAME`, `APP_DESCRIPTION`, `user_id`

## 📑 Key Templates

- Manager agents: `manager_system_prompt_template_zh.yaml`, `manager_system_prompt_template_en.yaml`
- Managed agents: `managed_system_prompt_template_zh.yaml`, `managed_system_prompt_template_en.yaml`
- Document summary: `document_summary_agent_zh.yaml`, `document_summary_agent_en.yaml`
- Cluster reduce: `cluster_summary_reduce_zh.yaml`, `cluster_summary_reduce_en.yaml`
- NL2Agent: `nl2agent_zh.yaml`, `nl2agent_en.yaml`
- Agent automation: `agent_automation_zh.yaml`, `agent_automation_en.yaml`
- Skill creation: `skill_creation_simple_*.yaml`, `skill_creation_complicate_*.yaml`
- Utilities (`utils/`): `prompt_generate*.yaml`, `prompt_optimize*.yaml`, `generate_title*.yaml`, `greeting_generate*.yaml`, `guardrail_regex*.yaml`
- Evaluation (`evaluation/`): `generate_evaluator*.yaml`, `generate_cases_system*.yaml`, `judge_system*.yaml`, `error_explain*.yaml`, `analyze_report*.yaml`, `plan_kb_queries*.yaml`

## 🚀 How to Extend

1. Copy the closest existing template, create paired `{name}_zh.yaml` / `{name}_en.yaml` files, and register the mapping in `template_paths` in `backend/utils/prompt_template_utils.py`.
2. Keep placeholders intact unless intentionally removed.
3. Align tool lists with the actual tools available to the agent.
4. Validate with a small task to ensure flows (`Think → Code → Observe → Repeat`) produce the expected behavior.

## ✅ Standards & Tips

- Use executable code fences for runnable snippets: ````py````, and display-only fences for non-executable examples.
- Prefer keyword args for tool calls; avoid excessive tool invocations per step.
- Keep comments and docstrings in English and follow repository rules.
