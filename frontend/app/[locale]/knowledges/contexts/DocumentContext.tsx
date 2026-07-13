"use client";

/**
 * @fileoverview DocumentContext — central state provider for document-level operations.
 *
 * ## Service imports (Approach A — hybrid)
 *
 * This file intentionally imports **both** `unifiedKBService` and
 * `knowledgeBaseService`. This is NOT a migration half-finished:
 *
 *   - `unifiedKBService` handles cross-platform standard document operations:
 *     `listDocuments`, `uploadDocuments`, `deleteDocument`. These route to
 *     `/api/v1/kb/adapters/{id}/...` and work uniformly for local and external KBs.
 *
 *   - `knowledgeBaseService` is retained for the legacy `fetchDocuments` /
 *     `uploadDocuments` / `deleteDocument` methods that are still used by
 *     pre-migration consumers (KBs loaded from old cache that might lack
 *     an `adapter_id`, and by components not yet moved). These call legacy
 *     `/api/file/upload` + `/api/file/process` and
 *     `/api/indices/{id}/documents` routes.
 *
 *   `uploadDocumentsUnified` also falls back to `knowledgeBaseService.getAllFiles`
 *   when `unifiedKBService.listDocuments` fails after an upload, so post-upload
 *   refresh still works for the local adapter in edge cases.
 *
 * The full design rationale lives in `P2-frontend-migration-plan.md`.
 * `knowledgeBaseService` is explicitly **not deprecated** — see its own
 * file header for the list of methods it intentionally retains.
 *
 * ## Future (Approach C)
 *
 * If local-only features later move under `/api/v1/kb/.../ext/*` (see
 * Plan §13), only the URL builder inside `knowledgeBaseService.ts` changes —
 * this file's imports and call sites remain the same.
 */

import {
  createContext,
  useReducer,
  useContext,
  ReactNode,
  useCallback,
  useEffect,
} from "react";
import { useTranslation } from "react-i18next";

import { DOCUMENT_ACTION_TYPES } from "@/const/knowledgeBase";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import unifiedKBService from "@/services/unifiedKBService";
import type { DocumentState, DocumentAction, Document } from "@/types/knowledgeBase";
import type { UnifiedDocument } from "@/types/unifiedKB";
import log from "@/lib/logger";
import { getAuthHeaders } from "@/lib/auth";

// Mapper: UnifiedDocument → legacy Document.
// Used by fetchDocumentsUnified to keep the legacy state shape unchanged.
// Fields without a direct Unified equivalent fall back to defensive defaults.
const mapUnifiedDocumentToLegacy = (
  ud: UnifiedDocument,
  kbId: string
): Document => ({
  id: ud.id,
  kb_id: kbId,
  name: ud.name || ud.id,
  type: "unknown", // UnifiedDocument does not carry a file-type field
  size: ud.size || 0,
  create_time: ud.created_at || "",
  chunk_num: ud.chunk_count || 0,
  token_num: 0, // not available on unified side
  status: ud.status || "unknown",
  latest_task_id: "", // not available on unified side
  error_reason: ud.error_message,
});

