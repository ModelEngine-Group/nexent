# Nexent 评测功能 API 接口文档

> Base URL: `http://localhost:5010/api`
> Auth: Bearer token from `/api/user/signin`

---

## 1. 评测器管理 `/api/evaluators`

### 1.1 列表查询 `GET /api/evaluators`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| source | query | 否 | `builtin` / `custom` |
| evaluator_type | query | 否 | `llm` / `code` |
| authorization | header | 是 | Bearer token |

Response: `{"message": "Success", "data": [...]}`

---

### 1.2 详情查询 `GET /api/evaluators/{evaluator_id}`

Response: `{"message": "Success", "data": {...}}`  
404: 评测器不存在

---

### 1.3 创建评测器 `POST /api/evaluators`

Body (JSON):
```json
{
  "name": "string (1-50 chars, required)",
  "description": "string (max 200, optional)",
  "evaluator_type": "llm | code (default: llm)",
  "prompt": "string (max 5000, optional)",
  "code": "string (max 20000, optional)",
  "score_range_min": "float (optional)",
  "score_range_max": "float (optional)",
  "pass_threshold": "float (optional)",
  "input_fields": "[{name, type, required}] (optional)",
  "model_id": "int (optional)"
}
```

校验规则: score_range_min < score_range_max, pass_threshold 在范围内, score_range_max ≤ 100

---

### 1.4 更新评测器 `PUT /api/evaluators/{evaluator_id}`

Body: 同 1.3 但所有字段可选，只更新提供的字段。
400: 非 DRAFT 或非 custom 不可编辑  
409: 评测器被运行中的评测引用

---

### 1.5 删除评测器 `DELETE /api/evaluators/{evaluator_id}`

400: 非 custom 不可删除  
409: 被运行中的评测引用

---

### 1.6 发布评测器 `POST /api/evaluators/{evaluator_id}/publish`

Body: `{"version_name": "string (optional)", "release_note": "string (optional)"}`  
400: 非 DRAFT 状态不可发布

---

### 1.7 版本列表 `GET /api/evaluators/{evaluator_id}/versions`



### 1.8 恢复版本 `POST /api/evaluators/{evaluator_id}/versions/{version_id}/restore`

404: 版本不存在  
409: 被运行中的评测引用

---

### 1.9 删除版本 `DELETE /api/evaluators/{evaluator_id}/versions/{version_id}`

404: 版本不存在  
409: 是当前版本或被引用

---

### 1.10 导出 `POST /api/evaluators/export`

Body: `{"evaluator_ids": [int, ...] (1-100 items)}`  
Response: `StreamingResponse` (JSON 文件下载)  
400: 存在非 custom 评测器 ID

---

### 1.11 导入 `POST /api/evaluators/import`

Body: `multipart/form-data` — `file` (JSON 文件)  
Response: `{"message": "Success", "data": {"imported": N, "skipped": N, "errors": [...]}}`  
400: 无效 JSON 文件

---

### 1.12 AI 生成 `POST /api/evaluators/generate`

Body:
```json
{
  "description": "string (1-500 chars, required)",
  "model_id": "int (required)",
  "agent_id": "int (optional)",
  "language": "zh | en (default: zh)"
}
```

400: 参数校验失败

---

## 2. 评测集管理 `/api/evaluation-sets`

### 2.1 列表 `GET /api/evaluation-sets`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| limit | query | 否 | 1-200, 默认 50 |
| offset | query | 否 | ≥0, 默认 0 |

---

### 2.2 创建 `POST /api/evaluation-sets`

Body:
```json
{
  "name": "string (required, min/max from consts)",
  "description": "string (optional)",
  "source_filename": "string (optional)",
  "jsonl_text": "string (default: \"\")"
}
```

400: 名称不合理  
429: 超过租户评测集上限

---

### 2.3 上传文件 `POST /api/evaluation-sets/upload`

Body: `multipart/form-data`
- `name`: string
- `description`: string (optional)
- `files`: List[UploadFile] — 支持 .xlsx/.xls (Excel) 和 JSONL

400: 无有效用例

---

### 2.4 模板下载 `GET /api/evaluation-sets/template`

无需认证。Response: `StreamingResponse` (Excel 文件)

---

### 2.5 详情 `GET /api/evaluation-sets/{evaluation_set_id}`

404: 不存在

---

### 2.6 导出 `GET /api/evaluation-sets/{evaluation_set_id}/export`

Response: `StreamingResponse` (Excel 文件)  
404: 不存在

---

### 2.7 用例列表 `GET /api/evaluation-sets/{evaluation_set_id}/cases`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| limit | query | 否 | 1-200, 默认 50 |
| offset | query | 否 | ≥0, 默认 0 |
| query | query | 否 | 模糊搜索 inputs.query |

Response: `{"message": "Success", "data": [...], "total": N}`

---

### 2.8 添加用例 `POST /api/evaluation-sets/{evaluation_set_id}/cases`

Body: `{"inputs": {...}, "label": {...}}`  
校验: query 长度约束, answer 长度约束  
400: 校验失败

---

### 2.9 更新用例 `PUT /api/evaluation-sets/{evaluation_set_id}/cases/{case_id}`

Body: `{"inputs": {...}, "label": {...}}`  
404: 用例不存在

---

### 2.10 删除用例 `DELETE /api/evaluation-sets/{evaluation_set_id}/cases/{case_id}`

404: 用例不存在

---

