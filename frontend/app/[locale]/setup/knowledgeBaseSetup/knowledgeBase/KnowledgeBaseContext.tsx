"use client"

import { createContext, useReducer, useEffect, useContext, ReactNode, useCallback, useMemo } from "react"
import { configStore } from "@/lib/config"
import knowledgeBaseService from "@/services/knowledgeBaseService"
import { userConfigService } from "@/services/userConfigService"
import { KnowledgeBase } from "@/types/knowledgeBase"
import { useTranslation } from 'react-i18next'

// State type definition
interface KnowledgeBaseState {
  knowledgeBases: KnowledgeBase[];
  selectedIds: string[];
  activeKnowledgeBase: KnowledgeBase | null;
  currentEmbeddingModel: string | null;
  isLoading: boolean;
  error: string | null;
}

// Action type definition
type KnowledgeBaseAction = 
  | { type: 'FETCH_SUCCESS', payload: KnowledgeBase[] }
  | { type: 'SELECT_KNOWLEDGE_BASE', payload: string[] }
  | { type: 'SET_ACTIVE', payload: KnowledgeBase | null }
  | { type: 'SET_MODEL', payload: string | null }
  | { type: 'DELETE_KNOWLEDGE_BASE', payload: string }
  | { type: 'ADD_KNOWLEDGE_BASE', payload: KnowledgeBase }
  | { type: 'LOADING', payload: boolean }
  | { type: 'ERROR', payload: string };

// Reducer function
const knowledgeBaseReducer = (state: KnowledgeBaseState, action: KnowledgeBaseAction): KnowledgeBaseState => {
  switch (action.type) {
    case 'FETCH_SUCCESS':
      return {
        ...state,
        knowledgeBases: action.payload,
        error: null
      };
    case 'SELECT_KNOWLEDGE_BASE':
      return {
        ...state,
        selectedIds: action.payload
      };
    case 'SET_ACTIVE':
      return {
        ...state,
        activeKnowledgeBase: action.payload
      };
    case 'SET_MODEL':
      return {
        ...state,
        currentEmbeddingModel: action.payload
      };
    case 'DELETE_KNOWLEDGE_BASE':
      return {
        ...state,
        knowledgeBases: state.knowledgeBases.filter(kb => kb.id !== action.payload),
        selectedIds: state.selectedIds.filter(id => id !== action.payload),
        activeKnowledgeBase: state.activeKnowledgeBase?.id === action.payload ? null : state.activeKnowledgeBase
      };
    case 'ADD_KNOWLEDGE_BASE':
      if (state.knowledgeBases.some(kb => kb.id === action.payload.id)) {
        return state; // If the knowledge base already exists, do not insert it
      }
      return {
        ...state,
        knowledgeBases: [...state.knowledgeBases, action.payload]
      };
    case 'LOADING':
      return {
        ...state,
        isLoading: action.payload
      };
    case 'ERROR':
      return {
        ...state,
        error: action.payload
      };
    default:
      return state;
  }
};

// Create context with default values
export const KnowledgeBaseContext = createContext<{
  state: KnowledgeBaseState;
  dispatch: React.Dispatch<KnowledgeBaseAction>;
  fetchKnowledgeBases: (skipHealthCheck?: boolean, shouldLoadSelected?: boolean) => Promise<void>;
  createKnowledgeBase: (name: string, description: string, source?: string) => Promise<KnowledgeBase | null>;
  deleteKnowledgeBase: (id: string) => Promise<boolean>;
  selectKnowledgeBase: (id: string) => void;
  setActiveKnowledgeBase: (kb: KnowledgeBase) => void;
  isKnowledgeBaseSelectable: (kb: KnowledgeBase) => boolean;
  refreshKnowledgeBaseData: (forceRefresh?: boolean) => Promise<void>;
  summaryIndex: (indexName: string, batchSize: number) => Promise<string>;
  loadUserSelectedKnowledgeBases: () => Promise<void>;
  saveUserSelectedKnowledgeBases: () => Promise<boolean>;
}>({
  state: {
    knowledgeBases: [],
    selectedIds: [],
    activeKnowledgeBase: null,
    currentEmbeddingModel: null,
    isLoading: false,
    error: null
  },
  dispatch: () => {},
  fetchKnowledgeBases: async () => {},
  createKnowledgeBase: async () => null,
  deleteKnowledgeBase: async () => false,
  selectKnowledgeBase: () => {},
  setActiveKnowledgeBase: () => {},
  isKnowledgeBaseSelectable: () => false,
  refreshKnowledgeBaseData: async () => {},
  summaryIndex: async () => '',
  loadUserSelectedKnowledgeBases: async () => {},
  saveUserSelectedKnowledgeBases: async () => false,
});

