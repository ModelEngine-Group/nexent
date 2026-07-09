"use client";

/**
 * @fileoverview KnowledgeBaseContext — central state provider for KB pages.
 *
 * ## Service imports (Approach A — hybrid)
 *
 * This file intentionally imports **both** `unifiedKBService` and
 * `knowledgeBaseService`. This is NOT a migration half-finished:
 *
 *   - `unifiedKBService` handles cross-platform standard operations
 *     (listAllKnowledgeBases, createKnowledgeBase, deleteKnowledgeBase,
 *     listDocuments). These work uniformly across local and external KBs.
 *
 *   - `knowledgeBaseService` is retained for two narrow, legitimate purposes:
 *       1. Enriching the unified KB list with local-only metadata fields
 *          (`summaryFrequency`, `lastSummaryTime`, `preserve_source_file`,
 *          `ingroup_permission`, `group_ids`) that `UnifiedKnowledgeBase`
 *          does not carry yet — see `_fetchAllKbsUnified`.
 *       2. `syncDataMateAndCreateRecords()` (DataMate sync) — still served
 *          by legacy `/api/datamate/*` routes.
 *       3. Fallback `getAllFiles()` for KBs missing `adapter_id` (only
 *          reachable with stale cache state) — see `_refreshActiveDocuments`.
 *
 * The full design rationale lives in `P2-frontend-migration-plan.md`
 * (§9.4 "Dual-import hygiene"). `knowledgeBaseService` is explicitly
 * **not deprecated** — see its own file header.
 *
 * ## Future (Approach C)
 *
 * If local-only features later move under `/api/v1/kb/.../ext/*` (see
 * Plan §13), only the URL builder inside `knowledgeBaseService.ts`
 * changes — this file's imports and call sites remain the same.
 */

import {
  createContext,
  useReducer,
  useEffect,
  useContext,
  ReactNode,
  useCallback,
  useMemo,
} from "react";
import { useTranslation } from "react-i18next";

import knowledgeBaseService from "@/services/knowledgeBaseService";
import unifiedKBService from "@/services/unifiedKBService";
import type { UnifiedAdapter, UnifiedKnowledgeBase } from "@/types/unifiedKB";

import {
  KnowledgeBase,
  KnowledgeBaseState,
  KnowledgeBaseAction,
  DataMateSyncError,
} from "@/types/knowledgeBase";
import { KNOWLEDGE_BASE_ACTION_TYPES } from "@/const/knowledgeBase";

import { useConfig } from "@/hooks/useConfig";
import log from "@/lib/logger";

// =============================================================================
// Module-level helpers
// =============================================================================

/**
 * Map a UnifiedKnowledgeBase (cross-platform shape from unifiedKBService) +
 * optional legacy metadata (from knowledgeBaseService.getKnowledgeBasesInfo)
 * into the legacy KnowledgeBase shape that all existing components expect.
 *
 * Under Approach A, the unified API carries only cross-platform fields
 * (name, document_count, chunk_count, embedding_model, adapter_id, ...).
 * Local-only fields like `summaryFrequency`, `lastSummaryTime`,
 * `preserve_source_file`, `ingroup_permission`, etc. are merged in from the
 * legacy metadata fetch.
 */
const buildKbFromUnified = (
  unified: UnifiedKnowledgeBase,
  legacyMeta: Partial<KnowledgeBase> | undefined
): KnowledgeBase => {
  const metadata = (unified.metadata ?? {}) as Record<string, unknown>;
  return {
    id: String(unified.knowledge_base_id),
    name: unified.name,
    index_name: (metadata.index_name as string) || String(unified.knowledge_base_id),
    display_name: unified.name,
    description: unified.description ?? null,
    documentCount: unified.document_count || 0,
    chunkCount: unified.chunk_count || 0,
    createdAt: (metadata.create_time as string) ?? null,
    updatedAt: (metadata.update_time as string) ?? null,
    embeddingModel: unified.embedding_model || "unknown",
    avatar: "",
    chunkNum: 0,
    language: "",
    nickname: "",
    parserId: "",
    permission: legacyMeta?.permission || "",
    tokenNum: 0,
    source: unified.platform || "nexent",
    tenant_id: (metadata.tenant_id as string) ?? undefined,
    adapter_id: unified.adapter_id,
    adapter_name: unified.adapter_name,
    // Local-only fields enriched from legacy metadata (only present for local KBs)
    summaryFrequency: legacyMeta?.summaryFrequency ?? null,
    lastSummaryTime: legacyMeta?.lastSummaryTime ?? null,
    is_multimodal: legacyMeta?.is_multimodal ?? false,
    preserve_source_file: legacyMeta?.preserve_source_file ?? true,
    knowledge_sources: legacyMeta?.knowledge_sources ?? undefined,
    ingroup_permission: legacyMeta?.ingroup_permission ?? "",
    group_ids: legacyMeta?.group_ids ?? [],
    store_size: legacyMeta?.store_size ?? "",
    process_source: legacyMeta?.process_source ?? "",
  };
};

/**
 * Empty legacy metadata bucket — used when `getKnowledgeBasesInfo` fails so
 * the unified-path mapping still proceeds (just without local-only enrichment).
 */
const emptyLegacyMeta = () => ({
  knowledgeBases: [] as KnowledgeBase[],
  dataMateSyncError: undefined as string | undefined,
});

// Reducer function
const knowledgeBaseReducer = (
  state: KnowledgeBaseState,
  action: KnowledgeBaseAction
): KnowledgeBaseState => {
  switch (action.type) {
    case KNOWLEDGE_BASE_ACTION_TYPES.FETCH_SUCCESS:
      return {
        ...state,
        knowledgeBases: action.payload,
        error: null,
      };
    case KNOWLEDGE_BASE_ACTION_TYPES.SELECT_KNOWLEDGE_BASE:
      return {
        ...state,
        selectedIds: action.payload,
      };
    case KNOWLEDGE_BASE_ACTION_TYPES.SET_ACTIVE:
      return {
        ...state,
        activeKnowledgeBase: action.payload,
      };
    case KNOWLEDGE_BASE_ACTION_TYPES.SET_MODEL:
      return {
        ...state,
        currentEmbeddingModel: action.payload,
      };
    case KNOWLEDGE_BASE_ACTION_TYPES.DELETE_KNOWLEDGE_BASE:
      return {
        ...state,
        knowledgeBases: state.knowledgeBases.filter(
          (kb) => kb.id !== action.payload
        ),
        selectedIds: state.selectedIds.filter((id) => id !== action.payload),
        activeKnowledgeBase:
          state.activeKnowledgeBase?.id === action.payload
            ? null
            : state.activeKnowledgeBase,
      };
    case KNOWLEDGE_BASE_ACTION_TYPES.ADD_KNOWLEDGE_BASE:
      if (state.knowledgeBases.some((kb) => kb.id === action.payload.id)) {
        return state; // If the knowledge base already exists, do not insert it
      }
      return {
        ...state,
        knowledgeBases: [...state.knowledgeBases, action.payload],
      };
    case KNOWLEDGE_BASE_ACTION_TYPES.UPDATE_KNOWLEDGE_BASE:
      return {
        ...state,
        knowledgeBases: state.knowledgeBases.map((kb) =>
          kb.id === action.payload.id ? action.payload : kb
        ),
      };
    case KNOWLEDGE_BASE_ACTION_TYPES.LOADING:
      return {
        ...state,
        isLoading: action.payload,
      };
    case KNOWLEDGE_BASE_ACTION_TYPES.SET_SYNC_LOADING:
      return {
        ...state,
        syncLoading: action.payload,
      };
    case KNOWLEDGE_BASE_ACTION_TYPES.SET_DATA_MATE_SYNC_ERROR:
      return {
        ...state,
        dataMateSyncError: action.payload,
      };
    case KNOWLEDGE_BASE_ACTION_TYPES.ERROR:
      return {
        ...state,
        error: action.payload,
      };
    default:
      return state;
  }
};

