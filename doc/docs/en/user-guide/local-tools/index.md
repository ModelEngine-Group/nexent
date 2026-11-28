# Built-in Tools

When adding a tool in the agent's configuration panel, choose a source.

| Source | Description |
| --- | --- |
| Local Tools | Tools included with Nexent for file operations, search, multimodal analysis, email, terminal access, and database queries. Some tools require a model, API key, or connection settings. |
| MCP Service | Tools supplied by an MCP service. Connect and enable the service in Nexent, then choose its tools. |

## Local tool catalog

Nexent includes **27 tools** that you can add manually from **Local Tools**. The tools you see depend on your tenant configuration and tool availability. Some tools require parameters or a suitable model before they can be selected. Search by tool name in the picker.

### Files and directories

File tools use paths relative to the agent's workspace. See [File Tools](./file-tools.md) for details.

| Tool | What it does |
| --- | --- |
| `create_directory` | Creates a directory and any missing parent directories using `directory_path`. Set `permissions` to change the default of `755`. Existing directories are preserved. |
| `create_file` | Writes `content` to `file_path` and creates missing parent directories. The default encoding is UTF-8. An existing file at the target path is overwritten. |
| `read_file` | Reads a workspace text file and its metadata. Provide `file_path` and optionally specify `encoding`. |
| `list_directory` | Lists files and directories as a tree. It defaults to the current directory and a depth of three levels. Adjust `max_depth`, `show_hidden`, or `show_size` as needed. |
| `move_item` | Moves or renames a file or directory using `source_path` and `destination_path`. The move stops if the destination already exists. |
| `delete_file` | Deletes the file at `file_path`. |
| `delete_directory` | Recursively deletes the directory at `directory_path`, including all subdirectories and files. |

### Public web search

Each tool accepts a `query` and requires the corresponding service's API key. Use `max_results` to set the result limit. See [Search Tools](./search-tools.md).

| Tool | What it does |
| --- | --- |
| `deepseek_search` | Finds public web sources through DeepSeek. Use `site:` or date filters to narrow the search, `only_high_quality` to filter results, and `need_content` to request page content. |
| `exa_search` | Finds related articles, documents, and background material through Exa. Configure `exa_api_key` and optionally set `image_filter`. |
| `tavily_search` | Finds recent news and public information through Tavily. Configure `tavily_api_key` and optionally set `image_filter`. |
| `linkup_search` | Finds public text and image sources through Linkup. Configure `linkup_api_key` and optionally set `image_filter`. |

### External knowledge base retrieval

Set up the connection to the target service, then choose the knowledge bases the agent can search. See [Search Tools](./search-tools.md).

| Tool | What it does |
| --- | --- |
| `datamate_search` | Retrieves document excerpts from DataMate. Set `server_url` and `index_names`. You can adjust result count, score threshold, and reranking. |
| `dify_search` | Retrieves material from Dify knowledge bases. Set the service address, API key, and `dataset_ids`. You can adjust retrieval mode, result count, and reranking. |
| `ragflow_search` | Retrieves excerpts from RAGFlow datasets. Set the service address, API key, and `dataset_ids`. You can adjust similarity threshold and vector weight, or use `doc_id` during testing. |
| `haotian_search` | Searches Haotian knowledge bases. Set `list_url`, `retrieve_url`, and authentication details, then select the datasets. You can adjust retrieval mode, thresholds, and reranking. |
| `idata_search` | Searches iData knowledge bases. Set the service address, API key, user ID, and knowledge space, then select datasets. Submit a test question using `question` and optionally set result count and similarity threshold. |
| `ind_aidp_search` | Searches a standalone AIDP deployment. Set the service address, API key, tenant ID, and `kds_list`. You can configure multimodal retrieval, search mode, and reranking. |

### File and multimodal analysis

Provide an accessible resource URL and a question in `query`. Use a model that supports the input type. See [Multimodal Tools](./multimodal-tools.md).

| Tool | What it does |
| --- | --- |
| `analyze_text_file` | Extracts and analyzes document text for tasks such as summarization or questions about specific passages. Provide one or more URLs in `file_url_list` and configure a model that supports long text. |
| `analyze_image` | Analyzes screenshots, reads text in images, or answers questions about charts. Provide `image_urls_list` and a model that accepts images. |
| `analyze_video` | Answers questions about a video, summarizes scenes, or identifies actions. Provide `video_url` and a model that accepts video. |
| `analyze_audio` | Answers questions about audio or extracts key points. Provide `audio_url` and a model that accepts audio. |

### Email

Receiving and sending email use separate server settings. Configure the account and its authorization code or password in the tool settings. See [Email Tools](./email-tools.md).

| Tool | What it does |
| --- | --- |
| `get_email` | Reads mail from an IMAP mailbox. Configure the IMAP address, port, and account. Use `days` or `sender` to filter messages and `max_emails` to limit results. |
| `send_email` | Sends HTML mail via SMTP. Configure the SMTP address, port, and account. Provide `to`, `subject`, and `content`, with optional CC and BCC recipients. |

### Terminal

| Tool | What it does |
| --- | --- |
| `terminal` | Runs commands on an authorized remote host over SSH and returns their output. Configure the host, port, username, and password. Use `session_name` to reuse a session and `timeout` to set the command timeout. See [Terminal Tool](./terminal-tool.md). |

### Database

Configure the host, port, username, password, and database name. Provide the query in `sql`, bind values with `parameters`, and limit the result size with `max_rows`. See [SQL Tools](./sql-tools.md).

| Tool | What it does |
| --- | --- |
| `mysql_database` | Executes SQL against MySQL on port `3306` by default. |
| `postgres_database` | Executes SQL against PostgreSQL on port `5432` by default. |
| `mssql_database` | Executes SQL against Microsoft SQL Server on port `1433` by default. |

Skills provide instructions for completing a type of task and are added separately from tools. See [Skill Repository](../resource-repository/skill-repository.md).

## Add local tools {#configure-local-tools}

1. Open the agent's [Configuration](../agent-configuration.md#edit-agent).
2. Under **Tools**, click **Add a tool**, select **Local Tools**, and choose the tools you need.
3. If a tool needs parameters, click its settings icon and fill in the required fields. Run a tool test in the configuration dialog to check the inputs and results.
4. Confirm the selection and check the tools list.

## Add MCP tools {#configure-mcp-tools}

1. If the service is new, click **New tool** under **Tools** to open the MCP repository. Connect a remote service, deploy a containerized service, or convert an API to MCP. See [MCP Integration](../../integration/integration-in/mcp.md) for parameters, authentication, and connectivity checks.
2. Return to the agent configuration, click **Add a tool**, and switch to **MCP Service**. Expand the connected service and select the tools you need.
3. Fill in the required parameters and confirm. Test the tool in its configuration dialog, then verify the call in agent debugging.

## System-injected tools

Nexent adds the following tools at runtime based on deployment settings, user permissions, and conversation context.

- `knowledge_base_search` and `aidp_search` retrieve information from platform-managed local and AIDP knowledge bases. Set the retrieval scope in the agent's knowledge base settings. See [AIDP Integration](../aidp.md).
- `store_memory` and `search_memory` write and retrieve memories. Availability depends on the tenant's memory settings.
- `upload_to_s3` and `download_from_s3` transfer conversation attachments to and from object storage.
- `parallel_executor` runs tasks in parallel.
- `create_scheduled_task_proposal` proposes a scheduled task that takes effect after confirmation in the conversation.
- `read_skill_md` and `run_skill_script` load skill packages and run skill scripts.
