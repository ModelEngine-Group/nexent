# Overview

Local tools let agents interact with the workspace, remote hosts, and external services across files, email, search, multimodal, and remote terminals. Each tool has its own page grouped by capability.

## 📂 Directory

- [File Tools](./file-tools): Create/read/move/delete files and folders; list directory trees.
- [Email Tools](./email-tools): Receive IMAP mail; send HTML mail with CC/BCC.
- [Search Tools](./search-tools): Local/DataMate KB search plus Exa/Tavily/Linkup web search.
- [Multimodal Tools](./multimodal-tools): Download/parse/analyze text files and images.
- [Terminal Tool](./terminal-tool): Persistent SSH sessions for remote commands.
- [SQL Tools](./sql-tools): Connect to MySQL, PostgreSQL, SQL Server to execute SQL queries.
- [Skills](../skills): Nexent's built-in tool combinations or custom capability packs with NL generation and version management.

## ⚙️ Configuration Entry

1. Go to **[Agent Development](../agent-development)**.
2. In “Select Agent Tools,” find the tool and open configuration.
3. Fill connection/auth parameters, save, and run a test connection first.

## 💡 Usage Tips

- File paths must stay inside the workspace and use relative paths.
- Set API keys for public search in the platform’s secure config.
- Terminal access touches remote hosts—confirm network and account controls.
- Delete/move operations are irreversible; double-check targets first.

Need help? Open a thread in [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions).
