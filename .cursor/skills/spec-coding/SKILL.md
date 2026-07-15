---
name: spec-coding
description: Use for Nexent feature work, architecture changes, database/API changes, multi-file refactors, or any implementation that should be driven by SPEC documentation. Enforces documentation-first development through the Nexent Development SPECs Wiki: organize by implementation status, then feature scope, then lifecycle documents; update requirements, functional design, technical design, and development plan before coding.
---

# Spec Coding（规格编码）

本技能适用于改变产品行为、架构、数据模型、API、持久化、运行时流程或多个模块的 Nexent 编码工作。目标是受控实现：先文档，后开发，并保持 Wiki 作为真相来源。

## 事实来源

使用飞书 Wiki，名为 `Nexent Development SPECs`。URL: https://dcnvjn24oieg.feishu.cn/wiki/KyU6wFj3siGJ1WkWlu8cTHgwnYb

**顶级组织按实现状态分类：**

```text
00 - Wiki Governance and Reading Guide（Wiki治理和阅读指南）
10 - Proposed Specs（提案中的规格）
20 - In Development Specs（开发中的规格）
30 - Implemented Specs（已实现的规格）
40 - Paused or Superseded Specs（暂停或已替代的规格）
90 - Templates and Standards（模板和标准）
```

在每个状态分类内，按功能范围组织。在每个功能范围内，使用生命周期文档：

```text
<功能范围>
├── 00 - Requirement Analysis（需求分析）
├── 01 - Functional Design（功能设计）
├── 02 - Technical Design（技术设计）
└── 03 - Development Plan（开发计划）
    └── <Phase 1 子页面>
    └── <Phase 2 子页面>
    └── ...
```

如果父页面有子页面，其正文可以包含 `Quick Access`（快速访问）表格，但仅限于直接子页面（深度1）。`Quick Access` 中的每个条目必须是子页面的可点击链接。不要在页面正文中维护全局目录；Wiki UI 已经提供了这个功能。

## Mandatory Workflow（强制工作流）

**所有文档编写必须使用中文。**

### 阶段一：需求澄清（需求不明确时执行）

在开始编写任何 SPEC 文档之前，必须先确认需求是否足够清晰以指导代码实现。

**触发条件**：当用户需求存在以下任一情况时：
- 功能边界不明确
- 输入/输出/异常处理未定义
- 关键设计决策未确定
- 存在多种实现路径未选择

**执行方式**：

加载并使用 `reference/grilling.md`，逐条向用户澄清需求。

示例澄清问题：
- "这个功能的核心输入是什么？数据类型和格式是什么？"
- "输出结果的格式要求是什么？"
- "边界条件和异常场景有哪些？"
- "这个功能和现有模块的集成点在哪里？"
- "性能要求是什么？延迟/吞吐量/TPS 目标？"

### 阶段二：识别与定位

1. **识别功能范围和当前实现状态**
   - 确定功能属于哪个状态分类（Proposal/In Development/Implemented/Paused）
   - 确定功能范围（Feature Scope）

2. **定位或创建功能范围**
   - 在正确状态分类下找到或创建功能范围节点

3. **确保生命周期文档完整**
   - `00 - Requirement Analysis`（需求分析）
   - `01 - Functional Design`（功能设计）
   - `02 - Technical Design`（技术设计）
   - `03 - Development Plan`（开发计划）
        - 包含多个 Phase 子页面

4. **阅读相关生命周期文档后再编辑代码**

### 阶段三：编码与同步

编码过程中：

- 保持实现与 `03 - Development Plan` 中的 Phase/PR 拆分对齐
- 如果代码发现使文档失效，先停止广泛实现，先更新相关生命周期文档
- 保持验收标准、测试、迁移和兼容性要求与文档同步

编码完成后：

- 仅当变更计划、设计或验收标准时，才更新相关生命周期文档的**实现笔记**
- 当生命周期状态变化时，在状态分类之间移动功能范围：
  - `10 - Proposed Specs` → `20 - In Development Specs`：实现开始时
  - `20 - In Development Specs` → `30 - Implemented Specs`：实现和验收后
  - 任何活跃状态 → `40 - Paused or Superseded Specs`：暂停、放弃或替换时

## Lifecycle Page Responsibilities

`00 - Requirement Analysis` (需求分析):

- 问题陈述
- 目标和非目标
- 用户或系统影响
- 约束条件
- 风险评估

`01 - Functional Design` (功能设计):

- 用户可见或系统可见的行为
- 能力边界
- 功能分解
- 错误处理、空状态、兼容性和迁移行为（如适用）

