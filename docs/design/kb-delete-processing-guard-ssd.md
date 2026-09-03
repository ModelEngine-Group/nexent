# Knowledge-base deletion guard — SSD

## 1. Document control

- **Status:** Approved for implementation
- **Date:** 2026-09-03
- **Scope:** Local Elasticsearch knowledge-base deletion
- **Out of scope:** DataMate, AIDP, Dify, iData and other externally managed knowledge bases; asynchronous deletion; changing the single-file deletion contract.

## 2. Problem statement

Deleting a knowledge base while one or more files are still being uploaded or processed can race with Celery/Ray ingestion tasks. The current delete path starts external cleanup and then performs broad Redis cleanup, but it does not use the durable PostgreSQL lifecycle table as a precondition. A late task can therefore continue writing after the delete request, and the user receives no actionable explanation when deletion should be blocked.

The deletion operation remains synchronous in this change. A file already in `DELETE_REQUESTED` is not treated as a new blocker; knowledge-base deletion continues with its broader cleanup path.

## 3. Goals and non-goals

### Goals

1. Prevent a knowledge-base delete from starting external cleanup when files are still in an active ingestion state.
2. Return a stable EDS error code and structured details identifying the blocking files.
3. Preserve the existing successful synchronous delete response and cleanup behavior.
4. Ensure the two frontend delete entry points show the backend reason and do not optimistically remove a failed item.
5. Treat `DELETE_REQUESTED` records as already-owned deletion work: do not block or duplicate their tombstone, and let the knowledge-base cleanup cover the remaining data.

### Non-goals

- No broker-message deletion or new Celery cancellation mechanism.
- No asynchronous knowledge-base deletion job or new job table.
- No migration of historical lifecycle rows.
- No behavior change for externally managed knowledge bases.

## 4. Current implementation findings

The service `ElasticSearchService.full_delete_knowledge_base()` currently performs source-object cleanup, broad Redis cleanup, Elasticsearch index deletion and the soft deletion of `knowledge_record_t`. Lifecycle records are available through `knowledge_file_lifecycle_db`, but there is no knowledge-base-level precondition check.

The lifecycle statuses relevant to the guard are:

| Status | Delete KB behavior |
| --- | --- |
| `UPLOADING` | Block and report the file |
| `UPLOADED` | Block and report the file |
| `PROCESSING` | Block and report the file |
| `FORWARDING` | Block and report the file |
| `DELETE_REQUESTED` | Do not create a duplicate request; broad cleanup owns the scope |
| `FAILED`, `COMPLETED`, `DELETED` | Not a blocker; normal bulk cleanup applies |

The existing application-wide `AppException` handler already serializes EDS errors as `{code, message, details}`. The delete routes currently catch broad exceptions, so the implementation must let `AppException` propagate to that handler.

## 5. Design

### 5.1 Lifecycle precondition

At the first line of `full_delete_knowledge_base()` (after authorization has already succeeded), query lifecycle rows by `index_name` with `include_hidden=True`. Filter only the four blocking statuses. If any exist, raise `AppException` with the new knowledge-module error code `KNOWLEDGE_DELETE_BLOCKED` (`060109`) and HTTP 409.

The error details are machine-readable and contain only the information needed by the UI:

```json
{
  "index_name": "kb_index",
  "blocking_files": [
    {
      "file_id": "stable-id",
      "file_name": "report.pdf",
      "status": "PROCESSING"
    }
  ]
}
```

No MinIO, Redis or Elasticsearch mutation is performed when this precondition fails.

### 5.2 Existing `DELETE_REQUESTED` records

Rows already in `DELETE_REQUESTED` are deliberately excluded from the blocking query. The status means that the single-file deletion flow has already hidden the file and established its deletion fence. Knowledge-base deletion continues with its normal broad cleanup, including Redis cancellation metadata and MinIO/Elasticsearch cleanup, without creating a second tombstone or returning a duplicate-delete error. The existing single-file callback remains idempotent when it observes that the knowledge base or lifecycle row has already been removed.

### 5.3 Cleanup ordering

