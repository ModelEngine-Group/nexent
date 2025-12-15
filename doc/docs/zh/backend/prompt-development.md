# 提示词开发指南

本指南说明 `backend/prompts/` 下提示词模板的组织方式，以及如何为新智能体扩展模板。

## 📂 文件布局与命名

- 核心模板位于 `backend/prompts/`，通常命名为 `{agent_type}_agent.yaml` 或 `{scope}_prompt_template.yaml`。
- 工具类/辅助模板位于 `backend/prompts/utils/`，用于元提示生成（如标题、提示词生成）。

## 🧩 模板结构

常见字段：
- `system_prompt`：角色/职责、执行流程、工具与子智能体使用规则、Python 代码约束、示例。
- `planning`：`initial_facts`、`initial_plan` 及更新前后提示。
- `managed_agent`：分配与汇报的子智能体提示。
- `final_answer`：生成最终答案前后提示。
- `tools_requirement`：工具使用优先级与规范。
- `few_shots`：少样本示例。

## 🔄 变量占位

模板中常用占位符：
- `tools`、`managed_agents`
- `task`、`remaining_steps`
- `authorized_imports`
- `facts_update`、`answer_facts`

## 📑 关键模板

- 管理器智能体：`manager_system_prompt_template.yaml`、`manager_system_prompt_template_en.yaml`
- 被管理智能体：`managed_system_prompt_template.yaml`、`managed_system_prompt_template_en.yaml`
- 知识总结：`knowledge_summary_agent.yaml`、`knowledge_summary_agent_en.yaml`
- 文件分析：`analyze_file.yaml`、`analyze_file_en.yaml`
- 聚类总结：`cluster_summary_agent.yaml`、`cluster_summary_reduce.yaml`（含 `_zh` 版本）
- 工具/生成辅助（`utils/`）：`prompt_generate*.yaml`、`generate_title*.yaml`

## 🚀 如何扩展

1. 选取最相近模板复制，调整 `system_prompt`/`planning` 适配场景。
2. 保留必要占位符，除非明确不需要。
3. 工具列表需与实际可用工具一致，必要时更新 `authorized_imports`。
4. 用小任务验证“思考 → 代码 → 观察 → 重复”流程是否符合预期。

## ✅ 规范与提示

- 可执行代码块使用 ````py````，仅展示代码用 ````code:语言````。
- 工具调用尽量用关键字参数，单轮避免过多工具调用。
- 注释/文档保持英文，遵守仓库规则与授权导入限制。
