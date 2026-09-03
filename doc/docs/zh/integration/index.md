# 第三方集成

Nexent 平台提供了完善的第三方集成能力，支持双向资源整合：您可以将外部 AI 资源（MCP 服务、Skill 技能、Agent 智能体）接入平台，也可以将平台开发的资源导出或发布给外部系统使用。无论您是第三方开发者、合作伙伴还是企业客户，都能通过这套集成体系实现与 Nexent 的深度整合。

## 📋 资源接入与导出

Nexent 平台提供双向资源整合能力，让您既能充分利用外部生态，也能将平台能力输出给外部系统：

### 接入外部资源

将外部 AI 资源接入平台进行管理和使用，丰富平台能力：

| 资源类型 | 接入方式 | 适用场景 |
|----------|---------------|----------|
| MCP 服务 | 远程链接、容器部署、API 转 MCP | 接入第三方 MCP 服务，或将企业 REST API 转换为 MCP 工具 |
| Skill 技能 | 上传 SKILL.md、上传 ZIP 包 | 接入第三方开发的技能包 |
| Agent 智能体 | A2A 协议发现 | 通过 URL 或 Nacos 发现第三方 Agent，实现跨平台协作 |

### 导出平台能力

将平台资源导出或发布给外部系统使用：

| 资源类型 | 方式 | 说明 | 适用场景 |
|----------|------|------|----------|
| Agent 智能体 | 导出为 JSON/ZIP | 将智能体配置迁移到其他 Nexent 环境部署，实现跨环境复用 | 迁移、备份、批量分发 |
| Agent 智能体 | 普通发布（北向 RESTful API） | 发布后通过标准 RESTful API 调用 | 与业务系统深度集成，实现工作流自动化 |
| Agent 智能体 | 发布为 A2A Agent | 将智能体暴露给外部支持 A2A 协议的系统调用，支持 REST 和 JSON-RPC 协议 | 跨平台 Agent 协作 |

## 🗂️ 文档结构

本部分文档按照以下结构组织：

```
第三方集成
├── 资源接入指南
│   ├── [MCP 服务接入](./integration-in/mcp) — 接入第三方 MCP 服务
│   ├── [Skill 技能接入](./integration-in/skill) — 接入第三方 Skill 技能
│   └── [Agent 智能体接入](./integration-in/agents) — 通过 A2A 协议接入第三方 Agent
└── 导出与发布指南
    ├── [Agent 智能体导出](./integration-out/agents-export) — 导出/导入 Agent 配置文件（JSON/ZIP）
    ├── [Agent 智能体发布](./integration-out/agents-publish) — 普通发布（北向 API）与 A2A 发布
    └── [调用 Agent 北向 API](./integration-out/northbound-api) — 北向 RESTful API 详细参考
```

## 🚀 快速开始

### 想要接入外部资源？

| 目标 | 操作步骤 | 详细文档 |
|------|----------|----------|
| **MCP 服务** | 准备服务 → 选择接入方式 → 配置并测试 → 配置给智能体 | [MCP 服务接入](./integration-in/mcp) |
| **Skill 技能** | 选择接入方式 → 准备技能内容 → 上传或生成 → 配置给智能体 | [Skill 技能接入](./integration-in/skills) |
| **Agent 智能体** | 发现外部 Agent → 配置调用协议 → 设为协作智能体 | [Agent 智能体接入](./integration-in/agents) |

### 想要将平台能力导出？

| 目标 | 操作步骤 | 详细文档 |
|------|----------|----------|
| **导出 Agent 配置** | 选择 Agent → 导出 JSON/ZIP → 导入到其他 Nexent 部署 | [Agent 智能体导出](./integration-out/agents-export) |
| **普通发布 Agent** | 发布 Agent → 生成 API Key → 调用北向 API | [Agent 智能体发布](./integration-out/agents-publish) / [调用 Agent 北向 API](./integration-out/northbound-api) |
| **发布为 A2A Agent** | 发布 Agent → 勾选 A2A 选项 → 获取调用信息 | [Agent 智能体发布](./integration-out/agents-publish) |

## 🔗 相关资源

- [智能体开发](../user-guide/agent-development) — 了解如何在 Nexent 中创建和配置智能体
- [MCP 生态系统](../mcp-ecosystem/overview) — 了解更多 MCP 生态相关内容

## 💬 获取帮助

如果在整合过程中遇到任何问题，欢迎通过以下渠道获取帮助：

- [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions) — 提问和讨论
- [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) — 报告问题
- [Discord 社区](https://discord.gg/tb5H3S3wyv) — 与社区成员交流
