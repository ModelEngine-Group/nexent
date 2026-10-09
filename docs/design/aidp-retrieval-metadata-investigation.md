# AIDP 知识检索元数据：接口核对与后续需求记录

记录日期：2026-10-09。

状态：已核对现有接口文档和代码；用户要求先记录，后续再看，暂不开发。

核对代码：`feat-knowledge-base-pages-refactor`，业务代码提交 `0cf1f44b4`。

## 需求背景

用户了解到 AIDP 知识检索接口将增加一些元数据字段，希望后续智能体对话使用 AIDP 知识库搜索时，也能在右侧检索来源面板展示相关信息，参考当前 ES 知识库的展示方式。

本次只确认已有接口是否包含元数据、现有代码是否保留这些数据，没有确定新增字段的名称和页面展示方案。

## 原始接口文档结论

来源：`C:\Users\cj\Downloads\AIDP-26.0.0-1790238797166.xls`，工作表 `AIDP`。融合检索接口的方法和地址在第 6075 行，示例在第 6077 行，元数据过滤参数在第 6085 行，返回字段说明在第 6100–6109 行。

Nexent 当前调用的是融合检索接口：

```text
POST /KnowledgeBase/Tenants/{tenant_id}/Retrieval/FusionSearch
```

现有文档已经包含以下字段：

| 位置 | 字段 | 文档含义及限制 |
| --- | --- | --- |
| 请求 | `metadata_condition` | 可选字典，元数据过滤条件；融合检索这一节未给出内部条件的完整字段定义 |
| 返回 | `result` | 检索结果列表 |
| 返回 | `total_return_count` | 返回结果数量 |
| 每条结果 | `title` | 切片所属文件名称 |
| 每条结果 | `id` | 切片主键，不能直接当成原始文件 ID |
| 每条结果 | `score` | 切片得分，范围 0–1 |
| 每条结果 | `text` | 切片内容 |
| 每条结果 | `metadata` | 元数据字典，示例为 `{}`，未说明内部键名、类型和含义 |
| 每条结果 | `chunk_type` | `text`、`image`、`table` |
| 每条结果 | `file_url` | 文档说明为图片文件地址，不能假定是原始文档下载地址 |
| 每条结果 | `pages` | 切片所属文件页码列表，未说明从 0 还是从 1 开始 |

因此，现有接口已经有承载元数据的字段，但文档不足以确认即将新增的具体内容。“增加元数据字段”可能是补充现有 `metadata` 对象里的内容，这只是推测，需以 AIDP 更新后的文档或真实响应为准。

文档另有 Dify 检索接口 `POST /KnowledgeBase/Tenants/{tenant_id}/Retrieval/FusionSearch/retrieval`，也包含 `metadata_condition` 和结果 `metadata`。这不是 Nexent 当前调用的接口。其中出现的 `source`、`department`、`tags` 属于过滤条件示例，不能当成融合检索必定返回的标准字段。

## 当前代码如何处理这些字段

1. `sdk/nexent/core/ext_components/aidp/aidp_search_tool.py` 调用融合检索接口，并在 `_build_chunk_message` 中读取 `metadata`、`pages`、`chunk_type`、`file_url`、`id`、`score`。其中元数据保存在 `score_details.metadata`，页码保存在 `score_details.pages`；完整 UI 结果通过 `ProcessType.SEARCH_CONTENT` 发出。SDK 已经保留元数据。
2. `frontend/app/[locale]/newchat/adapter/remote-chat-model-adapter.ts` 在转换检索结果时，仅取出部分字段，例如图片类型、检索高亮词、文件名和文本。传给来源面板的数据没有保留完整的 `score_details`、任意元数据、页码和得分。正常流式解析和末尾缓冲解析都有同类转换，后续修改需要同时检查。
3. `frontend/app/[locale]/newchat/ui/sources-panel.tsx` 的 `PanelSourceItem` 没有元数据、页码和得分字段，当前来源卡片也没有任意元数据的展示逻辑。

当前问题主要在前端数据转换和来源面板展示，不能说 SDK 已经丢掉了这些字段。后续还需检查历史消息恢复路径，确保重新打开对话后能够展示；本次没有做这条路径的端到端验证。

## 后续待确认内容

- 获取 AIDP 更新后的融合检索响应样例或字段说明，确认新增元数据的名称、类型、含义，以及哪些字段可能为空。
- 根据真实字段决定右侧面板展示哪些信息、顺序如何、缺失值如何处理。不要先编造知识库 ID、文件 ID 或原始文件下载地址的对应关系。
- 如果展示页码，确认页码起点；如果提供下载或跳转，确认接口给出的地址用途。
- 当前机器没有正式 AIDP 环境；mock 样例只能用于验证页面，不能证明 AIDP 新接口的实际返回。

## 后续开发建议

确认真实字段后，再补齐前端流式解析、来源数据和历史消息恢复的数据传递，并扩展现有右侧来源面板。对应更新 mock 和必要验证，覆盖文本、图片、表格切片，以及元数据缺失的情况。AIDP 新展示需保持 ES 知识库现有行为。

本记录不代表已确定最终页面设计，也不代表已经实施该需求。
