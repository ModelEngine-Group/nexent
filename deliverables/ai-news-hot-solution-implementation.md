# AI 资讯速递 Solution 包实现总结

> 实现日期：2026-07-29
> 基于：WorkBuddy `aihot` 专家包模式（作者：数字生命卡兹克）

## 实现概述

照搬 WorkBuddy 的 `aihot` 专家包模式（"人设 + 外部 API 调用工作流"），在 Nexent 创建了 `ai_news_hot` solution 包。用户一句话即可获取每天精选的 AI 模型/产品/行业/论文动态，自动整理成中文简报，免配置免登录。

## Solution 包文件结构

```
backend/resources/solutions/ai_news_hot/
├── solution.json              # 方案清单
├── agents/
│   └── ai_news_hot.md         # Agent 人设 + 工作规则
├── skills/
│   └── aihot/
│       └── SKILL.md           # API 调用工作流（~300 行）
└── recipe/
    └── variables.json         # 配置变量（模型/语言/格式）
```

## 核心设计：三层架构

| 层 | 文件 | 作用 |
|----|------|------|
| 方案清单 | `solution.json` | 元信息 + `start_agent_id: 3`（避免和 ai_daily_report=1, data_analyst=2 冲突） |
| 人设层 | `agents/ai_news_hot.md` | Agent 角色：AI 资讯速递专家，定义意图识别 → 技能调用 → 输出格式 |
| 技能层 | `skills/aihot/SKILL.md` | aihot.virxact.com 公开 API 的完整调用工作流 |

## Agent 工具配置

```yaml
tools:
  - terminal        # 执行 curl 命令调 API
  - create_file     # 生成 HTML 简报文件
  - read_skill_md   # 读取 SKILL.md 了解 API 路由规则
skill_names:
  - aihot
```

## Recipe 变量

| 变量 | 类型 | 说明 |
|------|------|------|
| `model_name` | model | LLM 模型选择（必填） |
| `output_language` | select | 中文 / English |
| `output_format` | select | HTML 页面 / Markdown 文本 |

## API 路由设计（照搬 WorkBuddy）

| 用户意图 | API 端点 |
|----------|----------|
| 宽问题（"今天 AI 圈有什么"） | `GET /api/public/items?mode=selected&since=<时间窗>` |
| 明确说"日报" | `GET /api/public/daily` |
| 明确说"全部/完整/所有" | `GET /api/public/items?mode=all` |
| 按公司/主题查询 | `GET /api/public/items?q=<关键词>` |
| 按分类查询 | `GET /api/public/items?mode=selected&category=<分类>` |
| 指定日期日报 | `GET /api/public/daily/{YYYY-MM-DD}` |

## 关键设计决策

1. **免配置**：aihot.virxact.com API 完全公开匿名，无需 token，无需 MCP server
2. **User-Agent 要求**：所有 API curl 必须带浏览器 UA，否则被 nginx 403 挡掉
3. **路由优先级**：默认走精选 `mode=selected`，仅当用户明确说"日报"才走 daily，明确说"全部"才走 `mode=all`
4. **时间窗兜底**：items 端点服务端默认 `since=now-7d`（硬上限），需要更早走 daily 翻存档
5. **server-side 关键词搜索**：`q` 参数走 PostgreSQL GIN 索引，不做客户端 grep
6. **输出规范**：优先 HTML 卡片式简报，备选 Markdown；时间转北京时间 + 人话格式；不暴露 API 细节

## 与 WorkBuddy 原版的映射关系

| WorkBuddy 专家包 | Nexent Solution 包 |
|-----------------|-------------------|
| `.codebuddy-plugin/plugin.json` | `solution.json` |
| `agents/aihot.md` | `agents/ai_news_hot.md` |
| `skills/aihot/SKILL.md` | `skills/aihot/SKILL.md` |
| Bash 工具执行 curl | `terminal` 工具执行 curl |
| `create_file` 生成 HTML | `create_file` 生成 HTML |
| Agent 自主读取 skill | `read_skill_md("aihot")` |

## 部署方式

1. 重建 Docker 镜像（seeder 从 `/opt/backend/resources/solutions/` 读取，baked into image）：
   ```bash
   cd docker
   docker compose --env-file ../env/.env -p nexent -f docker-compose.yml build nexent
   ```

2. 强制重建 nexent-config 容器（plain restart 不用新镜像）：
   ```bash
   docker compose --env-file ../env/.env -p nexent -f docker-compose.yml up -d nexent-config --force-recreate
   ```

3. 验证 seeder 是否成功播种：
   ```bash
   docker logs nexent-config 2>&1 | grep ai_news_hot
   ```

## 前端市场卡

在 `frontend/app/[locale]/market-v2/page.tsx` 的 `BUILTIN_SOLUTIONS` 数组中添加了 id=9 的卡片：
- `name: "ai_news_hot"`（与后端 solution.json 一致）
- `display_name: "AI 资讯速递"`
- `skill_count: 1`（有 1 个 skill）
- `tool_keywords` 包含 `"ai_news_hot"`, `"aihot"`, `"资讯"`, `"news"` 等，确保 `resolveSolutions` 能正确匹配到后端播种的 agent
