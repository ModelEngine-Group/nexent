# Agent Development

In the Agent Development page, you can create, configure, and manage agents. Agents are the core feature of Nexent—they can understand your needs and perform corresponding tasks.

## 🛠️ Agent Management

### Create an Agent

On the Agent Management tab, click "Create Agent" to create a new blank agent. Click "Exit Create" to leave creation mode.

If you have an existing agent configuration, you can also import it:

1. Click "Import Agent"
2. In the popup, select the agent configuration file (JSON format)
3. Click "Open"; the system will validate the file format and content, and display the imported agent information

<div style="display: flex; justify-content: left;">
  <img src="./assets/agent/import.png" style="width: 80%; height: auto;" />
</div>

### Agent List

On the Agent Management tab, you can view all created agents. Click an agent to select it for detailed configuration; click again to deselect.

## 👥 Configure Agent Capabilities

You can configure other collaborative agents for your created agent, as well as assign available tools to empower the agent to complete complex tasks.

### Collaborative Agents

1. Click the plus sign under the "Collaborative Agent" tab to open the selectable agent list
2. Select the agents you want to add from the dropdown
3. Multiple collaborative agents can be selected
4. Click × to remove an agent from the selection

<div style="display: flex; justify-content: left;">
  <img src="./assets/agent/set-collaboration.png" style="width: 50%; height: auto;" />
</div>

### Select Tools

Agents can use various tools to complete tasks, such as knowledge base search, email sending, file management, and more. They can also integrate third-party MCP tools or custom tools.

1. On the "Select Tools" tab, click "Refresh Tools" to update the available tool list
2. Select the group containing the tool you want to add
3. View all available tools under the group; click the gear icon to view tool details and configure parameters
4. Click the tool name to select/deselect it

<div style="display: flex; justify-content: left;">
  <img src="./assets/agent/set-tool.png" style="width: 50%; height: auto;" />
</div>

> 📚 Want to learn about all the built-in local tools in Nexent? Please see [Local Tools Overview](./local-tools/index.md).

### Add MCP Tools

Nexent allows you to quickly use third-party MCP tools to enrich agent capabilities.

1. On the "Select Tools" tab, click "MCP Config" to configure MCP servers in the popup and view configured servers
2. Enter the server name and URL (currently only SSE protocol is supported)
3. Click "Add" to complete the addition

<div style="display: flex; justify-content: left;">
  <img src="./assets/agent/mcp.png" style="width: 80%; height: auto;" />
</div>

Many third-party services such as [ModelScope](https://www.modelscope.cn/mcp) provide MCP services, which you can quickly integrate and use.

### Custom Tools

You can refer to the following guides to develop your own tools and integrate them into Nexent to enrich agent capabilities:
- [LangChain Tools Guide](../backend/tools/langchain)
- [MCP Tool Development](../backend/tools/mcp)
- [SDK Tool Documentation](../sdk/core/tools)

## 📝 Describe the Agent’s Logic

### Describe How the Agent Should Work

Once the collaborators and tools are ready, describe—in plain language—how you expect the agent to behave. Nexent uses this description plus your configuration to auto-generate the agent name, description, and prompts.

1. Enter the description under **Describe how this agent should work**
2. Click **Generate Agent** and wait for the detailed content
3. Review the generated role prompt, constraints, examples, and tweak anything you want

<div style="display: flex; justify-content: left;">
  <img src="./assets/agent/generate-agent.png" style="width: 50%; height: auto;" />
</div>

### Debug Agent

After completing the initial agent configuration, you can debug the agent and optimize its configuration based on the results to continuously improve agent performance.

1. In the lower right corner of the page, click the "Debug" button to open the agent debug page
2. Test conversations with the agent and observe its responses and behavior
3. Review conversation performance and error messages, and optimize the agent configuration based on the results

### Manage Agents

- **Save:** After you finish debugging, click **Save** in the lower-right corner so the agent becomes available in Start Chat.
- **Export:** Download a JSON file of any agent you like, then re-import it later to create copies.
- **Delete:** Remove an agent you no longer need (this cannot be undone).

## 🚀 Next Steps

After shipping an agent you can:

1. Manage every build inside **[Agent Space](./agent-space)**.
2. Start working with your agent on the **[Start Chat](./start-chat)** page.
3. Configure **[Memory Management](./memory-management)** to give agents persistent memory.

Need help? Check the **[FAQ](../getting-started/faq)** or open a thread in [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions).