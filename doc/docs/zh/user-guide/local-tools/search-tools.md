---
title: 搜索工具
---

# 搜索工具

搜索工具组提供多源信息检索，覆盖互联网搜索、本地知识库、AIDP 知识库、DataMate 知识库以及 Dify 知识库。适合实时信息查询、行业资料检索、私有文档查找以及企业级多模态知识库检索等场景。

## 🧭 工具清单

- 本地/私有知识库：
  - `knowledge_base_search`：本地知识库检索，支持多知识库与多种检索模式
  - `aidp_search`：对接 AIDP 企业级知识库，支持文本/表格/图片多模态 FusionSearch 检索
  - `datamate_search`：对接 DataMate 知识库的检索
  - `dify_search`：对接 Dify 知识库的检索
- 公网搜索：
  - `exa_search`：基于 EXA 的实时网页与图片搜索
  - `tavily_search`：基于 Tavily 的网页与图片搜索
  - `linkup_search`：基于 Linkup 的图文混合搜索

## 🧰 使用场景示例

- 查询内部文档、技术规范、行业资料（知识库、DataMate、Dify）
- 检索企业 AIDP 知识库中的多模态资料，包括文档、表格、图片、技术图纸等（AIDP）
- 获取最新新闻、数据或网页截图线索（Exa / Tavily / Linkup）
- 同时返回图片参考以丰富答案（开启图片过滤后可输出图片列表）

## 🧾 参数要求与行为

### knowledge_base_search
- **配置参数**：`top_k`（返回结果数量，默认 3）
- **检索参数**：
  - `query`：检索问题，必填。
  - `search_mode`：`hybrid`（默认，混合召回）、`accurate`（文本模糊匹配）、`semantic`（向量语义）。
  - `index_names`：指定要搜索的知识库名称列表（可用用户侧名称或内部索引名），可选。
  - `enable_rerank`：是否启用重排序，默认 False。开启后会对检索结果进行二次排序，提升结果相关性。
  - `rerank_model`：重排序使用的模型，默认为系统配置的 rerank 模型。`enable_rerank` 为 True 时生效。
- 返回匹配片段的标题、路径/URL、来源类型、得分等。
- 若未选择知识库，会提示"无可用知识库"。

### datamate_search
- **配置参数**：
  - `server_url`：DataMate 服务地址（如 `http://192.168.1.100:8080` 或 `https://datamate.example.com:8443`）
  - `verify_ssl`：是否验证 SSL 证书（HTTPS 默认 False，HTTP 默认 True）
- **检索参数**：
  - `query`：检索问题，必填。
  - `top_k`：返回数量，默认 3。
  - `threshold`：相似度阈值，默认 0.2。
  - `index_names`：指定要搜索的知识库名称列表，可选。
  - `kb_page` / `kb_page_size`：分页获取 DataMate 知识库列表。
  - `enable_rerank`：是否启用重排序，默认 False。开启后会对检索结果进行二次排序，提升结果相关性。
  - `rerank_model`：重排序使用的模型，默认为系统配置的 rerank 模型。`enable_rerank` 为 True 时生效。
- 返回包含文件名、下载链接、得分等结构化结果。

### dify_search
- **配置参数**：
  - `dify_api_base`：Dify API 基础地址
    - 若您本地部署了Dify，则直接使用`http://host.docker.internal/v1`
    - 若您在服务器部署了Dify，则使用`http://x.x.x.x:x/v1`并替换上合适的IP及端口
    - 若您使用Dify官网云服务，则直接使用`https://api.dify.ai/v1`
  - `api_key`：Dify 知识库 API 密钥，以`dataset-`开头（在 Dify 中查看知识库页面，点击左上角"API"页签，再点击右上角"API 密钥"按钮创建）
  - `dataset_ids`：知识库 ID 列表（如 `["e912e1f5-29c0-40da-8baf-d35da77c60df"]`，可在 Dify 知识库页面 URL 中查看知识库ID）
  - `top_k`：返回结果数量，默认 3
- **检索参数**：
  - `query`：检索问题，必填。
  - `search_method`：搜索方法，选项：`keyword_search`、`semantic_search`、`full_text_search`、`hybrid_search`，默认 `semantic_search`。
  - `enable_rerank`：是否启用重排序，默认 False。开启后会对检索结果进行二次排序，提升结果相关性。
  - `rerank_model`：重排序使用的模型，默认为系统配置的 rerank 模型。`enable_rerank` 为 True 时生效。
- 返回匹配片段的标题、内容、得分等。

