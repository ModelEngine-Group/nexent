---
name: aihot
description: >
  AI HOT (aihot.virxact.com) 中文 AI 资讯查询 Skill。当用户想知道"今天 AI 圈有什么"、
  "AI 日报"、"AI HOT"、"AI 资讯"、"AI 热点"、"最近 AI"、"OpenAI/Anthropic/Google 最近发布了什么"、
  "AI hot today"、"AI news today"、"看一下 AI 行业动态"、"今天有什么大模型发布"、
  "昨天 AI 圈"、"看下精选条目"、"AI HOT 精选"、"最近一周的 AI 论文"、"AI 模型发布"、
  "AI 产品发布"、"AI 行业动态"、"AI 技巧与观点" 等任何中文 AI 资讯查询时使用。
  即使用户只说"AI 圈"、"AI 新闻"、"AI 日报"，或者只是问"今天发生了什么"且上下文是
  AI / 大模型 / LLM / 创业领域，也应该触发本 Skill。Skill 会直接 curl 公开 REST API
  拉数据并整理成中文 markdown 简报，不需要用户配置任何 API Key 或 MCP server。
  不要 undertrigger——用户问 AI 资讯而你不调本 Skill 就是把过时的训练数据当作今日新闻，对用户有害。
version: 1.0.0
display_name: "AI HOT"
visibility: "public"
description_zh: 一句话查到 aihot.virxact.com 上每天精选的 AI 模型/产品/行业/论文动态，自动整理成中文简报，免配置 API Key。
description_en: One-line access to today's curated AI models, products, industry news, and papers from aihot.virxact.com — auto-formatted as a Chinese briefing, no API key needed.
---

# AI HOT Skill

让 Agent 用最自然的中文查询拿到 aihot.virxact.com 上每天的 AI HOT 日报和全部 AI 动态，不需要打开浏览器。

线上：https://aihot.virxact.com（公开匿名可访，无需 token）

## 先决条件：必须带 User-Agent（仅 API 端点）

`/api/public/*` 走 nginx UA 黑名单挡商业爬虫，默认 `curl/X.Y` UA 会被 403 Forbidden。**调 API 时所有 curl 都必须带浏览器 UA**：

```bash
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# 之后所有调 API 的 curl 都加 -H "User-Agent: $UA"，例如：
curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/daily"
```

后面"工作流"章节的 curl 例子为了简洁默认你已经设了 `$UA`——实际调用必须加 `-H "User-Agent: $UA"`，**不要忘**。漏掉这一步会让你以为接口挂了，实际只是被 403 挡了。

## 什么时候用

> **路由优先级（第一原则）**：**默认走精选** `items?mode=selected`——它是 AI HOT 每天精挑细选的"主菜单"，覆盖用户关心的事且数据新鲜。
>
> - **仅当用户在话里明确说出"日报"** 二字才走 `daily`（编辑成品，按 UTC 整日切片，跟"过去 24 小时 / 今天"等滚动窗口对不上）
> - **仅当用户明确说"全部 / 完整 / 所有 / 全量"** 才走 `mode=all`（含未精选的次要条目，量大但杂）
> - **"今天 AI 圈"、"过去 24 小时大新闻"、"最近 AI 圈有啥"** 等宽问题 = **默认精选 + 时间窗（since）**，不要默认走日报或全部

