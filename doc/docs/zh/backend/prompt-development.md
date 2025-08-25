# 提示词开发指南

本指南提供了关于 Nexent 中用于创建不同类型智能体的提示词模板系统的全面信息。`backend/prompts/` 目录中的 YAML 文件定义了各种智能体类型的系统提示词、规划提示词和其他关键提示词组件。

## 文件命名规范

命名格式为 `{agent_type}_agent.yaml`，其中：
- `agent_type`：描述智能体的主要功能或用途（如 manager、search 等）

## 提示词模板结构

每个 YAML 文件包含以下主要部分：

### 1. system_prompt

系统提示词是智能体的核心部分，定义了智能体的角色、能力和行为规范。通常包含以下部分：

- **核心职责**：智能体的主要职责和能力描述
- **执行流程**：智能体执行任务的标准流程和方法
- **可用资源**：智能体可以使用的工具和子智能体列表
- **资源使用要求**：使用不同工具的优先级和策略
- **Python代码规范**：编写代码的规范和约束
- **示例模板**：展示智能体执行任务的示例

### 2. planning

包含用于任务规划的各种提示词：

- **initial_facts**：初始事实收集提示词
- **initial_plan**：初始计划制定提示词
- **update_facts_pre_messages**：更新事实前的提示词
- **update_facts_post_messages**：更新事实后的提示词
- **update_plan_pre_messages**：更新计划前的提示词
- **update_plan_post_messages**：更新计划后的提示词

### 3. managed_agent

定义与子智能体交互的提示词：

- **task**：分配给子智能体的任务提示词
- **report**：子智能体报告结果的提示词

### 4. final_answer

定义最终答案生成的提示词：

- **pre_messages**：生成最终答案前的提示词
- **post_messages**：生成最终答案后的提示词

### 5. tools_requirement

定义工具使用规范和优先级的提示词。

### 6. few_shots

提供少样本学习示例的提示词，帮助智能体更好地理解任务执行方式。

## 模板变量

提示词模板中使用以下特殊变量进行动态替换：

- `{{tools}}`：可用工具列表
- `{{managed_agents}}`：可用子智能体列表
- `{{task}}`：当前任务描述
- `{{authorized_imports}}`：授权导入的Python模块
- `{{facts_update}}`：更新后的事实列表
- `{{answer_facts}}`：已知事实列表
- `{{remaining_steps}}`：剩余执行步骤数

## 可用的提示词模板

### 核心模板

1. **管理器智能体模板**
   - `manager_system_prompt_template.yaml` - 中文版本
   - `manager_system_prompt_template_en.yaml` - 英文版本
   
   这些模板定义了核心管理器智能体，负责协调和调度各种助手和工具来高效解决复杂任务。

2. **被管理智能体模板**
   - `managed_system_prompt_template.yaml` - 中文版本
   - `managed_system_prompt_template_en.yaml` - 英文版本
   
   这些模板定义了专门的智能体，在管理器智能体的协调下执行特定任务。

3. **专业智能体模板**
   - `knowledge_summary_agent.yaml` - 知识总结智能体（中文）
   - `knowledge_summary_agent_en.yaml` - 知识总结智能体（英文）
   - `analyze_file.yaml` - 文件分析智能体（中文）
   - `analyze_file_en.yaml` - 文件分析智能体（英文）

### 工具模板

位于 `utils/` 目录中：

1. **提示词生成模板**
   - `prompt_generate.yaml` - 中文版本
   - `prompt_generate_en.yaml` - 英文版本
   
   这些模板帮助为不同智能体类型生成高效、清晰的提示词。

2. **提示词微调模板**
   - `prompt_fine_tune.yaml` - 中文版本
   - `prompt_fine_tune_en.yaml` - 英文版本
   
   用于微调和优化现有提示词的模板。

3. **标题生成模板**
   - `generate_title.yaml` - 中文版本
   - `generate_title_en.yaml` - 英文版本

   用于为对话生成标题。

## 执行流程

标准智能体执行流程遵循以下模式：

1. **思考**：分析当前任务状态和进展
2. **代码**：编写简单的Python代码
3. **观察**：查看代码执行结果
4. **重复**：继续循环直到任务完成

## 代码规范

在提示词中编写Python代码时：

1. 使用格式 `代码：\n```py\n` 表示可执行代码
2. 使用格式 `代码：\n```code:语言类型\n` 表示仅用于展示的代码
3. 只使用已定义的变量，变量将在多次调用之间持续保持
4. 使用 `print()` 函数让变量信息可见
5. 使用关键字参数进行工具和智能体调用
6. 避免在一轮对话中进行过多的工具调用
7. 只能从授权模块导入：`{{authorized_imports}}`

## 最佳实践

1. **任务分解**：将复杂任务分解为可管理的子任务
2. **专业匹配**：根据智能体专长分配任务
3. **信息整合**：整合不同智能体的输出
4. **效率优化**：避免重复工作
5. **结果评估**：评估智能体返回结果，必要时提供额外指导
