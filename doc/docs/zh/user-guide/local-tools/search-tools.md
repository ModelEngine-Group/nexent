---
title: 搜索工具
---

# 搜索工具

搜索工具组提供多源信息检索，覆盖互联网搜索、本地知识库以及 DataMate 知识库。适合实时信息查询、行业资料检索、私有文档查找等场景。

## 🧭 工具清单

- 本地/私有知识库：
  - `knowledge_base_search`：本地知识库检索，支持多知识库与多种检索模式
  - `datamate_search_tool`：对接 DataMate 知识库的检索
- 公网搜索：
  - `exa_search`：基于 EXA 的实时网页与图片搜索
  - `tavily_search`：基于 Tavily 的网页与图片搜索
  - `linkup_search`：基于 Linkup 的图文混合搜索

## 🧰 使用场景示例

- 查询内部文档、技术规范、行业资料（知识库、DataMate）
- 获取最新新闻、数据或网页截图线索（Exa / Tavily / Linkup）
- 同时返回图片参考以丰富答案（开启图片过滤后可输出图片列表）

## 🧾 参数要求与行为

### knowledge_base_search
- `query`：检索问题，必填。
- `search_mode`：`hybrid`（默认，混合召回）、`accurate`（文本模糊匹配）、`semantic`（向量语义）。
- `index_names`：指定要搜索的知识库名称列表（可用用户侧名称或内部索引名），可选。
- 返回匹配片段的标题、路径/URL、来源类型、得分等。
- 若未选择知识库，会提示“无可用知识库”。

### datamate_search_tool
- `query`：检索问题，必填。
- `top_k`：返回数量，默认 10。
- `threshold`：相似度阈值，默认 0.2。
- `kb_page` / `kb_page_size`：分页获取 DataMate 知识库列表。
- 需要配置 DataMate 服务地址与端口。
- 返回包含文件名、下载链接、得分等结构化结果。

### exa_search / tavily_search / linkup_search
- `query`：检索问题，必填。
- `max_results`：返回条数，可配置。
- 图片过滤：默认开启，按查询语义过滤常见无关图片；可关闭以获取全部图片 URL。
- 需要对应服务的 API Key：
  - Exa：EXA API Key
  - Tavily：Tavily API Key
  - Linkup：Linkup API Key
- 返回标题、URL、摘要，可能附带图片 URL 列表（去重处理）。

## 🛠️ 操作指引

1. **选择数据源**：私有资料用 `knowledge_base_search` 或 `datamate_search_tool`；实时公开信息用 Exa/Tavily/Linkup。
2. **设置检索模式/数量**：知识库可在 `search_mode` 之间切换；公网搜索可调整 `max_results` 与是否启用图片过滤。
3. **限定范围**：需要特定知识库时填写 `index_names`，避免无关结果；DataMate 可通过阈值与 top_k 控制结果精度与数量。
4. **结果利用**：返回为 JSON，可直接用于回答、摘要或后续引用；包含 cite 索引便于引用管理。

## 🛡️ 安全与最佳实践

- 公网搜索需确保 API Key 已在平台安全配置中设置，不要在对话中暴露。
- 知识库检索前确认已同步最新文档，避免旧版本内容。
- 当查询过于宽泛导致无结果时，可缩短或拆分问题；图片过滤未命中时可尝试关闭过滤获取原始图片列表。

## 🔑 API Key 获取（公网搜索）

- Exa：前往 [exa.ai](https://exa.ai/) 注册并在控制台申请 EXA API Key。
- Tavily：访问 [tavily.com](https://www.tavily.com/) 创建账户，在 Dashboard 获取 Tavily API Key。
- Linkup：在 [linkup.so](https://www.linkup.so/) 注册并于个人中心创建 Linkup API Key。