`02 - Technical Design` (技术设计):

- 架构设计
- 接口和契约
- 数据模型和schema变更
- 运行时集成点
- 向后兼容性策略

`03 - Development Plan` (开发计划):

**核心原则：所有文档必须使用中文编写。**

开发计划由以下部分组成：
- **主页面**：概述所有 Phase，定义 Phase 之间的依赖关系
- **Phase 子页面**：每个 Phase 拆分为独立的子文档

### 03 - Development Plan 主页面结构

```markdown
# <功能范围> - 开发计划

## Phase 概览

| Phase | 名称 | 状态 | 依赖 |
|-------|------|------|------|
| Phase 1 | 实现配置加载模块 | [ ] | - |
| Phase 2 | 集成内存服务 | [ ] | Phase 1 |
| Phase 3 | 添加单元测试 | [ ] | Phase 2 |

## Phase 1: 实现配置加载模块

- **子页面**：[03.1 - 实现配置加载模块](./03.1%20-%20实现配置加载模块.md)
- **PR**: [待创建]

## Phase 2: 集成内存服务

- **子页面**：[03.2 - 集成内存服务](./03.2%20-%20集成内存服务.md)
- **PR**: [待创建]

...
```

### Phase 子页面结构

**每个 Phase 必须是一个独立的子文档**，命名为 `03.N - <Phase名称>.md`。

---

## Phase 子页面模板

````markdown
# Phase N: <阶段名称>

## 基本信息

| 属性 | 值 |
|------|-----|
| 所属功能 | <功能范围> |
| 预计工时 | <X 小时> |
| 依赖 Phase | <Phase X> |
| 状态 | [ ] 未开始 / [ ] 进行中 / [ ] 已完成 |

## 代码设计

| 文件 | 类/函数 | 职责 | 伪代码/逻辑说明 |
|------|---------|------|-----------------|
| `src/module_a.py` | `class AgentProcessor` | 处理代理核心逻辑 | 参见 `references/pseudocode-patterns.md` |
| `src/module_a.py` | `AgentProcessor.process()` | 主处理方法 | 完整类伪代码 |
| `src/module_b.py` | `validate_config()` | 配置校验 | 简单的参数校验逻辑 |

## 伪代码

**完整模板与示例见**：`references/pseudocode-patterns.md`

按需引用以下模板之一：
- 完整类伪代码（适用于主协调器类）
- 数据流伪代码（适用于向量检索、数据变换）
- 状态机伪代码（适用于任务生命周期）

## 关键设计决策

- 决策点 A：说明为什么选择这种实现方式
- 决策点 B：替代方案及未采用原因

## 任务清单

### 基础设施与准备
[ ] N.1 初始化任务描述
[ ] N.2 依赖安装或配置

### 核心实现
[ ] N.3 核心功能实现
[ ] N.4 辅助方法实现

### 测试与验证
[ ] N.5 单元测试编写
[ ] N.6 集成测试验证

### 文档与收尾
[ ] N.7 更新相关文档
[ ] N.8 代码审查准备

## 验收标准

[ ] 配置加载模块可正确读取 YAML 配置
[ ] 配置校验在参数缺失时抛出 ValidationError
[ ] 默认超时时间为 30 秒（可通过配置覆盖）
[ ] 单元测试覆盖率达到 90% 以上

## 实现笔记

（编码完成后填写，记录实际实现与设计的差异）
````

---

## Checkbox 格式说明

**⚠️ 重要：必须使用 `[ ]` 格式作为 Checkbox，不带前导的 `-` 或数字**

| 格式 | 含义 |
|------|------|
| `[ ] 任务描述` | 未完成的任务 |
| `[x] 任务描述` | 已完成的任务 |

**禁止使用以下格式：**
- `- [ ] 任务描述`（错误：多了前导 `-`）
- `1. [ ] 任务描述`（错误：多了数字前缀）

## 任务清单编写原则

- 任务必须小到可以在单次开发会话（1-2小时）内完成
- 按依赖顺序排列，确保前置任务在前
- 每个任务可独立验证完成
- 引用 `01 - Functional Design` 说明要构建什么
- 引用 `02 - Technical Design` 说明如何构建

## Phase/PR 拆分指南

- 每个 Phase 对应一个 PR，便于独立审查和回滚
- Phase 粒度：包含完整功能闭环，可测试、可演示
- 建议 Phase 数量：每个功能 2-5 个 Phase
- Phase 命名：使用动词短语，如"实现配置加载模块"、"集成内存服务"
- Phase 命名格式：`03.N - <阶段名称>`，例如 `03.1 - 实现配置加载模块`

