# 概览

内置工具为智能体提供与工作空间、远程主机、外部服务交互的能力，涵盖文件操作、邮件、搜索、多模态与远程终端。每个工具都有独立页面，按功能分组说明使用方式与注意事项。

## 📂 目录

- [文件工具](./file-tools)：创建/读取/移动/删除文件与目录，树形列目录。
- [邮件工具](./email-tools)：收取 IMAP 邮件，发送 HTML 邮件（支持抄送/密送）。
- [搜索工具](./search-tools)：本地/AIDP/DataMate/Dify/RAGFlow/昊天/iData 知识库检索与 Exa/Tavily/Linkup/DeepSeek 公网搜索。
- [多模态工具](./multimodal-tools)：文本文件与图片的下载、解析、模型分析。
- [终端工具](./terminal-tool)：持久化 SSH 会话，远程执行命令。
- [SQL 工具](./sql-tools)：连接 MySQL、PostgreSQL、SQL Server 执行 SQL 查询。
- [技能（Skills）](../resource-repository/skill-repository.md)：Nexent内置工具组合或自定义能力包，支持 NL 生成与版本管理。

## ⚙️ 配置入口

1. 打开 **[智能体配置](../agent-development/agent-configuration)** 页面。
2. 在工具管理中将工具添加到智能体，点击工具行的「配置」。
3. 填写连接或鉴权参数，保存并启用，建议先进行测试连接。

## 🤖 系统自动注入的工具

除上述可在工具面板中手动添加的工具外，平台还会在运行期**自动注入**一批系统托管工具，它们不出现在工具面板中，也无需手动配置：

- `knowledge_base_search` / `aidp_search`：本地与 AIDP 知识库检索，按部署开关与用户权限自动装配（见 [AIDP 知识库对接](../aidp)）
- `store_memory` / `search_memory`：智能体记忆的写入与检索（受租户记忆设置门控）
- `upload_to_s3` / `download_from_s3`：会话附件的对象存储上传与下载
- `parallel_executor`：多任务并行执行
- `create_scheduled_task_proposal`：自动任务的定时提案（经会话确认后生效）
- 技能运行时工具（`read_skill_md`、`run_skill_script` 等）：技能包的加载与脚本执行

这些工具由系统管理，参数与可用性随部署配置和运行上下文变化，无需在智能体配置中干预。

## 💡 使用建议

- 路径类操作仅限工作空间范围，请使用相对路径。
- 公网搜索需先在平台安全配置中填写 API Key。
- 终端工具涉及远程主机，请确认网络与账号安全策略。
- 删除、移动类操作不可恢复，执行前先确认目标。
