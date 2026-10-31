# Agent Integration

Nexent supports integrating third-party Agents via the **A2A (Agent-to-Agent) protocol**, enabling cross-platform multi-Agent collaboration. Through the A2A protocol, you can discover and use Agents developed on other platforms, incorporating them as collaborator Agents into your workflows.

## What is the A2A Protocol?

A2A (Agent-to-Agent) is an open protocol designed to enable interoperability between AI Agents from different platforms and technology stacks. Through the A2A protocol:

- **Standardized communication**: Unified Agent discovery and invocation mechanisms
- **Capability abstraction**: Agents can declare their capabilities without understanding each other's implementation details
- **Cross-platform collaboration**: Agents from different vendors can seamlessly collaborate

### A2A Protocol Core Concepts

| Concept | Description |
|---------|-------------|
| **Agent Card** | Metadata description file of an Agent, containing name, description, endpoint, capabilities, etc. |
| **Task** | Task entity representing a single Agent invocation |
| **Message** | Messages, supporting both synchronous and streaming modes |
| **Skill** | List of specific capabilities provided by an Agent |

## Discovering External A2A Agents

Nexent supports two methods for discovering external A2A Agents:

| Discovery Method | Use Case | Prerequisites |
|-----------------|----------|---------------|
| **URL Discovery** | When the Agent Card address is known | Agent Card URL is accessible |
| **Nacos Discovery** | Batch discover Agents registered in Nacos | Nacos service is running |

## Method 1: URL Discovery

When you know the target Agent's Agent Card address, you can use URL discovery.

### Agent Card Example

An Agent Card conforming to A2A 1.0 specification:

```json
{
  "name": "data-analysis-agent",
  "description": "Professional data analysis assistant that can perform statistical analysis, generate charts, and interpret data trends",
  "url": "https://agent.example.com/nb/a2a/agent-123",
  "version": "1.0.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false
  },
  "skills": [
    {
      "id": "statistical-analysis",
      "name": "Statistical Analysis",
      "description": "Perform descriptive and inferential statistics"
    },
    {
      "id": "chart-generation",
      "name": "Chart Generation",
      "description": "Generate various types of charts based on data"
    }
  ],
  "endpoints": {
    "http": "https://agent.example.com/nb/a2a/agent-123"
  }
}
```

### Steps

1. Navigate to **Agent Development** → **Collaborator Agents** page
2. Under the "External A2A Agent" tab, click "Add External Agent"
3. Select the "URL Discovery" tab
4. Fill in the Agent Card URL, e.g.: `https://example.com/.well-known/agent.json`
5. If authentication is needed, fill in custom request headers (JSON format):

```json
{"Authorization": "Bearer <token>"}
```

6. Click the "Discover" button
7. After the system retrieves Agent information, display Agent details
8. Click "Add to List" after confirming

### Notes

- Custom request headers are only used for fetching and refreshing Agent Cards, not for subsequent calls
- When rediscovering the same URL, leaving it empty will keep existing configuration, filling `{}` will clear it

## Method 2: Nacos Discovery

If the target Agent is registered in the Nacos service discovery platform, you can use Nacos discovery for batch integration.

### Steps

1. Navigate to **Agent Development** → **Collaborator Agents** page
2. Under the "External A2A Agent" tab, click "Add External Agent"
3. Select the "Nacos Discovery" tab
4. For first-time use, configure Nacos connection info:

| Config Item | Description | Example |
|-------------|-------------|---------|
| **Nacos Server Address** | Nacos service address | `http://127.0.0.1:8848` |
| **Namespace ID** | Nacos namespace (optional) | `dev` |
| **Group Name** | Service group name (default DEFAULT_GROUP) | `DEFAULT_GROUP` |
| **Username/Password** | Nacos access credentials (optional) | `nacos` / `nacos` |

5. Click "Save Configuration"
6. Fill in the Agent service name to scan
7. Click "Scan", and the system retrieves matching Agent list from Nacos
8. Select needed Agents and click "Add"

### Prerequisites

- Nacos service is running normally
- Target Agent is correctly registered to Nacos
- Service metadata contains Agent Card address

## Managing Discovered External Agents

In the external A2A Agent list, you can perform the following operations:

### Viewing Agent Details

Click on an Agent card to view complete information:
- Name, description, version
- URL endpoint
- Supported capability list (Skills)
- Call protocol support

### Testing Agent

Click the "Test" button to send a test message to the Agent, verifying it works correctly.

### Chatting with Agent

Click the "Chat" button to open the chat window for real-time interaction testing with the Agent.

### Configuring Call Protocol

Click the "Protocol Configuration" button to select the call protocol for this Agent:

| Protocol | Description | Use Case |
|----------|-------------|----------|
| **HTTP + JSON** | REST API style calls | General scenarios |
| **JSON-RPC** | JSON-RPC 2.0 protocol calls | Standardized RPC calls |

### Configuring Authentication

If the Agent Card declares `securitySchemes`, click "Agent Authentication" to fill in authentication info.

Supported authentication methods:
- Bearer Token
- API Key (Header/Query)
- Basic Auth

### Refreshing Agent Information

After Agent information changes, click "Refresh" to retrieve the latest Agent Card.

### Removing Agent

Click "Remove" to delete the Agent from the discovered list.

## Setting External Agent as Collaborator

After discovering and configuring external Agents, you can set them as collaborators for the current Agent.

### Steps

1. On the **Agent Development** page, enter "Collaborator Agent" configuration
2. In the "External A2A Agent" list, click to select the target Agent
3. The Agent appears in the "Selected Collaborator Agents" list
4. Save Agent configuration

### Collaboration Call Example

When the main Agent needs to execute a specific task, it can call collaborator Agents:

```
User: Help me analyze this sales data and generate a weekly report

After the main Agent analyzes the task, it decides:
- Call "Data Analysis Agent" to perform statistical calculations
- Call "Chart Generation Agent" to generate visualization charts
- Synthesize results to generate the final report
```

## Example: Integrating DataAgent A2A Agent

[DataAgent](https://gitcode.com/datagallery/dataagent) is an Agent platform supporting A2A protocol. Here are the integration steps:

### 1. Deploy DataAgent

Refer to DataAgent documentation to start in A2A service mode:

> Note: Currently Nexent does not support authenticated Agents, do not set auth-token when starting

### 2. Get Agent Card Address

After DataAgent starts in A2A mode, its Agent Card address is:
```
http://<IP>:9999/.well-known/agent-card.json
```

### 3. Add in Nexent

1. Select "URL Discovery"
2. Fill in URL: `http://<IP>:9999/.well-known/agent-card.json`
3. Click "Discover"
4. After successful addition, configure call protocol as HTTP + JSON

### 4. Test and Use

After successful addition, you can test Agent responses, confirm normal operation, and then set it as a collaborator for use.

## FAQ

### Q: What to do if Agent discovery fails?

1. Confirm the Agent Card URL is accessible
2. Check network connectivity and firewall configuration
3. Verify the Agent service is running normally
4. Confirm authentication info is correct

### Q: How to choose the call protocol?

- **HTTP + JSON**: Preferred for most scenarios, better compatibility
- **JSON-RPC**: If the Agent explicitly requires JSON-RPC protocol

### Q: How to develop an A2A-compliant Agent?

See the [A2A Protocol Specification](https://github.com/model-context-protocol/specification), or refer to Nexent's implementation.

## Related Resources

- [Add External A2A Agent](../../user-guide/agent-development/a2a-external) — Detailed instructions for adding external A2A Agent
- [A2A Protocol Specification](https://github.com/model-context-protocol/specification) — Official protocol documentation