### aidp_search
- **配置参数**：
  - `server_url`：AIDP API 服务地址，例如 `https://141.111.61.70:30080`。
  - `api_key`：AIDP API 密钥，通常以 `ak_` 开头，由 AIDP 平台管理员签发。
  - `tenant_id`：AIDP API 路径中的租户标识，例如 `aidp`。
  - `kds_list`：要对接的知识库 ID（`kds_id`）列表，以 JSON 字符串数组形式保存（如 `["aidp-kb-01", "aidp-kb-02"]`），决定该工具默认检索哪些 AIDP 知识库。
  - `search_method`：搜索方法，选项：`hybrid_search`（默认，融合检索）、`vector_search`（向量检索）、`full_text_search`（全文检索）。
  - `reranking_enable`：是否启用重排序，默认 True。
  - `reranking_mode`：重排序模式，选项：`performance`（默认）/ `high_accuracy`。
  - `rewrite_enable`：是否启用黑话/查询改写，默认 False。
  - `related_search_enable`：是否启用关联 Chunk 检索，默认 False。
  - `score_threshold`：相似度阈值（0–1），默认 0.0。
  - `top_k`：返回结果数量（1–100），默认 10。
  - `multi_modal`：是否返回多模态 Chunk（图片/表格），默认 True。
- **检索参数**：
  - `query`：检索问题，必填。
  - `kds_list`：可选。指定要检索的知识库 ID 列表，不传则使用工具配置中的默认 `kds_list`。
- 返回文本、表格、图片等多模态检索块，结果以双通道输出：所有块通过 `SEARCH_CONTENT` 发送，图片另通过 `PICTURE_WEB` 发送。
- 检索范围会按当前对话用户的 AIDP 权限白名单过滤：无论使用配置默认值还是 LLM 传入的值，都会与用户有权限访问的 KB 取交集，未授权的 KB 会被静默剔除。
- 若过滤后无可访问的知识库，工具会返回明确的无权限提示，而非静默返回空结果。

### exa_search / tavily_search / linkup_search
- **配置参数**：
  - `exa/tavily/linkup_api_key`：对应服务的 API 密钥
  - `max_results`：返回结果数量，默认 3
  - `image_filter`：是否启用图片过滤，默认 True
- **检索参数**：
  - `query`：检索问题，必填。
- 图片过滤：默认开启，按查询语义过滤常见无关图片；可关闭以获取全部图片 URL。
- API Key 获取：
  - Exa：前往 [exa.ai](https://exa.ai/) 注册并在控制台申请 EXA API Key
  - Tavily：访问 [tavily.com](https://www.tavily.com/) 创建账户，在 Dashboard 获取 Tavily API Key
  - Linkup：在 [linkup.so](https://www.linkup.so/) 注册并于个人中心创建 Linkup API Key
- 返回标题、URL、摘要，可能附带图片 URL 列表（去重处理）。

## 🛠️ 操作指引

1. **选择数据源**：私有资料用 `knowledge_base_search`、`aidp_search`、`datamate_search` 或 `dify_search`；实时公开信息用 Exa/Tavily/Linkup。
2. **设置检索模式/数量**：知识库可在 `search_mode`/`search_method` 之间切换；公网搜索可调整 `max_results` 与是否启用图片过滤。
3. **填写连接与鉴权参数**：AIDP 需要准确填写 `server_url`、`api_key` 与 `tenant_id`，建议先在平台安全配置中完成测试连接。
4. **配置可检索知识库范围**：AIDP 在工具配置中通过 `kds_list` 勾选该工具默认检索的知识库；实际调用时还会按当前对话用户的 AIDP 权限白名单再过滤一次。
5. **限定范围**：需要特定知识库时填写 `index_names`（本地知识库）或显式传入 `kds_list`（AIDP），避免无关结果；DataMate 可通过阈值与 top_k 控制结果精度与数量。
6. **启用重排序（可选）**：如需提升检索结果相关性，可设置 `enable_rerank: true` 或 `reranking_enable: true`，并通过对应的 model/mode 参数调整效果。
7. **结果利用**：返回为 JSON，可直接用于回答、摘要或后续引用；包含 cite 索引便于引用管理。

## 🛡️ 安全与最佳实践

- 公网搜索与 AIDP 等外部服务的凭证（`api_key` 等）需确保已在平台安全配置中设置，不要在对话中暴露。
- AIDP 知识库检索受当前对话用户的权限控制。如用户看不到某个 KB，即使该 KB 在工具的 `kds_list` 配置中，也不会被检索到，请联系 AIDP 管理员授予相应权限。
- 知识库检索前确认已同步最新文档，避免旧版本内容。
- 当查询过于宽泛导致无结果时，可缩短或拆分问题；图片过滤未命中时可尝试关闭过滤获取原始图片列表。
