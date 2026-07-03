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
cd nexent
bash deploy.sh docker
```

The root `deploy.sh` only forwards to the target deploy script; the native Docker implementation is `bash deploy/docker/deploy.sh`. The Docker and Kubernetes deploy scripts share the same deployment configuration model. Interactive runs show Bash TUI menus for component selection, port policy, and image source. `infrastructure` is required; `application`, `data-process`, and `supabase` are selected by default and can be disabled when you want a smaller deployment. Use `b`/Backspace to return to the previous TUI step and `q` to quit. Non-interactive runs can pass the same choices with `--version`, `--components`, `--port-policy development|production`, and `--image-source general|mainland|local-latest`. Successful deployments save non-sensitive choices to each deploy directory's `deploy.options` for reuse on the next run.

Docker and Kubernetes both use `deploy/env/.env` as the runtime configuration file. Existing `deploy/env/.env` is kept as-is. If it does not exist, the deploy scripts first reuse `docker/.env`, then fall back to `deploy/env/.env.example`. Monitoring-specific settings are generated from `deploy/env/monitoring.env.example` into `deploy/env/monitoring.env`.

Docker uninstall is handled by `bash uninstall.sh docker`. It can preserve or delete data volumes: run it interactively, pass `--delete-volumes true|false`, or use `bash uninstall.sh docker delete-all` to remove containers and persistent data.

Offline image packages can be built with `bash build.sh --package --target docker --compress true` or `bash deploy/offline/build_offline_package.sh --target docker --compress true`. The package includes image tar files, `load-images.sh`, root deploy/uninstall entrypoints, deployment scripts, SQL files, `manifest.yaml`, and `checksums.txt`; deploy it with `bash deploy.sh --load-images docker ...` on the target host.

For detailed deployment instructions, see [Docker Installation](https://modelengine-group.github.io/nexent/en/quick-start/installation.html).

### Kubernetes Deployment (For Enterprise Production)

Ideal for enterprise scenarios requiring high availability and elastic scaling. Prerequisites: Kubernetes 1.24+ and Helm 3+:

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent
bash deploy.sh k8s
```

The native Kubernetes implementation is `bash deploy/k8s/deploy.sh`. It reads the same `deploy/env/.env` as Docker and renders explicit values into Helm ConfigMap and Secret overrides. Use `--persistence-mode local|dynamic|existing`, `--storage-class`/`--sc`, `--local-path`, `--local-node-name`, and `--existing-claim-prefix` to control PVC behavior. Local mode renders `hostPath` PVs and does not require node affinity.

Kubernetes uninstall is handled by `bash uninstall.sh k8s`. It removes the Helm release first, then can optionally delete the namespace and local PV data. Use `--delete-namespace true|false`, `--delete-local-data true|false`, or `bash uninstall.sh k8s delete-all`; pass `--keep-local-data` with `delete-all` to preserve local volume contents.

Kubernetes offline packages use the same builder with `--target k8s` or `--target all`. Run `load-images.sh` on every cluster node that needs the images, or push the loaded images to an internal registry before deploying with the same version and image-source options used during packaging.

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
