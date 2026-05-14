# MCP Tools

In the MCP Tools module, you can centrally manage all MCP (Model Context Protocol) servers and tools. It supports custom addition, Registry import, and Community import, covering connection configuration, tool synchronization, health monitoring, and community sharing.

The MCP Tools page has two parallel tabs:

- **Imported Services**: Manage MCP services already accessed by the current tenant — configure, monitor, and maintain your MCP services here.
- **Published Services**: Manage the MCP services you have published to the community — browse, edit, and unpublish.

---

## ➕ Add MCP Services

Click the **Add MCP Service** button to open the add dialog. The dialog provides three tabs, each corresponding to a different source.

### Local Add

The **Local Add** tab lets you manually configure an MCP service with two transport types.

#### Add via URL

For independently deployed MCP services (HTTP / SSE), connect by entering the endpoint URL.

1. In the **Local Add** tab, set **Transport Type** to "URL"
2. Fill in the service details:
   - **Service Name (required)**: A recognizable name for the MCP service
   - **Service URL (required)**: The MCP service endpoint address
   - **Description** (optional): A brief description of the service
   - **Authorization Token** (optional): Bearer token if the service requires authentication
3. Click **Confirm** — the system will connect to the service and retrieve the available tool list

#### Add via Container Configuration

For MCP services that need to run locally in a container (e.g., services launched via npx), the system automatically creates and manages a container based on your JSON configuration.

1. In the **Local Add** tab, set **Transport Type** to "Container"
2. Fill in the container configuration:
   - **Service Name (required)**: A recognizable name for the MCP service
   - **Description** (optional): A brief description of the service
   - **Container Configuration JSON (required)**: Enter the standard MCP configuration format, for example:
     ```json
     {
       "mcpServers": {
         "service-name": {
           "args": ["mcp-package-name@version"],
           "command": "npx",
           "env": {
                "API_KEY": "xxxx"
           }
         }
       }
     }
     ```
   - **Port**: The port exposed by the container service — the system automatically detects port conflicts and suggests available ports
3. Click **Confirm** — the system parses the JSON, creates the container, and registers the service

### Import from MCP Registry

Nexent integrates with the MCP Registry, allowing you to browse and import community-maintained MCP services in one click.

1. Switch to the **MCP Registry** tab
2. Browse the available MCP services — search by name or tags
3. Click a service to view its details (description, version, required parameters, etc.)
4. Configure required parameters (e.g., API Key and other environment variables)
5. Click **Import** — the system automatically installs and configures the service

### Import from Community

Browse MCP services published by other Nexent users and quickly import them.

1. Switch to the **Community Market** tab
2. Browse published community MCP services — filter by name, tags, or transport type
3. Click a service to view details, then click **Import** to add it to your service list

---

## 📋 Imported Services

The **Imported Services** tab displays all MCP services accessed by the current tenant as cards. View, edit, monitor, and publish your services here.

### View & Filter

Each service card shows:

- Service name and description
- Source indicator (Custom / Registry / Community)
- Enable / Disable toggle
- Tags

Use the filter bar at the top to filter by **Source**, **Transport Type**, and **Tags**, or use the search box to quickly locate services by name.

### Edit Service Details

Click any service card to open the detail modal, where you can:

- **Edit basic info**: Modify name, description, URL, Authorization Token, and tags
- **Enable / Disable**: Toggle the service on or off — tools from a disabled service will not appear in agent tool selection
- **Delete**: Remove the MCP service record — containerized services will also have their container resources cleaned up

### View Tool List

In the service detail modal, click **Tool List** to view all tools provided by this MCP service.

### Health Check

Click the **Health Check** button in the detail modal to test the connection to the MCP service. Possible statuses:

- **Healthy**: The service is reachable
- **Unhealthy**: The service cannot be reached or responded abnormally
- **Unchecked**: A health check has not been performed yet

### Container Management

For containerized MCP services, the detail modal also provides:

- **View Container Logs**: Real-time logs from the running container for troubleshooting
- **View Container Config**: The configuration JSON used when creating the container

### Publish to Community

In the service detail modal, click **Publish to Community**:

1. Review or edit the publication info (name, description, tags, etc.)
2. Click **Confirm Publish** — the service will be published to the community
3. Other users can then browse and import it from the **Community Market** tab in the add dialog

---

## 🌐 Published Services

The **Published Services** tab shows all MCP services you have published to the community. Manage your published content here.

Each card shows the service name, description, version, and tags. Filter by name, tags, and transport type.

Click a service card to view details, where you can:

- **Edit published service**: Modify the published service's name, description, and tags
- **Delete published service**: Withdraw the service from the community — it will no longer be visible to other users

---

## 🔗 Integrating with Agents

Once an MCP service is added, its tools are automatically synced to the agent tool selection list. When configuring an agent on the **[Agent Development](./agent-development)** page:

1. In the **Select Agent Tools** tab, locate the corresponding MCP service group
2. Click a tool name to enable it
3. Click ⚙️ to view the tool description and configure its parameters

## 🚀 Next Steps

After configuring MCP services, we recommend:

1. **[Agent Development](./agent-development)** — Assign MCP tools to your agents
2. **[Agent Space](./agent-space)** — View collaboration between agents and MCP services
3. **[Start Chat](./start-chat)** — Experience agents calling MCP tools in conversations

If you encounter any issues, please refer to our **[FAQ](../quick-start/faq)** or ask for support in [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions).

