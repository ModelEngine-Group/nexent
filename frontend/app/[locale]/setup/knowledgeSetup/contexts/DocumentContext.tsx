"use client"

import { createContext, useReducer, useContext, ReactNode, useCallback, useEffect } from "react";
import { useTranslation } from 'react-i18next';

import { DOCUMENT_ACTION_TYPES } from "@/const/knowledgeBase";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { DocumentState, DocumentAction } from "@/types/knowledgeBase";
import log from "@/lib/logger";

// Reducer function
const documentReducer = (state: DocumentState, action: DocumentAction): DocumentState => {
  switch (action.type) {
    case DOCUMENT_ACTION_TYPES.FETCH_SUCCESS:
      return {
        ...state,
        documentsMap: {
          ...state.documentsMap,
          [action.payload.kbId]: action.payload.documents
        },
        isLoadingDocuments: false,
        error: null
      };
    case DOCUMENT_ACTION_TYPES.SELECT_DOCUMENT:
      // Toggle document selection
      const docId = action.payload;
      const isSelected = state.selectedIds.includes(docId);
      return {
        ...state,
        selectedIds: isSelected
          ? state.selectedIds.filter(id => id !== docId)
          : [...state.selectedIds, docId]
      };
    case DOCUMENT_ACTION_TYPES.SELECT_DOCUMENTS:
      return {
        ...state,
        selectedIds: action.payload
      };
    case DOCUMENT_ACTION_TYPES.SELECT_ALL:
      const { kbId, selected } = action.payload;
      const documents = state.documentsMap[kbId] || [];
      
      // If selected is true, add all document IDs, else remove all
      const newSelectedIds = selected
        ? [...new Set([...state.selectedIds, ...documents.map(doc => doc.id)])]
        : state.selectedIds.filter(id => !documents.some(doc => doc.id === id));
      
      return {
        ...state,
        selectedIds: newSelectedIds
      };
    case DOCUMENT_ACTION_TYPES.SET_UPLOAD_FILES:
      return {
        ...state,
        uploadFiles: action.payload
      };
    case DOCUMENT_ACTION_TYPES.SET_UPLOADING:
      return {
        ...state,
        isUploading: action.payload
      };
    case DOCUMENT_ACTION_TYPES.SET_LOADING_DOCUMENTS:
      return {
        ...state,
        isLoadingDocuments: action.payload
      };
    case DOCUMENT_ACTION_TYPES.DELETE_DOCUMENT:
      const { kbId: deleteKbId, docId: deleteDocId } = action.payload;
      // Remove the document from the map and the selected IDs
      return {
        ...state,
        documentsMap: {
          ...state.documentsMap,
          [deleteKbId]: state.documentsMap[deleteKbId]?.filter(doc => doc.id !== deleteDocId) || []
        },
        selectedIds: state.selectedIds.filter(id => id !== deleteDocId)
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
        loadingKbIds: newLoadingKbIds
      };
    case DOCUMENT_ACTION_TYPES.CLEAR_DOCUMENTS:
      return {
        ...state,
        documentsMap: {},
        selectedIds: [],
        error: null
      };
    case DOCUMENT_ACTION_TYPES.ERROR:
      return {
        ...state,
        error: action.payload,
        isLoadingDocuments: false
      };
    default:
      return state;
  }
};

// Create context with default values
export const DocumentContext = createContext<{
  state: DocumentState;
  dispatch: React.Dispatch<DocumentAction>;
  fetchDocuments: (kbId: string, forceRefresh?: boolean) => Promise<void>;
  uploadDocuments: (kbId: string, files: File[]) => Promise<void>;
  deleteDocument: (kbId: string, docId: string) => Promise<void>;
}>({
  state: {
    documentsMap: {},
    selectedIds: [],
    uploadFiles: [],
    isUploading: false,
    loadingKbIds: new Set<string>(),
    isLoadingDocuments: false,
    error: null
  },
  dispatch: () => {},
  fetchDocuments: async () => {},
  uploadDocuments: async () => {},
  deleteDocument: async () => {}
});

// Custom hook for using the context
export const useDocumentContext = () => useContext(DocumentContext);

// Provider component
interface DocumentProviderProps {
  children: ReactNode;
}

