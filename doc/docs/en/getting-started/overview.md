# Nexent

Nexent is a zero-code platform for auto-generating production-grade AI agents, built on **Harness Engineering** principles. It provides unified tools, skills, memory, and orchestration with built-in constraints, feedback loops, and control planes — no orchestration, no complex drag-and-drop required, using pure language to develop any agent you want.

> One prompt. Endless reach.

![Nexent Banner](../../assets/NexentBanner.png)

## 🎬 Demo Video

<video controls width="100%" style="max-width: 800px;">
  <source src="https://github.com/user-attachments/assets/b844e05d-5277-4509-9463-1c5b3516f11e" type="video/mp4" />
  <p>Your browser does not support the video tag. <a href="https://github.com/user-attachments/assets/b844e05d-5277-4509-9463-1c5b3516f11e">View the demo video</a></p>
</video>

## 🤝 Join Our Community

> *If you want to go fast, go alone; if you want to go far, go together.*

We have released **Nexent v2.0** — a major upgrade over v1.0. This release brings A2A protocol support, progressive Skill disclosure, layered memory architecture, full-featured user management with RBAC, agent version management, and the Agent Market. Core capabilities like knowledge base integration, multimodal interaction, and the MCP tool ecosystem have been significantly enhanced. The platform is maturing rapidly and we welcome your feedback.

- **🗺️ Check our [Feature Map](https://github.com/orgs/ModelEngine-Group/projects/6)** to explore current and upcoming features.
- **🔍 Try the current build** and leave ideas or bugs in the [Issues](https://github.com/ModelEngine-Group/nexent/issues) tab.

> *Rome wasn't built in a day.*

If our vision speaks to you, jump in via the **[Contribution Guide](../contributing)** and shape Nexent with us.

Early contributors won't go unnoticed: from special badges and swag to other tangible rewards, we're committed to thanking the pioneers who help bring Nexent to life.

Most of all, we need visibility. Star ⭐ and watch the [GitHub repository](https://github.com/ModelEngine-Group/nexent), share it with friends, and help more developers discover Nexent — your click brings new hands to the project and keeps the momentum growing.

## ✨ Key Features

Nexent v2.0 delivers a comprehensive feature set for building powerful AI agents:

- **⚙️ Multi-Model Integration** — OpenAI-compatible any provider, with full Embedding/VLM/STT/TTS support
- **🤖 Zero-Code Agent Generation** — Describe in plain language, deploy in one click
- **🤝 A2A Agent Collaboration** — Agent-to-Agent protocol for seamless multi-agent workflows
- **🧠 Layered Memory Architecture** — Two-tier memory system with cross-conversation context accumulation
- **📝 Progressive Skill Disclosure** — Context-aware tool suggestions that reveal as you go
- **🗄️ Personal-Grade Knowledge Base** — 20+ format document import with intelligent retrieval
- **🔧 MCP Tool Ecosystem** — Plug-and-play extensibility with custom tool development
- **🌐 Internet Knowledge Integration** — Multi-source hybrid search blending real-time web with private data
- **🔍 Knowledge-Level Traceability** — Precise citations and verifiable sources on every answer
- **🎭 Multimodal Interaction** — Voice, text, images, and files for fully natural conversations
- **🔢 Agent Version Management** — Version iteration and rollback for safe, controlled deployments
- **🏪 Agent Market** — Official and community agents ready to install and use
- **👥 Multi-Tenant RBAC** — Tenant isolation, role-based permissions, and fine-grained resource access

For detailed feature information and examples, see our **[Features Guide](./features)**.

## 🏗️ Software Architecture

Nexent adopts a modern distributed microservices architecture designed to provide high-performance, scalable AI agent platform. The entire system is based on containerized deployment, supporting cloud-native and enterprise-grade application scenarios.

### 🌐 Layered Architecture Design

- **Frontend Layer** — Modern user interface built with Next.js + React + TypeScript
- **API Gateway Layer** — FastAPI high-performance web framework for request routing and load balancing
- **Business Logic Layer** — Agent management, conversation management, knowledge base management, and model management
- **Data Layer** — Distributed storage architecture with PostgreSQL, Elasticsearch, Redis, and MinIO

### 🚀 Core Service Architecture

- **Agent Services** — Agent generation and execution based on SmolAgents framework
- **Data Processing Services** — Real-time and batch processing supporting 20+ file formats
- **MCP Ecosystem** — Standardized tool interfaces and plugin architecture

### ⚡ Distributed Features

- **Asynchronous Processing** — High-performance async processing architecture based on asyncio
- **Microservices Design** — Service decoupling with independent scaling and deployment
- **Containerized Deployment** — Docker Compose service orchestration supporting cloud-native deployment

For detailed architectural design and technical implementation, see our **[Software Architecture](./software-architecture)**.

## ⚡ Quick Start

Ready to get started? Here are your next steps:

1. **📋 [Installation & Deployment](../quick-start/installation)** — System requirements and deployment guide
2. **🔧 [Developer Guide](../developer-guide/overview)** — Build from source and customize
3. **❓ [FAQ](../quick-start/faq)** — Common questions and troubleshooting

## 💬 Community & contact

Join our [Discord community](https://discord.gg/tb5H3S3wyv) to chat with other developers and get help!

## 📄 License

Nexent is licensed under the [MIT License](../license).