// Reducer function
const documentReducer = (
  state: DocumentState,
  action: DocumentAction
): DocumentState => {
  switch (action.type) {
    case DOCUMENT_ACTION_TYPES.FETCH_SUCCESS:
      return {
        ...state,
        documentsMap: {
          ...state.documentsMap,
          [action.payload.kbId]: action.payload.documents,
        },
        isLoadingDocuments: false,
        error: null,
      };
    case DOCUMENT_ACTION_TYPES.SELECT_DOCUMENT:
      // Toggle document selection
      const docId = action.payload;
      const isSelected = state.selectedIds.includes(docId);
      return {
        ...state,
        selectedIds: isSelected
          ? state.selectedIds.filter((id) => id !== docId)
          : [...state.selectedIds, docId],
      };
    case DOCUMENT_ACTION_TYPES.SELECT_DOCUMENTS:
      return {
        ...state,
        selectedIds: action.payload,
      };
    case DOCUMENT_ACTION_TYPES.SELECT_ALL:
      const { kbId, selected } = action.payload;
      const documents = state.documentsMap[kbId] || [];

      // If selected is true, add all document IDs, else remove all
      const newSelectedIds = selected
        ? [
            ...new Set([
              ...state.selectedIds,
              ...documents.map((doc) => doc.id),
            ]),
          ]
        : state.selectedIds.filter(
            (id) => !documents.some((doc) => doc.id === id)
          );

      return {
        ...state,
        selectedIds: newSelectedIds,
      };
    case DOCUMENT_ACTION_TYPES.SET_UPLOAD_FILES:
      return {
        ...state,
        uploadFiles: action.payload,
      };
    case DOCUMENT_ACTION_TYPES.SET_UPLOADING:
      return {
        ...state,
        isUploading: action.payload,
      };
    case DOCUMENT_ACTION_TYPES.SET_LOADING_DOCUMENTS:
      return {
        ...state,
        isLoadingDocuments: action.payload,
      };
    case DOCUMENT_ACTION_TYPES.DELETE_DOCUMENT:
      const { kbId: deleteKbId, docId: deleteDocId } = action.payload;
      // Remove the document from the map and the selected IDs
      return {
        ...state,
        documentsMap: {
          ...state.documentsMap,
          [deleteKbId]:
            state.documentsMap[deleteKbId]?.filter(
              (doc) => doc.id !== deleteDocId
            ) || [],
        },
        selectedIds: state.selectedIds.filter((id) => id !== deleteDocId),
      };
    case DOCUMENT_ACTION_TYPES.SET_LOADING_KB_ID:
      const { kbId: loadingKbId, isLoading } = action.payload;
      const newLoadingKbIds = new Set(state.loadingKbIds);

      if (isLoading) {
        newLoadingKbIds.add(loadingKbId);
      } else {
        newLoadingKbIds.delete(loadingKbId);
      }

      return {
        ...state,
        loadingKbIds: newLoadingKbIds,
      };
    case DOCUMENT_ACTION_TYPES.CLEAR_DOCUMENTS:
      return {
        ...state,
        documentsMap: {},
        selectedIds: [],
        error: null,
      };
    case DOCUMENT_ACTION_TYPES.ERROR:
      return {
        ...state,
        error: action.payload,
        isLoadingDocuments: false,
      };
    default:
      return state;
  }
};

// Create context with default values
export const DocumentContext = createContext<{
  state: DocumentState;
  dispatch: React.Dispatch<DocumentAction>;
  // Standard-document methods. Route through `/api/v1/kb/adapters/{id}/...`
  // when `adapterId` is provided. Missing `adapterId` is treated as a data
  // mapping bug — the call throws instead of silently falling back to the
  // legacy `/api/indices/{id}/files` endpoint, so the upstream source of KB
  // data can be fixed.
  fetchDocuments: (
    kbId: string,
    adapterId?: number,
    opts?: { forceRefresh?: boolean; kbSource?: string }
  ) => Promise<Document[]>;
  uploadDocuments: (
    kbId: string,
    files: File[],
    modelId?: number,
    adapterId?: number
  ) => Promise<void>;
  deleteDocument: (kbId: string, docId: string) => Promise<void>;
  // New unified methods — route through the /api/v1/kb/adapters/{id}/... surface.
  // Each requires an explicit `adapterId` (caller is responsible for obtaining
  // it from the KnowledgeBase object's `adapter_id` field).
  fetchDocumentsUnified: (
    adapterId: number,
    kbId: string,
    opts?: { forceRefresh?: boolean; page?: number; pageSize?: number }
  ) => Promise<void>;
  uploadDocumentsUnified: (
    adapterId: number,
    kbId: string,
    files: File[],
    opts?: { chunking_strategy?: string; metadata?: string }
  ) => Promise<void>;
  deleteDocumentUnified: (
    adapterId: number,
    kbId: string,
    docId: string
  ) => Promise<void>;
}>({
  state: {
    documentsMap: {},
    selectedIds: [],
    uploadFiles: [],
    isUploading: false,
    loadingKbIds: new Set<string>(),
    isLoadingDocuments: false,
    error: null,
  },
  dispatch: () => {},
  fetchDocuments: async () => [],
  uploadDocuments: async () => {},
  deleteDocument: async () => {},
  fetchDocumentsUnified: async () => {},
  uploadDocumentsUnified: async () => {},
  deleteDocumentUnified: async () => {},
});

// Custom hook for using the context
export const useDocumentContext = () => useContext(DocumentContext);

// Provider component
interface DocumentProviderProps {
  children: ReactNode;
}

