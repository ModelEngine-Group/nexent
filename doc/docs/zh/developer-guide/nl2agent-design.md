# NL2AGENT 设计说明

NL2AGENT 是智能体配置页内的对话式生成助手。它不会出现在普通聊天的智能体列表或历史会话列表中。

## 页面与会话绑定

用户在智能体配置页点击“智能体生成助手”后，原两列配置区扩展为三列：左列复用 `newchat` 的消息、流式请求和 Markdown 渲染组件，中列和右列保持原有配置界面。生成会话进行时，配置列只读；最终卡片应用成功后，页面重新读取 Draft，实时刷新两列并恢复手工编辑。

每个会话在 PostgreSQL 中同时绑定 `draft_agent_id`、内部 runner 的 `runner_agent_id` 和 `conversation_id`。配置页按 `draft_agent_id` 查询会话，因此重新打开同一智能体时会从数据库恢复对应聊天与工作流，而不依赖浏览器存储。内部 conversation 由普通历史查询排除。

## 信任边界

LLM 仅在最终答案中提出 fenced JSON 卡片。前端先按共享 JSON Schema 校验，再注册载荷并发送渲染回执。后端只接受最新、已完整持久化的 assistant message 的回执；搜索推荐还必须匹配 SDK 搜索工具预先落库的可信批次。工作流阶段只能由卡片动作推进，聊天文本不能越过确认步骤。

PostgreSQL 是会话与目录快照的权威存储，工作流修改使用 revision CAS。Redis 仅保存可重建投影和安装锁。

## 前端挂载点

- `Nl2AgentEmbeddedChat` 为配置页创建固定 conversation 的 `useLocalRuntime`，并复用 newchat 的 `Thread`、附件适配器、历史适配器和远程模型适配器。
- `MarkdownTextPrimitive.componentsByLanguage` 将九种 `nl2agent-*` fence 交给卡片注册表；流式阶段显示占位，历史卡片只读，只有最新完成消息可交互。
- `Nl2AgentWorkflowProvider` 管理卡片动作、输入锁、隐藏续聊、失败重试和 session state 刷新。
- 自动续聊哨兵在实时消息与历史恢复映射中同时过滤。
- 旧聊天和分享页仅展示无副作用的静态卡片摘要，不暴露 JSON。

## 生命周期

工作流包含需求收集、需求确认、模型选择、本地资源搜索与确认、在线资源搜索与确认、身份配置和最终检查。finalize 只把持久态写入 Draft 并结束生成会话，不创建发布版本。用户可在配置页继续手工编辑，或从只读聊天顶部重新开启调整。

删除 Draft 会同时软删除绑定 session 和内部 conversation；删除 conversation 会将活动 session 标记为 abandoned。完成态 session 随智能体保留，用于之后恢复生成记录。