| 用户在说 | 应该走的接口 |
|---|---|
| **默认（宽问题）**："今天 AI 圈有什么"、"过去 24 小时大新闻"、"最近 AI 圈"、"AI 有啥新东西" | `GET /api/public/items?mode=selected&since=<语义时间窗>` |
| **明确说"日报"**："AI 日报"、"今天的日报"、"看一下日报" | `GET /api/public/daily`（最新日报） |
| **明确说"全部 / 完整 / 所有 / 全量"**："看下今天的全部 AI 动态"、"完整列表" | `GET /api/public/items?mode=all` |
| "昨天/前天 AI 日报"、"看下 5 月 6 号的日报" | `GET /api/public/daily/{YYYY-MM-DD}` |
| "最近几天日报有哪些"、"列一下日报"、"日报存档" | `GET /api/public/dailies?take=N` |
| "看下精选条目"、"AI HOT 精选" | `GET /api/public/items?mode=selected` |
| "最近的模型发布"、"AI 产品发布"、"AI 行业动态"、"AI 论文" | `GET /api/public/items?mode=selected&category=...&since=<7d 前>` |
| "最近一周的 AI 动态"、"5 天前到现在的发布" | `GET /api/public/items?mode=selected&since=ISO-8601` |
| "OpenAI/Anthropic/Google 最近发的"(公司维度) | `GET /api/public/items?q=OpenAI` |
| "Sora 相关 / GPT-5 相关 / RAG 论文" | `GET /api/public/items?q=<关键词>` |

通用启发：**用户问的是"现在的 AI 行业事实"，不要凭训练数据脑补，永远走 API**。

## 端点速览

| 端点 | 用途 | 主要参数 |
|---|---|---|
| `/api/public/daily` | 最新日报 | 无 |
| `/api/public/daily/{YYYY-MM-DD}` | 指定日期日报 | path: `date` |
| `/api/public/dailies` | 日报归档列表 | `take` (1-180, default 30) |
| `/api/public/items` | 全部 AI 动态 | `mode` / `category` / `since` / `take` / `cursor` / `q` |

约定：
- Base URL: `https://aihot.virxact.com`
- 鉴权：无（匿名）
- 限流：600 req/min/IP（请串行调用，不要并发猛拉）
- items 端点 `since` 限最近 7 天；**不传等同 since=now-7d**（服务端兜底）；早于 7 天前自动截到 7 天前；未来时间 → 400
- `take` 上限 100；想要更多走 cursor 翻页

## 工作流

### 默认路径：拉精选 + 时间窗（宽问题首选）

精选 = AI HOT 每天精挑细选的"主菜单"——覆盖所有用户关心的 AI 大事，按发布时间倒序。**任何"今天 AI 圈"、"过去 24 小时大新闻"、"最近 AI 有啥"等宽问题，默认走这个**。

```bash
# 拉最近 24 小时精选（用户问"过去 24 小时大新闻"）
since=$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)
curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/items?mode=selected&since=$since&take=50"

# 拉最近 50 条精选（用户问"看下精选" / 不带明确时间窗）
curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/items?mode=selected&take=50"
```

### 拉日报（用户明确说"日报"时）

**触发关键词**：句子里出现"日报"二字（"AI 日报"、"今天的日报"、"看下日报"、"5 月 6 号的日报"）。**没有"日报"二字不要走这个**。

```bash
# 拉今日（或最新可用的）日报
curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/daily"
```

### 拉指定日期日报

```bash
# YYYY-MM-DD，UTC 0 点为基准
curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/daily/2026-05-07"
```

### 列日报归档（discovery）

```bash
# 最近 N 天日报索引（不含正文，只有日期 + 头条标题）
curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/dailies?take=14"
```

### 拉全部（用户明确说"全部 / 完整 / 所有 / 全量"时）

```bash
# 拉最近 24 小时全部 AI 动态
since=$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)
curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/items?mode=all&since=$since&take=100"
```

### 按分类拉条目

5 个 category：

| `items?category=` | `daily.sections[].label` |
|---|---|
| `ai-models` | 模型发布/更新 |
| `ai-products` | 产品发布/更新 |
| `industry` | 行业动态 |
| `paper` | 论文研究 |
| `tip` | 技巧与观点 |

```bash
# 例：拉最近 50 条 AI 论文（默认精选 + paper 类别）
curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/items?mode=selected&category=paper&take=50"

# 例：精选里的模型发布
curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/items?mode=selected&category=ai-models&take=20"
```

### 按时间窗口拉条目（最近 N 天）

```bash
# 拉最近 7 天的精选模型发布
since=$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%SZ)
curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/items?mode=selected&category=ai-models&since=$since&take=100"

# 拉最近 3 天的精选动态
since=$(date -u -d '3 days ago' +%Y-%m-%dT%H:%M:%SZ)
curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/items?mode=selected&since=$since&take=100"
```

