---
title: 搜索工具
---

# 搜索工具

搜索工具组提供多源信息检索，覆盖互联网搜索、本地知识库、AIDP 知识库、DataMate 知识库、Dify、RAGFlow、昊天与 iData 知识库。适合实时信息查询、行业资料检索、私有文档查找以及企业级多模态知识库检索等场景。

## 🧭 工具清单

- 本地/私有知识库：
  - `knowledge_base_search`：本地知识库检索，支持多知识库与多种检索模式（系统托管，运行期自动注入）
  - `aidp_search`：对接 AIDP 企业级知识库，支持向量、全文、图谱多通道 FusionSearch 检索（系统托管，运行期自动注入）
  - `datamate_search`：对接 DataMate 知识库的检索
  - `dify_search`：对接 Dify 知识库的检索
  - `ragflow_search`：对接 RAGFlow 知识库的检索
  - `idata_search`：对接 iData 知识库的检索
  - `haotian_search`：对接昊天外部知识库的检索
  - `ind_aidp_search`：对接独立部署 AIDP 知识库的检索
- 公网搜索：
  - `exa_search`：基于 Exa 的实时网页与图片搜索
  - `tavily_search`：基于 Tavily 的网页与图片搜索
  - `linkup_search`：基于 Linkup 的图文混合搜索
  - `deepseek_search`：基于 DeepSeek 的公网检索，支持站点限定与日期过滤

> 💡 `knowledge_base_search` 与 `aidp_search` 是**系统托管工具**：它们不出现在智能体的工具面板中，无法手动添加或配置；运行期由系统按部署开关与用户权限自动注入，检索范围始终与当前用户的权限白名单取交集。详见 [AIDP 知识库对接](../aidp)。

## 🧰 使用场景示例

- 查询内部文档、技术规范、行业资料（本地知识库、DataMate、Dify、RAGFlow、昊天、iData）
- 检索企业 AIDP 知识库中的多模态资料，包括文档、表格、图片、技术图纸等（AIDP）
- 获取最新新闻、数据或网页截图线索（Exa / Tavily / Linkup / DeepSeek）
- 同时返回图片参考以丰富答案（开启图片过滤后可输出图片列表）

## 🧾 参数要求与行为

各工具的参数分两类：**检索参数**由 LLM 在运行时提供；**配置参数**在工具配置弹窗中填写（保存后对该智能体的所有调用生效）。

### knowledge_base_search（系统托管）

- **检索参数**：
  - `query`：检索问题，必填
  - `index_names`：指定要搜索的知识库名称列表，可选
- **配置参数**：
  - `top_k`：返回结果数量，默认 3（1–100）
  - `search_mode`：`hybrid`（默认，混合召回）、`accurate`（文本模糊匹配）、`semantic`（向量语义）
  - `rerank`：是否启用重排序，默认关闭
  - `rerank_model_name`：重排序使用的模型名称，默认为空（使用系统配置的 rerank 模型）
- 返回匹配片段的标题、路径/URL、来源类型、得分等
- 该工具不可在工具面板中手动选配；连接与知识库范围由系统在运行期注入

### datamate_search
- **检索参数**：
  - `query`：检索问题，必填
- **配置参数**：
  - `server_url`：DataMate 服务地址（如 `http://192.168.1.100:8080` 或 `https://datamate.example.com:8443`）
  - `verify_ssl`：是否验证 SSL 证书（HTTPS 默认 False，HTTP 默认 True）
  - `top_k`：返回数量，默认 3
  - `threshold`：相似度阈值，默认 0.2
  - `index_names`：指定要搜索的知识库名称列表，可选
  - `kb_page` / `kb_page_size`：分页获取 DataMate 知识库列表
  - `rerank`：是否启用重排序，默认关闭
  - `rerank_model_name`：重排序使用的模型名称
- 返回包含文件名、下载链接、得分等结构化结果

### dify_search
- **检索参数**：
  - `query`：检索问题，必填
- **配置参数**：
  - `server_url`：Dify API 基础地址
    - 若您本地部署了 Dify，则直接使用 `http://host.docker.internal/v1`
    - 若您在服务器部署了 Dify，则使用 `http://x.x.x.x:x/v1` 并替换上合适的 IP 及端口
    - 若您使用 Dify 官网云服务，则直接使用 `https://api.dify.ai/v1`
  - `api_key`：Dify 知识库 API 密钥，以 `dataset-` 开头（在 Dify 中查看知识库页面，点击左上角"API"页签，再点击右上角"API 密钥"按钮创建）
  - `dataset_ids`：知识库 ID 列表（如 `["e912e1f5-29c0-40da-8baf-d35da77c60df"]`，可在 Dify 知识库页面 URL 中查看知识库 ID）
  - `top_k`：每个知识库返回结果数量，默认 3
  - `search_method`：搜索方法，选项：`keyword_search`、`semantic_search`、`full_text_search`、`hybrid_search`，默认 `semantic_search`
  - `rerank`：是否启用重排序，默认关闭
  - `rerank_model_name`：重排序使用的模型名称
