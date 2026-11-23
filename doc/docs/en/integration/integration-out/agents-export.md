# Agent Export

Nexent supports exporting complete Agent configuration in JSON or ZIP format for cross-environment migration, backup, and batch distribution. This document introduces Agent export formats, processes, and import methods.

## Overview

| Method | Description | Use Case |
|--------|-------------|----------|
| **Export configuration** | Export Agent configuration as JSON/ZIP file | Migrate to other Nexent deployments, backup |
| **Import configuration** | Import Agent from JSON/ZIP file | Reuse existing configuration, cross-environment migration |

## Export Agent Configuration

### Steps

1. Navigate to **Agent Repository** → **My Agents** page
2. Find the Agent you want to export
3. Click the "Export" button on the right side of the Agent
4. Select export format:
   - **JSON**: Contains only configuration, no skill packages
   - **ZIP**: Contains configuration and all skill files
5. System generates file and downloads automatically

### Exported File Description

#### JSON Format

```json
{
  "name": "data-analyst",
  "version": "1.0.0",
  "model": "gpt-4",
  "prompt": {
    "role": "You are a professional data analysis assistant...",
    "requirements": "...",
    "examples": "..."
  },
  "tools": [
    {
      "type": "knowledge_base",
      "name": "kb_search"
    },
    {
      "type": "mcp",
      "name": "github-tools"
    }
  ],
  "skills": [
    {
      "name": "csv-analyzer",
      "params": {"top_k": 5}
    }
  ],
  "collaborators": [
    "visualization-agent"
  ],
  "memory": {
    "type": "layered",
    "short_term": {...},
    "long_term": {...}
  }
}
```

#### ZIP Format

Contains JSON configuration file and all skill packages:

```
data-analyst.zip
├── agent.json           # Agent configuration
└── skills/
    ├── csv-analyzer/
    │   ├── SKILL.md
    │   └── scripts/
    │       └── analyze.py
    └── report-generator/
        ├── SKILL.md
        └── assets/
            └── template.md
```

### Use Cases

- **Cross-environment migration**: From dev environment to production
- **Backup and recovery**: Regular export as configuration backup
- **Batch distribution**: Distribute mature Agents to other tenants

## Import Agent Configuration

### Steps

1. Navigate to **Agent Repository** → **My Agents** page
2. Click the "Import" button
3. Select JSON or ZIP file in the popup file selector
4. System verifies configuration file format and content
5. Display imported Agent preview information
6. Confirm to complete import

### Dependency Handling

The system checks Agent dependency configuration during import:

| Dependency Type | Handling Method |
|----------------|-----------------|
| **Model** | Check if enabled; if not, configure first |
| **Knowledge base** | Inherit importer permissions; retrieval scope limited by importer permissions |
| **MCP services** | Check if configured; if not, add manually |
| **Skills** | Automatically import skill packages (if included in ZIP) |
| **Collaborator Agents** | Check if exists; configure manually |

### Notes

- **Name conflicts**: If importing an Agent with the same name, the system prompts to modify
- **Knowledge base permissions**: Import does not inherit the original author's knowledge base permissions
- **Variable name uniqueness**: Check and ensure variable names don't conflict

### Two Import Methods

| Method | Description | Use Case |
|--------|-------------|----------|
| **Direct import** | Keep duplicate names; manually modify after import | Quick import with manual follow-up |
| **Regenerate** | Call LLM to rename Agent | Many name conflicts; want automatic handling |

## FAQ

### Q: Exported Agent cannot be used in new environment

1. Check if dependency configuration is complete
2. Confirm models, knowledge bases and other resources are enabled
3. Verify MCP services and Skills are configured correctly

### Q: Knowledge base retrieval results differ from original author after import

Import does not inherit the original author's knowledge base permissions; retrieval scope is limited by importer permissions. This is by design. Ensure the importer has sufficient knowledge base access permissions in the target environment.

### Q: How to choose between JSON and ZIP format?

- Choose JSON when migrating only Agent configuration without skill files.
- Choose ZIP when migrating Agent with all dependent skill packages.

## Related Resources

- [Agent Publishing](./agents-publish) — Publish Agent as an externally callable service
- [Agent Integration](../integration-in/agents) — Integrate third-party Agents via A2A protocol
- [Agent Configuration](../../user-guide/agent-development/agent-configuration) — Agent configuration details
