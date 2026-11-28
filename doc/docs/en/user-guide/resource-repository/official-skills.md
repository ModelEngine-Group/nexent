---
title: Official Skills
---

# Official Skills

Nexent ships with a set of ready-to-install official skills. Once installed, you can enable the corresponding capabilities in an agent's skill configuration and fill in skill parameters as needed.

## Skill list

### Document generation

| Skill Name | Description |
| ---------- | ----------- |
| `docx` | Create, read, and edit Word documents with revision and formatting support |
| [`create-docx`](./create-docx.md) | Generate Word documents from structured content specifications and return downloadable file artifacts |
| `pdf` | Read, create, merge, and split PDF files |
| `pptx` | Create and edit PowerPoint presentations |
| `xlsx` | Create and edit Excel spreadsheets with formulas and data analysis |
| `create-excel` | Generate Excel workbooks from structured content specifications |

### Design and frontend

| Skill Name | Description |
| ---------- | ----------- |
| `canvas-design` | Create PNG/PDF visual artwork using design philosophy |
| `frontend-design` | Distinctive visual design guidance when building or reshaping UIs |
| `web-artifacts-builder` | Build elaborate multi-component web pages with modern frontend technologies |
| `slack-gif-creator` | Create animated GIFs optimized for Slack |

### Search and retrieval

| Skill Name | Description |
| ---------- | ----------- |
| `search-knowledge-base` | Search the Nexent local knowledge base with hybrid, accurate, and semantic modes |
| `search-dify` | Search Dify knowledge bases with keyword, semantic, full-text, and hybrid modes |
| `search-datamate` | Search DataMate knowledge bases with similarity threshold control |
| `search-idata` | Search iData knowledge bases |
| `search-web-tavily` | Real-time web search with Tavily |
| `search-web-linkup` | Mixed image-and-text web search with Linkup |
| `search-web-exa` | Deep web search with Exa |

### Multimodal analysis

| Skill Name | Description |
| ---------- | ----------- |
| `analyze-image` | Analyze image content and answer questions with a vision language model |
| `analyze-text-file` | Extract and analyze content from PDF, Word, Excel, and other files |

### Communication and terminal

| Skill Name | Description |
| ---------- | ----------- |
| `email-utils` | Fetch email via IMAP and send email via SMTP, with HTML, CC, and BCC support |
| `run-shell-ssh` | Execute shell commands on remote terminals over SSH, with session management |

### Development tools

| Skill Name | Description |
| ---------- | ----------- |
| `mcp-builder` | Create high-quality MCP servers that let LLMs integrate with external systems |
| `skill-creator` | Create new skills, improve existing skills, and measure skill performance |

## Install and use

1. As a super administrator or tenant administrator, open the **Resource Management** page and go to the "Skills" tab.
2. Select **Install official skills** to view the available official skills and their status in the dialog (installed skills are labeled).
3. Choose the skills you need and complete the installation.
4. Enable the installed skills in an agent's skill list.
5. Fill in the parameters required by each skill and save the configuration.

> 💡 When a new tenant is created, the system automatically installs the official skills for the tenant — no manual action needed.

For specific parameters and invocation constraints, refer to the `SKILL.md` inside each skill package.

## Custom file generation Skill

To extend the Word capabilities of the official `create-docx` skill, or to develop custom skills that generate Markdown, PDF, spreadsheets, presentations, and other files, see the [Custom File Generation Skill Guide](./custom-file-generation-skill.md).

## Related documents

- [Skill Space](./skill-repository.md)
- [Skills System Overview](/en/backend/skills/overview)
- [Agent Configuration](../agent-configuration.md)
