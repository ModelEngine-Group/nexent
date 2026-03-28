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

We have released **Nexent v1**, and the platform is now relatively stable. However, there may still be some bugs, and we are continuously improving and adding new features. Stay tuned: we will announce **v2.0** soon!

* **🗺️ Check our [Feature Map](https://github.com/orgs/ModelEngine-Group/projects/6)** to explore current and upcoming features.
* **🔍 Try the current build** and leave ideas or bugs in the [Issues](https://github.com/ModelEngine-Group/nexent/issues) tab.

> *Rome wasn't built in a day.*

If our vision speaks to you, jump in via the **[Contribution Guide](../contributing)** and shape Nexent with us.

Early contributors won't go unnoticed: from special badges and swag to other tangible rewards, we're committed to thanking the pioneers who help bring Nexent to life.

Most of all, we need visibility. Star ⭐ and watch the [GitHub repository](https://github.com/ModelEngine-Group/nexent), share it with friends, and help more developers discover Nexent — your click brings new hands to the project and keeps the momentum growing.

## ✨ Key Features

Nexent offers a comprehensive set of features for building powerful AI agents:

- **🤖 Smart Agent Generation** - Zero-code agent creation using natural language
- **📊 Scalable Data Processing** - Handle 20+ file formats with intelligent extraction
- **🧠 Personal Knowledge Base** - Real-time file import with auto-summarization
- **🌐 Internet Integration** - Connect to multiple search providers and web sources
- **🔍 Knowledge Traceability** - Precise citation and source verification
- **🎭 Multimodal Support** - Voice, text, images, and file processing
- **🔧 MCP Ecosystem** - Extensible tool integration and custom development

For detailed feature information and examples, see our **[Features Guide](./features)**.

## 🏗️ Software Architecture

Nexent adopts a modern distributed microservices architecture designed to provide high-performance, scalable AI agent platform. The entire system is based on containerized deployment, supporting cloud-native and enterprise-grade application scenarios.

### 🌐 Layered Architecture Design
- **Frontend Layer** - Modern user interface built with Next.js + React + TypeScript
- **API Gateway Layer** - FastAPI high-performance web framework for request routing and load balancing
- **Business Logic Layer** - Agent management, conversation management, knowledge base management, and model management
- **Data Layer** - Distributed storage architecture with PostgreSQL, Elasticsearch, Redis, and MinIO

### 🚀 Core Service Architecture
- **Agent Services** - Agent generation and execution based on SmolAgents framework
- **Data Processing Services** - Real-time and batch processing supporting 20+ file formats
- **MCP Ecosystem** - Standardized tool interfaces and plugin architecture

### ⚡ Distributed Features
- **Asynchronous Processing** - High-performance async processing architecture based on asyncio
- **Microservices Design** - Service decoupling with independent scaling and deployment
- **Containerized Deployment** - Docker Compose service orchestration supporting cloud-native deployment

For detailed architectural design and technical implementation, see our **[Software Architecture](./software-architecture)**.

## ⚡ Quick Start

Ready to get started? Here are your next steps:

1. **📋 [Installation & Deployment](../quick-start/installation)** - System requirements and deployment guide
2. **🔧 [Developer Guide](../developer-guide/overview)** - Build from source and customize
3. **❓ [FAQ](../quick-start/faq)** - Common questions and troubleshooting

## 💬 Community & contact

Join our [Discord community](https://discord.gg/tb5H3S3wyv) to chat with other developers and get help!

## 📄 License

Nexent is licensed under the [MIT License](../license).
