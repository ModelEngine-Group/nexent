# 提示词开发指南

Nexent 将内置提示词 YAML 放在 `sdk/nexent/core/prompts/`。Backend 收集业务数据并选择模板，SDK 加载资源和渲染带参数的字段。

## 文件与接口

- 语言资源位于 `zh/` 和 `en/`，下一层按 `agent`、`meta`、`evaluation`、`tool` 等用途分类。两种语言的相对路径一一对应，文件名不重复语言后缀。`meta/` 保存用于生成提示词、Agent 和技能草稿的元提示词。
- Agent 模板位于 `zh/agent/` 和 `en/agent/`，主、子角色分别使用 `agent_manager.yaml`、`agent_worker.yaml`。聊天标题生成使用 `agent/generate_chat_title.yaml`。主、子角色模板的顶层字段为 `system_sections`、对应角色的阶段字段和 `final_answer`。
- 人在回路、上下文摘要和答案校验策略分别保存在两种语言的 `agent/human_interaction.yaml`、`agent/context_summary.yaml`、`agent/answer_verifier.yaml`。中文摘要和校验策略是对原英文资源的简译。
- `load_prompt(language, relative_path)` 根据语言目录下的相对路径加载独立的模板映射，例如 `load_prompt("zh", "agent/human_interaction")`。路径也可写为 `agent/human_interaction.yaml`。`render_prompt_text(source, parameters)` 渲染带参数的 Jinja 文本。
- Backend 服务按语言、用途和文件名直接调用 SDK。用户自定义提示词生成模板仍由数据库管理，内置默认值来自 SDK YAML。

## 参数

调用方将本轮实际值传给 SDK 渲染接口。Agent 运行时的 `duty`、`constraint`、`few_shots` 和角色任务等值由配置或会话提供。NL2Agent、技能创建及其他工作流也按当前任务传入工具名、技能草稿或文档内容。缺少必需的 Jinja 参数会报错，避免把未渲染的模板占位符原样发给模型。

## 扩展模板

1. 在 SDK 提示词目录的语言和功能子目录添加 YAML，例如 `zh/evaluation/judge.yaml`。保留该工作流现有字段名和占位符。
2. 在调用处使用资源的语言和相对路径；已有 Agent 模板继续通过 SDK 的 bundle 校验。元提示词使用 `meta/nl2agent.yaml` 和 `meta/nl2skill.yaml`。
3. 为动态字段增加参数渲染测试，为资源增加包内加载测试。SDK 的 `pyproject.toml` 声明了两级子目录内的 YAML package data。
4. 用对应 Backend 服务的测试核对最终消息内容、语言选择和用户模板覆盖顺序。
