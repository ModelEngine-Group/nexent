# AIDP Knowledge Base Adapter Design

## Goal

Build a FastAPI service adapter under `sdk/nexent/core/knowledge_base` that exposes the Nexent external knowledge-base standard API and translates those calls to the current AIDP knowledge-base API.

This first version is intentionally narrow:

- Tenant ID is hardcoded to `aidp`.
- AIDP base URL, API key, and default knowledge-base creation parameters are hardcoded in code.
- Document deletion is not implemented yet and returns a clear not-implemented response.
- The adapter is service-shaped: Nexent calls it over HTTP using the standard adapter API.

## Scope

The adapter will implement these standard endpoints:

- `GET /health`
- `GET /capabilities`
- `POST /api/v1/knowledge-bases`
- `GET /api/v1/knowledge-bases`
- `GET /api/v1/knowledge-bases/{knowledge_base_id}`
- `PUT /api/v1/knowledge-bases/{knowledge_base_id}`
- `DELETE /api/v1/knowledge-bases/{knowledge_base_id}`
- `POST /api/v1/knowledge-bases/{knowledge_base_id}/documents`
- `GET /api/v1/knowledge-bases/{knowledge_base_id}/documents`
- `DELETE /api/v1/knowledge-bases/{knowledge_base_id}/documents/{document_id}`
- `POST /api/v1/retrieve`

The document deletion endpoint is part of the route surface but is deliberately disabled in this version.

## Proposed Structure

Create a package at `sdk/nexent/core/knowledge_base`:

- `__init__.py`: package exports.
- `config.py`: hardcoded AIDP adapter configuration.
- `aidp_client.py`: AIDP native HTTP client.
- `mapper.py`: standard-to-AIDP and AIDP-to-standard field mapping.
- `app.py`: FastAPI application and standard adapter routes.

This keeps the HTTP service thin while leaving AIDP-specific request logic and mapping logic testable in isolation.

## Hardcoded Configuration

`config.py` will define:

- `AIDP_BASE_URL`
- `AIDP_API_KEY`
- `AIDP_TENANT_ID = "aidp"`
- `DEFAULT_CHUNK_TOKEN_NUM = 1024`
- `DEFAULT_CHUNK_OVERLAP_NUM = 128`
- `DEFAULT_IS_PERSONAL = 0`
- `DEFAULT_CAPTION_ENABLE = 0`
- `DEFAULT_EMBEDDING_MODEL = "default"`
- `DEFAULT_VLM_MODEL = ""`

These are hardcoded for the first version because the current goal is adapter validation, not deployment configuration. They can later move to environment variables without changing route behavior.

`AIDP_API_KEY` can use the AK provided during implementation discussion. `AIDP_BASE_URL` must be filled with the target AIDP service URL before the adapter can be run against a real AIDP instance.

## Endpoint Mapping

### Health

`GET /health` calls AIDP knowledge-base list or count with `TenantId=aidp`.

If AIDP responds successfully:

```json
{
  "status": "ok",
  "platform": "aidp",
  "version": "1.0.0",
  "external_kb_reachable": true
}
```

If the call fails, return `status: "error"` and `external_kb_reachable: false`.

### Capabilities

`GET /capabilities` returns static capabilities:

- create/update/delete knowledge base: true
- upload/list document: true
- delete document: false
- search modes: `semantic_search`, `keyword_search`, `hybrid_search`
- rerank: true
- multimodal: true

### Create Knowledge Base

Standard endpoint:

`POST /api/v1/knowledge-bases`

AIDP endpoint:

`PUT /KnowledgeBase/Tenants/aidp/KnowledgeBases`

The standard request supplies `name`, optional `description`, optional `embedding_model`, optional `is_multimodal`, and optional `vision_model`.

The adapter fills AIDP-required fields:

- `chunk_token_num`
- `chunk_overlap_num`
- `is_personal`
- `caption_enable`
- `embedding_model`
- `vlm_model`

AIDP returns only `kds_id`, so the adapter will fetch the created knowledge base detail after creation when possible. If detail fetch fails, it returns a minimal standard object using the request values and the returned `kds_id`.

### List Knowledge Bases

Standard endpoint:

`GET /api/v1/knowledge-bases?page=1&page_size=20`

AIDP endpoint:

`GET /KnowledgeBase/Tenants/aidp/KnowledgeBases`

For `has_more`, the adapter will not use `next_link`. It will call:

`POST /KnowledgeBase/Tenants/aidp/KnowledgeBases/0/Count`

with:

```json
{
  "is_personal": 0
}
```

Then:

```text
has_more = page * page_size < count
```

