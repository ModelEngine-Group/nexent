# AIDP file upload behavior

Updated 2026-10-09. Applies only to the AIDP knowledge-base overview and detail import drawer; ES upload behavior is unchanged.

## User flow

- Selecting or dropping files immediately uploads all valid files from that selection in one multipart request. Each part uses `files`; there is no per-file concurrency limit or separate staging API.
- The drawer holds at most 50 rows, including failures. Its file list scrolls independently while the dropzone and footer stay visible.
- Each uploading row shares the request's browser transfer percentage in a ring over its file icon. Its second line displays only its own total size, without transferred-byte text or a batch-progress label.
- Transfer at 100% means waiting for the response, not acceptance or completed indexing. Rows remain dashed until the corresponding file is accepted. Accepted rows use a solid near-black border; failures stay dashed and show the returned reason.
- Successful and failed rows remain visible. Only failed rows expose Delete, which removes a frontend row without a backend deletion request. There is no Retry action; remove a failed row and select the file again if needed.
- Confirm, Cancel, Escape, the close icon and mask dismissal are unavailable while selection processing or the upload request is active. After every request returns a success or failure response, Confirm can close the drawer without sending files again. Extraction/indexing may continue in AIDP afterward.
- A new selection after completion sends only new files. Reopening the drawer starts with an empty list.

## Transport

`AidpImportDrawer` calls `aidpKnowledgeService.uploadDocsWithProgress`, using XHR to report multipart progress. The existing `uploadDocs` contract remains available to other callers. Browser credentials use the existing cookie/proxy authentication; AIDP credentials stay server-side.

The frontend proxy sends the body to Nexent's `POST /aidp-mgmt/knowledge-bases/{id}/documents`. FastAPI receives `List[UploadFile]`, validates permissions and files, then `upload_aidp_docs_impl` sends all files to AIDP's `KnowledgeFiles/Upload` endpoint in one request. It returns the existing summary, success_list and failed_list response. No MinIO, ES, persistent upload staging or background job is introduced.

Refreshing the browser can interrupt transfer before Nexent receives the complete body. Once upstream work begins, cancellation cannot reliably withdraw the AIDP operation or recover its result. Therefore browser 100% alone does not enable Confirm. Unmounting the component aborts its browser request; ordinary drawer close is blocked until that request settles.

## Verification on a real AIDP environment

Set `ENABLE_AIDP_KNOWLEDGE=true`, configure `AIDP_SERVER_URL`, `AIDP_API_KEY` and `AIDP_TENANT_ID` for the real environment, restart the services, and use this branch for both frontend and backend. Keep secrets in local environment configuration, outside Git. Existing file/history search and page filters are forwarded to AIDP; the mock service is updated as well.

1. Select multiple supported files together; verify one browser multipart request with repeated `files` parts and the same percentage in each uploading ring.
2. Verify Confirm remains disabled after transfer completes while the response is pending.
3. Check success and failure rows, including a partially successful batch. Confirm becomes available after the response; failed-row Delete sends no request.
4. Confirm closes without uploading again; extraction and indexing may continue in AIDP after upload acceptance. Add a second selection before confirming and check it does not resend previous files.
5. Check a 50-file selection, a long filename/reason and short viewport height: only the list should scroll; footer actions stay visible.

Local component and service tests use mocked responses. They do not establish actual AIDP compatibility, which must be verified against a reachable AIDP environment.
