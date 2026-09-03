# Third-Party Integration

Nexent provides comprehensive third-party integration capabilities with bidirectional resource integration: you can integrate external AI resources (MCP services, Skills, Agents) into the platform, and export or publish platform-developed resources for use by external systems. Whether you are a third-party developer, partner, or enterprise customer, you can achieve deep integration with Nexent through this integration system.

## Resource Integration Overview

Nexent offers bidirectional resource integration capabilities, enabling you to both leverage external ecosystems and export platform capabilities to external systems:

### Integrate External Resources

Integrate external AI resources into the platform for management and use, enriching platform capabilities:

| Resource Type | Integration Method | Use Case |
|--------------|-------------------|----------|
| MCP Services | Remote URL, Container, API-to-MCP | Integrate third-party MCP services, or convert enterprise REST APIs to MCP tools |
| Skills | Upload SKILL.md, Upload ZIP package | Integrate third-party developed skill packages |
| Agents | A2A protocol discovery | Discover third-party Agents via URL or Nacos for cross-platform collaboration |

### Export Platform Capabilities

Export or publish platform resources for use by external systems:

| Resource Type | Method | Description | Use Case |
|--------------|--------|-------------|----------|
| Agent | Export as JSON/ZIP | Migrate Agent configuration to other Nexent environments for cross-environment reuse | Migration, backup, batch distribution |
| Agent | Normal publishing (Northbound RESTful API) | Publish and call via standard RESTful API | Deep integration with business systems for workflow automation |
| Agent | Publish as A2A Agent | Expose Agents to external systems with REST and JSON-RPC protocol support | Cross-platform Agent collaboration |

## Documentation Structure

This section is organized as follows:

```
Third-Party Integration
├── Integration-In (Inbound)
│   ├── [Overview](./integration-in/overview) — Integration capabilities overview
│   ├── [MCP Service Integration](./integration-in/mcp) — Integrate third-party MCP services
│   ├── [Skill Integration](./integration-in/skills) — Integrate third-party Skills
│   └── [Agent Integration](./integration-in/agents) — Integrate third-party Agents via A2A protocol
└── Integration-Out (Outbound)
    ├── [Overview](./integration-out/overview) — Export and publish capabilities overview
    ├── [Agent Export](./integration-out/agents-export) — Export/import Agent configuration files (JSON/ZIP)
    ├── [Agent Publishing](./integration-out/agents-publish) — Normal publishing (Northbound API) and A2A publishing
    └── [Northbound API](./integration-out/northbound-api) — Northbound RESTful API detailed reference
```

## Quick Start

### Want to integrate external resources?

| Goal | Steps | Documentation |
|------|-------|--------------|
| **MCP Services** | Prepare service → Choose integration method → Configure and test → Assign to Agent | [MCP Integration](./integration-in/mcp) |
| **Skills** | Choose integration method → Prepare skill content → Upload → Assign to Agent | [Skill Integration](./integration-in/skills) |
| **Agents** | Discover external Agent → Configure call protocol → Set as collaborator | [Agent Integration](./integration-in/agents) |

### Want to export platform capabilities?

| Goal | Steps | Documentation |
|------|-------|--------------|
| **Export Agent configuration** | Select Agent → Export JSON/ZIP → Import to other Nexent deployment | [Agent Export](./integration-out/agents-export) |
| **Normal publishing** | Publish Agent → Generate API Key → Call Northbound API | [Agent Publishing](./integration-out/agents-publish) / [Northbound API](./integration-out/northbound-api) |
| **Publish as A2A Agent** | Publish Agent → Check A2A option → Get call info | [Agent Publishing](./integration-out/agents-publish) |

## Related Resources

- [Agent Development](../user-guide/agent-development) — Learn how to create and configure Agents in Nexent
- [MCP Ecosystem](../mcp-ecosystem/overview) — Learn more about MCP ecosystem

## Getting Help

If you encounter any issues during integration, feel free to get help through the following channels:

- [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions) — Ask questions and discuss
- [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) — Report issues
- [Discord Community](https://discord.gg/tb5H3S3wyv) — Connect with community members
