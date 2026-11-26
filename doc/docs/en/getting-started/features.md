# Key Features

Nexent brings agent development, execution, and administration into one platform. This page introduces the core features: how to turn a business need into a working agent, connect it to models, knowledge, and tools, and evaluate, publish, and operate it as a team.

## 🛠️ Agent Development

### Build and refine agents in conversation

With NL2Agent, start by describing the problem the agent should solve. Nexent asks follow-up questions, finds tools and skills that are installed or available, and helps install and assign them. It also drafts the core prompt, greeting, and example questions.

Once you have a draft, refine it in conversation or edit the configuration directly, then test it online before publishing. You can also copy, import, or export an agent to build on an existing configuration.

### Optimize prompts in one click

If a prompt does not capture the task clearly, ask the development assistant to refine the relevant parts. Review its suggestion before deciding whether to replace the existing prompt.

### Debug visually and compare models

- **Follow a test run:** Watch the answer stream while inspecting execution steps, tool selection, inputs, and returned results. Stop the run or clear the session when needed.
- **Compare two models:** Give both models the same prompt and review their answers side by side before choosing a model for release.

## ⚙️ Agent Runtime

### Coordinate agents and run tasks in parallel

A lead agent can split a complex task into workstreams, such as researching a topic and organizing existing documents, then combine the results. Collaborating agents can delegate further or work in parallel. Each can use its own model, tools, and execution strategy, and you can inspect individual results separately.

### Work with multiple media types and deliver files

- **Provide inputs that suit the task:** Depending on the configured models, agents can accept text, images, audio, video, and documents. Speech recognition and speech synthesis support voice input and spoken replies, respectively.
- **Get files in the conversation:** Preview or download generated documents, spreadsheets, and images without leaving the chat.

### Schedule tasks

Describe what to do and when. Nexent drafts a schedule for you to confirm, then creates a one-time or recurring task tied to that conversation. If plans change, run it immediately, pause or resume it, or edit it. Check the execution history to see how earlier runs went.

### Load skills on demand

Agents start with a brief skill summary. Only when a task calls for the skill does the agent retrieve its full `SKILL.md`, references, or scripts. This progressive disclosure leaves room in the conversation for relevant material. During development, NL2Agent can recommend, install, and assign skills based on the task.

### Run code in an isolated sandbox

Model-generated code and skill scripts run in a sandbox separate from the main platform service and business data. This lets agents use scripts to process files or produce deliverables without running that code directly in the main service.

### Configure safety guardrails

Enable guardrails for an agent when you need rules to block unsafe tool or model calls. Describe what to block in natural language to draft candidate rules, then check which rules match sample text before using them.

## 🚀 Agent Management

### Manage versions and reuse agents

Drafts are separate from published versions, so you can keep editing and debugging a draft until it is ready to publish. Use earlier versions to compare answers or roll back to a previous configuration. Import, export, or copy agents to reuse configurations across environments.

### Integrate with business systems and external agents

Use the REST API and managed API keys to bring agent conversations and other capabilities into existing applications. For cross-platform collaboration, use the Agent-to-Agent (A2A) protocol to publish an agent as a service or discover and call external agents through an Agent Card URL or registry.

### Evaluate agents before release

Build an evaluation set from scenario descriptions or existing test case files, then score the cases in batches with one or more evaluators. Use the overall results to assess release readiness and examine individual scores and failure reasons to decide what to improve next. Export the report for team review.

## 🧩 AI Asset Management

### Connect and manage models in one place

Connect OpenAI-compatible model services or sync models from ModelEngine. Manage language, embedding, reranking, image understanding and generation, video and audio understanding, speech recognition, and speech synthesis models centrally. Check connectivity and configure model capabilities before assigning them to agents.

### Combine knowledge sources and verify citations

Agents can draw on one or more sources, depending on the task:

- **Local knowledge bases:** Upload text, PDFs, Office documents, CSV, JSON, or EPUB files to a personal or group-shared knowledge base. Nexent parses, chunks, and embeds the documents for semantic or hybrid retrieval. You can review summaries and manage individual chunks.
- **Third-party knowledge bases:** Connect existing sources such as Dify or AIDP so agents can retrieve supporting material without uploading the original documents again.
- **Web search:** Use search services such as Exa, Linkup, or DeepSeek to find public information that fills gaps in internal materials.

When an answer includes citations, open the matching passage or webpage to check the evidence, or download the original document if it is available.

### Recall and consolidate memory

Nexent organizes memory by where the information is useful:

- **Tenant memory** keeps long-term information that can be reused within the tenant.
- **User memory** records the current user's long-term preferences and background.
- **Agent memory** retains short-term information from the current user's interactions with a specific agent.

Nexent can extract useful details from conversations and retrieve relevant memories for later tasks. You can review and manage memories or use Dreaming to consolidate short-term information into versioned long-term memory.

### Connect MCP tools

Nexent uses the Model Context Protocol (MCP) to connect agents with external services:

- **Connect tools:** Use a remote MCP service, deploy one in a container, or expose an existing REST API as MCP tools through OpenAPI.
- **Verify availability:** Check connectivity, inspect container startup logs, or refresh the tool list. Test a tool's inputs and returned results before assigning it to an agent.

### Create skills

Upload a `SKILL.md` file or a `.zip` skill package, or use NL2Skill to describe a workflow in natural language and generate a skill package. You can also use natural language to refine an existing skill.

### Asset repository

The repository brings together shareable agents, MCP services, and skills. Developers can submit assets for listing, and administrators review those submissions. Users within the tenant can browse, install, or copy listed assets. When users install or copy an agent, Nexent checks for conflicts involving models, tools, and skills and guides them through any required setup.

## 🔐 Users and Resource Permissions

Nexent manages permissions by tenant and role:

- **Five roles:** Super administrators, tenant administrators, operations administrators, developers, and regular users have distinct responsibilities.
- **Tenant isolation:** Data is fully isolated between tenants, with platform-level administration across tenants.
- **User groups:** Manage resources and access through groups and delegate permissions as needed.
- **Invitation codes:** Control who can register to help secure the platform.
- **Resource-level permissions:** Grant user groups read-only or edit access to agents, knowledge bases, models, MCP services, and skills.
- **API access management:** Administrators can manage northbound API keys for tenant users.

## 📊 Operations and Observability

Nexent provides two views for day-to-day operations: a platform-wide overview and a detailed record of an individual agent run.

- **Review platform usage in the dashboard:** Agent count and active users show the scale of usage, while average response latency provides a baseline for response speed. Use these metrics during routine checks to decide when to investigate further.
- **Investigate a run in the Observability Center:** If an answer looks wrong or takes longer than expected, follow the trace to see which tools ran, what inputs they received, what they returned, and how long each call took.

To see how these capabilities fit together, read the [Software Architecture](./software-architecture) guide.