## 参考资料（按需加载）

| 文档 | 何时读取 |
|------|----------|
| `references/pseudocode-patterns.md` | 编写 Phase 子页面时查阅伪代码模板 |
| `references/grilling.md` | 需求不明确、需要澄清时使用 |
| `references/lark-wiki-push-python.md` | 将 Markdown 拆分为 XML 时参考 Python 脚本模式（由 `lark-wiki-spec-push` skill 提供） |

## Nexent 特定检查

**所有文档编写必须使用中文。**

对于后端工作，保持 `AGENTS.md` 中描述的 app/service/const 层边界。

对于环境变量，保持 `backend/consts/const.py` 作为唯一真相来源。SDK 代码不得直接读取环境变量。

对于数据库 schema 变更，更新所有必需的位置：

- `docker/sql/*.sql` 下的版本化迁移脚本
- Docker Compose 全新部署的 init SQL
- K8s 全新部署的 init SQL
- 如果项目版本控制规则要求，更新 `APP_VERSION`

对于测试，遵循项目的 pytest 约定，并添加与文档化验收标准匹配的针对性覆盖率。

## 何时可以轻量化文档

当以下条件全部满足时，小型机械修复可以使用简短的现有范围说明代替完整的生命周期文档集：

- 变更单一目的且低风险
- 无 API、数据库、运行时契约或用户可见行为变更
- 无需跨模块协调
- 用户明确要求小型修复

即使如此，也要提及相关的现有 SPEC 或解释为何不需要更新 SPEC。

<!-- NEW -->

## Feishu Wiki Push 实践指南

本文档记录将 Markdown 设计文档推送至飞书 Wiki 的完整工作流，适用于 `Nexent Development SPECs` 空间（space_id = `7660349659210091744`）。

### Wiki Token 速查表

飞书 Wiki 和 Docx 操作涉及三类 token，含义不同：

| Token 类型 | 用途 | 获取方式 |
|---|---|---|
| `node_token` | Wiki 层级导航（`wiki +node-*` 系列命令） | `wiki +node-create` 返回 `node_token` |
| `obj_token`（即 `doc_token`）| 文档内容读写（`docs +fetch` / `docs +update`） | `wiki +node-create` 同时返回 `obj_token`，也是文档 URL 中 `/docx/` 后的字段 |
| `space_id` | Wiki 空间标识 | `wiki +space-list` 返回 |

**常见错误**：将 `node_token` 用于 `docs +update` 的 `--doc` 参数。应始终使用 `obj_token`（即 `doc_token`）。

### 认证状态处理

```bash
lark-cli auth status --json --verify
```

| `user.status` | 含义 | 是否需要干预 |
|---|---|---|
| `ready` | 用户身份可用 | 不需要干预 |
| `needs_refresh` | token 即将过期但仍可写 | 不需要干预，所有写操作仍成功；lark-cli 会在下次 API 调用时自动刷新 |

### Lifecycle Page 推送：Initial vs Republish

首次推送一个新功能范围时，使用 `append`（安全，因为失败后可恢复）。

**Republish（重新推送已存在的 scope）时的策略**：

| 页面状态 | 推荐命令 | 原因 |
|---|---|---|
| 页面为空（新创建） | `append` | 安全 |
| 页面有旧内容，需要完整替换 | `overwrite` | 避免重复内容 |
| 页面有旧内容，只需修一个单元格 | `str_replace` | 精确修补已有块 |

**常见场景**：同一 scope 的 lifecycle 页面 repush 时，00/01/02 通常已存在旧内容，用 `overwrite` 替换；03 主页面用 `overwrite` 或 `append`（取决于是否要保留旧 Phase 概览表）；新增的 Phase 子页面用 `append`。

### `--content @file` 的路径基准

`--content @filename` 的文件路径**必须相对于当前工作目录（cwd）**，不是脚本所在目录，也不是绝对路径。

```bash
# ✅ 正确：cd 到文件所在目录后使用相对路径
cd .spec_tmp/memory && lark-cli docs +update --doc "$DOC" --command append --content @"./phase_1.xml"

# ❌ 错误：绝对路径会被 lark-cli 拒绝
lark-cli docs +update --doc "$DOC" --content @"/mnt/c/Project/nexent/.spec_tmp/memory/phase_1.xml"
```

### Phase 子页面推送完整流程

创建 Phase 子页面需要三步：**创建 Wiki 节点 → 生成内容 XML → 上传内容 → 更新父页面 sub-page-list**。

**步骤 1：创建 Wiki 子节点**