export const DocumentProvider: React.FC<DocumentProviderProps> = ({ children }) => {
  const { t } = useTranslation();
  const [state, dispatch] = useReducer(documentReducer, {
    documentsMap: {},
    selectedIds: [],
    uploadFiles: [],
    isUploading: false,
    loadingKbIds: new Set<string>(),
    isLoadingDocuments: false,
    error: null
  });

  // Listen for document update events
  useEffect(() => {
    const handleDocumentsUpdated = (event: Event) => {
      const customEvent = event as CustomEvent;
      if (customEvent.detail && customEvent.detail.kbId && customEvent.detail.documents) {
        const { kbId, documents } = customEvent.detail;
        
        // Update document information directly
        dispatch({ 
          type: DOCUMENT_ACTION_TYPES.FETCH_SUCCESS, 
          payload: { kbId, documents } 
        });
      }
    };
    
    // Add event listener
    window.addEventListener('documentsUpdated', handleDocumentsUpdated as EventListener);
    
    // Cleanup function
    return () => {
      window.removeEventListener('documentsUpdated', handleDocumentsUpdated as EventListener);
    };
  }, []);

  // Fetch documents for a knowledge base
  const fetchDocuments = useCallback(async (kbId: string, forceRefresh?: boolean) => {
    // Skip if already loading this kb
    if (state.loadingKbIds.has(kbId)) return;
    
    // If forceRefresh is false and we have cached data, return directly
    if (!forceRefresh && state.documentsMap[kbId] && state.documentsMap[kbId].length > 0) {
      return; // If we have cached data and don't need force refresh, return directly without server request
    }
    
    dispatch({ type: DOCUMENT_ACTION_TYPES.SET_LOADING_KB_ID, payload: { kbId, isLoading: true } });
    
    try {
      // Use getAllFiles() to get documents including those not yet in ES
      const documents = await knowledgeBaseService.getAllFiles(kbId);
      dispatch({ 
        type: DOCUMENT_ACTION_TYPES.FETCH_SUCCESS, 
        payload: { kbId, documents } 
      });
    } catch (error) {
      log.error(t('document.error.fetch'), error);
      dispatch({ type: DOCUMENT_ACTION_TYPES.ERROR, payload: t('document.error.load') });
    } finally {
      dispatch({ type: DOCUMENT_ACTION_TYPES.SET_LOADING_KB_ID, payload: { kbId, isLoading: false } });
    }
  }, [state.loadingKbIds, state.documentsMap, t]);

  // Upload documents to a knowledge base
  const uploadDocuments = useCallback(async (kbId: string, files: File[]) => {
    dispatch({ type: DOCUMENT_ACTION_TYPES.SET_UPLOADING, payload: true });
    
    try {
      await knowledgeBaseService.uploadDocuments(kbId, files);
      
      // Set loading state before fetching latest documents
      dispatch({ type: DOCUMENT_ACTION_TYPES.SET_LOADING_DOCUMENTS, payload: true });
      
      // Get latest status immediately after upload
      const latestDocuments = await knowledgeBaseService.getAllFiles(kbId);
      // Update document status
      dispatch({ 
        type: DOCUMENT_ACTION_TYPES.FETCH_SUCCESS, 
        payload: { kbId, documents: latestDocuments } 
      });
      
      // Trigger document status update event to notify other components
      window.dispatchEvent(new CustomEvent('documentsUpdated', {
        detail: { 
          kbId,
          documents: latestDocuments 
        }
      }));
      
      // Clear upload files
      dispatch({ type: DOCUMENT_ACTION_TYPES.SET_UPLOAD_FILES, payload: [] });
    } catch (error) {
      log.error(t('document.error.upload'), error);
      dispatch({ type: DOCUMENT_ACTION_TYPES.ERROR, payload: `${t('document.error.upload')}. ${t('document.error.retry')}` });
    } finally {
      dispatch({ type: DOCUMENT_ACTION_TYPES.SET_UPLOADING, payload: false });
      dispatch({ type: DOCUMENT_ACTION_TYPES.SET_LOADING_DOCUMENTS, payload: false });
    }
  }, [t]);

  // Delete a document
  const deleteDocument = useCallback(async (kbId: string, docId: string) => {
    try {
      await knowledgeBaseService.deleteDocument(docId, kbId);
      dispatch({ 
        type: DOCUMENT_ACTION_TYPES.DELETE_DOCUMENT, 
        payload: { kbId, docId } 
      });
    } catch (error) {
      log.error(t('document.error.delete'), error);
      dispatch({ type: DOCUMENT_ACTION_TYPES.ERROR, payload: `${t('document.error.delete')}. ${t('document.error.retry')}` });
    }
  }, [t]);

  return (
    <DocumentContext.Provider 
      value={{ 
        state, 
        dispatch,
        fetchDocuments,
        uploadDocuments,
        deleteDocument,
      }}
    >
      {children}
    </DocumentContext.Provider>
  );
}; 