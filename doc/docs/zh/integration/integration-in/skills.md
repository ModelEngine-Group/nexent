# Skill 技能集成

Skill（技能）是 Nexent 平台为智能体扩展能力的核心机制。Nexent 支持接入外部开发的技能包，也可以利用平台的自然语言生成功能快速创建新技能。

## 接入方式概览

Nexent 支持多种 Skill 接入方式：

| 接入方式 | 适用场景 | 文件要求 |
|----------|----------|----------|
|----------|----------|----------|
| **上传 SKILL.md** | 单文件技能，简单场景 | `.md` 文件，包含 YAML Front Matter |
| **上传 ZIP 包** | 多文件技能，包含脚本和资源 | ZIP 包内含 `SKILL.md` |
| **NL2Skill 生成** | 从自然语言描述自动创建 | 无，需描述需求 |
| **从仓库复制** | 使用平台已上架的技能 | 无，直接选择 |

## 方式一：上传 Skill 文件

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

## 方式二：NL2Skill 自然语言生成

NL2Skill 是 Nexent 提供的智能创建功能，只需用自然语言描述需求，系统即可自动生成完整的技能包。

### 功能特点

- **零门槛**：无需了解技能包格式，用日常语言描述即可
- **一键生成**：自动生成 SKILL.md、参数配置、甚至配套脚本
- **实时预览**：生成过程实时可见，可随时调整
- **智能优化**：支持多轮对话，持续完善技能内容

### 使用场景

| 场景 | 描述示例 |
|------|----------|
| **数据采集** | 「创建一个技能，可以根据关键词在 GitHub 上搜索仓库并提取 Star 数」 |
| **文件处理** | 「上传一个 CSV 文件，自动统计各列数据并生成图表」 |
| **API 封装** | 「创建一个调用天气 API 并返回未来三天预报的技能」 |
| **多工具组合** | 「输入商品链接，自动比价并返回最低价链接」 |
| **数据清洗** | 「读取一段文本，提取邮箱、手机号、日期并格式化输出」 |

### 操作步骤

1. 进入 **Skill 仓库** → **我的 Skill** 页面
2. 点击「创建 Skill」
3. 选择「交互式创建」
4. 在左侧对话区描述技能需求

**描述技巧**：
- 明确输入输出：「输入 GitHub 仓库地址，返回 Star 数、Fork 数」
- 说明使用场景：「用于快速查询开源项目流行度，帮助技术选型」
- 描述边界条件：「如果仓库不存在，返回友好提示」

5. 查看实时生成预览
6. 根据需要调整或补充需求
7. 预览满意后点击「创建」

### 生成模式

| 模式 | 说明 | Token 消耗 |
|------|------|------------|
| **简单模式** | 生成基础技能结构 | 较少 |
| **复杂模式** | 生成完整技能包，包含脚本和详细示例 | 较多 |

### 质量建议

1. **描述清晰**：需求越明确，生成质量越好
2. **分步创建**：复杂技能可以先做简单版本，再手动扩展
3. **选择强模型**：更聪明的模型能生成更准确的技能
4. **验证测试**：生成后使用工具测试验证效果

## 方式三：从仓库复制

如果平台仓库中已有可用的技能，可以直接复制使用。

### 操作步骤

1. 进入 **Skill 仓库** → **仓库** 页面
2. 浏览或搜索目标技能
3. 点击技能卡片上的「详情」查看内容
4. 点击「复制」将技能添加到「我的 Skill」
5. 在「我的 Skill」中编辑和使用

### 注意事项

- 复制后的技能是独立副本，与原技能无关联
- 如需修改，编辑后不影响原技能
- 同租户内共享的技能必须先复制才能编辑

## SKILL.md 格式详解

无论采用哪种接入方式，最终都会导入 SKILL.md 格式的技能定义。了解其格式有助于创建更高质量的技能。

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

## 在智能体中使用 Skill

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

## 即将推出：第三方 Skill 仓库

Nexent 即将推出**第三方 Skill 仓库**功能，届时您将能够：

- **浏览社区 Skill 市场**：发现更多优质技能
- **一键安装社区技能**：快速获取并使用
- **发布自己的技能**：与社区共享您的作品
- **技能版本管理**：追踪技能更新历史

敬请期待！

## 安全与权限

### 知识库访问控制

导入包含知识库工具的技能时，实际检索范围受当前用户权限限制。

### 公网搜索

Tavily / Linkup / Exa 等公网搜索需先在平台安全配置中填写对应 API Key。

### 路径安全

技能包内文件操作仅限技能目录范围内，无法访问系统任意路径。

## 常见问题

### Q: 上传 ZIP 包时报错「缺少 SKILL.md」

确保 ZIP 包根目录下包含 `SKILL.md` 文件，而非将其放在子文件夹中。

### Q: 技能描述不生效

技能描述应写在 YAML Front Matter 的 `description` 字段中，而非正文的 Markdown 部分。

### Q: NL2Skill 生成结果不理想怎么办？

1. 简化需求描述
2. 切换到更强大的模型
3. 分步骤创建，先做简单版本再扩展
4. 在预览中手动调整

## 相关资源

- [Skill 仓库](../user-guide/resource-repository/skill-repository) — 平台 Skill 管理
- [智能体配置](../user-guide/agent-development/agent-configuration) — 在智能体中使用 Skill
- [技能系统概览](../../backend/skills/overview) — 深入了解 Skill 机制
- [NL2Skill 详解](../user-guide/resource-repository/skill-repository#nl-to-skill) — 自然语言生成技能