```text
authorize
  -> lifecycle precondition (block UPLOADING/UPLOADED/PROCESSING/FORWARDING)
  -> ignore DELETE_REQUESTED rows as blockers (broad cleanup owns the scope)
  -> delete canonical MinIO source objects and storage charges
  -> clean Redis result/progress/error/chunk metadata
  -> delete Elasticsearch index
  -> soft-delete knowledge_record_t
  -> return existing success payload
```

If an external cleanup step reports failure, existing behavior and warnings are preserved. The new guard does not introduce a partial rollback protocol; it only prevents known active ingestion races before mutation starts.

### 5.4 EDS error handling

Add `ErrorCode.KNOWLEDGE_DELETE_BLOCKED = "060109"` and map it to HTTP 409. Add its default message to `ErrorMessage`.

Both `backend/apps/vectordatabase_app.py` and `backend/apps/northbound_knowledge_app.py` must preserve `AppException` instead of converting it to a generic HTTP 500. Other legacy exception mappings remain unchanged.

### 5.5 Frontend behavior

`knowledgeBaseService.deleteKnowledgeBase()` already uses the shared `fetchWithErrorHandling()` path, which preserves EDS response fields. Both `KnowledgeBaseConfiguration` and resource-management `KnowledgeList` will display the preserved message. For `060109`, the UI will additionally format the returned file names and statuses when available. The list is refreshed or the item is removed only after a successful response.

## 6. Compatibility

- Existing successful delete callers receive the same response shape.
- Existing permission and authentication behavior is unchanged.
- Only local Elasticsearch knowledge-base deletion is guarded by this lifecycle check.
- If the lifecycle table cannot be queried, the service fails with an EDS database error rather than silently performing an unsafe broad delete.

## 7. Verification plan

### API tests

| ID | Priority | Scenario and expected result | source_role | Trace |
| --- | --- | --- | --- | --- |
| API-01 | P0 | Delete a KB with no lifecycle rows; the existing success response and cleanup calls are preserved. | `direct_input` | `KB-DELETE-GUARD` |
| API-02 | P0 | For each of `UPLOADING`, `UPLOADED`, `PROCESSING`, and `FORWARDING`, delete returns HTTP 409/code `060109`, includes file name/status in `details`, and performs no external cleanup. | `direct_input` | `KB-DELETE-GUARD`, `EDS-060109` |
| API-03 | P1 | A KB containing `DELETE_REQUESTED` plus completed files is not blocked; broad cleanup proceeds without a duplicate tombstone. | `direct_input` | `DELETE-REQUESTED-COMPAT` |
| API-04 | P1 | Lifecycle lookup/database failure returns the EDS database error and does not start external cleanup. | `direct_input` | `EDS-ERROR-PROPAGATION` |
| API-05 | P1 | Unauthorized or read-only callers retain the existing 401/403 behavior. | `direct_input` | `DELETE-AUTH-COMPAT` |
| API-06 | P1 | The northbound delete endpoint preserves the same EDS code/message/details contract. | `direct_input` | `NORTHBOUND-EDS-CONTRACT` |

### UI tests

| ID | Priority | Scenario and expected result | source_role | Trace |
| --- | --- | --- | --- | --- |
| UI-01 | P0 | Delete a KB with processing files; the notification names the blocking files/statuses. | `direct_input` | `UI-DELETE-ERROR` |
| UI-02 | P0 | A blocked delete leaves the KB visible and shows no success notification. | `direct_input` | `UI-DELETE-ERROR` |
| UI-03 | P1 | A successful delete still refreshes the list and quota state. | `direct_input` | `DELETE-SUCCESS-COMPAT` |
| UI-04 | P1 | Both knowledge configuration and resource-management delete entry points use the same EDS error formatting. | `direct_input` | `UI-DELETE-ERROR` |
| UI-05 | P2 | A generic server error still uses the existing fallback message. | `direct_input` | `UI-DELETE-FALLBACK` |

## 8. Acceptance criteria

- No external delete/cleanup is started when an active lifecycle row is present.
- The frontend can explain why deletion was blocked without inspecting logs.
- `DELETE_REQUESTED` is excluded from the blocker list and is cleaned by the existing broad deletion path without duplicate tombstones.
- Existing successful deletion and permission behavior remain compatible.
- API and UI test cases above pass in the local environment.