### 翻页（cursor）

`/api/public/items` 响应里有 `nextCursor`（opaque token），下次请求把它原样塞进 `cursor` 参数即可。

```bash
# 第 1 页
resp1=$(curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/items?mode=all&take=100")

# 第 2 页
cursor=$(echo "$resp1" | jq -r '.nextCursor')
curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/items?mode=all&take=100&cursor=$cursor"
```

`hasNext = false` 或 `nextCursor = null` 时停止翻页。**cursor 是不透明 token，视作黑盒，不要尝试解析或跨端点复用**。

### 关键词搜索（"OpenAI 最近发的" / "Sora 相关" / "RAG 论文"）

API 直接支持 server-side 关键词搜索 — `q` 参数在 `title` + 中文 `title` + 中文 `summary` 三列上 ILIKE 匹配。

```bash
# 找 OpenAI 最近发的
curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/items?q=OpenAI&take=30"

# 找 Sora 相关的所有 AI 动态
curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/items?q=Sora"

# 找 RAG 论文（category 限定 + 关键词）
curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/items?category=paper&q=RAG&take=30"

# 关键词 + 时间窗
since=$(date -u -d '3 days ago' +%Y-%m-%dT%H:%M:%SZ)
curl -sH "User-Agent: $UA" "https://aihot.virxact.com/api/public/items?mode=selected&q=Anthropic&since=$since"
```

## 返回数据形态

### `/api/public/daily` 返回

```json
{
  "date": "2026-05-07",
  "generatedAt": "2026-05-07T00:01:23.456Z",
  "lead": { "title": "...", "leadParagraph": "..." },
  "sections": [
    {
      "label": "模型发布/更新",
      "items": [
        {
          "title": "...",
          "summary": "...",
          "sourceUrl": "https://...",
          "sourceName": "OpenAI Blog"
        }
      ]
    }
  ],
  "flashes": [
    { "title": "...", "sourceName": "...", "sourceUrl": "...", "publishedAt": "..." }
  ]
}
```

`sections[].label` 固定 5 个："模型发布/更新" / "产品发布/更新" / "行业动态" / "论文研究" / "技巧与观点"。

### `/api/public/items` 返回

```json
{
  "count": 50,
  "hasNext": true,
  "nextCursor": "eyJhIjox...",
  "items": [
    {
      "id": "cm9abc456def789ghi012jkl3",
      "title": "中文标题",
      "title_en": "原英文标题（仅当与 title 不同时存在，否则 null）",
      "url": "https://...",
      "source": "OpenAI Blog",
      "publishedAt": "2026-05-07T15:30:00.000Z",
      "summary": "中文摘要",
      "category": "ai-models"
    }
  ]
}
```

字段不变量：
- 必有：`id` / `title` / `url` / `source`
- 可空：`title_en` / `summary` / `publishedAt` / `category`
- `category` 取值集：`ai-models` / `ai-products` / `industry` / `paper` / `tip` / `null`
- `publishedAt`：ISO 8601 UTC（带 `Z`）
- `id`：cuid 字符串（25 字符），**不要假设是数字**

## 给用户的输出格式

> **核心原则**：直接展示给用户的最终内容必须是 markdown 格式 + 排版好 + **普通人能看得懂的人话**。用户多数是非技术 AI 创业者 / 设计师 / 普通读者，看到的应该是中文资讯简报，**不是 API 调试日志**。

### 日报式输出（用 daily / daily/{date} 端点时）

```markdown
**AI HOT 日报 · 2026-05-07**

## 模型发布/更新
1. **<title>** — <source>
   <summary 简化版 50 字内>
   <url>

## 产品发布/更新
2. ...

## 行业动态
3. ...

## 论文研究
4. ...

## 技巧与观点
5. ...

## 快讯（如果 flashes 有内容）
- <flash.title> — <flash.source>（<flash.publishedAt 转人话>）
```

