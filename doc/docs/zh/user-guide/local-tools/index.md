# 内置工具

在“智能体配置”的“工具管理”中，添加工具时可以按来源选择。

| 工具来源 | 说明 |
| --- | --- |
| 本地工具 | Nexent 内置工具，涵盖文件操作、搜索、多模态分析、邮件、终端和数据库查询。部分工具需要先配置模型、服务密钥或连接参数。 |
| MCP 服务 | 通过 MCP 接入的工具。先在 Nexent 中添加并启用服务，再按服务选择需要的工具。 |

## 本地工具清单

下表列出 Nexent 随附、可在“本地工具”中手动添加的 **27 项工具**。实际列表受租户配置和工具可用状态影响。部分工具需要补齐参数或配置对应的模型后才能选中。工具名可用于在添加窗口中搜索。

### 文件与目录

文件类工具操作智能体的工作空间，调用时使用工作空间内的相对路径。详细参数见[文件工具](./file-tools.md)。

| 工具 | 用途和操作要点 |
| --- | --- |
| `create_directory` | 创建目录及缺少的父目录。传入 `directory_path`，可用 `permissions` 指定新建目录权限，默认 `755`。已有同名目录会保留。 |
| `create_file` | 创建文本文件并写入 `content`，也会创建缺少的父目录。用 `file_path` 指定目标，默认使用 UTF-8。目标文件已存在时会覆盖内容。 |
| `read_file` | 读取工作空间中的文本文件及文件信息。传入 `file_path`，可通过 `encoding` 指定文件编码。 |
| `list_directory` | 以树形结构列出目录和文件。默认从当前目录开始，最多展开 3 层，可设置 `max_depth`、`show_hidden` 和 `show_size`。 |
| `move_item` | 移动或重命名文件及目录。传入 `source_path` 和 `destination_path`。目标路径已存在时取消移动，原有文件不会被覆盖。 |
| `delete_file` | 按 `file_path` 删除一个文件。清理单个文件时使用此工具。 |
| `delete_directory` | 按 `directory_path` 递归删除整个目录，包括子目录及其中的文件。 |

### 公开网页搜索

这四项工具都接收 `query`。添加时填写对应搜索服务的 API Key，可用 `max_results` 控制结果数。详细参数见[搜索工具](./search-tools.md)。

| 工具 | 用途和操作要点 |
| --- | --- |
| `deepseek_search` | 通过 DeepSeek 检索公开网页并返回可引用的来源。支持用 `site:` 和日期条件限定查询，可用 `only_high_quality` 筛选结果，用 `need_content` 请求正文。 |
| `exa_search` | 通过 Exa 查找与主题相关的公开网页，适合搜集文章、文档和背景资料。填写 `exa_api_key`，可用 `image_filter` 控制图片过滤。 |
| `tavily_search` | 通过 Tavily 查询新闻、近期信息和公开资料。填写 `tavily_api_key`，可用 `image_filter` 控制图片过滤。 |
| `linkup_search` | 通过 Linkup 搜索公开图文资料。填写 `linkup_api_key`，可用 `image_filter` 控制图片过滤。 |

### 外部知识库检索

先配置目标服务的连接信息，再选择智能体可检索的知识库。详细参数见[搜索工具](./search-tools.md)。

| 工具 | 用途和操作要点 |
| --- | --- |
| `datamate_search` | 检索 DataMate 中的文档片段。填写服务地址 `server_url`，选择检索范围 `index_names`，可设置结果数、分数阈值和重排。 |
| `dify_search` | 从 Dify 知识库检索资料。配置服务地址、API Key 和 `dataset_ids`，可选择检索方式、结果数及重排配置。 |
| `ragflow_search` | 从 RAGFlow 数据集检索相关片段。配置服务地址、API Key 和 `dataset_ids`，可设置相似度阈值及向量权重。测试时可通过 `doc_id` 限定文档。 |
| `haotian_search` | 检索昊天知识库。配置知识库列表地址 `list_url`、检索地址 `retrieve_url` 和鉴权信息，选择目标数据集。可调整检索方式、阈值和重排。 |
| `idata_search` | 检索 iData 知识库。配置服务地址、API Key、用户标识和知识空间，选择数据集。测试时使用 `question` 提交问题，可配置结果数和相似度阈值。 |
| `ind_aidp_search` | 检索独立部署的 AIDP 知识库。配置服务地址、API Key、租户 ID 和知识库范围 `kds_list`，可按需设置多模态检索、检索方式和重排。 |

