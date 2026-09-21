# Skills System Overview

A Skill is Nexent's way of extending an agent's capabilities. Each skill consists of:

- **Skill description**: What this skill does and when to use it
- **Tool bundle**: A package of one or more Nexent SDK methods or user-defined tools
- **Parameter template**: Which parameters users can fill in for this skill
- **Usage examples**: How this skill is typically used

Compared to selecting tools one by one, skills make configuring complex capabilities simple — install one skill package instead of configuring each tool separately.

## Skill Package Structure

A skill can be a single `SKILL.md` file or a ZIP package with multiple files:

```
skill-name/
├── SKILL.md              # Skill definition file (required)
├── config/
│   ├── config.yaml       # Default parameter values (optional)
│   └── schema.yaml        # Parameter types and descriptions (optional)
├── scripts/
│   └── *.py               # Python scripts (optional)
├── examples.md            # Usage examples (optional)
└── assets/                # Static assets (optional)
```

### SKILL.md Structure

Each skill must have a `SKILL.md` file, consisting of two parts:

**Part 1: YAML Frontmatter (required)**

```yaml
---
name: skill-name           # Required: skill name, must be unique
description: |             # Required: description of what the skill does
  A description of what this skill does and when to use it.
  Write in third person, e.g., "This skill is used for..."
allowed-tools:             # Optional: list of nexent sdk methods or tool names exposed by tool skills
  - read_file
  - write_file
tags:                      # Optional: skill tags for categorization and retrieval
  - tag1
  - tag2
# script_outputs:          # Optional: declared script outputs for script-based skills
#   scripts/generate.py:   #   (e.g., location and MIME type of generated files)
#     kind: file
#     mime_types:
#       - text/plain
# Other extra fields (such as output_type / output_mime_types) are per-skill extensions
---
```

**Part 2: Skill Body**

Below the frontmatter, you can write Markdown content including:
- Detailed usage instructions and guidelines
- Example code for tool invocation
- Error handling instructions
- Usage limits and caveats

### Two Skill Types

Skills fall into two categories based on their purpose:

**Tool Skills**: Used to expose the capabilities of one or more Nexent SDK methods. The body should include tool parameter descriptions, usage examples, return formats, and error handling. Once the user configures the parameters, the agent can call these tools directly.

**Agent Skills**: Used to teach an agent how to perform a complex task. The body should include workflow instructions, domain knowledge, best practices, and sometimes helper scripts. The body will contain detailed step-by-step guidance.

## Official Skills Overview

### File Operations

| Skill Name | Description |
|-----------|-------------|
| `read-file` | Read file content and metadata within the workspace |
| `create-file-directory` | Create files or directories |
| `delete-file-directory` | Delete files or directories |
| `move-file-directory` | Move or rename files/directories |
| `list-directory` | List directory structure in a tree view |
| `create-docx` | Create/generate Word documents from structured specs, supporting one-shot generation and fine-grained editing |
| `create-excel` | Create/generate Excel workbooks from structured specs, supporting one-shot generation and fine-grained editing |

### Knowledge Base Search

| Skill Name | Description |
|-----------|-------------|
| `search-knowledge-base` | Local knowledge base semantic search (supports hybrid / accurate / semantic modes) |
| `search-dify` | Dify knowledge base search |
| `search-idata` | iData knowledge base search |
| `search-datamate` | DataMate knowledge base search (with similarity threshold control) |

### Web Search

| Skill Name | Description |
|-----------|-------------|
| `search-web-tavily` | Tavily real-time web search |
| `search-web-linkup` | Linkup image and text mixed search |
| `search-web-exa` | Exa deep web search |

### Multimodal Analysis

| Skill Name | Description |
|-----------|-------------|
| `analyze-image` | VLM-based image content analysis and Q&A |
| `analyze-text-file` | PDF/Word/Excel file content extraction and Q&A |

### Communication and Remote Operations

| Skill Name | Description |
|-----------|-------------|
| `email-utils` | IMAP receive / SMTP send (supports HTML / CC / BCC) |
| `run-shell-ssh` | Persistent SSH session for remote command execution |

## Skill Lifecycle

### Version Management

Each skill supports two version states:

- **Draft version (version=0)**: Development and debugging stage, changes take effect immediately, suitable for iterative adjustments
- **Published version (version>=1)**: Production use, parameters locked to prevent accidental changes

### Skill Instances

The same skill can be configured with different parameter values for different agents, independently.

For example, a search skill can be configured for a "Technical Documentation Agent" to search only the technical knowledge base, and for a "Customer Service Agent" to search only the customer service knowledge base.

### Common Workflow

```
Create skill → Configure parameters → Select skill for agent → Debug → Publish
                       ↓
              Edit draft version
```

## Security Notes

- **Path isolation**: Files within a skill package can only be accessed within the skill directory scope
- **Parameter validation**: Parameters defined in schema.yaml are validated by the frontend form
- **Permission control**: Skill instances are tenant-isolated; APIs require authentication tokens

## Related References

- [Skill Management (User Guide)](../../user-guide/resource-repository/skill-repository.md)
- [Agent Development Guide](../../user-guide/agent-development)
- [Local Tools Overview](../../user-guide/local-tools/index)