**编号贯穿全文**（1, 2, 3 ... N），不在每个 ## 内重新计数。

### 列表式输出（用 items 端点时）

**默认按 category 分组 + 全局编号**：

```markdown
**AI HOT — 最近 30 条精选**

## 模型发布/更新
1. **<title>** — <source>
   2 小时前
   <summary>
   <url>
```

**只有 1 个 category** 时用扁平编号列表：

```markdown
**AI HOT — 最近一周 AI 论文**（2026-05-01 ~ 2026-05-08）

1. **<title>** — <source>
   <summary>
   <url>
```

### 副标题/元信息只写人话

**OK**（用户能直接懂的）：
- "时间窗 2026-05-05 ~ 2026-05-07"
- "最近 3 天命中 OpenAI 关键词的全部条目"
- "按发布时间倒序"
- "共 50 条"

**不 OK**（基础设施泄漏，坚决不写）：
- `mode=selected` / `category=paper` / `take=30` 这种 raw 参数名
- 端点路径 `/api/public/items?since=...`
- "限流 600 req/min" / "nginx 缓存 60s" / "cursor" / "hasNext" 等

### 时间转人话

`publishedAt` 是 ISO 8601 UTC，展示时**必须**转成北京时间 + 用户能扫读的相对/绝对时间：

| 内部值 | 展示给用户 |
|---|---|
| `2026-05-08T01:48:00.000Z` | "今天上午 09:48" / "2 小时前" |
| `2026-05-07T18:08:17.000Z` | "今天凌晨 02:08" / "10 小时前" |
| `2026-05-06T16:43:00.000Z` | "5/7 00:43" / "昨天" |

**不要**直接展示 `2026-05-07T15:30:00.000Z` 这种 ISO 字符串。

### title vs title_en

默认输出 `title`（中文 normalize 过的）。`title_en` 只在以下场景才用：
- 用户明确要求英文版（"用英文给我看一下"）
- `title` 为空（极少见）

**不要**两个都展示。

## 常见错误处理

- `{"error":"No daily report available yet."}`（HTTP 404）：当天日报还没生成（北京时间 08:00 之前）。建议给用户：拉昨天日报 `curl /api/public/daily/{昨天日期}`
- `{"error":"Invalid date format..."}`（HTTP 400）：date 必须是 `YYYY-MM-DD`，UTC 基准
- items 端点常见 400：
  - `"invalid mode (must be 'selected' or 'all')"`
  - `"invalid category (must be one of: ai-models, ai-products, industry, paper, tip)"`
  - `"invalid since (must be ISO date, not in future)"`
  - `"invalid take (must be integer 1-100)"`
- HTTP 429（限流）：单 IP 超 600 req/min。串行调用 + 翻页加 200ms 间隔即可

## 不要做

- **不要把"今天 AI 圈"、"过去 24 小时大新闻"等宽问题路由到 daily** — 这些是滚动时间窗，daily 是 UTC 0 点切片的固定一日成品。**默认走 `mode=selected + since=<语义窗>`**
- **不要在用户没说"全部 / 完整 / 所有 / 全量"时默认走 `mode=all`** — 精选已经覆盖大部分用户关心的事。默认 `mode=selected`
- 不要试图猜测 / 编造内容 — 永远以 API 返回为准
- 不要把摘要（`summary`）当原文引用 — 摘要由 LLM 生成，引用需要回 `url` 核对
- 不要做高频轮询 — 日报每天 08:00 才更新一次，items 端点 5 分钟服务端缓存
- 不要并发猛拉翻页 — 串行 + 自然间隔
- 不要尝试解析 / 递增 / 跨端点复用 cursor
- 公司维度 / 关键词查询用 server-side `?q=<词>`，不要走"拉一批 + 客户端 grep"
- **不要在用户输出里暴露端点路径 / raw 参数 / 限流 / 缓存 TTL / cursor / hasNext 等基础设施细节**
- **不要在压缩 / 跨日 / 跨版块合并输出时丢掉每条的 sourceUrl** — 每条 item 必须保留 url