// Create context with default values
export const KnowledgeBaseContext = createContext<{
  state: KnowledgeBaseState;
  dispatch: React.Dispatch<KnowledgeBaseAction>;
  fetchKnowledgeBases: (
    skipHealthCheck?: boolean,
    shouldLoadSelected?: boolean
  ) => Promise<void>;
  createKnowledgeBase: (
    name: string,
    description: string,
    source?: string,
    ingroup_permission?: string,
    group_ids?: number[],
    embeddingModel?: string,
    is_multimodal?: boolean,
    preserve_source_file?: boolean
  ) => Promise<KnowledgeBase | null>;
  deleteKnowledgeBase: (id: string) => Promise<boolean>;
  selectKnowledgeBase: (id: string) => void;
  setActiveKnowledgeBase: (kb: KnowledgeBase | null) => void;
  updateKnowledgeBase: (kb: KnowledgeBase) => void;
  isKnowledgeBaseSelectable: (kb: KnowledgeBase) => boolean;
  hasKnowledgeBaseModelMismatch: (kb: KnowledgeBase) => boolean;
  refreshKnowledgeBaseData: (forceRefresh?: boolean) => Promise<void>;
  refreshKnowledgeBaseDataWithDataMate: () => Promise<void>;
}>({
  state: {
    knowledgeBases: [],
    selectedIds: [],
    activeKnowledgeBase: null,
    currentEmbeddingModel: null,
    currentMultiEmbeddingModel: null,
    isLoading: false,
    syncLoading: false,
    error: null,
  },
  dispatch: () => {},
  fetchKnowledgeBases: async () => {},
  createKnowledgeBase: async () => null,
  deleteKnowledgeBase: async () => false,
  selectKnowledgeBase: () => {},
  setActiveKnowledgeBase: () => {},
  updateKnowledgeBase: () => {},
  isKnowledgeBaseSelectable: () => false,
  hasKnowledgeBaseModelMismatch: () => false,
  refreshKnowledgeBaseData: async () => {},
  refreshKnowledgeBaseDataWithDataMate: async () => {},
});

// Custom hook for using the context
export const useKnowledgeBaseContext = () => useContext(KnowledgeBaseContext);

// Provider component
interface KnowledgeBaseProviderProps {
  children: ReactNode;
}

