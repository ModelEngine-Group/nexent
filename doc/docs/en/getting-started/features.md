# Key Features

Nexent v2.0 delivers powerful capabilities for building and deploying AI agents. Here are the core features that make Nexent unique.

## ⚙️ Multi-Model Integration

Nexent is compatible with any OpenAI-compatible model provider, offering one-stop coverage for LLM, Embedding, VLM, STT, and TTS model types. Supports seamless synchronization with the ModelEngine platform, with built-in connection monitoring and automatic failover. The platform supports connecting to any service that follows the OpenAI API protocol, making it easy to diversify models or switch to domestic alternatives.

## 🤖 Zero-Code Agent Generation

Describe your needs in natural language and Nexent automatically transforms them into executable agent configurations. The system intelligently selects appropriate tools, plans the optimal execution path, and generates professional prompts. No code, no drag-and-drop configuration — experience true "what you imagine is what you get" agent creation. Agents can also be imported and exported for easy sharing and reuse. Built-in debugging provides online testing so you can iterate and refine rapidly.

## 🤝 A2A Protocol & Agent Collaboration

Nexent supports the **Agent-to-Agent (A2A)** communication protocol, enabling seamless multi-agent collaboration. A main agent can invoke sub-agents to complete specific tasks; once a sub-agent finishes execution, results are aggregated back to the main agent. Multiple collaborative sub-agents can be configured, each with its own toolset, model configuration, and execution strategy — making it easy to build complex distributed agent workflows.

## 🧠 Layered Memory Architecture

Intelligent context management is the key to agents that truly understand you. Nexent provides a two-tier memory system:

- **User-Level Memory**: Personal preferences, habits, and usage patterns
- **User-Agent Memory**: Collaboration history and context for a specific user with a specific agent

The system automatically extracts key information from conversations to generate memory entries — no manual input required. Memory entries can also be added or modified manually for greater flexibility. Smart retrieval ensures every conversation automatically pulls in the most relevant contextual memories, enabling truly personalized service.

## 📝 Progressive Skill Disclosure

Nexent introduces a **Progressive Skill Disclosure** mechanism. As users input tasks, the system dynamically reveals the most relevant Skill suggestions based on the current context — helping users quickly find the tools and methods best suited to the current task. This mechanism helps preventing context explosion and maximizing context window efficiency.

## 🗄️ Personal-Grade Knowledge Base

Create personal knowledge bases on the Nexent platform. Import files in real time with automatic parsing and vectorization, enabling agents to access private data instantly. Supports 20+ document formats including text, PDF, Word, PowerPoint, Excel, and CSV — with fast OCR and table structure extraction built in. Each knowledge base automatically generates its own summary, helping the agent accurately determine when to retrieve from it. Fine-grained access controls can be set: private, department-wide, or organization-wide visibility.

## 🔧 MCP Tool Ecosystem

Nexent builds its tool ecosystem on the **Model Context Protocol (MCP)** — described as the "USB-C of AI" — a universal interface standard for connecting AI agents to the external world.

- Add third-party MCP services quickly via URL or JSON configuration
- Develop local MCP tools with LangChain integrations and custom Python plugins
- Hot-swap tools, models, and toolchains without touching core code
- Built-in tool testing lets you verify whether tools work as expected before building an agent

## 🌐 Internet Knowledge Integration

Connect to multiple web search providers so agents can blend the freshest internet information with your private data. Hybrid search mode balances real-time accuracy with relevance.

## 🔍 Knowledge Traceability & Citations

Every answer comes with precise citations from web search results or knowledge base documents, making every fact transparent and verifiable. Source information is fully traceable with one click, building trust in agent responses.

## 🎭 Multimodal Interaction

Supports multiple input modes: voice, text, images, and files. Agents can understand voice, text, and images, and can generate new images on demand — delivering a truly natural multimodal conversation experience.

## 🔢 Agent Version Management

A comprehensive version control system supports agent iteration and historical rollback. Every version is independently archived; view change history, compare versions, and roll back whenever needed. Agent configurations can also be imported and exported in JSON format, enabling seamless migration across environments and smooth team collaboration.

## 🏪 Agent Market

A built-in agent marketplace brings together high-quality agents from both official and community creators. Download with one click to use immediately, or integrate them as sub-agents into your own agent workflows to rapidly build complex applications.

## 👥 Multi-Tenant RBAC & User Management

Nexent provides a complete multi-tenant, role-based permission management system:

- **Four Roles**: Super Administrator, Tenant Administrator, Developer, and Regular User — each with clearly defined responsibilities
- **Multi-Tenant Isolation**: Complete data isolation between tenants, with platform-wide management support
- **User Group Mechanism**: Manage resources and access permissions through groups, supporting flexible permission delegation
- **Invitation Code Mechanism**: Controlled registration safeguards platform security
- **Resource-Level Permissions**: Fine-grained access control on agents, knowledge bases, and more — down to the user group level

For detailed information about Nexent's software architecture and technical advantages, see our **[Software Architecture](./software-architecture)** guide.
