# Nexent

Nexent 是一个基于 **Harness Engineering** 原则构建的零代码智能体平台。用户只需用自然语言描述目标，系统便可生成智能体配置，并协助完成工具、Skill、知识库、记忆和协作智能体的配置。智能体生成后可直接调试、发布和持续迭代，无需手动编排复杂工作流。

> 一个提示词，无限种可能。

![Nexent Banner](../../assets/NexentBanner.png)

## 🎬 Demo 视频

<video controls width="100%" style="max-width: 800px;">
  <source src="https://github.com/user-attachments/assets/b844e05d-5277-4509-9463-1c5b3516f11e" type="video/mp4" />
  <p>您的浏览器不支持视频标签。<a href="https://github.com/user-attachments/assets/b844e05d-5277-4509-9463-1c5b3516f11e">查看演示视频</a></p>
</video>

## 🤝 加入我们的社区

> *If you want to go fast, go alone; if you want to go far, go together.*

当前文档对应 **Nexent v2.5.0**。该版本增强了自然语言生成智能体（NL2Agent）、工具与 Skill 推荐、隔离沙箱执行、文件产物处理、分层记忆、个人知识库容量和北向 API 等能力。平台同时支持 A2A 智能体协作、MCP 工具、知识库检索、多模态交互、版本管理和多租户权限控制。

- **🗺️ 查看我们的 [功能地图](https://github.com/orgs/ModelEngine-Group/projects/6)** 探索当前和即将推出的功能。
- **🔍 试用当前版本** 并在 [问题反馈](https://github.com/ModelEngine-Group/nexent/issues) 中留下想法或报告错误。

> *Rome wasn't built in a day.*

如果我们的愿景与您产生共鸣，请通过 **[贡献指南](../contributing)** 加入我们，共同塑造 Nexent。

早期贡献者不会被忽视：从特殊徽章和纪念品到其他实质性奖励，我们致力于感谢那些帮助 Nexent 诞生的先驱者。

最重要的是，我们需要关注度。请 [前往 GitHub](https://github.com/ModelEngine-Group/nexent) 为我们点星 ⭐ 并关注，与朋友分享，帮助更多开发者发现 Nexent —— 您的每一次点击都能为项目带来新的参与者，保持发展势头。

## ✨ 核心特性

Nexent v2.5.0 提供以下核心能力：

- **⚙️ 多模型集成** — 统一管理 LLM、Embedding、Rerank、图像、视频、音频、STT 和 TTS 模型
- **🤖 智能体零代码生成** — 通过多轮自然语言对话澄清需求、推荐资源并生成可调试的智能体配置
- **🤝 A2A 智能体协作** — Agent-to-Agent 协议支持多智能体无缝协作
- **🧠 分层记忆机制** — Tenant、User 和 Agent 三层记忆，并支持 Dreaming 整理长期记忆
- **📝 Skill 渐进式披露** — 按需读取 Skill 说明与资源，并在沙箱中隔离执行脚本
- **🗄️ 个人级知识库** — 支持多种文档格式、智能检索、访问权限和容量配额
- **🔧 MCP 工具生态** — 即插即用的扩展工具体系，可自定义开发
- **🌐 互联网知识集成** — 多搜索源混合，实时信息与私有数据融合
- **🔍 知识级溯源** — 精确引用与来源验证，每个事实透明可查
- **🎭 多模态与文件处理** — 支持文本、图像、音频、视频和文档输入，并展示可预览或下载的生成文件
- **🔢 智能体版本管理** — 版本迭代与历史回溯，安全可控
- **🏪 资源仓库** — 共享和复用智能体、MCP 服务与 Skill，并支持上架审核
- **👥 分权分域管理** — 多租户隔离、RBAC、用户组、资源授权、API Key 和知识库容量管理

有关详细的功能信息和示例，请参阅我们的 **[核心特性](./features)**。

## 🏗️ 软件架构

Nexent 将配置管理、智能体运行、MCP、北向接口、数据处理和 Web 前端拆分为独立服务，并通过 Docker Compose 或 Kubernetes 部署。PostgreSQL、Elasticsearch、Redis 和 MinIO 分别承担业务数据、检索索引、缓存与任务队列、对象存储等职责。

### 🌐 分层架构设计

- **前端层** — Next.js + React + TypeScript 构建的现代化用户界面
- **API 服务层** — 基于 FastAPI 提供配置、运行时、MCP、北向接口和数据处理 API
- **业务逻辑层** — 负责智能体、会话、知识库、模型、记忆、权限和资源仓库管理
- **数据层** — 使用 PostgreSQL、Elasticsearch、Redis 和 MinIO 保存不同类型的数据

### 🚀 核心服务架构

- **智能体服务** — 基于 SmolAgents 生成和执行智能体，通过 Runtime 输出流式结果
- **沙箱与文件工作区** — 隔离执行模型生成的代码和 Skill 脚本，并将生成文件同步到对象存储
- **数据处理服务** — 解析、分块和向量化文档，为知识库检索建立索引
- **MCP 生态系统** — 统一接入远程、容器化和自定义 API 工具

### ⚡ 分布式特性

- **异步与流式处理** — 使用异步任务和 SSE 持续返回智能体执行结果
- **服务拆分** — 配置、运行和数据处理服务可独立部署和扩展
- **容器化部署** — 同时提供 Docker Compose 与 Helm 部署方案

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