export const KnowledgeBaseProvider: React.FC<KnowledgeBaseProviderProps> = ({
  children,
}) => {
  const { t } = useTranslation();
  const { appConfig, modelConfig } = useConfig();
  const [state, dispatch] = useReducer(knowledgeBaseReducer, {
    knowledgeBases: [],
    selectedIds: [],
    activeKnowledgeBase: null,
    currentEmbeddingModel: null,
    currentMultiEmbeddingModel: null,
    isLoading: false,
    syncLoading: false,
    error: null,
    dataMateSyncError: undefined,
  });

  // Check if knowledge base is selectable - memoized with useCallback
  const isKnowledgeBaseSelectable = useCallback(
    (kb: KnowledgeBase): boolean => {
      // Check if knowledge base has content (documents or chunks)
      const hasContent =
        (kb.documentCount || 0) > 0 || (kb.chunkCount || 0) > 0;

      // Empty knowledge bases cannot be selected
      if (!hasContent) {
        return false;
      }

      // DataMate knowledge bases are selectable if they have content (even if model doesn't match)
      if (kb.source === "datamate") {
        return true;
      }

      if (kb.embeddingModel === "unknown") {
        return true;
      }

      const currentEmbeddingModel = state.currentEmbeddingModel?.trim() || "";
      const currentMultiEmbeddingModel =
        modelConfig?.multiEmbedding?.modelName?.trim() || "";

      if (kb.is_multimodal) {
        // Multimodal KB is selectable as long as current multimodal model is configured.
        return !!currentMultiEmbeddingModel;
      }

      // Text KB is selectable as long as current embedding model is configured.
      return !!currentEmbeddingModel;
    },
    [modelConfig?.multiEmbedding?.modelName, state.currentEmbeddingModel]
  );

  // Check if knowledge base has model mismatch (for display purposes)
  const hasKnowledgeBaseModelMismatch = useCallback(
    (kb: KnowledgeBase): boolean => {
      if (kb.embeddingModel === "unknown") {
        return false;
      }
      if (kb.source === "datamate") {
        return false;
      }

      if (kb.is_multimodal) {
        const multiEmbeddingModel =
          modelConfig?.multiEmbedding?.modelName?.trim() || "";
        // Only show warning when the required current model is not configured.
        return !multiEmbeddingModel;
      }

      // Only show warning when the required current model is not configured.
      return !state.currentEmbeddingModel;
    },
    [modelConfig?.multiEmbedding?.modelName, state.currentEmbeddingModel]
  );

  // ---------------------------------------------------------------------------
  // Private inner helpers (Approach A)
  //
  // Under Approach A, the cross-platform KB list fetches go through
  // unifiedKBService.listAllKnowledgeBases() and the legacy
  // knowledgeBaseService is kept in parallel ONLY to enrich the list with
  // local-only metadata (summaryFrequency, lastSummaryTime,
  // preserve_source_file, ingroup_permission, group_ids, etc.) that doesn't
  // exist on UnifiedKnowledgeBase yet.
  // ---------------------------------------------------------------------------

  /**
   * Core unified fetch: pulls the cross-platform KB list, enriches with legacy
   * metadata, optionally triggers DataMate sync, and returns the mapped
   * KnowledgeBase[] plus any DataMate error.
   *
   * Both legacy and DataMate calls are wrapped in `.catch()` so a partial
   * failure doesn't drop the unified list.
   */
  const _fetchAllKbsUnified = useCallback(
    async (
      includeDataMateSync: boolean
    ): Promise<{
      mapped: KnowledgeBase[];
      dataMateSyncError: string | undefined;
    }> => {
      // 1. Parallel fetch: unified list + legacy local metadata.
      const [unified, legacyMeta] = await Promise.all([
        unifiedKBService.listAllKnowledgeBases().catch((err) => {
          log.warn("listAllKnowledgeBases failed:", err);
          return { list: [], total: 0 } as Awaited<
            ReturnType<typeof unifiedKBService.listAllKnowledgeBases>
          >;
        }),
        knowledgeBaseService
          .getKnowledgeBasesInfo(true, false)
          .catch((err) => {
            log.warn(
              "legacy metadata fetch failed (continuing without summary fields):",
              err
            );
            return emptyLegacyMeta();
          }),
      ]);

      // 2. Build lookup keyed by kb_id (legacy stores id === index_name,
      //    which for local KBs matches knowledge_base_id).
      const metaById = new Map<string, KnowledgeBase>();
      legacyMeta.knowledgeBases.forEach((kb) => metaById.set(kb.id, kb));

      // 3. Map UnifiedKnowledgeBase → legacy KnowledgeBase shape, enriched
      //    with local-only metadata from the legacy fetch when available.
      const mapped: KnowledgeBase[] = unified.list.map((unifiedKb) => {
        const legacyKb = metaById.get(String(unifiedKb.knowledge_base_id));
        return buildKbFromUnified(unifiedKb, legacyKb);
      });

      // 4. DataMate sync (only when caller opts in and datamateUrl is configured).
      let dataMateSyncError: string | undefined;
      if (includeDataMateSync) {
        const datamateUrl = appConfig?.datamateUrl ?? null;
        if (datamateUrl && datamateUrl.trim() !== "") {
          try {
            const syncResult =
              await knowledgeBaseService.syncDataMateAndCreateRecords();
            if (syncResult.indices_info) {
              const datamateRecords: KnowledgeBase[] = syncResult.indices_info.map(
                (indexInfo: any) => {
                  const stats = indexInfo.stats?.base_info || {};
                  return {
                    id: String(indexInfo.name),
                    name: indexInfo.display_name || indexInfo.name,
                    index_name: String(indexInfo.name),
                    display_name: indexInfo.display_name || indexInfo.name,
                    description: "DataMate knowledge base",
                    documentCount: stats.doc_count || 0,
                    chunkCount: stats.chunk_count || 0,
                    createdAt: stats.creation_date || null,
                    updatedAt:
                      stats.update_date || stats.creation_date || null,
                    embeddingModel: stats.embedding_model || "unknown",
                    avatar: "",
                    chunkNum: 0,
                    language: "",
                    nickname: "",
                    parserId: "",
                    permission: "",
                    tokenNum: 0,
                    source: "datamate",
                    tenant_id: indexInfo.tenant_id || "",
                  };
                }
              );
              // Merge DataMate-only KBs, avoiding duplicates by id
              const existingIds = new Set(mapped.map((k) => k.id));
              datamateRecords.forEach((dm) => {
                if (!existingIds.has(dm.id)) mapped.push(dm);
              });
            }
          } catch (e) {
            dataMateSyncError = e instanceof Error ? e.message : String(e);
            log.error("Failed to sync DataMate knowledge bases:", e);
          }
        } else {
          log.info(
            "DataMate URL not configured, skipping DataMate knowledge base sync"
          );
        }
      }

      return { mapped, dataMateSyncError };
    },
    [appConfig?.datamateUrl]
  );

  /**
   * Refresh the active KB's document list via the unified surface.
   *
   * Phase 4 (Approach A): replaces legacy `knowledgeBaseService.getAllFiles`.
   * Uses `unifiedKBService.listDocuments` when the active KB carries an
   * `adapter_id`; the legacy `getAllFiles` is kept as a fallback for KBs
   * loaded from a pre-migration cache that might be missing `adapter_id`.
   *
   * Maps `UnifiedDocument[]` back to the legacy `Document[]` shape so that
   * the dispatched `documentsUpdated` event continues to carry the same
   * payload that existing consumers expect.
   */
  const _refreshActiveDocuments = useCallback(
    async (activeKnowledgeBase: KnowledgeBase) => {
      try {
        const adapterId = activeKnowledgeBase.adapter_id;
        let documents: import("@/types/knowledgeBase").Document[];

        if (typeof adapterId === "number") {
          const response = await unifiedKBService.listDocuments(
            adapterId,
            activeKnowledgeBase.id,
            { pageSize: 1000 }
          );
          documents = (response.list || []).map((ud) => ({
            id: ud.id,
            kb_id: activeKnowledgeBase.id,
            name: ud.name || ud.id,
            type: ud.type || "unknown",
            size: ud.size || 0,
            create_time: ud.created_at || "",
            chunk_num: ud.chunk_count || 0,
            token_num: 0,
            status: ud.status || "unknown",
            latest_task_id: "",
            error_reason: ud.error_message,
          }));
        } else {
          // Stale-state KB or one loaded from pre-migration cache — fall back
          // to legacy. Phase 5 (component-level) will eventually eliminate
          // these paths entirely.
          log.warn(
            `KB ${activeKnowledgeBase.id} has no adapter_id; falling back to legacy getAllFiles for document refresh`
          );
          documents = await knowledgeBaseService.getAllFiles(
            activeKnowledgeBase.id,
            activeKnowledgeBase.source
          );
        }

        log.log("documents", documents);
        window.dispatchEvent(
          new CustomEvent("documentsUpdated", {
            detail: {
              kbId: activeKnowledgeBase.id,
              documents,
            },
          })
        );
      } catch (error) {
        log.error("Failed to refresh document information:", error);
      }
    },
    []
  );

  // Load knowledge base data (supports force fetch from server and load selected status) - optimized with useCallback
  const fetchKnowledgeBases = useCallback(
    async (
      skipHealthCheck = true,
      shouldLoadSelected = true,
      includeDataMateSync = true
    ) => {
      // If already loading, return directly
      if (state.isLoading) {
        return;
      }

      dispatch({ type: KNOWLEDGE_BASE_ACTION_TYPES.LOADING, payload: true });
      // Clear previous DataMate sync error
      dispatch({
        type: KNOWLEDGE_BASE_ACTION_TYPES.SET_DATA_MATE_SYNC_ERROR,
        payload: undefined,
      });
      try {
        // Clear possible cache interference
        localStorage.removeItem("preloaded_kb_data");
        localStorage.removeItem("kb_cache");

        const { mapped, dataMateSyncError } = await _fetchAllKbsUnified(
          includeDataMateSync
        );

        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.FETCH_SUCCESS,
          payload: mapped,
        });

        // Set DataMate sync error if present and throw to trigger error handling
        if (dataMateSyncError) {
          dispatch({
            type: KNOWLEDGE_BASE_ACTION_TYPES.SET_DATA_MATE_SYNC_ERROR,
            payload: dataMateSyncError,
          });
          // Throw DataMateSyncError to signal failure to the caller
          throw new DataMateSyncError(dataMateSyncError);
        }
      } catch (error) {
        // Check if it's a DataMate sync error
        if (error instanceof DataMateSyncError) {
          // Re-throw DataMateSyncError to be handled by the caller
          throw error;
        }
        log.error(t("knowledgeBase.error.fetchList"), error);
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.ERROR,
          payload: t("knowledgeBase.error.fetchListRetry"),
        });
      } finally {
        dispatch({ type: KNOWLEDGE_BASE_ACTION_TYPES.LOADING, payload: false });
      }
    },
    [state.isLoading, t, _fetchAllKbsUnified]
  );

  // Select knowledge base - memoized with useCallback
  const selectKnowledgeBase = useCallback(
    (id: string) => {
      const kb = state.knowledgeBases.find((kb) => kb.id === id);
      if (!kb) return;

      const isSelected = state.selectedIds.includes(id);

      // If trying to select an item, check for model compatibility. Deselection is always allowed.
      if (!isSelected && !isKnowledgeBaseSelectable(kb)) {
        log.warn(`Cannot select knowledge base ${kb.name}, model mismatch`);
        return;
      }

      // Toggle selection status
      const newSelectedIds = isSelected
        ? state.selectedIds.filter((kbId) => kbId !== id)
        : [...state.selectedIds, id];

      // Update state
      dispatch({
        type: KNOWLEDGE_BASE_ACTION_TYPES.SELECT_KNOWLEDGE_BASE,
        payload: newSelectedIds,
      });

      // Note: removed logic for saving selection status to config
      // This feature is no longer needed as we don't store data config
    },
    [state.knowledgeBases, state.selectedIds, isKnowledgeBaseSelectable]
  );

  // Set current active knowledge base - memoized with useCallback
  const setActiveKnowledgeBase = useCallback((kb: KnowledgeBase | null) => {
    dispatch({ type: KNOWLEDGE_BASE_ACTION_TYPES.SET_ACTIVE, payload: kb });
  }, []);

  // Update knowledge base in list - memoized with useCallback
  const updateKnowledgeBase = useCallback((kb: KnowledgeBase) => {
    dispatch({ type: KNOWLEDGE_BASE_ACTION_TYPES.UPDATE_KNOWLEDGE_BASE, payload: kb });
  }, []);

  // Create knowledge base - memoized with useCallback
  const createKnowledgeBase = useCallback(
    async (
      name: string,
      description: string,
      source: string = "elasticsearch",
      ingroup_permission?: string,
      group_ids?: number[],
      embeddingModel?: string,
      is_multimodal?: boolean,
      preserve_source_file?: boolean
    ) => {
      try {
        // Resolve embedding model from model config
        const selectedEmbeddingModel = embeddingModel?.trim() || "";
        const defaultMultiEmbeddingModel =
          modelConfig?.multiEmbedding?.modelName?.trim() || "";
        const resolvedIsMultimodal =
          typeof is_multimodal === "boolean"
            ? is_multimodal
            : !!defaultMultiEmbeddingModel &&
              selectedEmbeddingModel === defaultMultiEmbeddingModel;
        const fallbackEmbeddingModel = resolvedIsMultimodal
          ? defaultMultiEmbeddingModel
          : state.currentEmbeddingModel || "";
        const resolvedEmbeddingModel =
          selectedEmbeddingModel || fallbackEmbeddingModel;

        // Get local adapter ID
        const adaptersResponse = await unifiedKBService.listAdapters();
        const localAdapter = adaptersResponse.list.find(
          (a: UnifiedAdapter) => a.platform === "local"
        );
        if (!localAdapter) {
          throw new Error("Local adapter not found");
        }

        // Create knowledge base via unified service
        // Backend LocalKBAdapter.create_knowledge_base() accepts:
        //   extra = { embedding_model, ingroup_permission, group_ids, is_multimodal, preserve_source_file }
        const unifiedKB = await unifiedKBService.createKnowledgeBase(
          localAdapter.adapter_id,
          {
            name,
            description,
            extra: {
              embedding_model: resolvedEmbeddingModel,
              ingroup_permission,
              group_ids,
              is_multimodal: resolvedIsMultimodal,
              preserve_source_file,
            },
          }
        );

        // Map UnifiedKnowledgeBase → legacy KnowledgeBase (must supply all required fields).
        const newKB: KnowledgeBase = {
          id: unifiedKB.knowledge_base_id,
          name: unifiedKB.name,
          description: unifiedKB.description || "",
          chunkCount: unifiedKB.chunk_count || 0,
          documentCount: unifiedKB.document_count || 0,
          createdAt: null,
          avatar: "",
          chunkNum: 0,
          language: "",
          nickname: "",
          parserId: "",
          permission: "",
          tokenNum: 0,
          source: unifiedKB.platform || source,
          embeddingModel: unifiedKB.embedding_model || resolvedEmbeddingModel,
          is_multimodal: resolvedIsMultimodal,
          adapter_id: unifiedKB.adapter_id,
          adapter_name: unifiedKB.adapter_name,
        };
        return newKB;
      } catch (error) {
        log.error(t("knowledgeBase.error.create"), error);
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.ERROR,
          payload: t("knowledgeBase.error.createRetry"),
        });
        return null;
      }
    },
    [modelConfig?.multiEmbedding?.modelName, state.currentEmbeddingModel, t]
  );

  // Delete knowledge base - memoized with useCallback
  const deleteKnowledgeBase = useCallback(
    async (id: string) => {
      try {
        // Look up the KB in local state to get its adapter_id.
        // All KBs (local + external) should carry adapter_id after fetchKnowledgeBases.
        const kb = state.knowledgeBases.find((k) => k.id === id);
        if (kb && typeof kb.adapter_id === "number") {
          await unifiedKBService.deleteKnowledgeBase(kb.adapter_id, id);
        } else {
          // Fallback to legacy path - should only trigger if state is stale
          // or the KB was loaded from a pre-migration cache.
          log.warn(
            `KB ${id} has no adapter_id in local state; falling back to legacy deleteKnowledgeBase`
          );
          await knowledgeBaseService.deleteKnowledgeBase(id);
        }

        // Update knowledge base list
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.DELETE_KNOWLEDGE_BASE,
          payload: id,
        });

        // If current active knowledge base is deleted, clear active state
        if (state.activeKnowledgeBase?.id === id) {
          dispatch({
            type: KNOWLEDGE_BASE_ACTION_TYPES.SET_ACTIVE,
            payload: null,
          });
        }

        // Update selected knowledge base list
        const newSelectedIds = state.selectedIds.filter((kbId) => kbId !== id);

        if (newSelectedIds.length !== state.selectedIds.length) {
          // Update state
          dispatch({
            type: KNOWLEDGE_BASE_ACTION_TYPES.SELECT_KNOWLEDGE_BASE,
            payload: newSelectedIds,
          });
        }

        return true;
      } catch (error) {
        log.error(t("knowledgeBase.error.delete"), error);
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.ERROR,
          payload: t("knowledgeBase.error.deleteRetry"),
        });
        return false;
      }
    },
    [state.knowledgeBases, state.selectedIds, state.activeKnowledgeBase, t]
  );

  // Refresh knowledge base data (no DataMate sync — used for background refreshes).
  // Uses unified KB list + legacy metadata enrichment via _fetchAllKbsUnified.
  const refreshKnowledgeBaseData = useCallback(
    async (forceRefresh = false) => {
      try {
        const { mapped, dataMateSyncError } = await _fetchAllKbsUnified(false);

        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.FETCH_SUCCESS,
          payload: mapped,
        });

        if (dataMateSyncError) {
          dispatch({
            type: KNOWLEDGE_BASE_ACTION_TYPES.SET_DATA_MATE_SYNC_ERROR,
            payload: dataMateSyncError,
          });
        }

        // If there is an active knowledge base, also refresh its document information
        if (state.activeKnowledgeBase) {
          await _refreshActiveDocuments(state.activeKnowledgeBase);
        }
      } catch (error) {
        log.error("Failed to refresh knowledge base data:", error);
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.ERROR,
          payload: "Failed to refresh knowledge base data",
        });
      }
    },
    [state.activeKnowledgeBase, _fetchAllKbsUnified, _refreshActiveDocuments]
  );

  // Refresh knowledge base data AND trigger DataMate sync.
  // Uses unified KB list + legacy DataMate sync via _fetchAllKbsUnified.
  // Throws DataMateSyncError on DataMate failure so callers can react.
  const refreshKnowledgeBaseDataWithDataMate = useCallback(async () => {
    try {
      const { mapped, dataMateSyncError } = await _fetchAllKbsUnified(true);

      dispatch({
        type: KNOWLEDGE_BASE_ACTION_TYPES.FETCH_SUCCESS,
        payload: mapped,
      });

      // Handle DataMate sync error
      if (dataMateSyncError) {
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.SET_DATA_MATE_SYNC_ERROR,
          payload: dataMateSyncError,
        });
        // Throw DataMateSyncError to signal failure to the caller
        throw new DataMateSyncError(dataMateSyncError);
      }

      // If there is an active knowledge base, also refresh its document information
      if (state.activeKnowledgeBase) {
        await _refreshActiveDocuments(state.activeKnowledgeBase);
      }
    } catch (error) {
      // Check if it's a DataMate sync error - re-throw to be handled by caller
      if (error instanceof DataMateSyncError) {
        throw error;
      }
      log.error("Failed to refresh knowledge base data with DataMate:", error);
      dispatch({
        type: KNOWLEDGE_BASE_ACTION_TYPES.ERROR,
        payload: "Failed to refresh knowledge base data with DataMate",
      });
    }
  }, [state.activeKnowledgeBase, _fetchAllKbsUnified, _refreshActiveDocuments]);

  // Initial data loading - with optimized dependencies
  useEffect(() => {
    // Use ref to track if data has been loaded to avoid duplicate loading
    let initialDataLoaded = false;

    // Get current model config at initial load
    const loadInitialData = async () => {
      if (modelConfig?.embedding?.modelName) {
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.SET_MODEL,
          payload: modelConfig.embedding.modelName,
        });
      }

      // Don't load knowledge base list here, wait for knowledgeBaseDataUpdated event
    };

    loadInitialData();

    // Listen for embedding model change event
    const handleEmbeddingModelChange = (e: CustomEvent) => {
      const newModel = e.detail.model || null;

      // If model changes
      if (newModel !== state.currentEmbeddingModel) {
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.SET_MODEL,
          payload: newModel,
        });

        // Reload knowledge base list when model changes
        fetchKnowledgeBases(true, true, true);
      }
    };

    // Listen for env config change event
    const handleEnvConfigChanged = () => {
      // Reload env related config
      if (modelConfig?.embedding?.modelName !== state.currentEmbeddingModel) {
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.SET_MODEL,
          payload: modelConfig?.embedding?.modelName || null,
        });

        // Reload knowledge base list when model changes
        fetchKnowledgeBases(true, true, true);
      }
    };

    // Listen for knowledge base data update event
    const handleKnowledgeBaseDataUpdated = (e: Event) => {
      // Check if need to force fetch data from server
      const customEvent = e as CustomEvent;
      const forceRefresh = customEvent.detail?.forceRefresh === true;

      // If first time loading data or force refresh, get from server
      if (!initialDataLoaded || forceRefresh) {
        // For force refresh, don't reload user selections to preserve current state
        fetchKnowledgeBases(false, !forceRefresh, true);
        initialDataLoaded = true;
      }
    };

    window.addEventListener(
      "embeddingModelChanged",
      handleEmbeddingModelChange as EventListener
    );
    window.addEventListener(
      "configChanged",
      handleEnvConfigChanged as EventListener
    );
    window.addEventListener(
      "knowledgeBaseDataUpdated",
      handleKnowledgeBaseDataUpdated as EventListener
    );

    return () => {
      window.removeEventListener(
        "embeddingModelChanged",
        handleEmbeddingModelChange as EventListener
      );
      window.removeEventListener(
        "configChanged",
        handleEnvConfigChanged as EventListener
      );
      window.removeEventListener(
        "knowledgeBaseDataUpdated",
        handleKnowledgeBaseDataUpdated as EventListener
      );
    };
  }, [fetchKnowledgeBases, state.currentEmbeddingModel]);

  // Memoized context value to prevent unnecessary re-renders
  const contextValue = useMemo(
    () => ({
      state,
      dispatch,
      fetchKnowledgeBases,
      createKnowledgeBase,
      deleteKnowledgeBase,
      selectKnowledgeBase,
      setActiveKnowledgeBase,
      updateKnowledgeBase,
      isKnowledgeBaseSelectable,
      hasKnowledgeBaseModelMismatch,
      refreshKnowledgeBaseData,
      refreshKnowledgeBaseDataWithDataMate,
    }),
    [
      state,
      dispatch,
      fetchKnowledgeBases,
      createKnowledgeBase,
      deleteKnowledgeBase,
      selectKnowledgeBase,
      setActiveKnowledgeBase,
      updateKnowledgeBase,
      isKnowledgeBaseSelectable,
      hasKnowledgeBaseModelMismatch,
      refreshKnowledgeBaseData,
      refreshKnowledgeBaseDataWithDataMate,
    ]
  );

  return (
    <KnowledgeBaseContext.Provider value={contextValue}>
      {children}
    </KnowledgeBaseContext.Provider>
  );
};