### 文件与多模态分析

分析时提供可访问的资源地址和问题 `query`。可根据工具选择支持对应输入类型的模型。详细参数见[多模态工具](./multimodal-tools.md)。

| 工具 | 用途和操作要点 |
| --- | --- |
| `analyze_text_file` | 从文档中提取文本并按问题分析，可用于总结或针对段落提问。使用 `file_url_list` 提供一个或多个文件，需有可用的长文本模型。 |
| `analyze_image` | 分析图片内容，可用于截图理解、图中文字识别或图表问答。使用 `image_urls_list` 提供图片，需有支持图片输入的模型。 |
| `analyze_video` | 根据问题分析一段视频，可用于概述场景或识别关键动作。使用 `video_url` 提供视频，需有支持视频输入的模型。 |
| `analyze_audio` | 根据问题分析一段音频，可用于整理语音内容或提取要点。使用 `audio_url` 提供音频，需有支持音频输入的模型。 |

### 邮件

收信和发信使用不同的服务器配置。账号、授权码或密码在工具配置中填写。详细参数见[邮件工具](./email-tools.md)。

| 工具 | 用途和操作要点 |
| --- | --- |
| `get_email` | 从 IMAP 邮箱读取邮件。配置 IMAP 地址、端口和账号，调用时可按最近天数 `days` 或发件人 `sender` 筛选，并通过 `max_emails` 限制返回数量。 |
| `send_email` | 通过 SMTP 发送 HTML 邮件。配置 SMTP 地址、端口和账号，调用时传入收件人 `to`、主题 `subject` 和正文 `content`，可选填抄送和密送地址。 |

### 终端

| 工具 | 用途和操作要点 |
| --- | --- |
| `terminal` | 通过 SSH 在已授权的远程主机执行命令并返回输出。配置主机、端口、用户名和密码。可通过 `session_name` 复用同一会话，通过 `timeout` 设置命令超时。连接和测试步骤见[终端工具](./terminal-tool.md)。 |

### 数据库

三项数据库工具都需要配置主机、端口、用户名、密码及数据库名称。调用时传入 `sql`，并可用 `parameters` 绑定参数、用 `max_rows` 限制返回行数。各数据库的参数写法和执行限制见[SQL 工具](./sql-tools.md)。

| 工具 | 用途和操作要点 |
| --- | --- |
| `mysql_database` | 连接 MySQL 并执行 SQL，默认端口为 `3306`。 |
| `postgres_database` | 连接 PostgreSQL 并执行 SQL，默认端口为 `5432`。 |
| `mssql_database` | 连接 Microsoft SQL Server 并执行 SQL，默认端口为 `1433`。 |

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

- `knowledge_base_search` 和 `aidp_search` 分别检索平台管理的本地与 AIDP 知识库。可在智能体的“知识库管理”中配置检索范围。AIDP 的接入方式见[AIDP 知识库对接](../aidp.md)。
- `store_memory` 和 `search_memory` 用于记忆写入与检索，可用性取决于租户记忆设置。
- `upload_to_s3` 和 `download_from_s3` 用于会话附件的对象存储上传与下载。
- `parallel_executor` 用于并行执行任务。
- `create_scheduled_task_proposal` 用于提出定时任务，经会话确认后生效。
- `read_skill_md`、`run_skill_script` 等工具用于加载技能包和执行技能脚本。
