# iData 知识库对接

Nexent 支持通过 `idata_search` 工具检索 iData 平台的知识库：智能体根据查询词在选定知识空间的知识库中检索，返回最相关的结果，特别适合访问未公开存储知识的场景。

## 前置条件

- 可访问的 iData 服务地址
- iData API 密钥与用户 ID
- 目标知识空间下已创建知识库，以及可用的 Rerank 模型 ID

## 配置步骤

1. 进入「智能体配置」页面，打开目标智能体
2. 在工具管理中将 **idata_search**（本地工具）添加到智能体
3. 点击该工具行的 **配置** 按钮，在配置参数中填写：

| 参数 | 说明 |
| --- | --- |
| **server_url** | iData API 基础 URL |
| **api_key** | iData API 密钥（以密码框显示） |
| **user_id** | iData 用户 ID |
| **knowledge_space_id** | iData 知识空间 ID：填写前三项后自动拉取空间列表，从可搜索下拉中选择 |
| **dataset_ids** | 点击选择框，从当前空间同步的知识库中勾选（可多选） |
| **rerank_model_id** | Rerank 模型 ID（必填） |
| **top_k** | 最大返回结果数量，默认 10（1–100） |
| **similarity_threshold** | Rerank 相似度阈值，默认 -10.0（≤1.0） |
| **keyword_similarity_weight / vector_similarity_weight** | 关键词与向量相似度权重，默认 0.10 / 0.3（0–1） |

4. 点击 **保存配置**。未选择知识库时无法保存

iData 采用「知识空间 → 知识库」两级选择：先在配置参数中选择知识空间，切换空间会清空已选知识库并重新拉取；再点击 **dataset_ids** 选择框，从该空间的知识库列表中勾选。打开选择框时会自动同步一次列表。

## 运行参数

智能体运行时，LLM 只需提供：

- **question**：搜索查询词

## 注意事项

- server_url、api_key、user_id、knowledge_space_id、rerank_model_id 五项均为必填
- iData 支持自签名证书环境；检索结果会附带文档下载链接作为引用来源
- 同一智能体可同时配置其他知识检索工具