### 2.11 批量删除用例 `POST /api/evaluation-sets/{evaluation_set_id}/cases/batch-delete`

Body: `{"case_ids": [...]}`  
Response: `{"message": "Success", "data": {"deleted": N}}`

---

### 2.12 删除评测集 `DELETE /api/evaluation-sets/{evaluation_set_id}`

400: 校验失败  
404: 不存在  
409: 被引用

---

### 2.13 异步 AI 生成用例 `POST /api/evaluation-sets/generate-cases-async`

Body:
```json
{
  "description": "string (1-1000, required)",
  "count": "int (1-200, default 20)",
  "model_id": "int (required)",
  "knowledge_base_names": ["string"],
  "agent_id": "int",
  "agent_version_no": "int",
  "file_content": "string (max 5M)",
  "file_name": "string",
  "set_name": "string (当不指定 target_set_id 时需要)",
  "set_description": "string",
  "target_set_id": "int (指定则追加到已有评测集)"
}
```

---

### 2.14 同步 AI 生成用例 `POST /api/evaluation-sets/generate-cases`

Body: 同 2.13  
400: 参数校验失败

---

## 3. 评测执行 `/api/agent-evaluations`

### 3.1 创建评测运行 `POST /api/agent-evaluations`

Body:
```json
{
  "agent_id": "int (required)",
  "judge_model_id": "int (required)",
  "evaluator_ids": "[int] (optional)",
  "field_mappings": "object (optional)",
  "evaluation_set_id": "int (optional)",
  "agent_version_no": "int (optional)",
  "query_count": "int (default 10)"
}
```

两种模式:
- 指定 `evaluation_set_id`: 使用已有评测集的用例
- 不指定: AI 自动生成 `query_count` 条用例

400: 校验失败  
404: Agent/评测集不存在  
409: 资源冲突  
429: 超出限制

---

### 3.2 列表 `GET /api/agent-evaluations?agent_id=<id>`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| agent_id | query | 是 | |
| limit | query | 否 | 1-200, 默认 50 |
| offset | query | 否 | ≥0, 默认 0 |

---

### 3.3 详情 `GET /api/agent-evaluations/{agent_evaluation_id}`

404: 不存在

---

### 3.4 评测用例列表 `GET /api/agent-evaluations/{agent_evaluation_id}/cases`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| limit | query | 否 | 1-200, 默认 10 |
| offset | query | 否 | ≥0 |
| sort_by | query | 否 | 排序字段 |
| sort_order | query | 否 | asc/desc |
| pass_filter | query | 否 | 通过筛选 |
| anno_schema_id | query | 否 | 标注筛选 |
| anno_value | query | 否 | 标注值筛选 |

---

### 3.5 统计数据 `GET /api/agent-evaluations/{agent_evaluation_id}/stats`

Response: `{"message": "Success", "data": {...}}` (图表数据)

---

### 3.6 PDF 报告下载 `GET /api/agent-evaluations/{agent_evaluation_id}/report`

Response: `StreamingResponse` (PDF, `application/pdf`)

---

### 3.7 AI 分析报告 `POST /api/agent-evaluations/{agent_evaluation_id}/analyze`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| force | query | 否 | 是否强制重新生成 |

---

### 3.8 标注 Schema 绑定 `PUT /api/agent-evaluations/{agent_evaluation_id}/annotation-schemas`

Body: `{"schema_ids": [int, ...]}`

---

### 3.9 删除评测 `DELETE /api/agent-evaluations/{agent_evaluation_id}`

400: 校验失败  
404: 不存在  
409: 资源冲突

---

### 3.10 单次试运行 `POST /api/agent-evaluations/trial-run`

Body:
```json
{
  "agent_id": "int (required)",
  "agent_version_no": "int (default 1)",
  "query": "string (required)",
  "judge_model_id": "int (required)",
  "evaluator_ids": "[int]",
  "field_mappings": "object",
  "language": "zh | en (default: zh)"
}
```

异步执行，返回单次评估结果。

---

## 4. 标注管理 `/api/evaluation-annotations`

### 4.1 Schema 列表 `GET /api/evaluation-annotations/schemas`



### 4.2 创建 Schema `POST /api/evaluation-annotations/schemas`

Body:
```json
{
  "name": "string (1-50, required)",
  "description": "string (max 200)",
  "annotation_type": "string (default: classification)",
  "options": "[{...}]"
}
```



### 4.3 更新 Schema `PUT /api/evaluation-annotations/schemas/{schema_id}`

Body: `name`, `description`, `options` (all optional)  
404: 不存在

---

### 4.4 删除 Schema `DELETE /api/evaluation-annotations/schemas/{schema_id}`

404: 不存在  
409: 被引用

---

### 4.5 获取标注数据 `GET /api/evaluation-annotations/{agent_evaluation_id}/annotations`



### 4.6 批量保存标注 `PUT /api/evaluation-annotations/{agent_evaluation_id}/annotations`

Body: `{"annotations": [{...}]}`



### 4.7 标注统计 `GET /api/evaluation-annotations/{agent_evaluation_id}/annotation-stats`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| schema_id | query | 是 | |

---

## 错误码汇总

| HTTP Status | 含义 |
|-------------|------|
| 400 | 参数校验失败 / 状态不允许操作 |
| 401 | 未认证 |
| 404 | 资源不存在 |
| 409 | 资源冲突（被引用中） |
| 429 | 超出限额 |
| 500 | 服务端错误 |
