# Integration-In Overview

The integration capabilities are a key component of Nexent's open ecosystem. By integrating external AI resources, the platform can fully leverage external tools and Agents, giving your Agents more powerful capabilities and broader application scenarios.

## Integration Capabilities Overview

Nexent supports three main types of resource integration:

| Resource Type | Description | Integration Method | Typical Sources |
|--------------|-------------|-------------------|----------------|
| **MCP Services** | Model Context Protocol tool services | URL link, Container config, API-to-MCP | ModelScope, Third-party self-hosted |
| **Skills** | Reusable capability packages containing tools, configuration, and documentation | Upload SKILL.md, Upload ZIP | Third-party skill packages |
| **Agents** | Third-party Agents conforming to A2A protocol | URL discovery, Nacos discovery | Enterprise internal systems, Third-party platforms |

## Why Integrate External Resources?

### Extend Agent Capability Boundaries

By integrating external MCP services, your Agents can call various specialized tools such as GitHub code management, database queries, file processing, etc., without developing these capabilities from scratch. Nexent integrates popular MCP markets like ModelScope, allowing you to quickly access rich tool capabilities.

### Extend Reusable Capabilities

The Skill mechanism encapsulates multiple tools, parameter configurations, and documentation into a reusable capability package, allowing your team's best practices and domain knowledge to be "packaged for immediate use, shared across scenarios." By uploading single-file `SKILL.md` skills or multi-file ZIP skill packages, you can quickly integrate third-party developed skills into Nexent Agents without developing similar scenarios repeatedly. Compared to single tools, skill packages are easier to version, manage permissions, and distribute across teams.

### Join the Larger Ecosystem

By integrating third-party Agents via the A2A protocol, your Agents can collaborate with Agents from other platforms, forming more powerful multi-Agent workflows. This cross-platform collaboration capability allows your system to call specialized-domain Agents for more complex business scenarios.

## Integration Process Overview

### MCP Service Integration Process

```
1. Prepare MCP service ──► 2. Choose integration method ──► 3. Configure and test ──► 4. Assign to Agent
```

Nexent provides three MCP integration methods:
- **Remote URL**: For independently deployed MCP services
- **Container**: For MCP services running in Docker
- **API-to-MCP**: Quickly convert enterprise REST APIs to MCP tools

For detailed steps, see [MCP Service Integration](./mcp).

### Skill Integration Process

```
1. Prepare skill package ──► 2. Choose upload method ──► 3. Check and save ──► 4. Assign to Agent
```

Nexent supports two Skill integration methods:
- **Upload SKILL.md**: Single-file skill, suitable for simple scenarios
- **Upload ZIP package**: Multi-file skill with scripts and resources

For detailed steps, see [Skill Integration](./skills).

### Agent Integration Process

```
1. Discover external Agent ──► 2. Configure call protocol ──► 3. Set as collaborator
```

Nexent supports two Agent discovery methods:
- **URL discovery**: Used when the Agent Card address is known
- **Nacos discovery**: Batch discover Agents registered in Nacos

For detailed steps, see [Agent Integration](./agents).

## Security Considerations

When integrating external resources, pay attention to the following security matters:

| Consideration | Description | Recommendation |
|--------------|-------------|----------------|
| **Authentication info** | External services may require API Key or Token | Use the platform's key management feature, avoid storing in plain text |
| **Network connectivity** | Ensure the platform can access external services | Check firewall configuration and security policies |
| **Data permissions** | Integrated services may access sensitive data | Evaluate service permissions, grant only necessary access |
| **Source trustworthiness** | Ensure integrated services are from trusted sources | Prefer officially certified or community-verified services |

## Next Steps

Based on the resource type you need to integrate, select the corresponding guide:

- [MCP Service Integration](./mcp) — Integrate third-party MCP services
- [Skill Integration](./skills) — Integrate reusable skill packages
- [Agent Integration](./agents) — Integrate third-party Agents via A2A protocol

## Related Resources

- [MCP Ecosystem](../../mcp-ecosystem/overview) — Learn more about MCP ecosystem
- [Agent Configuration](../../user-guide/agent-development/agent-configuration) — Use integrated resources in Agents
- [Skill System Overview](../../backend/skills/overview) — Deep dive into the Skill mechanism