export const DocumentProvider: React.FC<DocumentProviderProps> = ({
  children,
}) => {
  const { t } = useTranslation();
  const [state, dispatch] = useReducer(documentReducer, {
    documentsMap: {},
    selectedIds: [],
    uploadFiles: [],
    isUploading: false,
    loadingKbIds: new Set<string>(),
    isLoadingDocuments: false,
    error: null,
  });

  // Listen for document update events
  useEffect(() => {
    const handleDocumentsUpdated = (event: Event) => {
      const customEvent = event as CustomEvent;
      if (
        customEvent.detail &&
        customEvent.detail.kbId &&
        customEvent.detail.documents
      ) {
        const { kbId, documents } = customEvent.detail;

        // Update document information directly
        dispatch({
          type: DOCUMENT_ACTION_TYPES.FETCH_SUCCESS,
          payload: { kbId, documents },
        });
      }
    };

    // Add event listener
    window.addEventListener(
      "documentsUpdated",
      handleDocumentsUpdated as EventListener
    );

    // Cleanup function
    return () => {
      window.removeEventListener(
        "documentsUpdated",
        handleDocumentsUpdated as EventListener
      );
    };
  }, []);

  // Fetch documents for a knowledge base through the unified KB surface.
  //
  // `adapterId` is required. A missing value is treated as a data mapping bug
  // (caller should have obtained it from `KnowledgeBase.adapter_id`) and the
  // call rejects with a descriptive error — it does NOT silently fall back to
  // `knowledgeBaseService.getAllFiles`, because that path uses `/api/indices/
  // {numeric_id}/files` which does not work once the real ES index carries a
  // UUID suffix (e.g. "4-6b4730d0..."), and it would hide the upstream bug.
  const fetchDocuments = useCallback(
    async (
      kbId: string,
      adapterId?: number,
      opts: { forceRefresh?: boolean; kbSource?: string } = {}
    ): Promise<Document[]> => {
      // Skip if already loading this kb
      if (state.loadingKbIds.has(kbId)) {
        return state.documentsMap[kbId] || [];
      }

      // If forceRefresh is false and we have cached data, return directly
      if (
        !opts.forceRefresh &&
        state.documentsMap[kbId] &&
        state.documentsMap[kbId].length > 0
      ) {
        return state.documentsMap[kbId];
      }

      // Missing adapter_id is a data bug. Surface it as an error instead of
      // falling back to the legacy interface (which uses a numeric index name
      // and misses the real ES index).
      if (typeof adapterId !== "number") {
        const msg = `KB ${kbId} is missing adapter_id; refusing to call legacy /api/indices endpoint. Check the KB data source so adapter_id is populated.`;
        log.error(msg);
        // Dispatch an error so the UI can surface a hint, and also rethrow
        // so callers can decide whether to refetch / abort.
        dispatch({
          type: DOCUMENT_ACTION_TYPES.ERROR,
          payload: t("document.error.load"),
        });
        throw new Error(msg);
      }

      dispatch({
        type: DOCUMENT_ACTION_TYPES.SET_LOADING_KB_ID,
        payload: { kbId, isLoading: true },
      });

      try {
        const response = await unifiedKBService.listDocuments(
          adapterId,
          kbId,
          { pageSize: 100 }
        );
        const documents = (response.list || []).map((ud) =>
          mapUnifiedDocumentToLegacy(ud, kbId)
        );
        dispatch({
          type: DOCUMENT_ACTION_TYPES.FETCH_SUCCESS,
          payload: { kbId, documents },
        });
        return documents;
      } catch (error) {
        log.error(t("document.error.fetch"), error);
        dispatch({
          type: DOCUMENT_ACTION_TYPES.ERROR,
          payload: t("document.error.load"),
        });
        throw error;
      } finally {
        dispatch({
          type: DOCUMENT_ACTION_TYPES.SET_LOADING_KB_ID,
          payload: { kbId, isLoading: false },
        });
      }
    },
    [state.loadingKbIds, state.documentsMap, t]
  );

  // Upload documents to a knowledge base.
  //
  // The upload itself (multipart POST) continues to go through the legacy
  // `knowledgeBaseService.uploadDocuments` endpoint — that code path is what
  // drives the file→minio→celery pipeline and is not yet replaced by the
  // unified surface. Post-upload refresh, however, is routed through
  // `fetchDocuments(kbId, adapterId)`, which requires a valid `adapterId`.
  // Without an `adapterId`, post-upload refresh will throw a data-bug error.
  const uploadDocuments = useCallback(
    async (
      kbId: string,
      files: File[],
      modelId?: number,
      adapterId?: number
    ) => {
      dispatch({ type: DOCUMENT_ACTION_TYPES.SET_UPLOADING, payload: true });

      try {
        await knowledgeBaseService.uploadDocuments(
          kbId,
          files,
          undefined,
          modelId
        );

        // Set loading state before fetching latest documents
        dispatch({
          type: DOCUMENT_ACTION_TYPES.SET_LOADING_DOCUMENTS,
          payload: true,
        });

        // Get latest status immediately after upload — via unified surface.
        // Throws if adapterId is missing (data mapping bug).
        const latestDocuments = await fetchDocuments(
          kbId,
          adapterId,
          { forceRefresh: true }
        );

        // Trigger document status update event to notify other components
        window.dispatchEvent(
          new CustomEvent("documentsUpdated", {
            detail: {
              kbId,
              documents: latestDocuments,
            },
          })
        );

        // Clear upload files
        dispatch({ type: DOCUMENT_ACTION_TYPES.SET_UPLOAD_FILES, payload: [] });
      } catch (error) {
        log.error(t("document.error.upload"), error);
        dispatch({
          type: DOCUMENT_ACTION_TYPES.ERROR,
          payload: `${t("document.error.upload")}. ${t("document.error.retry")}`,
        });
      } finally {
        dispatch({ type: DOCUMENT_ACTION_TYPES.SET_UPLOADING, payload: false });
        dispatch({
          type: DOCUMENT_ACTION_TYPES.SET_LOADING_DOCUMENTS,
          payload: false,
        });
      }
    },
    [t, fetchDocuments]
  );

  // Delete a document (legacy path, kept for backward compatibility)
  const deleteDocument = useCallback(
    async (kbId: string, docId: string) => {
      try {
        await knowledgeBaseService.deleteDocument(docId, kbId);
        dispatch({
          type: DOCUMENT_ACTION_TYPES.DELETE_DOCUMENT,
          payload: { kbId, docId },
        });
      } catch (error) {
        log.error(t("document.error.delete"), error);
        dispatch({
          type: DOCUMENT_ACTION_TYPES.ERROR,
          payload: `${t("document.error.delete")}. ${t("document.error.retry")}`,
        });
      }
    },
    [t]
  );

  // ---------------------------------------------------------------------------
  // Unified variants — route through /api/v1/kb/adapters/{adapterId}/...
  // ---------------------------------------------------------------------------

  // Fetch documents via the unified KB surface. Maps UnifiedDocument → legacy
  // Document so the state shape (`documentsMap[kbId]: Document[]`) stays stable
  // for any pre-migration consumer.
  const fetchDocumentsUnified = useCallback(
    async (
      adapterId: number,
      kbId: string,
      opts: { forceRefresh?: boolean; page?: number; pageSize?: number } = {}
    ) => {
      if (state.loadingKbIds.has(kbId)) return;

      if (
        !opts.forceRefresh &&
        state.documentsMap[kbId] &&
        state.documentsMap[kbId].length > 0
      ) {
        return;
      }

      dispatch({
        type: DOCUMENT_ACTION_TYPES.SET_LOADING_KB_ID,
        payload: { kbId, isLoading: true },
      });

      try {
        const response = await unifiedKBService.listDocuments(
          adapterId,
          kbId,
          { page: opts.page ?? 1, pageSize: opts.pageSize ?? 20 }
        );
        const documents = (response.list || []).map((ud) =>
          mapUnifiedDocumentToLegacy(ud, kbId)
        );
        dispatch({
          type: DOCUMENT_ACTION_TYPES.FETCH_SUCCESS,
          payload: { kbId, documents },
        });
      } catch (error) {
        log.error(t("document.error.fetch"), error);
        dispatch({
          type: DOCUMENT_ACTION_TYPES.ERROR,
          payload: t("document.error.load"),
        });
      } finally {
        dispatch({
          type: DOCUMENT_ACTION_TYPES.SET_LOADING_KB_ID,
          payload: { kbId, isLoading: false },
        });
      }
    },
    [state.loadingKbIds, state.documentsMap, t]
  );

  // Upload documents via the unified KB surface, then refresh the document
  // list via the same unified surface (`listDocuments`). Maps the returned
  // `UnifiedDocument[]` back to legacy `Document[]` so the dispatched
  // `documentsUpdated` event keeps its historical payload shape.
  //
  // Post-upload refresh does NOT fall back to `knowledgeBaseService.getAllFiles` —
  // the unified call is authoritative for this path. If refresh fails the
  // upload is still considered successful (the file is already persisted
  // server-side) but the user must manually refresh to see the updated list.
  const uploadDocumentsUnified = useCallback(
    async (
      adapterId: number,
      kbId: string,
      files: File[],
      opts: { chunking_strategy?: string; metadata?: string } = {}
    ) => {
      dispatch({ type: DOCUMENT_ACTION_TYPES.SET_UPLOADING, payload: true });

      try {
        // Multipart/form-data is required by FastAPI's File(...)/Form(...) signature.
        // JSON.stringify(files) produces empty braces, so a JSON body is always
        // rejected with 422. Build FormData explicitly.
        //
        // CRITICAL: Do NOT pass `Content-Type` in headers. Fetch needs to set
        // it automatically to "multipart/form-data; boundary=..." when the body
        // is FormData. Passing "application/json" (from getAuthHeaders()) makes
        // FastAPI fail with 422 Unprocessable Entity because it tries to parse
        // a multipart byte-stream as JSON and cannot find the `files` field.
        const { "Content-Type": _drop, ...authHeadersWithoutContentType } = getAuthHeaders();
        const formData = new FormData();
        for (const file of files) {
          formData.append("files", file);
        }
        if (opts.chunking_strategy) {
          formData.append("chunking_strategy", opts.chunking_strategy);
        }
        if (opts.metadata) {
          formData.append("metadata", opts.metadata);
        }
        const uploadResponse = await fetch(
          `/api/v1/kb/adapters/${adapterId}/knowledge-bases/${kbId}/documents`,
          {
            method: "POST",
            headers: authHeadersWithoutContentType,
            body: formData,
          },
        );
        if (!uploadResponse.ok) {
          const text = await uploadResponse.text().catch(() => "");
          throw new Error(
            `Upload failed: HTTP ${uploadResponse.status} ${text || uploadResponse.statusText}`
          );
        }

        dispatch({
          type: DOCUMENT_ACTION_TYPES.SET_LOADING_DOCUMENTS,
          payload: true,
        });

        // Refresh via unified listDocuments — same namespace as the upload.
        // Do NOT silently fall back to legacy `getAllFiles`: the unified call
        // is expected to be authoritative. If it fails, surface the failure —
        // upload still succeeds (file is already persisted server-side) but
        // the user must manually refresh to see the updated list.
        let latestDocuments: Document[];
        try {
          const response = await unifiedKBService.listDocuments(
            adapterId,
            kbId,
            { pageSize: 100 }
          );
          latestDocuments = (response.list || []).map((ud) =>
            mapUnifiedDocumentToLegacy(ud, kbId)
          );
        } catch (refreshErr) {
          log.error(
            `unified listDocuments refresh failed for kb ${kbId} after upload:`,
            refreshErr
          );
          dispatch({
            type: DOCUMENT_ACTION_TYPES.ERROR,
            payload: t("document.error.load"),
          });
          // Keep the previous document list rather than silently loading
          // from the legacy `/api/indices/{id}/files` path.
          latestDocuments = state.documentsMap[kbId] || [];
        }

        dispatch({
          type: DOCUMENT_ACTION_TYPES.FETCH_SUCCESS,
          payload: { kbId, documents: latestDocuments },
        });

        window.dispatchEvent(
          new CustomEvent("documentsUpdated", {
            detail: { kbId, documents: latestDocuments },
          })
        );

        dispatch({ type: DOCUMENT_ACTION_TYPES.SET_UPLOAD_FILES, payload: [] });
      } catch (error) {
        log.error(t("document.error.upload"), error);
        dispatch({
          type: DOCUMENT_ACTION_TYPES.ERROR,
          payload: `${t("document.error.upload")}. ${t("document.error.retry")}`,
        });
      } finally {
        dispatch({ type: DOCUMENT_ACTION_TYPES.SET_UPLOADING, payload: false });
        dispatch({
          type: DOCUMENT_ACTION_TYPES.SET_LOADING_DOCUMENTS,
          payload: false,
        });
      }
    },
    [t]
  );

  // Delete a document via the unified KB surface.
  const deleteDocumentUnified = useCallback(
    async (adapterId: number, kbId: string, docId: string) => {
      try {
        await unifiedKBService.deleteDocument(adapterId, kbId, docId);
        dispatch({
          type: DOCUMENT_ACTION_TYPES.DELETE_DOCUMENT,
          payload: { kbId, docId },
        });
      } catch (error) {
        log.error(t("document.error.delete"), error);
        dispatch({
          type: DOCUMENT_ACTION_TYPES.ERROR,
          payload: `${t("document.error.delete")}. ${t("document.error.retry")}`,
        });
      }
    },
    [t]
  );

  return (
    <DocumentContext.Provider
      value={{
        state,
        dispatch,
        fetchDocuments,
        uploadDocuments,
        deleteDocument,
        fetchDocumentsUnified,
        uploadDocumentsUnified,
        deleteDocumentUnified,
      }}
    >
      {children}
    </DocumentContext.Provider>
  );
};
