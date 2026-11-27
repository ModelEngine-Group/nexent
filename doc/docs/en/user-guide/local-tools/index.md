# Overview

Local tools let agents interact with the workspace, remote hosts, and external services across files, email, search, multimodal, and remote terminals. Each tool has its own page grouped by capability.

## 📂 Directory

- [File Tools](./file-tools): Create/read/move/delete files and folders; list directory trees.
- [Email Tools](./email-tools): Receive IMAP mail; send HTML mail with CC/BCC.
- [Search Tools](./search-tools): Local/AIDP/DataMate/Dify/RAGFlow/Haotian/iData KB search plus Exa/Tavily/Linkup/DeepSeek web search.
- [Multimodal Tools](./multimodal-tools): Download/parse/analyze text files and images.
- [Terminal Tool](./terminal-tool): Persistent SSH sessions for remote commands.
- [SQL Tools](./sql-tools): Connect to MySQL, PostgreSQL, SQL Server to execute SQL queries.
- [Skills](../resource-repository/skill-repository.md): Nexent's built-in tool combinations or custom capability packs with NL generation and version management.

## ⚙️ Configuration Entry

1. Go to **[Agent Configuration](../agent-development/agent-configuration)**.
2. Add the tool to the agent in tool management and select Configure on its row.
3. Fill connection/auth parameters, save, and run a test connection first.

## 🤖 System-injected tools

Besides the tools above that can be added manually from the tool pool, the platform also **injects** a set of system-managed tools at runtime. They do not appear in the tool pool and require no manual configuration:

- `knowledge_base_search` / `aidp_search`: local and AIDP knowledge retrieval, assembled automatically by the deployment switch and user permissions (see [AIDP Integration](../aidp))
- `store_memory` / `search_memory`: agent memory writing and retrieval (gated by tenant memory settings)
- `upload_to_s3` / `download_from_s3`: object storage upload and download for conversation attachments
- `parallel_executor`: parallel execution of multiple tasks
- `create_scheduled_task_proposal`: scheduled-task proposals for agent tasks (effective after confirmation in the conversation)
- Skill runtime tools (`read_skill_md`, `run_skill_script`, etc.): skill package loading and script execution

These tools are system-managed; their parameters and availability follow the deployment configuration and runtime context, with no intervention needed in agent configuration.

## 💡 Usage Tips

- File paths must stay inside the workspace and use relative paths.
- Set API keys for public search in the platform’s secure config.
- Terminal access touches remote hosts—confirm network and account controls.
- Delete/move operations are irreversible; double-check targets first.

Need help? Open a thread in [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions).
