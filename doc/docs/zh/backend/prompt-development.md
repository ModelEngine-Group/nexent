# 提示词开发指南

本指南说明 `backend/prompts/` 下提示词模板的组织方式，以及如何为新智能体扩展模板。

## 📂 文件布局与命名

- 核心模板位于 `backend/prompts/`，统一按语言拆分为 `{name}_zh.yaml` 与 `{name}_en.yaml` 成对文件（如 `manager_system_prompt_template_zh.yaml` / `manager_system_prompt_template_en.yaml`）。模板类型到文件的映射集中在 `backend/utils/prompt_template_utils.py`。
- 工具类/辅助模板位于 `backend/prompts/utils/`，用于元提示生成（如标题、提示词生成、问候语、正则护栏）。
- 评测相关模板位于 `backend/prompts/evaluation/`（评测器生成、用例生成、判分、报告分析等）。

## 🧩 模板结构

智能体模板（manager/managed）常见顶层字段：
- `managed_agent`：子智能体的 `task` 与 `report` 提示。
- `planning`：`initial_plan`、`update_plan_pre_messages`、`update_plan_post_messages`。
- `final_answer`：`pre_messages` / `post_messages`（达到最大步数时的总结提示）。
- `verification`：答案校验的 `pre_messages` / `post_messages`。

智能体的角色/约束/少样本内容（`duty`、`constraint`、`few_shots`）由后端在渲染时作为变量注入模板，不单独成文件（见 `backend/agents/create_agent_info.py` 中的 `render_kwargs`）。

## 🔄 变量占位

模板中常用占位符：
- `{{name}}`、`{{task}}`、`{{final_answer}}`
- 渲染变量：`tools`、`managed_agents`、`skills`、`external_a2a_agents`
- 渲染变量：`duty`、`constraint`、`few_shots`
- 渲染变量：`memory_list`、`knowledge_base_summary`、`APP_NAME`、`APP_DESCRIPTION`、`user_id`

## 📑 关键模板

- 管理器智能体：`manager_system_prompt_template_zh.yaml`、`manager_system_prompt_template_en.yaml`
- 被管理智能体：`managed_system_prompt_template_zh.yaml`、`managed_system_prompt_template_en.yaml`
- 文档总结：`document_summary_agent_zh.yaml`、`document_summary_agent_en.yaml`
- 聚类归并：`cluster_summary_reduce_zh.yaml`、`cluster_summary_reduce_en.yaml`
- NL2Agent：`nl2agent_zh.yaml`、`nl2agent_en.yaml`
- 智能体自动化：`agent_automation_zh.yaml`、`agent_automation_en.yaml`
- 技能创建：`skill_creation_simple_*.yaml`、`skill_creation_complicate_*.yaml`
- 工具/生成辅助（`utils/`）：`prompt_generate*.yaml`、`prompt_optimize*.yaml`、`generate_title*.yaml`、`greeting_generate*.yaml`、`guardrail_regex*.yaml`
- 评测（`evaluation/`）：`generate_evaluator*.yaml`、`generate_cases_system*.yaml`、`judge_system*.yaml`、`error_explain*.yaml`、`analyze_report*.yaml`、`plan_kb_queries*.yaml`

## 🚀 如何扩展

1. 选取最相近模板复制，按 `{name}_zh.yaml` / `{name}_en.yaml` 成对创建，并在 `backend/utils/prompt_template_utils.py` 的 `template_paths` 中注册映射。
2. 保留必要占位符，除非明确不需要。
3. 工具列表需与实际可用工具一致。
4. 用小任务验证"思考 → 代码 → 观察 → 重复"流程是否符合预期。

## ✅ 规范与提示

- 可执行代码块使用 ````py````，仅展示代码用 ````code:语言````。
- 工具调用尽量用关键字参数，单轮避免过多工具调用。
- 注释/文档保持英文，遵守仓库规则。
