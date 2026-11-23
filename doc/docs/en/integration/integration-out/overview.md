# Integration-Out Overview

Nexent platform not only supports integrating external resources but also supports exporting or publishing platform-developed resources (Agents) for use by external systems, extending platform capabilities. Through export and publish, Nexent can seamlessly embed into your enterprise's overall IT architecture and collaborate with various business systems.

## Overview

Nexent provides the following export and publish methods:

| Resource Type | Method | Description | Use Case |
|--------------|--------|-------------|----------|
| **Agent** | Export configuration | Export Agent configuration in JSON/ZIP format | Migrate Agent to other Nexent environments |
| **Agent** | Normal publishing | Provide Northbound RESTful API after publishing | Deep integration with business systems for workflow automation |
| **Agent** | Publish as A2A Agent | Expose Agent as A2A service | Cross-platform Agent collaboration, external systems calling via A2A protocol |

### Ecosystem Integration

Through A2A protocol and Northbound API, Nexent can deeply integrate with external systems:

- **Enterprise integration**: Integrate with business systems like ERP, CRM
- **Workflow automation**: Embed Agent capabilities into automated processes
- **Multi-Agent collaboration**: Collaborate with Agents from other platforms

## Process Overview

### Agent Export Process

```
1. Select Agent ──► 2. Export configuration file ──► 3. Import to other Nexent deployment
```

Supports both JSON and ZIP formats. ZIP format contains complete configuration and resource files, suitable for full migration. For detailed steps, see [Agent Export](./agents-export).

### Agent Normal Publishing Process

```
1. Publish Agent version ──► 2. Generate API Key ──► 3. Call Northbound API ──► 4. Integrate with business system
```

Northbound API provides complete conversation management capabilities with streaming response and attachment upload support. For detailed steps, see [Agent Publishing](./agents-publish) and [Northbound API](./northbound-api).

### Agent Publish as A2A Process

```
1. Publish Agent version ──► 2. Check "Publish as A2A Agent" ──► 3. Get call info ──► 4. External system calls
```

After publishing, the Agent generates an Agent Card conforming to A2A 1.0 specification, which external systems can discover and call. For detailed steps, see [Agent Publishing](./agents-publish).

## Capability Comparison

| Method | Interaction Mode | Real-time | Protocol | Use Case |
|--------|----------------|-----------|----------|----------|
| **Export configuration** | Offline | None | — | Migration, backup |
| **Normal publishing (Northbound API)** | Online | Real-time/streaming | RESTful API | Business system integration |
| **A2A publishing** | Online | Real-time | A2A 1.0 (REST + JSON-RPC) | Cross-platform Agent collaboration |

## Security Considerations

When exporting or publishing resources, pay attention to the following security matters:

| Consideration | Description | Recommendation |
|--------------|-------------|----------------|
| **Sensitive info** | Exported configuration may contain API Keys and other sensitive info | Check and handle appropriately before use |
| **Access control** | Exposed APIs need authentication protection | Only authorize trusted systems |
| **Data security** | External calls may access sensitive data | Set appropriate data permission policies |
| **Audit tracking** | Record API call logs for auditing | Enable logging and monitoring |

## Next Steps

Based on your needs, select the corresponding guide:

- [Agent Export](./agents-export) — Export and import Agent configuration files (JSON/ZIP)
- [Agent Publishing](./agents-publish) — Normal publishing (Northbound API) and A2A publishing
- [Northbound API](./northbound-api) — Northbound RESTful API detailed reference

## Related Resources

- [Agent Development](../../user-guide/agent-development) — Learn how to develop and publish Agents
- [API Reference](../../backend/api-reference) — Complete API interface reference
- [A2A Protocol Specification](https://a2a-protocol.org/) — Official protocol documentation
