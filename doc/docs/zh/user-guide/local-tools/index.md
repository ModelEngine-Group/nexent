# 内置工具

在“智能体配置”的“工具管理”中，添加工具时可以按来源选择。

| 工具来源 | 说明 |
| --- | --- |
| 本地工具 | Nexent 内置工具，涵盖文件操作、搜索、多模态分析、邮件、终端和数据库查询。部分工具需要先配置模型、服务密钥或连接参数。 |
| MCP 服务 | 通过 MCP 接入的工具。先在 Nexent 中添加并启用服务，再按服务选择需要的工具。 |

## 本地工具清单

- [文件工具](./file-tools.md)可读取、创建、移动或删除文件与目录，并列出目录结构。
- [邮件工具](./email-tools.md)可通过 IMAP 收取邮件，也可发送 HTML 邮件。
- [搜索工具](./search-tools.md)用于检索本地、AIDP、DataMate、Dify、RAGFlow、昊天和 iData 知识库，或通过 Exa、Tavily、Linkup 和 DeepSeek 搜索公开网页。
- [多模态工具](./multimodal-tools.md)可解析文本文件，分析图片、视频和音频。
- [终端工具](./terminal-tool.md)可通过 SSH 会话连接远程主机并执行命令。
- [SQL 工具](./sql-tools.md)用于连接 MySQL、PostgreSQL 或 SQL Server 执行 SQL 查询。

技能提供完成一类任务的操作指南，可以在“技能管理”中添加。具体操作见[技能仓库](../resource-repository/skill-repository.md)。

## 添加本地工具 {#configure-local-tools}

1. 打开要编辑的智能体，进入[智能体配置](../agent-development/agent-configuration.md#edit-agent)。
2. 在“工具管理”中点击“点击添加工具”，切换到“本地工具”，找到并勾选所需工具。
3. 工具需要参数时，点击齿轮打开配置，填写必填项。可以在配置窗口运行“工具测试”，检查入参和返回结果。
4. 确认选择后，在“工具管理”中检查已添加的工具。

## 添加 MCP 工具 {#configure-mcp-tools}

1. 如果服务尚未接入，从“工具管理”点击“新建工具”，进入 MCP 仓库。按需要选择远程链接、容器化部署或 API 转 MCP，完成服务接入。各方式的参数、认证和连通性检查见[MCP 服务接入](../../integration/integration-in/mcp.md)。
2. 返回智能体配置，在“工具管理”中点击“点击添加工具”，切换到“MCP 服务”。在目标服务中勾选要使用的工具。
3. 按工具要求配置必填参数并确认选择。可以在工具配置窗口运行“工具测试”，再在智能体调试区验证实际调用。

## 系统自动注入的工具

以下工具由平台根据部署配置、用户权限和会话上下文自动装配，使用时无需在工具面板中手动添加。

- `knowledge_base_search` 和 `aidp_search` 分别检索本地与 AIDP 知识库。AIDP 的接入方式见[AIDP 知识库对接](../aidp.md)。
- `store_memory` 和 `search_memory` 用于记忆写入与检索，可用性取决于租户记忆设置。
- `upload_to_s3` 和 `download_from_s3` 用于会话附件的对象存储上传与下载。
- `parallel_executor` 用于并行执行任务。
- `create_scheduled_task_proposal` 用于提出定时任务，经会话确认后生效。
- `read_skill_md`、`run_skill_script` 等工具用于加载技能包和执行技能脚本。