- 返回匹配片段的标题、内容、得分等

### ragflow_search
- **检索参数**：
  - `query`：检索问题，必填
  - `doc_id`：可选，限定搜索到特定文档（单个 ID 或 JSON 数组）
  - `dataset_ids`：可选，临时覆盖本次搜索的知识库范围
- **配置参数**：
  - `server_url`：RAGFlow API 基础地址（如 `http://<host>:9380`）
  - `api_key`：RAGFlow API 密钥
  - `dataset_ids`：要检索的 RAGFlow 知识库 ID 列表
  - `top_k`：返回结果数量，默认 3
  - `similarity_threshold`：最小相似度阈值，默认 0.2
  - `vector_similarity_weight`：混合搜索中向量相似度权重，默认 0.3
  - `keyword`：混合搜索中是否启用关键词搜索，默认关闭
  - `highlight`：是否在结果中启用高亮，默认开启
- 结果按相似度降序返回；无结果时提示放宽或缩短查询词

### idata_search
- **检索参数**：
  - `question`：检索问题，必填
- **配置参数**：
  - `server_url`：iData API 基础地址
  - `api_key`：iData API 密钥
  - `user_id`：iData 用户 ID
  - `knowledge_space_id`：知识空间 ID（填写前三项后自动拉取空间列表，从下拉中选择）
  - `dataset_ids`：当前空间内要检索的知识库 ID 列表
  - `rerank_model_id`：Rerank 模型 ID（必填）
  - `top_k`：最大返回结果数量，默认 10
  - `similarity_threshold`：Rerank 相似度阈值，默认 -10.0
  - `keyword_similarity_weight` / `vector_similarity_weight`：关键词与向量相似度权重，默认 0.10 / 0.3
- 支持 iData 两级选择（知识空间 → 知识库）；结果附带文档下载链接作为引用来源

### haotian_search
- **检索参数**：
  - `query`：检索问题，必填
- **配置参数**：
  - `list_url`：昊天知识集/知识库列表 URL
  - `retrieve_url`：昊天检索 API URL
  - `authorization`：Authorization 请求头（如 `Bearer xxx`）
  - `dataset_ids`：要检索的知识库 ID 列表（通过专用选择弹窗按「知识集 → 知识库」勾选）
  - `top_k`：返回结果数量，默认 3
  - `reranking_enable`：是否启用检索接口内置重排，默认关闭
  - `keyword_weight` / `vector_weight`：关键词与向量相似度权重，默认 0.1 / 0.3
  - `score_threshold_enabled` / `score_threshold`：是否启用结果过滤阈值及阈值取值
- **仅支持关键词检索**：昊天接口不支持语义与混合搜索，请保持默认搜索方法

### aidp_search（系统托管）
- **检索参数**：
  - `query`：检索问题，必填
  - `kds_list`：可选，指定本次检索的知识库 ID 列表（最多 10 个），不传则使用系统注入的默认范围
- **配置参数**（由系统按部署配置注入，无法手动修改）：
  - `search_method`：检索通道，`vector_search`（向量）、`full_text_search`（全文）、`graph_search`（图谱）或竖线组合，默认三通道全开
  - `reranking_enable`：是否启用重排序，默认开启
  - `reranking_mode`：重排策略，`performance`（默认，性能优先）/ `high_accuracy`（精度优先）/ `jargon_coverage`（术语覆盖优先）
  - `rewrite_enable`：黑话/查询改写，默认关闭
  - `query_expansion_enable`：查询扩展，默认关闭
  - `related_search_enable`：关联 Chunk 检索，默认关闭
  - `score_threshold`：相似度阈值（0–1），默认 0.0
  - `top_k`：返回结果数量（1–100），默认 10
  - `multi_modal`：是否返回多模态 Chunk（图片/表格），默认开启
  - 通道细参：`vector_candidates` / `full_text_candidates`（候选数，默认 10）、`hybrid_top_k` / `graph_top_k`（通道返回上限，0 表示不单独限制）、`vector_score_threshold` / `full_text_score_threshold` / `graph_score_threshold`（各通道阈值）、`graph_reranking_enable`（图谱参与重排）
- 返回文本、表格、图片等多模态检索块；图片另通过独立通道发送
- 检索范围按当前对话用户的 AIDP 权限白名单过滤：无论使用默认范围还是 LLM 传入的 `kds_list`，都会与用户有权限访问的知识库取交集，未授权的知识库会被剔除
- 若过滤后无可访问的知识库，工具会返回明确的无权限提示，而非静默返回空结果

