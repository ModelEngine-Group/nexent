# Prompt Development Guide

This guide explains how Nexent prompt templates are organized under `backend/prompts/` and how to extend them for new agents.

## 📂 File Layout & Naming

- Core templates live in `backend/prompts/` using `{agent_type}_agent.yaml` or `{scope}_prompt_template.yaml`.
- Utility templates are under `backend/prompts/utils/` for meta generation (e.g., prompt/title helpers).

## 🧩 Template Structure

Each YAML may contain:
- `system_prompt`: role, responsibilities, execution flow, tool/sub-agent usage rules, Python code constraints, and examples.
- `planning`: `initial_facts`, `initial_plan`, update hooks before/after facts or plans.
- `managed_agent`: prompts for delegating tasks and collecting reports from sub-agents.
- `final_answer`: pre/post messages to shape final output.
- `tools_requirement`: priorities and guardrails for tool usage.
- `few_shots`: examples to steer behavior.

## 🔄 Variables

Common placeholders for runtime rendering:
- `tools`, `managed_agents`
- `task`, `remaining_steps`
- `authorized_imports`
- `facts_update`, `answer_facts`

## 📑 Key Templates

- Manager agents: `manager_system_prompt_template.yaml`, `manager_system_prompt_template_en.yaml`
- Managed agents: `managed_system_prompt_template.yaml`, `managed_system_prompt_template_en.yaml`
- Knowledge summary: `knowledge_summary_agent.yaml`, `knowledge_summary_agent_en.yaml`
- File analysis: `analyze_file.yaml`, `analyze_file_en.yaml`
- Cluster summary: `cluster_summary_agent.yaml`, `cluster_summary_reduce.yaml` (and `_zh` variants)
- Utilities (`utils/`): `prompt_generate*.yaml`, `generate_title*.yaml`

## 🚀 How to Extend

1. Copy the closest existing template and adjust `system_prompt`/`planning` for your scenario.
2. Keep placeholders intact unless intentionally removed.
3. Align tool lists with actual tools available to the agent; update `authorized_imports` if needed.
4. Validate with a small task to ensure flows (`Think → Code → Observe → Repeat`) produce the expected behavior.

## ✅ Standards & Tips

- Use executable code fences for runnable snippets: ````py````, and display-only fences for non-executable examples.
- Prefer keyword args for tool calls; avoid excessive tool invocations per step.
- Keep comments and docstrings in English and respect repository coding rules.
