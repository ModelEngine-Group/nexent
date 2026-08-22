# Nexent

Nexent 是一个基于 **Harness Engineering** 原则打造的零代码智能体自动生成平台。集统一工具、技能、记忆和编排能力于一体，内置约束机制、反馈循环和控制平面。无需编排，无需复杂的拖拉拽操作，使用纯语言开发你想要的任何智能体。

> 一个提示词，无限种可能。

![Nexent Banner](../../assets/NexentBanner.png)

## 🎬 Demo 视频

<video controls width="100%" style="max-width: 800px;">
  <source src="https://github.com/user-attachments/assets/b844e05d-5277-4509-9463-1c5b3516f11e" type="video/mp4" />
  <p>您的浏览器不支持视频标签。<a href="https://github.com/user-attachments/assets/b844e05d-5277-4509-9463-1c5b3516f11e">查看演示视频</a></p>
</video>

## 🤝 加入我们的社区

> *If you want to go fast, go alone; if you want to go far, go together.*

我们已发布 **Nexent v2.0**！在 v1.0 的基础上全面升级，带来 A2A 协议支持、Skill 渐进式披露、分层记忆机制、用户管理与分权分域、智能体版本管理、智能体市场等重磅功能。同时保留并强化了知识库集成、多模态交互、MCP 工具生态等核心能力。平台功能日趋完善，欢迎试用并提出您的宝贵意见。

- **🗺️ 查看我们的 [功能地图](https://github.com/orgs/ModelEngine-Group/projects/6)** 探索当前和即将推出的功能。
- **🔍 试用当前版本** 并在 [问题反馈](https://github.com/ModelEngine-Group/nexent/issues) 中留下想法或报告错误。

> *Rome wasn't built in a day.*

如果我们的愿景与您产生共鸣，请通过 **[贡献指南](../contributing)** 加入我们，共同塑造 Nexent。

早期贡献者不会被忽视：从特殊徽章和纪念品到其他实质性奖励，我们致力于感谢那些帮助 Nexent 诞生的先驱者。

最重要的是，我们需要关注度。请 [前往 GitHub](https://github.com/ModelEngine-Group/nexent) 为我们点星 ⭐ 并关注，与朋友分享，帮助更多开发者发现 Nexent —— 您的每一次点击都能为项目带来新的参与者，保持发展势头。

## ✨ 核心特性

Nexent v2.0 为构建强大的 AI 智能体提供全面的功能集：

- **⚙️ 多模型集成** — OpenAI 兼容任意提供商，Embedding/VLM/STT/TTS 全覆盖
- **🤖 智能体零代码生成** — 纯自然语言描述需求，一键生成可执行智能体
- **🤝 A2A 智能体协作** — Agent-to-Agent 协议支持多智能体无缝协作
- **🧠 分层记忆机制** — 两层记忆体系，跨对话持续积累上下文
- **📝 Skill 渐进式披露** — 动态揭示最相关工具，渐进探索系统能力
- **🗄️ 个人级知识库** — 20+ 格式文档实时导入与智能检索
- **🔧 MCP 工具生态** — 即插即用的扩展工具体系，可自定义开发
- **🌐 互联网知识集成** — 多搜索源混合，实时信息与私有数据融合
- **🔍 知识级溯源** — 精确引用与来源验证，每个事实透明可查
- **🎭 多模态交互** — 语音、文字、图像、文件，全方位自然对话
- **🔢 智能体版本管理** — 版本迭代与历史回溯，安全可控
- **🏪 智能体市场** — 官方与社区优质智能体，一键安装即用
- **👥 分权分域管理** — 多租户隔离，RBAC 权限体系，精细化资源管控

有关详细的功能信息和示例，请参阅我们的 **[核心特性](./features)**。

## 🏗️ 软件架构

Nexent 采用现代化的分布式微服务架构，专为高性能、可扩展的 AI 智能体平台而设计。整个系统基于容器化部署，支持云原生和企业级应用场景。

### 🌐 分层架构设计

- **前端层** — Next.js + React + TypeScript 构建的现代化用户界面
- **API 网关层** — FastAPI 高性能 Web 框架，负责请求路由和负载均衡
- **业务逻辑层** — 智能体管理、对话管理、知识库管理和模型管理
- **数据层** — PostgreSQL、Elasticsearch、Redis、MinIO 分布式存储架构

### 🚀 核心服务架构

- **智能体服务** — 基于 SmolAgents 框架的智能体生成和执行
- **数据处理服务** — 支持 20+ 种文件格式的实时和批量处理
- **MCP 生态系统** — 标准化的工具接口和插件架构

### ⚡ 分布式特性

- **异步处理** — 基于 asyncio 的高性能异步处理架构
- **微服务设计** — 服务解耦，独立扩展和部署
- **容器化部署** — Docker Compose 服务编排，支持云原生部署

有关详细的架构设计和技术实现，请参阅我们的 **[软件架构](./software-architecture)**。

## ⚡ 快速开始

准备好开始了吗？以下是您的下一步：

1. **📋 [安装部署](../quick-start/installation)** — 系统要求和部署指南
2. **🔧 [开发者指南](../developer-guide/overview)** — 从源码构建和自定义
3. **❓ [常见问题](../quick-start/faq)** — 常见问题和故障排除

## 💬 社区与联系方式

加入我们的 [Discord 社区](https://discord.gg/tb5H3S3wyv) 与其他开发者交流并获取帮助！

## 📄 许可证

Nexent 采用 [MIT 许可证](../license)。
