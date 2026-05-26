![Nexent Banner](./assets/NexentBanner.png)

[![Website](https://img.shields.io/badge/Website-blue?logo=icloud&logoColor=white)](https://nexent.tech)
[![English](https://img.shields.io/badge/English-README-blue?logo=github)](README.md)
[![中文](https://img.shields.io/badge/中文-README-green?logo=github)](README_CN.md)
[![Documentation](https://img.shields.io/badge/Documentation-CN/EN-red?logo=googledocs&logoColor=%23ECD53F)](https://modelengine-group.github.io/nexent)
[![Docker Pulls](https://img.shields.io/docker/pulls/nexent/nexent?logo=docker&label=DockerPull)](https://hub.docker.com/repositories/nexent)
[![Codecov (with branch)](https://img.shields.io/codecov/c/github/ModelEngine-Group/nexent/develop?logo=codecov&color=green)](https://codecov.io/gh/ModelEngine-Group/nexent)

Nexent 是一个基于 **Harness Engineering** 原则打造的零代码智能体自动生成平台。集统一工具、技能、记忆和编排能力于一体，内置约束机制、反馈循环和控制平面。无需编排，无需复杂的拖拉拽操作，使用纯语言开发你想要的任何智能体。

> 一个提示词，无限种可能。

<video controls width="100%" style="max-width: 800px;">
  <source src="https://github.com/user-attachments/assets/b844e05d-5277-4509-9463-1c5b3516f11e" type="video/mp4" />
  <p><a href="https://github.com/user-attachments/assets/b844e05d-5277-4509-9463-1c5b3516f11e">查看演示视频</a></p>
</video>

# 🚀 先来试试看

> ⭐ 在您开始使用前，请您顺手在 [GitHub](https://github.com/ModelEngine-Group/nexent) 为我们点个 Star，您的支持是我们前进的动力！

## 方式一：使用官方体验环境

无需安装，直接访问我们的 **[在线体验环境](http://60.204.251.153:3000/zh)**，快速体验 Nexent 的强大功能。

## 方式二：自行部署

如果需要在本地或私有环境中部署 Nexent，我们提供两种部署方式：

### 系统要求

| 资源 | Docker 部署 | Kubernetes 部署 |
|------|------------|----------------|
| **CPU** | 4 核（最低）/ 8 核（推荐） | 4 核（最低）/ 8 核（推荐） |
| **内存** | 8 GiB（最低）/ 16 GiB（推荐） | 16 GiB（最低）/ 64 GiB（推荐） |
| **磁盘** | 40 GiB（最低）/ 100 GiB（推荐） | 100 GiB（最低）/ 200 GiB（推荐） |
| **架构** | x86_64 / ARM64 | x86_64 / ARM64 |
| **软件** | Docker 24+, Docker Compose v2+ | Kubernetes 1.24+, Helm 3+ |

> **注意：** 推荐配置可确保生产环境下的最佳性能。

### Docker 部署（推荐个人/小团队使用）

适用于大多数用户，快速简单。部署前需准备Docker 24+, Docker Compose v2+：

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent/docker
cp .env.example .env
bash deploy.sh
```

详细部署指南请参考 [Docker 安装部署](https://modelengine-group.github.io/nexent/zh/quick-start/installation.html)。

### Kubernetes 部署（适合企业级生产环境）

适用于需要高可用、弹性扩展的企业场景。部署前需准备 Kubernetes 集群（1.24+）和 Helm 3+：

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent/k8s/helm
./deploy-helm.sh apply
```

详细部署指南请参考 [Kubernetes 安装部署](https://modelengine-group.github.io/nexent/zh/quick-start/kubernetes-installation.html)。

# ✨ 核心特性

Nexent 为构建强大的 AI 智能体提供全面的功能集：

| 特性 | 描述 |
|------|------|
| **⚙️ 多模型集成** | OpenAI 兼容任意提供商，LLM/Embedding/VLM/STT/TTS 全覆盖，支持灵活切换 |
| **🤖 零代码智能体生成** | 纯自然语言描述需求，一键生成可执行智能体，所想即所得 |
| **🤝 A2A 智能体协作** | Agent-to-Agent 协议支持多智能体无缝协作，构建分布式工作流 |
| **🧠 分层记忆机制** | 两层记忆体系（用户级+用户-智能体级），跨对话持续积累上下文 |
| **📝 Skill 渐进式披露** | 动态加载 Skill 内容至上下文，高效利用上下文窗口 |
| **🗄️ 个人级知识库** | 20+ 文档格式实时导入与智能检索，自动摘要，细粒度权限控制 |
| **🔧 MCP 工具生态** | 即插即用的扩展工具体系，支持自定义开发和第三方 MCP 服务 |
| **🌐 互联网知识集成** | 多搜索源混合，实时信息与私有数据融合 |
| **🔍 知识级溯源** | 精确引用与来源验证，每个事实透明可查 |
| **🎭 多模态交互** | 语音、文字、图像、文件，全方位自然对话 |
| **🔢 智能体版本管理** | 版本迭代与历史回溯，安全可控 |
| **🏪 智能体市场** | 官方与社区优质智能体一键安装即用 |
| **👥 分权分域管理** | 多租户隔离，RBAC 权限体系，资源级精细管控 |

# 🤝 加入我们的社区

> *If you want to go fast, go alone; if you want to go far, go together.*

- **🗺️ 查看我们的 [功能地图](https://github.com/orgs/ModelEngine-Group/projects/6)** 探索当前和即将推出的功能。
- **🔍 试用当前版本** 并在 [问题反馈](https://github.com/ModelEngine-Group/nexent/issues) 中留下想法或报告错误。

> *Rome wasn't built in a day.*

如果我们的愿景与您产生共鸣，请通过 **[贡献指南](https://modelengine-group.github.io/nexent/zh/contributing)** 加入我们，共同塑造 Nexent。

早期贡献者不会被忽视：从特殊徽章和纪念品到其他实质性奖励，我们致力于感谢那些帮助 Nexent 诞生的先驱者。

最重要的是，我们需要关注度。请 [前往 GitHub](https://github.com/ModelEngine-Group/nexent) 为我们点星 ⭐ 并关注，与朋友分享，帮助更多开发者发现 Nexent —— 您的每一次点击都能为项目带来新的参与者，保持发展势头。

# 📖 下一步

准备好深入了解了吗？以下是主要文档入口：

- **[快速开始](https://modelengine-group.github.io/nexent/zh/quick-start/installation.html)** — 系统要求和部署指南
- **[核心特性详解](https://modelengine-group.github.io/nexent/zh/getting-started/features.html)** — 完整的功能说明
- **[用户指南](https://modelengine-group.github.io/nexent/zh/user-guide/home-page.html)** — 智能体开发与使用
- **[开发者指南](https://modelengine-group.github.io/nexent/zh/developer-guide/overview)** — 从源码构建和自定义
- **[常见问题](https://modelengine-group.github.io/nexent/zh/quick-start/faq.html)** — 常见问题和故障排除

# 📄 许可证

Nexent 采用 [MIT 许可证](LICENSE)。
