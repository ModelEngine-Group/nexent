"use client";

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
import { userConfigService } from "@/services/userConfigService";

import {
  KnowledgeBase,
  KnowledgeBaseState,
  KnowledgeBaseAction,
} from "@/types/knowledgeBase";
import { KNOWLEDGE_BASE_ACTION_TYPES } from "@/const/knowledgeBase";

import { configStore } from "@/lib/config";
import log from "@/lib/logger";

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
    source?: string
  ) => Promise<KnowledgeBase | null>;
  deleteKnowledgeBase: (id: string) => Promise<boolean>;
  selectKnowledgeBase: (id: string) => void;
  setActiveKnowledgeBase: (kb: KnowledgeBase) => void;
  isKnowledgeBaseSelectable: (kb: KnowledgeBase) => boolean;
  hasKnowledgeBaseModelMismatch: (kb: KnowledgeBase) => boolean;
  refreshKnowledgeBaseData: (forceRefresh?: boolean) => Promise<void>;
  refreshKnowledgeBaseDataWithDataMate: () => Promise<void>;
  loadUserSelectedKnowledgeBases: () => Promise<void>;
  saveUserSelectedKnowledgeBases: () => Promise<boolean>;
}>({
  state: {
    knowledgeBases: [],
    selectedIds: [],
    activeKnowledgeBase: null,
    currentEmbeddingModel: null,
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
  isKnowledgeBaseSelectable: () => false,
  hasKnowledgeBaseModelMismatch: () => false,
  refreshKnowledgeBaseData: async () => {},
  refreshKnowledgeBaseDataWithDataMate: async () => {},
  loadUserSelectedKnowledgeBases: async () => {},
  saveUserSelectedKnowledgeBases: async () => false,
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
  const [state, dispatch] = useReducer(knowledgeBaseReducer, {
    knowledgeBases: [],
    selectedIds: [],
    activeKnowledgeBase: null,
    currentEmbeddingModel: null,
    isLoading: false,
    syncLoading: false,
    error: null,
  });

  // Check if knowledge base is selectable - memoized with useCallback
  const isKnowledgeBaseSelectable = useCallback(
    (kb: KnowledgeBase): boolean => {
      // If no current embedding model is set, not selectable
      if (!state.currentEmbeddingModel) {
        return false;
      }
      // DataMate knowledge bases are always selectable (even if model doesn't match)
      if (kb.source === "datamate") {
        return true;
      }
      // Only selectable when knowledge base model exactly matches current model
      return (
        kb.embeddingModel === "unknown" ||
        kb.embeddingModel === state.currentEmbeddingModel
      );
    },
    [state.currentEmbeddingModel]
  );

  // Check if knowledge base has model mismatch (for display purposes)
  const hasKnowledgeBaseModelMismatch = useCallback(
    (kb: KnowledgeBase): boolean => {
      if (!state.currentEmbeddingModel || kb.embeddingModel === "unknown") {
        return false;
      }
      // DataMate knowledge bases don't report model mismatch (they are always selectable)
      if (kb.source === "datamate") {
        return false;
      }
      return kb.embeddingModel !== state.currentEmbeddingModel;
    },
    [state.currentEmbeddingModel]
  );

  // Load user selected knowledge bases from backend
  const loadUserSelectedKnowledgeBases = useCallback(async () => {
    try {
      const userConfig = await userConfigService.loadKnowledgeList();
      if (userConfig) {
        let allSelectedNames: string[] = [];

        // Handle new format (selectedKbNames array)
        if (
          userConfig.selectedKbNames &&
          userConfig.selectedKbNames.length > 0
        ) {
          allSelectedNames = userConfig.selectedKbNames;
        }
        // Fallback to legacy grouped format for backward compatibility
        else if (userConfig.nexent || userConfig.datamate) {
          allSelectedNames = [
            ...(userConfig.nexent || []),
            ...(userConfig.datamate || []),
          ];
        }

        if (allSelectedNames.length > 0) {
          // Find matching knowledge base IDs based on index names
          const selectedIds = state.knowledgeBases
            .filter((kb) => allSelectedNames.includes(kb.id))
            .map((kb) => kb.id);

          dispatch({
            type: KNOWLEDGE_BASE_ACTION_TYPES.SELECT_KNOWLEDGE_BASE,
            payload: selectedIds,
          });
        }
      }
    } catch (error) {
      log.error(t("knowledgeBase.error.loadSelected"), error);
      dispatch({
        type: KNOWLEDGE_BASE_ACTION_TYPES.ERROR,
        payload: t("knowledgeBase.error.loadSelectedRetry"),
      });
    }
  }, [state.knowledgeBases]);

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
      try {
        // Clear possible cache interference
        localStorage.removeItem("preloaded_kb_data");
        localStorage.removeItem("kb_cache");

        // Get knowledge base list data directly from server
        const kbs = await knowledgeBaseService.getKnowledgeBasesInfo(
          skipHealthCheck,
          includeDataMateSync
        );

        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.FETCH_SUCCESS,
          payload: kbs,
        });

        // After loading knowledge bases, automatically load user's selected knowledge bases if requested
        if (shouldLoadSelected && kbs.length > 0) {
          await loadUserSelectedKnowledgeBases();
        }
      } catch (error) {
        log.error(t("knowledgeBase.error.fetchList"), error);
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.ERROR,
          payload: t("knowledgeBase.error.fetchListRetry"),
        });
      } finally {
        dispatch({ type: KNOWLEDGE_BASE_ACTION_TYPES.LOADING, payload: false });
      }
    },
    [state.isLoading, t, loadUserSelectedKnowledgeBases]
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
  const setActiveKnowledgeBase = useCallback((kb: KnowledgeBase) => {
    dispatch({ type: KNOWLEDGE_BASE_ACTION_TYPES.SET_ACTIVE, payload: kb });
  }, []);

  // Create knowledge base - memoized with useCallback
  const createKnowledgeBase = useCallback(
    async (
      name: string,
      description: string,
      source: string = "elasticsearch"
    ) => {
      try {
        const newKB = await knowledgeBaseService.createKnowledgeBase({
          name,
          description,
          source,
          embeddingModel:
            state.currentEmbeddingModel || "text-embedding-3-small",
        });
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
    [state.currentEmbeddingModel, t]
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
        return false;
      }
    },
    [state.knowledgeBases, state.selectedIds, state.activeKnowledgeBase]
  );

  // Save user selected knowledge bases to backend
  const saveUserSelectedKnowledgeBases = useCallback(async () => {
    try {
      // Get selected knowledge bases grouped by source
      const selectedKnowledgeBases = state.knowledgeBases.filter((kb) =>
        state.selectedIds.includes(kb.id)
      );

      // Group knowledge bases by source
      const knowledgeBySource: { nexent?: string[]; datamate?: string[] } = {};
      selectedKnowledgeBases.forEach((kb) => {
        const source = kb.source as keyof typeof knowledgeBySource;
        if (!knowledgeBySource[source]) {
          knowledgeBySource[source] = [];
        }
        knowledgeBySource[source]!.push(kb.id);
      });

      const result =
        await userConfigService.updateKnowledgeList(knowledgeBySource);
      if (!result) {
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.ERROR,
          payload: t("knowledgeBase.error.saveSelected"),
        });
        return false;
      }
      return true;
    } catch (error) {
      log.error(t("knowledgeBase.error.saveSelected"), error);
      dispatch({
        type: KNOWLEDGE_BASE_ACTION_TYPES.ERROR,
        payload: t("knowledgeBase.error.saveSelectedRetry"),
      });
      return false;
    }
  }, [state.knowledgeBases, state.selectedIds, t]);

  // Add a function to refresh the knowledge base data
  const refreshKnowledgeBaseData = useCallback(
    async (forceRefresh = false) => {
      try {
        // Get latest knowledge base data directly from server, but don't reload user selections and skip DataMate sync
        await fetchKnowledgeBases(false, false, false);

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
    [fetchKnowledgeBases, state.activeKnowledgeBase]
  );

  // Add a function to refresh the knowledge base data with DataMate sync and create records
  const refreshKnowledgeBaseDataWithDataMate = useCallback(async () => {
    try {
      // Get latest knowledge base data directly from server, which includes DataMate sync
      // The getKnowledgeBasesInfo method already handles syncDataMateAndCreateRecords internally
      await fetchKnowledgeBases(false, false, true);

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
      log.error("Failed to refresh knowledge base data with DataMate:", error);
      dispatch({
        type: KNOWLEDGE_BASE_ACTION_TYPES.ERROR,
        payload: "Failed to refresh knowledge base data with DataMate",
      });
    }
  }, [fetchKnowledgeBases, state.activeKnowledgeBase]);

  // Initial data loading - with optimized dependencies
  useEffect(() => {
    // Use ref to track if data has been loaded to avoid duplicate loading
    let initialDataLoaded = false;

    // Get current model config at initial load
    const loadInitialData = async () => {
      const modelConfig = configStore.getModelConfig();
      if (modelConfig.embedding?.modelName) {
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
      const newModelConfig = configStore.getModelConfig();
      if (newModelConfig.embedding?.modelName !== state.currentEmbeddingModel) {
        dispatch({
          type: KNOWLEDGE_BASE_ACTION_TYPES.SET_MODEL,
          payload: newModelConfig.embedding?.modelName || null,
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
      isKnowledgeBaseSelectable,
      hasKnowledgeBaseModelMismatch,
      refreshKnowledgeBaseData,
      refreshKnowledgeBaseDataWithDataMate,
      loadUserSelectedKnowledgeBases,
      saveUserSelectedKnowledgeBases,
    }),
    [
      state,
      fetchKnowledgeBases,
      createKnowledgeBase,
      deleteKnowledgeBase,
      selectKnowledgeBase,
      setActiveKnowledgeBase,
      isKnowledgeBaseSelectable,
      refreshKnowledgeBaseData,
      refreshKnowledgeBaseDataWithDataMate,
      loadUserSelectedKnowledgeBases,
      saveUserSelectedKnowledgeBases,
    ]
  );

  return (
    <KnowledgeBaseContext.Provider value={contextValue}>
      {children}
    </KnowledgeBaseContext.Provider>
  );
};