The path `KdsId=0` is used as a placeholder because AIDP documents that `KdsId` is required in the count path, while the operation is tenant-level.

### Knowledge Base Detail

Standard endpoint:

`GET /api/v1/knowledge-bases/{knowledge_base_id}`

AIDP endpoint:

`GET /KnowledgeBase/Tenants/aidp/KnowledgeBases/{KdsId}`

The adapter treats `knowledge_base_id` as AIDP `kds_id` string.

### Update Knowledge Base

Standard endpoint:

`PUT /api/v1/knowledge-bases/{knowledge_base_id}`

AIDP endpoint:

`PATCH /KnowledgeBase/Tenants/aidp/KnowledgeBases/{KdsId}`

Only fields supplied by the standard request are forwarded. After update, the adapter fetches detail and returns a standard knowledge-base object.

### Delete Knowledge Base

Standard endpoint:

`DELETE /api/v1/knowledge-bases/{knowledge_base_id}`

AIDP endpoint:

`DELETE /KnowledgeBase/Tenants/aidp/KnowledgeBases/{KdsId}`

AIDP success is `204 No Content`. The adapter returns:

```json
{
  "code": 0,
  "data": {
    "success": true
  },
  "message": "success"
}
```

### Upload Documents

Standard endpoint:

`POST /api/v1/knowledge-bases/{knowledge_base_id}/documents`

AIDP endpoint:

`POST /KnowledgeBase/Tenants/aidp/KnowledgeBases/{KdsId}/KnowledgeFiles/Upload`

The adapter forwards multipart files and uses only:

```text
Authorization: Bearer <AIDP_API_KEY>
```

It does not send `X-Auth-User-Id` or `X-Auth-Nickname`.

AIDP `success_list` entries are mapped into standard `document_ids`. Because AIDP upload returns file metadata rather than a standard document UUID, the first version will generate stable document IDs from AIDP file fields using an encoded representation. Failed files map to `failed_files`.

### List Documents

Standard endpoint:

`GET /api/v1/knowledge-bases/{knowledge_base_id}/documents`

AIDP endpoint:

`GET /KnowledgeBase/Tenants/aidp/KnowledgeBases/{KdsId}/KnowledgeFiles`

AIDP file fields map as:

- `file_name` -> `name`
- encoded file identity -> `id`
- `file_size` -> `size`
- `file_type` -> `type`
- `first_upload_time` -> `created_at`
- `update_time` -> `updated_at`
- imported files -> `status: "completed"`

Fields AIDP does not provide directly, such as `chunk_count` and `token_count`, default to `0`.

### Delete Document

Standard endpoint:

`DELETE /api/v1/knowledge-bases/{knowledge_base_id}/documents/{document_id}`

This is not implemented in the first version. It returns an error response with a 501 HTTP status. This avoids pretending deletion works while AIDP requires extra delete fields that the standard request does not currently provide.

### Retrieve

Standard endpoint:

`POST /api/v1/retrieve`

AIDP endpoint:

`POST /KnowledgeBase/Tenants/aidp/Retrieval/FusionSearch`

Search method mapping:

- `semantic_search` -> `vector_search`
- `keyword_search` -> `full_text_search`
- `hybrid_search` -> `hybrid_search`

The adapter maps:

- `knowledge_base_ids` -> `kds_list`
- `retrieval_model.top_k` -> `top_k`
- `retrieval_model.score_threshold` -> `score_threshold`
- `retrieval_model.reranking_enable` -> `reranking_enable`
- `retrieval_model.reranking_model.model` is not passed directly unless AIDP later requires it.

AIDP `result[]` maps to standard `records[]` with `segment` plus outer `score`.

## Response and Error Handling

All successful standard responses use:

```json
{
  "code": 0,
  "data": {},
  "message": "success"
}
```

AIDP errors are normalized to:

```json
{
  "code": 50001,
  "data": null,
  "message": "AIDP error message"
}
```

Validation errors use `40001`, missing resources use `40002` where AIDP returns 404, and unsupported document deletion uses `50004` with HTTP 501.

## Testing Plan

Unit-level checks:

- Map knowledge-base list items into standard objects.
- Compute `has_more` from public knowledge-base count.
- Fill default fields for create knowledge-base requests.
- Map search method enums.
- Map AIDP retrieval results into standard `records`.
- Confirm document delete returns 501.

Light integration checks can use mocked AIDP HTTP responses through `httpx.MockTransport` or monkeypatched client methods.

## Implementation Note

The intentionally deferred item is document deletion. The implementation also needs the real `AIDP_BASE_URL` value before live integration testing can pass.
