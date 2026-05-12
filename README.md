![Nexent Banner](./assets/NexentBanner.png)

[![Website](https://img.shields.io/badge/Website-blue?logo=icloud&logoColor=white)](https://nexent.tech)
[![English](https://img.shields.io/badge/English-README-blue?logo=github)](README.md)
[![中文](https://img.shields.io/badge/中文-README-green?logo=github)](README_CN.md)
[![Documentation](https://img.shields.io/badge/Documentation-CN/EN-red?logo=googledocs&logoColor=%23ECD53F)](https://modelengine-group.github.io/nexent)
[![Docker Pulls](https://img.shields.io/docker/pulls/nexent/nexent?logo=docker&label=DockerPull)](https://hub.docker.com/repositories/nexent)
[![Codecov (with branch)](https://img.shields.io/codecov/c/github/ModelEngine-Group/nexent/develop?logo=codecov&color=green)](https://codecov.io/gh/ModelEngine-Group/nexent)

Nexent is a zero-code platform for auto-generating production-grade AI agents, built on **Harness Engineering** principles. It provides unified tools, skills, memory, and orchestration with built-in constraints, feedback loops, and control planes — no orchestration, no complex drag-and-drop required, using pure language to develop any agent you want.

> One prompt. Endless reach.

<video controls width="100%" style="max-width: 800px;">
  <source src="https://github.com/user-attachments/assets/db6b7f5a-9ee8-4327-ae6f-c5af896126b4" type="video/mp4" />
  <p><a href="https://github.com/user-attachments/assets/db6b7f5a-9ee8-4327-ae6f-c5af896126b4">Watch the demo video</a></p>
</video>

# 🚀 Get Started Now

> ⭐ Before you get started, please star us on [GitHub](https://github.com/ModelEngine-Group/nexent) — your support drives us forward!

## Option 1: Try Our Official Demo

No installation required — jump right in with our **[online demo environment](http://60.204.251.153:3000/en)** to experience Nexent's capabilities instantly.

## Option 2: Deploy on Your Own

If you need to run Nexent locally or in your private infrastructure, we offer two deployment options:

### System Requirements

| Resource | Docker | Kubernetes |
|----------|--------|-------------|
| **CPU** | 4 cores (min) / 8 cores (rec.) | 4 cores (min) / 8 cores (rec.) |
| **Memory** | 8 GiB (min) / 16 GiB (rec.) | 16 GiB (min) / 64 GiB (rec.) |
| **Disk** | 40 GiB (min) / 100 GiB (rec.) | 100 GiB (min) / 200 GiB (rec.) |
| **Architecture** | x86_64 / ARM64 | x86_64 / ARM64 |
| **Software** | Docker 24+, Docker Compose v2+ | Kubernetes 1.24+, Helm 3+ |

> **Note:** Recommended configurations ensure optimal performance in production environments.

### Docker Deployment (Recommended for Individuals/Small Teams)

Quick and straightforward for most users. Prerequisites: Docker 24+ and Docker Compose v2+:

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent/docker
cp .env.example .env
bash deploy.sh
```

For detailed deployment instructions, see [Docker Installation](https://modelengine-group.github.io/nexent/en/quick-start/installation.html).

### Kubernetes Deployment (For Enterprise Production)

Ideal for enterprise scenarios requiring high availability and elastic scaling. Prerequisites: Kubernetes 1.24+ and Helm 3+:

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent/k8s/helm
./deploy-helm.sh apply
```

For detailed deployment instructions, see [Kubernetes Installation](https://modelengine-group.github.io/nexent/en/quick-start/kubernetes-installation.html).

# ✨ Core Features

Nexent provides a comprehensive feature set for building powerful AI agents:

| Feature | Description |
|---------|-------------|
| **⚙️ Multi-Model Integration** | OpenAI-compatible with any provider, full LLM/Embedding/VLM/STT/TTS coverage, supports domestic model switching |
| **🤖 Zero-Code Agent Generation** | Describe requirements in natural language, generate executable agents instantly, what you think is what you get |
| **🤝 A2A Agent Collaboration** | Agent-to-Agent protocol enables seamless multi-agent cooperation and distributed workflows |
| **🧠 Layered Memory Mechanism** | Two-tier memory (user-level + user-agent-level) for persistent context across conversations |
| **📝 Progressive Skill Disclosure** | Dynamically loads Skill into context, maximizing context window efficiency |
| **🗄️ Personal-Grade Knowledge Base** | Real-time import and intelligent retrieval for 20+ document formats, auto summaries, fine-grained access control |
| **🔧 MCP Tool Ecosystem** | Plug-and-play extension system with custom development and third-party MCP service support |
| **🌐 Internet Knowledge Integration** | Multi-source search blending real-time information with private data |
| **🔍 Knowledge-Level Traceability** | Precise citations and source verification, full transparency for every fact |
| **🎭 Multimodal Interaction** | Voice, text, images, files — comprehensive natural dialogue |
| **🔢 Agent Version Management** | Version iteration and history rollback, safe and controllable |
| **🏪 Agent Marketplace** | Official and community curated agents, one-click install and use |
| **👥 Multi-Tenancy & RBAC** | Multi-tenant isolation, role-based access control, fine-grained resource management |

# 🤝 Join Our Community

> *If you want to go fast, go alone; if you want to go far, go together.*

We have released **Nexent v2.0**! A comprehensive upgrade from v1.0, featuring A2A protocol support, progressive Skill disclosure, layered memory mechanism, user management with multi-tenancy, agent version management, agent marketplace, and more.

- **🗺️ Check our [Feature Map](https://github.com/orgs/ModelEngine-Group/projects/6)** to explore current and upcoming features.
- **🔍 Try the current build** and leave ideas or bugs in the [Issues](https://github.com/ModelEngine-Group/nexent/issues) tab.

> *Rome wasn't built in a day.*

If our vision speaks to you, jump in via the **[Contribution Guide](https://modelengine-group.github.io/nexent/en/contributing)** and shape Nexent with us.

Early contributors won't go unnoticed: from special badges and swag to other tangible rewards, we're committed to thanking the pioneers who help bring Nexent to life.

Most of all, we need visibility. Star ⭐ and watch the repo, share it with friends, and help more developers discover Nexent — your click brings new hands to the project and keeps the momentum growing.

# 📖 What's Next

Ready to dive deeper? Here are the main documentation entry points:

- **[Quick Start](https://modelengine-group.github.io/nexent/en/quick-start/installation.html)** — System requirements and deployment guide
- **[Core Features](https://modelengine-group.github.io/nexent/en/getting-started/features.html)** — Comprehensive feature documentation
- **[User Guide](https://modelengine-group.github.io/nexent/en/user-guide/home-page.html)** — Agent development and usage
- **[Developer Guide](https://modelengine-group.github.io/nexent/en/developer-guide/overview)** — Build from source and customization
- **[FAQ](https://modelengine-group.github.io/nexent/en/quick-start/faq.html)** — Common questions and troubleshooting

# 📄 License

Nexent is licensed under the [MIT License](LICENSE).
