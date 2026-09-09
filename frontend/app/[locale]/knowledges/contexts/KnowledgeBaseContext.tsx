"use client";

import {
  createContext,
  useReducer,
  useEffect,
  useContext,
  ReactNode,
  useCallback,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import knowledgeBaseService from "@/services/knowledgeBaseService";

import {
  KnowledgeBase,
  KnowledgeBaseState,
  KnowledgeBaseAction,
  DataMateSyncError,
  KnowledgeBaseListFacets,
  KnowledgeBaseListQuery,
} from "@/types/knowledgeBase";
import { KNOWLEDGE_BASE_ACTION_TYPES } from "@/const/knowledgeBase";

import { useConfig } from "@/hooks/useConfig";
import log from "@/lib/logger";

const KNOWLEDGE_BASE_PAGE_SIZE = 10;

interface KnowledgeBaseListPagination {
  total: number;
  hasMore: boolean;
  nextOffset: number | null;
  facets: KnowledgeBaseListFacets;
  estimatedRowHeight: number;
  estimatedItemHeights: Record<string, number> | null;
}

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
    shouldLoadSelected?: boolean,
    includeDataMateSync?: boolean,
    query?: KnowledgeBaseListQuery
  ) => Promise<void>;
  loadMoreKnowledgeBases: () => Promise<void>;
  listPagination: KnowledgeBaseListPagination;
  isLoadingMore: boolean;
  createKnowledgeBase: (
    name: string,
    description: string,
    source?: string,
    ingroup_permission?: string,
    group_ids?: number[],
    embeddingModelId?: number,
    preserve_source_file?: boolean,
    quota_limit_bytes?: number | null
  ) => Promise<KnowledgeBase>;
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
  loadMoreKnowledgeBases: async () => {},
  listPagination: {
    total: 0,
    hasMore: false,
    nextOffset: null,
    facets: { sources: [], models: [] },
    estimatedRowHeight: 112,
    estimatedItemHeights: null,
  },
  isLoadingMore: false,
  createKnowledgeBase: async () => {
    throw new Error("KnowledgeBaseProvider is required");
  },
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
  const queryRef = useRef<KnowledgeBaseListQuery>({});
  const listRequestIdRef = useRef(0);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [listPagination, setListPagination] =
    useState<KnowledgeBaseListPagination>({
      total: 0,
      hasMore: false,
      nextOffset: null,
      facets: { sources: [], models: [] },
      estimatedRowHeight: 112,
      estimatedItemHeights: null,
    });
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

  // Keep currentEmbeddingModel aligned with configured embedding displayName
  // (KB embeddingModel is stored as display_name).
  useEffect(() => {
    const displayName = modelConfig?.embedding?.displayName?.trim() || null;
    if (displayName !== state.currentEmbeddingModel) {
      dispatch({
        type: KNOWLEDGE_BASE_ACTION_TYPES.SET_MODEL,
        payload: displayName,
      });
    }
  }, [modelConfig?.embedding?.displayName, state.currentEmbeddingModel]);

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
        modelConfig?.multiEmbedding?.displayName?.trim() || "";

      if (kb.is_multimodal) {
        // Multimodal KB is selectable as long as current multimodal model is configured.
        return !!currentMultiEmbeddingModel;
      }

      // Text KB is selectable as long as current embedding model is configured.
      return !!currentEmbeddingModel;
    },
    [modelConfig?.multiEmbedding?.displayName, state.currentEmbeddingModel]
  );

  // Check if knowledge base has model mismatch (for display purposes).
  // Compare configured displayName with KB embeddingModel (stored as display_name).
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
          modelConfig?.multiEmbedding?.displayName?.trim() || "";
        return multiEmbeddingModel !== kb.embeddingModel.trim();
      }

      const currentEmbeddingModel = state.currentEmbeddingModel?.trim() || "";
      return currentEmbeddingModel !== kb.embeddingModel.trim();
    },
    [modelConfig?.multiEmbedding?.displayName, state.currentEmbeddingModel]
  );

  // Load knowledge base data (supports force fetch from server and load selected status) - optimized with useCallback
  const fetchKnowledgeBases = useCallback(
    async (
      skipHealthCheck = true,
      shouldLoadSelected = true,
      includeDataMateSync = true,
      query?: KnowledgeBaseListQuery
    ) => {
      if (query) queryRef.current = query;
      const requestId = ++listRequestIdRef.current;

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

        const result = await knowledgeBaseService.getKnowledgeBasesInfo(
          skipHealthCheck,
          includeDataMateSync,
          null,
          appConfig?.datamateUrl ?? null,
          {
            ...queryRef.current,
            offset: 0,
            limit:
              query?.limit ??
              queryRef.current.limit ??
              KNOWLEDGE_BASE_PAGE_SIZE,
          }
        );
        if (requestId !== listRequestIdRef.current) return;

        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.FETCH_SUCCESS,
          payload: result.knowledgeBases,
        });
        const externalCount = Math.max(
          0,
          result.knowledgeBases.length -
            (result.pageCount ?? result.knowledgeBases.length)
        );
        setListPagination({
          total: (result.total ?? result.knowledgeBases.length) + externalCount,
          hasMore: result.hasMore ?? false,
          nextOffset: result.nextOffset ?? null,
          facets: result.facets ?? { sources: [], models: [] },
          estimatedRowHeight: result.estimatedRowHeight ?? 112,
          estimatedItemHeights: result.estimatedItemHeights ?? null,
        });

        // Set DataMate sync error if present and throw to trigger error handling
        if (result.dataMateSyncError) {
          dispatch({
            type: KNOWLEDGE_BASE_ACTION_TYPES.SET_DATA_MATE_SYNC_ERROR,
            payload: result.dataMateSyncError,
          });
          // Throw DataMateSyncError to signal failure to the caller
          throw new DataMateSyncError(result.dataMateSyncError);
        }
      } catch (error) {
        if (requestId !== listRequestIdRef.current) return;
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
        if (requestId === listRequestIdRef.current) {
          dispatch({
            type: KNOWLEDGE_BASE_ACTION_TYPES.LOADING,
            payload: false,
          });
        }
      }
    },
    [appConfig?.datamateUrl, t]
  );

  const loadMoreKnowledgeBases = useCallback(async () => {
    if (isLoadingMore || !listPagination.hasMore) return;
    const requestId = listRequestIdRef.current;
    setIsLoadingMore(true);
    try {
      const result = await knowledgeBaseService.getKnowledgeBasesInfo(
        true,
        false,
        null,
        appConfig?.datamateUrl ?? null,
        {
          ...queryRef.current,
          offset: listPagination.nextOffset ?? state.knowledgeBases.length,
          limit: KNOWLEDGE_BASE_PAGE_SIZE,
        }
      );
      if (requestId !== listRequestIdRef.current) return;
      const merged = [...state.knowledgeBases, ...result.knowledgeBases].filter(
        (kb, index, items) =>
          items.findIndex((item) => item.id === kb.id) === index
      );
      dispatch({
        type: KNOWLEDGE_BASE_ACTION_TYPES.FETCH_SUCCESS,
        payload: merged,
      });
      setListPagination((current) => ({
        ...current,
        total: Math.max(current.total, result.total ?? current.total),
        hasMore: result.hasMore ?? false,
        nextOffset: result.nextOffset ?? null,
        facets: result.facets ?? current.facets,
      }));
    } catch (error) {
      log.error("Failed to load the next knowledge base page:", error);
    } finally {
      setIsLoadingMore(false);
    }
  }, [
    appConfig?.datamateUrl,
    isLoadingMore,
    listPagination.hasMore,
    listPagination.nextOffset,
    state.knowledgeBases,
  ]);

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
    dispatch({
      type: KNOWLEDGE_BASE_ACTION_TYPES.UPDATE_KNOWLEDGE_BASE,
      payload: kb,
    });
  }, []);

  // Create knowledge base - memoized with useCallback
  const createKnowledgeBase = useCallback(
    async (
      name: string,
      description: string,
      source: string = "elasticsearch",
      ingroup_permission?: string,
      group_ids?: number[],
      embeddingModelId?: number,
      preserve_source_file?: boolean,
      quota_limit_bytes?: number | null
    ) => {
      try {
        if (embeddingModelId === undefined) {
          throw new Error("Embedding model ID is required");
        }
        const newKB = await knowledgeBaseService.createKnowledgeBase({
          name,
          description,
          source,
          embeddingModelId,
          ingroup_permission,
          group_ids,
          preserve_source_file,
          quota_limit_bytes,
        });
        return newKB;
      } catch (error) {
        log.error(t("knowledgeBase.error.create"), error);
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.ERROR,
          payload: t("knowledgeBase.error.createRetry"),
        });
        throw error;
      }
    },
    [t]
  );

  // Delete knowledge base - memoized with useCallback
  const deleteKnowledgeBase = useCallback(
    async (id: string) => {
      try {
        await knowledgeBaseService.deleteKnowledgeBase(id);

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
        // Keep the original API error so the caller can show its EDS code/details.
        throw error;
      }
    },
    [state.knowledgeBases, state.selectedIds, state.activeKnowledgeBase]
  );

  // Add a function to refresh the knowledge base data
  const refreshKnowledgeBaseData = useCallback(
    async (forceRefresh = false) => {
      try {
        const result = await knowledgeBaseService.getKnowledgeBasesInfo(
          false,
          true,
          null,
          appConfig?.datamateUrl ?? null,
          {
            ...queryRef.current,
            offset: 0,
            limit: queryRef.current.limit ?? KNOWLEDGE_BASE_PAGE_SIZE,
          }
        );

        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.FETCH_SUCCESS,
          payload: result.knowledgeBases,
        });
        setListPagination((current) => ({
          ...current,
          total: result.total ?? result.knowledgeBases.length,
          hasMore: result.hasMore ?? false,
          nextOffset: result.nextOffset ?? null,
          facets: result.facets ?? current.facets,
        }));

        if (result.dataMateSyncError) {
          dispatch({
            type: KNOWLEDGE_BASE_ACTION_TYPES.SET_DATA_MATE_SYNC_ERROR,
            payload: result.dataMateSyncError,
          });
        }

        // If there is an active knowledge base, also refresh its document information
        if (state.activeKnowledgeBase) {
          // Publish document update event to notify document list component to refresh document data
          try {
            const documents = await knowledgeBaseService.getAllFiles(
              state.activeKnowledgeBase.id,
              state.activeKnowledgeBase.source
            );
            log.log("documents", documents);
            window.dispatchEvent(
              new CustomEvent("documentsUpdated", {
                detail: {
                  kbId: state.activeKnowledgeBase.id,
                  documents,
                },
              })
            );
          } catch (error) {
            log.error("Failed to refresh document information:", error);
          }
        }
      } catch (error) {
        log.error("Failed to refresh knowledge base data:", error);
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.ERROR,
          payload: "Failed to refresh knowledge base data",
        });
      }
    },
    [state.activeKnowledgeBase]
  );

  // Add a function to refresh the knowledge base data with DataMate sync and create records
  const refreshKnowledgeBaseDataWithDataMate = useCallback(async () => {
    try {
      const result = await knowledgeBaseService.getKnowledgeBasesInfo(
        false,
        true,
        null,
        appConfig?.datamateUrl ?? null,
        {
          ...queryRef.current,
          offset: 0,
          limit: queryRef.current.limit ?? KNOWLEDGE_BASE_PAGE_SIZE,
        }
      );

      dispatch({
        type: KNOWLEDGE_BASE_ACTION_TYPES.FETCH_SUCCESS,
        payload: result.knowledgeBases,
      });
      setListPagination((current) => ({
        ...current,
        total: result.total ?? result.knowledgeBases.length,
        hasMore: result.hasMore ?? false,
        nextOffset: result.nextOffset ?? null,
        facets: result.facets ?? current.facets,
      }));

      // Handle DataMate sync error
      if (result.dataMateSyncError) {
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.SET_DATA_MATE_SYNC_ERROR,
          payload: result.dataMateSyncError,
        });
        // Throw DataMateSyncError to signal failure to the caller
        throw new DataMateSyncError(result.dataMateSyncError);
      }

      // If there is an active knowledge base, also refresh its document information
      if (state.activeKnowledgeBase) {
        // Publish document update event to notify document list component to refresh document data
        try {
          const documents = await knowledgeBaseService.getAllFiles(
            state.activeKnowledgeBase.id,
            state.activeKnowledgeBase.source
          );
          log.log("documents", documents);
          window.dispatchEvent(
            new CustomEvent("documentsUpdated", {
              detail: {
                kbId: state.activeKnowledgeBase.id,
                documents,
              },
            })
          );
        } catch (error) {
          log.error("Failed to refresh document information:", error);
        }
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
  }, [state.activeKnowledgeBase]);

  // Initial data loading - with optimized dependencies
  useEffect(() => {
    // Use ref to track if data has been loaded to avoid duplicate loading
    let initialDataLoaded = false;

    // Get current model config at initial load (use displayName to match KB embeddingModel)
    const loadInitialData = async () => {
      if (modelConfig?.embedding?.displayName) {
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.SET_MODEL,
          payload: modelConfig.embedding.displayName,
        });
      }

      // Don't load knowledge base list here, wait for knowledgeBaseDataUpdated event
    };

    loadInitialData();

    // Listen for embedding model change event (detail.model is displayName)
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
      if (modelConfig?.embedding?.displayName !== state.currentEmbeddingModel) {
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.SET_MODEL,
          payload: modelConfig?.embedding?.displayName || null,
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
      loadMoreKnowledgeBases,
      listPagination,
      isLoadingMore,
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
      loadMoreKnowledgeBases,
      listPagination,
      isLoadingMore,
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