### ind_aidp_search
- **检索参数**：
  - `query`：检索问题，必填
  - `kds_list`：可选，本次调用的知识库 ID 列表（最多 10 个），不传则使用工具配置中的知识库
- **配置参数**：
  - `server_url`：AIDP 服务地址（必须为 http/https 地址，不支持携带账号密码）
  - `api_key`：AIDP API 密钥
  - `tenant_id`：AIDP 租户 ID，默认 `aidp`
  - `kds_list`：要检索的知识库 ID 列表（通过选择弹窗勾选，最多 10 个）
  - 检索配置参数与 `aidp_search` 一致（检索通道、重排策略、候选数、查询增强、多模态等），在工具配置弹窗的「检索配置参数」区块中自定义，支持恢复默认
- 独立持有连接配置，不参与托管形态的权限体系；多模态图片经 Nexent 代理展示，密钥不会下发浏览器

### exa_search / tavily_search / linkup_search
- **检索参数**：
  - `query`：检索问题，必填
- **配置参数**：
  - `exa/tavily/linkup_api_key`：对应服务的 API 密钥
  - `max_results`：返回结果数量，默认 3
  - `image_filter`：是否启用图片过滤，默认开启
- 图片过滤：默认开启，按查询语义过滤常见无关图片；可关闭以获取全部图片 URL
- API Key 获取：
  - Exa：前往 [exa.ai](https://exa.ai/) 注册并在控制台申请 Exa API Key
  - Tavily：访问 [tavily.com](https://www.tavily.com/) 创建账户，在 Dashboard 获取 Tavily API Key
  - Linkup：在 [linkup.so](https://www.linkup.so/) 注册并于个人中心创建 Linkup API Key
- 返回标题、URL、摘要，可能附带图片 URL 列表（去重处理）

### deepseek_search
- **检索参数**：
  - `query`：检索问题，必填。支持 `site:domain` 限定站点（多个站点用 OR 连接）、`-site:domain` 排除站点、`-关键词` 与 `-"短语"` 排除内容、`"精确短语"` 精确匹配、`after:` 与 `before:` 限定日期或年份；建议控制在 120 字符以内
- **配置参数**：
  - `deepseek_api_key`：DeepSeek API 密钥（必填）
  - `max_results`：请求结果数量，默认 10（1–50）
  - `only_high_quality`：开启后仅返回排序分不低于 1.5 的结果
  - `need_content`：返回网页正文，缺失时使用摘要
  - `timeout_seconds`：每次 HTTP 尝试的网络超时秒数，默认 30（1–120）
  - `max_retries`：失败后的最大重试次数，默认 2（0–2）

## 🛠️ 操作指引

1. **选择数据源**：私有资料可检索本地知识库与 AIDP（均由系统托管注入）；外部知识库按平台选 DataMate、Dify、RAGFlow、昊天或 iData；独立部署的 AIDP 使用 `ind_aidp_search`；实时公开信息用 Exa、Tavily、Linkup 或 DeepSeek。
2. **设置检索模式/数量**：知识库可切换 `search_mode`/`search_method`；公网搜索可调整 `max_results` 与是否启用图片过滤。
3. **填写连接与鉴权参数**：DataMate、Dify、RAGFlow、昊天、iData、独立 AIDP 均需在工具配置中填写服务地址与密钥；托管形态的 AIDP 凭证由部署配置注入，无需手动填写。
4. **配置可检索知识库范围**：各外部知识库工具在配置弹窗中通过知识库选择器勾选检索范围；AIDP 的实际检索范围还会按当前对话用户的权限白名单再过滤一次。
5. **限定范围**：需要特定知识库时填写 `index_names`（本地知识库）或显式传入 `kds_list`（AIDP），避免无关结果；DataMate 可通过阈值与 top_k 控制结果精度与数量。
6. **启用重排序（可选）**：如需提升检索结果相关性，可开启各工具的 `rerank` / `reranking_enable`，并通过对应的模型名称或重排策略调整效果。
7. **结果利用**：返回为 JSON，可直接用于回答、摘要或后续引用；包含 cite 索引便于引用管理。

## 🛡️ 安全与最佳实践

- 公网搜索与外部知识库服务的凭证（`api_key` 等）需确保已在平台安全配置中设置，不要在对话中暴露。
- AIDP 知识库检索受当前对话用户的权限控制。如用户看不到某个知识库，即使该知识库在检索范围配置中，也不会被检索到，请联系 AIDP 管理员授予相应权限。
- 知识库检索前确认已同步最新文档，避免旧版本内容。
- 当查询过于宽泛导致无结果时，可缩短或拆分问题；图片过滤未命中时可尝试关闭过滤获取原始图片列表。
