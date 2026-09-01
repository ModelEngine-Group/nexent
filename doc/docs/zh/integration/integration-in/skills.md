# Skill 技能接入

Skill（技能）是 Nexent 平台为智能体扩展能力的核心机制。Nexent 支持接入外部开发的技能包，将第三方能力快速整合到智能体中。

## 📋 接入方式概览

Nexent 支持多种 Skill 接入方式：

| 接入方式 | 适用场景 | 文件要求 |
|----------|----------|----------|
| **上传 SKILL.md** | 单文件技能，简单场景 | `.md` 文件，包含 YAML Front Matter |
| **上传 ZIP 包** | 多文件技能，包含脚本和资源 | ZIP 包内含 `SKILL.md` |

## 📦 上传 Skill 文件

### 单文件 Skill（.md）

适用于不包含脚本和额外资源的简单技能。

**文件要求**：
- 文件名：`SKILL.md`（或任意文件名）
- 编码：UTF-8
- 包含 YAML Front Matter，必须字段：`name`、`description`

**SKILL.md 基本结构**：

```markdown
---
name: csv-analyzer
description: |
  分析 CSV 文件并生成数据质量报告。适用于用户上传 CSV 文件后的数据检查场景。
tags:
  - data-analysis
  - csv
---

# CSV 数据质量报告

## 功能说明

此技能用于分析 CSV 文件的数据质量，包括：
- 缺失值统计
- 重复数据检测
- 字段类型分析

## 使用示例

当用户提供 CSV 文件时，自动执行数据质量检查。
```

### 多文件 Skill（.zip）

适用于包含脚本、资源文件等辅助内容的复杂技能。

**文件结构**：

```
skill-name.zip
├── SKILL.md              # 必需：技能定义文件
├── config/
│   ├── config.yaml       # 可选：参数默认值
│   └── schema.yaml       # 可选：参数类型定义
├── scripts/
│   └── analyze.py        # 可选：Python 脚本
├── examples.md           # 可选：使用示例
└── assets/               # 可选：静态资源
```

### 操作步骤

1. 进入 **Skill 仓库** → **我的 Skill** 页面
2. 点击「创建 Skill」
3. 选择「上传技能文件」
4. 拖拽或选择 `.md` / `.zip` 文件
5. 系统自动解析并展示技能信息
6. 检查解析结果，确认无误后点击「创建」

### 注意事项

- `SKILL.md` 必须包含有效的 YAML Front Matter
- `name` 字段不能与已有技能重名
- ZIP 包内的 `SKILL.md` 可以在根目录或子目录中
- 导入不会覆盖同名技能

## 📖 SKILL.md 格式详解

通过上述接入方式导入技能后，都会以 SKILL.md 格式存储。了解其格式有助于评估和管理接入的技能。

### YAML Front Matter

```yaml
---
name: skill-name                    # 必需：技能名称（全英文、小写、连字符分隔）
description: |                     # 必需：功能描述（建议 1-3 句话）
  一段描述，说明这个技能是做什么的、什么时候该用它。
  建议用第三人称书写。
tags:                              # 可选：标签列表
  - tag1
  - tag2
---
```

### 参数定义（schema.yaml）

如果技能需要用户填写参数，创建 `config/schema.yaml`：

```yaml
query:
  type: string
  required: true
  description: "Search query string"
  description_zh: "搜索关键词"
  default: ""

top_k:
  type: number
  required: false
  description: "Number of results to return"
  description_zh: "返回结果数量"
  default: 3
```

支持的类型：`string`、`number`、`boolean`、`array`、`object`

### 参数默认值（config.yaml）

```yaml
# 初始工作路径
init_path: "/mnt/nexent"

# 最大返回数量
top_k: 5
```

### 特殊标签

#### `<reference>`：按需加载文件

```markdown
<reference path="examples.md" />
```

#### `<use_script>`：声明捆绑脚本

```markdown
<use_script path="scripts/analyze.py" />
```

#### `<code>`：展示代码示例

```markdown
<code>
result = run_skill_script(
    "csv-analyzer",
    "scripts/analyze.py",
    {"--file": "/path/to/data.csv"}
)
</code>
```

### 辅助函数

在技能中可使用以下函数：

- `run_skill_script(skill_name, script_path, params)`：执行技能包中的脚本
- `read_skill_md(skill_name, files)`：读取技能包中的文件

## 🤖 在智能体中使用 Skill

### 分配 Skill 到智能体

1. 进入 **智能体开发** 页面
2. 在「选择智能体的工具」中切换到 **Skills** 页签
3. 点击「选择 Skill」
4. 找到目标技能并选中
5. 如有必填参数，配置参数后保存

### 技能与工具的区别

| 维度 | 工具 | 技能 |
|------|------|------|
| 粒度 | 单个原子操作 | 多个工具 + 配置 + 文档的组合 |
| Token 消耗 | 每次对话都占用上下文 | 仅在激活时才加载 |
| 参数 | 固定参数 schema | 可自定义参数模板 |
| 分发 | 代码级 | ZIP 包分发，即插即用 |

## ❓ 常见问题

### Q: 上传 ZIP 包时报错「缺少 SKILL.md」

确保 ZIP 包根目录下包含 `SKILL.md` 文件，而非将其放在子文件夹中。

### Q: 技能描述不生效

技能描述应写在 YAML Front Matter 的 `description` 字段中，而非正文的 Markdown 部分。

## 🔗 相关资源

- [智能体配置](../../user-guide/agent-development/agent-configuration) — 在智能体中使用 Skill
- [技能系统概览](../../backend/skills/overview) — 深入了解 Skill 机制
