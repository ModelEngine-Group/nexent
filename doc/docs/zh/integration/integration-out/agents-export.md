# Agent 导出

Nexent 支持将 Agent 智能体的完整配置以 JSON 或 ZIP 文件的形式导出，便于跨环境迁移、备份与批量分发。本文档介绍 Agent 导出的格式、流程与导入方法。

## 📋 概述

| 方式 | 说明 | 适用场景 |
|------|------|----------|
| **导出配置** | 将 Agent 配置导出为 JSON/ZIP 文件 | 迁移到其他 Nexent 部署、备份 |
| **导入配置** | 从 JSON/ZIP 文件导入 Agent | 复用现有配置、跨环境迁移 |

## 📤 导出 Agent 配置

### 操作步骤

1. 进入 **Agent 仓库** → **我的 Agent** 页面
2. 找到需要导出的 Agent
3. 点击 Agent 右侧的「导出」按钮
4. 选择导出格式：
   - **JSON**：仅包含配置，无技能包
   - **ZIP**：包含配置和所有技能文件
5. 系统生成文件并自动下载

### 导出文件说明

#### JSON 格式

```json
{
  "name": "data-analyst",
  "version": "1.0.0",
  "model": "gpt-4",
  "prompt": {
    "role": "你是一个专业的数据分析助手...",
    "requirements": "...",
    "examples": "..."
  },
  "tools": [
    {
      "type": "knowledge_base",
      "name": "kb_search"
    },
    {
      "type": "mcp",
      "name": "github-tools"
    }
  ],
  "skills": [
    {
      "name": "csv-analyzer",
      "params": {"top_k": 5}
    }
  ],
  "collaborators": [
    "visualization-agent"
  ],
  "memory": {
    "type": "layered",
    "short_term": {...},
    "long_term": {...}
  }
}
```

#### ZIP 格式

包含 JSON 配置文件和所有技能包：

```
data-analyst.zip
├── agent.json           # Agent 配置
└── skills/
    ├── csv-analyzer/
    │   ├── SKILL.md
    │   └── scripts/
    │       └── analyze.py
    └── report-generator/
        ├── SKILL.md
        └── assets/
            └── template.md
```

### 使用场景

- **跨环境迁移**：从开发环境迁移到生产环境
- **备份恢复**：定期导出作为配置备份
- **批量分发**：将成熟的 Agent 分发给其他租户

## 📥 导入 Agent 配置

### 操作步骤

1. 进入 **Agent 仓库** → **我的 Agent** 页面
2. 点击「导入」按钮
3. 在弹出的文件选择框中选择 JSON 或 ZIP 文件
4. 系统验证配置文件格式和内容
5. 展示导入的 Agent 预览信息
6. 确认后完成导入

### 依赖处理

导入时系统会检查 Agent 的依赖配置：

| 依赖类型 | 处理方式 |
|----------|----------|
| **模型** | 检查是否已开通，未开通需先配置 |
| **知识库** | 继承导入者权限，检索范围受限于导入者权限 |
| **MCP 服务** | 检查是否已配置，未配置需手动添加 |
| **Skill** | 自动导入技能包（如 ZIP 中包含） |
| **协作 Agent** | 检查是否已存在，需手动配置 |

### 注意事项

- **名称冲突**：如导入同名 Agent，系统会提示修改
- **知识库权限**：导入不会继承原作者的知识库权限
- **变量名唯一性**：检查并确保变量名不冲突

### 两种导入方式

| 方式 | 说明 | 适用场景 |
|------|------|----------|
| **直接导入** | 保留重复名称，导入后需手动修改 | 快速导入，后续手动处理 |
| **重新生成** | 调用 LLM 重命名 Agent | 名称冲突较多，希望自动处理 |

## ❓ 常见问题

### Q: 导出的 Agent 在新环境无法使用

1. 检查依赖配置是否完整
2. 确认模型、知识库等资源是否已开通
3. 验证 MCP 服务和 Skill 是否已正确配置

### Q: 导入时知识库检索结果与原作者不同

导入不会继承原作者的知识库权限，检索范围受限于导入者权限。这是设计如此，请确保导入者在目标环境有足够的知识库访问权限。

### Q: JSON 和 ZIP 格式如何选择？

- 仅迁移 Agent 配置、不需要附带技能文件时，选择 JSON。
- 需要完整迁移 Agent 及其依赖技能包时，选择 ZIP。

## 🔗 相关资源

- [Agent 智能体发布](./agents-publish) — 将 Agent 发布为可外部调用的服务
- [Agent 接入](../integration-in/agents) — 通过 A2A 协议接入第三方 Agent
- [智能体配置](../../user-guide/agent-development/agent-configuration) — Agent 配置详解