// Custom hook for using the context
export const useKnowledgeBaseContext = () => useContext(KnowledgeBaseContext);

// Provider component
interface KnowledgeBaseProviderProps {
  children: ReactNode;
}

export const KnowledgeBaseProvider: React.FC<KnowledgeBaseProviderProps> = ({ children }) => {
  const { t } = useTranslation();
  const [state, dispatch] = useReducer(knowledgeBaseReducer, {
    knowledgeBases: [],
    selectedIds: [],
    activeKnowledgeBase: null,
    currentEmbeddingModel: null,
    isLoading: false,
    error: null
  });
  
  // Check if knowledge base is selectable - memoized with useCallback
  const isKnowledgeBaseSelectable = useCallback((kb: KnowledgeBase): boolean => {
    // If no current embedding model is set, not selectable
    if (!state.currentEmbeddingModel) {
      return false;
    }
    // Only selectable when knowledge base model exactly matches current model
    return kb.embeddingModel === "unknown" || kb.embeddingModel === state.currentEmbeddingModel;
  }, [state.currentEmbeddingModel]);

  // Load knowledge base data (supports force fetch from server and load selected status) - optimized with useCallback
  const fetchKnowledgeBases = useCallback(async (skipHealthCheck = true, shouldLoadSelected = false) => {
    // If already loading, return directly
    if (state.isLoading) {
      return;
    }

    dispatch({ type: 'LOADING', payload: true });
    try {
      // Clear possible cache interference
      localStorage.removeItem('preloaded_kb_data');
      localStorage.removeItem('kb_cache');

      // Get knowledge base list data directly from server
      const kbs = await knowledgeBaseService.getKnowledgeBasesInfo(skipHealthCheck);
      
      dispatch({ type: 'FETCH_SUCCESS', payload: kbs });
      
    } catch (error) {
      console.error(t('knowledgeBase.error.fetchList'), error);
      dispatch({ type: 'ERROR', payload: t('knowledgeBase.error.fetchListRetry') });
    } finally {
      dispatch({ type: 'LOADING', payload: false });
    }
  }, [state.isLoading, t]);

  // Select knowledge base - memoized with useCallback
  const selectKnowledgeBase = useCallback((id: string) => {
    const kb = state.knowledgeBases.find((kb) => kb.id === id);
    if (!kb) return;

    // Check model compatibility
    if (!isKnowledgeBaseSelectable(kb)) {
      console.warn(`Cannot select knowledge base ${kb.name}, model mismatch`);
      return;
    }

    // Toggle selection status
    const isSelected = state.selectedIds.includes(id);
    const newSelectedIds = isSelected
      ? state.selectedIds.filter(kbId => kbId !== id)
      : [...state.selectedIds, id];

    // Update state
    dispatch({ type: 'SELECT_KNOWLEDGE_BASE', payload: newSelectedIds });
    
    // Note: removed logic for saving selection status to config
    // This feature is no longer needed as we don't store data config
  }, [state.knowledgeBases, state.selectedIds, isKnowledgeBaseSelectable]);

  // Set current active knowledge base - memoized with useCallback
  const setActiveKnowledgeBase = useCallback((kb: KnowledgeBase) => {
    dispatch({ type: 'SET_ACTIVE', payload: kb });
  }, []);

  // Create knowledge base - memoized with useCallback
  const createKnowledgeBase = useCallback(async (name: string, description: string, source: string = "elasticsearch") => {
    try {
      const newKB = await knowledgeBaseService.createKnowledgeBase({
        name,
        description,
        source,
        embeddingModel: state.currentEmbeddingModel || "text-embedding-3-small"
      });
      return newKB;
    } catch (error) {
      console.error(t('knowledgeBase.error.create'), error);
      dispatch({ type: 'ERROR', payload: t('knowledgeBase.error.createRetry') });
      return null;
    }
  }, [state.currentEmbeddingModel, t]);

  // Delete knowledge base - memoized with useCallback
  const deleteKnowledgeBase = useCallback(async (id: string) => {
    try {
      await knowledgeBaseService.deleteKnowledgeBase(id);
      
      // Update knowledge base list
      dispatch({ type: 'DELETE_KNOWLEDGE_BASE', payload: id });
      
      // If current active knowledge base is deleted, clear active state
      if (state.activeKnowledgeBase?.id === id) {
        dispatch({ type: 'SET_ACTIVE', payload: null });
      }
      
      // Update selected knowledge base list
      const newSelectedIds = state.selectedIds.filter(kbId => kbId !== id);
      
      if (newSelectedIds.length !== state.selectedIds.length) {
        // Update state
        dispatch({ type: 'SELECT_KNOWLEDGE_BASE', payload: newSelectedIds });
      }
      
      return true;
    } catch (error) {
      console.error(t('knowledgeBase.error.delete'), error);
      dispatch({ type: 'ERROR', payload: t('knowledgeBase.error.deleteRetry') });
      return false;
    }
  }, [state.knowledgeBases, state.selectedIds, state.activeKnowledgeBase]);

  // Summarize the content of the knowledge base
  const summaryIndex = useCallback(async (indexName: string, batchSize: number = 1000) => {
    try {
      const result = await knowledgeBaseService.summaryIndex(indexName, batchSize);
      return result;
    } catch (error) {
      dispatch({ type: 'ERROR', payload: t('knowledgeBase.error.summary') });
      throw error;
    }
  }, [t]);

  // Modify the summary of the knowledge base
  const changekKnowledgeSummary = useCallback(async (indexName: string, summary: string) => {
    try {
      const result = await knowledgeBaseService.changeSummary(indexName, summary);
      return result;
    } catch (error) {
      dispatch({ type: 'ERROR', payload: error as string });
      throw error;
    }
  }, []);

  // Load user selected knowledge bases from backend
  const loadUserSelectedKnowledgeBases = useCallback(async () => {
    try {
      const userConfig = await userConfigService.loadKnowledgeList();
      if (userConfig && userConfig.selectedKbNames.length > 0) {
        // Find matching knowledge base IDs based on names
        const selectedIds = state.knowledgeBases
          .filter(kb => userConfig.selectedKbNames.includes(kb.name))
          .map(kb => kb.id);

        dispatch({ type: 'SELECT_KNOWLEDGE_BASE', payload: selectedIds });
      }
    } catch (error) {
      console.error(t('knowledgeBase.error.loadSelected'), error);
      dispatch({ type: 'ERROR', payload: t('knowledgeBase.error.loadSelectedRetry') });
    }
  }, [state.knowledgeBases]);

  // Save user selected knowledge bases to backend
  const saveUserSelectedKnowledgeBases = useCallback(async () => {
    try {
      // Get selected knowledge base names
      const selectedKbNames = state.knowledgeBases
        .filter(kb => state.selectedIds.includes(kb.id))
        .map(kb => kb.name);

      const success = await userConfigService.updateKnowledgeList(selectedKbNames);
      if (!success) {
        dispatch({ type: 'ERROR', payload: t('knowledgeBase.error.saveSelected') });
      }
      return success;
    } catch (error) {
      console.error(t('knowledgeBase.error.saveSelected'), error);
      dispatch({ type: 'ERROR', payload: t('knowledgeBase.error.saveSelectedRetry') });
      return false;
    }
  }, [state.knowledgeBases, state.selectedIds, t]);

  // Add a function to refresh the knowledge base data
  const refreshKnowledgeBaseData = useCallback(async () => {
    try {
      // Get latest knowledge base data directly from server
      await fetchKnowledgeBases(false, true);

      // If there is an active knowledge base, also refresh its document information
      if (state.activeKnowledgeBase) {
        // Publish document update event to notify document list component to refresh document data
        try {
          const documents = await knowledgeBaseService.getAllFiles(state.activeKnowledgeBase.id);
          window.dispatchEvent(new CustomEvent('documentsUpdated', {
            detail: {
              kbId: state.activeKnowledgeBase.id,
              documents
            }
          }));
        } catch (error) {
          console.error("Failed to refresh document information:", error);
        }
      }
    } catch (error) {
      console.error("Failed to refresh knowledge base data:", error);
      dispatch({ type: 'ERROR', payload: 'Failed to refresh knowledge base data' });
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
        dispatch({ type: 'SET_MODEL', payload: modelConfig.embedding.modelName });
      }
      
      // Don't load knowledge base list here, wait for knowledgeBaseDataUpdated event
    };
    
    loadInitialData();
    
    // Listen for embedding model change event
    const handleEmbeddingModelChange = (e: CustomEvent) => {
      const newModel = e.detail.model || null;
      
      // If model changes
      if (newModel !== state.currentEmbeddingModel) {
        dispatch({ type: 'SET_MODEL', payload: newModel });
        
        // Reload knowledge base list when model changes
        fetchKnowledgeBases(true);
      }
    };
    
    // Listen for env config change event
    const handleEnvConfigChanged = () => {
      // Reload env related config
      const newModelConfig = configStore.getModelConfig();
      if (newModelConfig.embedding?.modelName !== state.currentEmbeddingModel) {
        dispatch({ type: 'SET_MODEL', payload: newModelConfig.embedding?.modelName || null });
        
        // Reload knowledge base list when model changes
        fetchKnowledgeBases(true);
      }
    };
    
    // Listen for knowledge base data update event
    const handleKnowledgeBaseDataUpdated = (e: Event) => {
      // Check if need to force fetch data from server
      const customEvent = e as CustomEvent;
      const forceRefresh = customEvent.detail?.forceRefresh === true;
      
      // If first time loading data or force refresh, get from server
      if (!initialDataLoaded || forceRefresh) {
        fetchKnowledgeBases(false, true);
        initialDataLoaded = true;
      }
    };
    
    window.addEventListener("embeddingModelChanged", handleEmbeddingModelChange as EventListener);
    window.addEventListener("configChanged", handleEnvConfigChanged as EventListener);
    window.addEventListener("knowledgeBaseDataUpdated", handleKnowledgeBaseDataUpdated as EventListener);
    
    return () => {
      window.removeEventListener("embeddingModelChanged", handleEmbeddingModelChange as EventListener);
      window.removeEventListener("configChanged", handleEnvConfigChanged as EventListener);
      window.removeEventListener("knowledgeBaseDataUpdated", handleKnowledgeBaseDataUpdated as EventListener);
    };
  }, [fetchKnowledgeBases, state.currentEmbeddingModel]);

  // Memoized context value to prevent unnecessary re-renders
  const contextValue = useMemo(() => ({
    state,
    dispatch,
    fetchKnowledgeBases,
    createKnowledgeBase,
    deleteKnowledgeBase,
    selectKnowledgeBase,
    setActiveKnowledgeBase,
    isKnowledgeBaseSelectable,
    refreshKnowledgeBaseData,
    summaryIndex,
    loadUserSelectedKnowledgeBases,
    saveUserSelectedKnowledgeBases
  }), [
    state,
    fetchKnowledgeBases,
    createKnowledgeBase,
    deleteKnowledgeBase,
    selectKnowledgeBase,
    setActiveKnowledgeBase,
    isKnowledgeBaseSelectable,
    refreshKnowledgeBaseData,
    summaryIndex,
    loadUserSelectedKnowledgeBases,
    saveUserSelectedKnowledgeBases
  ]);
  
  return (
    <KnowledgeBaseContext.Provider value={contextValue}>
      {children}
    </KnowledgeBaseContext.Provider>
  );
}; 