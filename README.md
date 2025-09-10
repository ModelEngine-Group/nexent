![Nexent Banner](./assets/NexentBanner.png)

[![English](https://img.shields.io/badge/English-README-blue)](README.md)
[![中文](https://img.shields.io/badge/中文-README-green)](README_CN.md)
[![Documentation](https://img.shields.io/badge/Documentation-yellow)](https://modelengine-group.github.io/nexent)
[![codecov](https://codecov.io/gh/ModelEngine-Group/nexent/branch/develop/graph/badge.svg?token=00JM5YAD5V)](https://codecov.io/gh/ModelEngine-Group/nexent?branch=develop)

Nexent is a zero-code platform for auto-generating agents — no orchestration, no complex drag-and-drop required, using pure language to develop any agent you want. Built on the MCP ecosystem with rich tool integration, Nexent also provides various built-in agents to meet your intelligent service needs in different scenarios such as work, travel, and daily life. Nexent offers powerful capabilities for agent running control, multi-agent collaboration, data processing and knowledge tracing, multimodal dialogue, and batch scaling.

> One prompt. Endless reach.

### 🌟 Try Nexent Now

- 🌐 Visit our [official website](http://nexent.tech/) to learn more
- 🚀 [Try it now](http://nexent.tech/try) to experience the power of Nexent

https://github.com/ModelEngine-Group/nexent/discussions/46#discussioncomment-14358057

# 🤝 Join Our Community

> *If you want to go fast, go alone; if you want to go far, go together.*

We have released **Nexent v1**, and the platform is now relatively stable. However, there may still be some bugs, and we are continuously improving and adding new features. Stay tuned: we will announce **v2.0** soon!

* **🗺️ Check our [Feature Map](https://github.com/orgs/ModelEngine-Group/projects/6)** to explore current and upcoming features.
* **🔍 Try the current build** and leave ideas or bugs in the [Issues](https://github.com/ModelEngine-Group/nexent/issues) tab.

> *Rome wasn't built in a day.*

If our vision speaks to you, jump in via the **[Contribution Guide](https://modelengine-group.github.io/nexent/en/contributing)** and shape Nexent with us.

Early contributors won't go unnoticed: from special badges and swag to other tangible rewards, we're committed to thanking the pioneers who help bring Nexent to life.

Most of all, we need visibility. Star ⭐ and watch the repo, share it with friends, and help more developers discover Nexent — your click brings new hands to the project and keeps the momentum growing.

# ⚡ Have a try first

### 1. 📋 Prerequisites  

| Resource | Minimum |
|----------|---------|
| **CPU**  | 2 cores |
| **RAM**  | 6 GiB   |
| **Software** | Docker & Docker Compose installed |

### 2. 🛠️ Quick start with Docker Compose

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent/docker
cp .env.example .env # fill only necessary configs
bash deploy.sh
```

When the containers are running, open **http://localhost:3000** in your browser and follow the setup wizard.

# 🌱 MCP Tool Ecosystem

Check our [MCP Ecosystem page](https://modelengine-group.github.io/nexent/en/mcp-ecosystem/overview.html) for detailed information about the MCP tool ecosystem, including community hubs, recommended tools, and integration guides.

### 🚀 Suggested Agent Scenarios

Check our [Agent Scenarios page](https://modelengine-group.github.io/nexent/en/mcp-ecosystem/use-cases.html) for detailed agent use cases and best practices, including travel planning, research assistant, business intelligence, smart lifestyle, and more scenarios.

# ✨ Key Features

`1` **Smart agent prompt generation**  
   Turn plain language into runnable prompts. Nexent automatically chooses the right tools and plans the best action path for every request.

   ![Feature 1](./assets/Feature1.png)

`2` **Scalable data process engine**  
   Process 20+ data formats with fast OCR and table structure extraction, scaling smoothly from a single process to large-batch pipelines.

   ![Feature 2](./assets/Feature2.png)

`3` **Personal-grade knowledge base**  
   Import files in real time, auto-summarise them, and let agents access both personal and global knowledge instantly, also knowing what it can get from each knowledge base.

   ![Feature 3](./assets/Feature3.png)

`4` **Internet knowledge search**  
   Connect to 5+ web search providers so agents can mix fresh internet facts with your private data.

   ![Feature 4](./assets/Feature4.png)

`5` **Knowledge-level traceability**  
   Serve answers with precise citations from web and knowledge-base sources, making every fact verifiable.

   ![Feature 5](./assets/Feature5.png)

`6` **Multimodal understanding & dialogue**  
   Speak, type, files, or show images. Nexent understands voice, text, and pictures, and can even generate new images on demand.

   ![Feature 6](./assets/Feature6.png)

`7` **MCP tool ecosystem**  
   Drop in or build Python plug-ins that follow the MCP spec; swap models, tools, and chains without touching core code.

   ![Feature 7](./assets/Feature7.png)

# 🛠️ Developer Guide

### 🤖 Model Configuration & Provider Recommendations

Check our [Model Providers page](https://modelengine-group.github.io/nexent/en/getting-started/model-providers.html) for detailed model configuration guides and recommended provider information.

### 🔧 Hack on Nexent

Want to build from source or add new features? Check the [Contribution Guide](https://modelengine-group.github.io/nexent/en/contributing) for step-by-step instructions.

### 🛠️ Build from Source

Prefer to run Nexent from source code? Follow our [Developer Guide](https://modelengine-group.github.io/nexent/en/getting-started/development-guide) for detailed setup instructions and customization options.

# 🐛 Known Issues

Check our [Known Issues page](https://modelengine-group.github.io/nexent/en/known-issues.html) for the latest issue status and solutions.

# 💬 Community & contact

- Browse the [FAQ](https://modelengine-group.github.io/nexent/en/faq) for common install issues.  
- Join our [Discord community](https://discord.gg/tb5H3S3wyv) to chat with other developers and get help!
- File bugs or feature ideas in [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues).

# 📄 License

Nexent is licensed under the [MIT](LICENSE) with additional conditions. Please read the [LICENSE](LICENSE) file for details.