```bash
# 03 页面的 node_token = OToHwx7p0iQhAmkFQTtcrIs7nmh（已知）
lark-cli wiki +node-create \
  --space-id 7660349659210091744 \
  --parent-node-token OToHwx7p0iQhAmkFQTtcrIs7nmh \
  --title "03.1 - 协议与抽象" \
  --as user --format json
```

返回中的 `obj_token`（即 `doc_token`）用于后续 `docs +update`。

**步骤 2：用 Python 生成 XML 内容**

参见 `references/lark-wiki-push-python.md`（由 `lark-wiki-spec-push` skill 提供），或直接复用该 skill 的 `examples.md` 中的 `build_spec_xml.py` 脚本来构建 Phase 内容。

**步骤 3：上传内容**

```bash
cd /path/to/.spec_tmp/<feature>/ && lark-cli docs +update \
  --doc "$OBJ_TOKEN" --command append \
  --as user --format json \
  --content @"./phase_N.xml"
```

**步骤 4：在父页面插入 sub-page-list**

在父 03 页面追加 `<sub-page-list></sub-page-list>` 块（Wiki 特殊块），lark-cli 会自动将所有子节点的 doc_token 填充进去：

```xml
<title>补充子页面导航</title>
<sub-page-list></sub-page-list>
```

```bash
lark-cli docs +update \
  --doc "$PARENT_OBJ_TOKEN" \
  --command append \
  --as user --format json \
  --content @"sub_page_list.xml"
```

验证方式：`wiki +node-list --parent-node-token "$PARENT_NODE_TOKEN"` 确认子节点数量正确。

### str_replace 精确修补典型场景

当需要修改已有页面中的某个单元格或链接时，用 `str_replace`：

```bash
# 场景：Quick Access 表格中 03 Development Plan 的链接是占位符，需要替换为真实 URL
lark-cli docs +update \
  --doc "$SCOPE_OBJ_TOKEN" \
  --command str_replace \
  --as user --format json \
  --pattern '<a href="https://dcnvjn24oieg.feishu.cn/wiki/STALE_NODE_TOKEN">Memory Architecture — 03 Development Plan</a>' \
  --content '<a href="https://dcnvjn24oieg.feishu.cn/wiki/NEW_NODE_TOKEN">Memory Architecture — 03 Development Plan</a>'
```

`str_replace` 在 XML 模式下是行内匹配，`--pattern` 必须完整匹配目标字符串。

### 常见陷阱与处理

| 陷阱 | 症状 | 处理方式 |
|---|---|---|
| 用 `node_token` 而不是 `doc_token` 调用 `docs +update` | `"ok": false, "error": "invalid doc"` | 确认使用 `wiki +node-create` 返回的 `obj_token` |
| `--content @` 使用绝对路径 | `--file must be a relative path within the current directory` | 先 `cd` 到文件所在目录，再使用相对路径 |
| 对已存在页面用 `append` | 页面出现重复内容 | 用 `overwrite` 替换（republish 场景） |
| `needs_refresh` auth 状态 | 担心写操作失败 | 不需要干预，lark-cli 会自动刷新，所有写操作实际成功 |
| for 循环中变量传入 python heredoc | 变量为空 | 放弃 bash 循环，每个 doc 单独写一个命令 |
| 生成的 XML 超过 lark-cli 单次容量 | 上传失败 | 拆分为 ≤ 15 KB 的小块后多次 append |

### Status Section Token（Nexent SPECs 固定值）

| Status | node_token | 用途 |
|---|---|---|
| `10 - Proposed Specs` | `KGAEwAceZizF7AkMjCfcVhH6n9e` | 尚未开始实现 |
| `20 - In Development Specs` | `JhSIwbBd2i0e5DkmoqicqC3Dn5e` | 设计 + 开发中（git 有相关代码） |
| `30 - Implemented Specs` | `Kls1wtADQiI3sYk97ilc81v0nYc` | 已合并验收 |
| `40 - Paused or Superseded Specs` | `BJeHwwiiYiEXT4krOhIc2N87nuc` | 暂停或被替代 |

**判断规则**：git status 有相关代码变更时，推送至 `20 - In Development Specs`；完全无代码时推至 `10 - Proposed Specs`。

### Cleanup 强制规则

每次推送完成后**必须**立即清理临时文件：

```bash
rm -rf .spec_tmp/<feature>/
```

`.spec_tmp/` 如果不在 `.gitignore` 中，残留文件会污染 `git status`。本次推送产生的所有 `.spec_tmp/memory/` 文件必须在任务结束前删除。