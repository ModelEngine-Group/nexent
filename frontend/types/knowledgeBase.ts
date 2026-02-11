// Knowledge base related type definitions

import {
  DOCUMENT_ACTION_TYPES,
  KNOWLEDGE_BASE_ACTION_TYPES,
  UI_ACTION_TYPES,
  NOTIFICATION_TYPES,
} from "@/const/knowledgeBase";

// Knowledge base basic type
export interface KnowledgeBase {
  id: string;
  name: string;
  display_name?: string; // User-friendly display name, falls back to name if not available
  description: string | null;
  chunkCount: number;
  documentCount: number;
  createdAt: any;
  // Last update time of the knowledge base/index (may fall back to createdAt)
  updatedAt?: any;
  embeddingModel: string;
  knowledge_sources?: string;
  ingroup_permission?: string;
  group_ids?: number[];
  store_size?: string;
  process_source?: string;
  avatar: string;
  chunkNum: number;
  language: string;
  nickname: string;
  parserId: string;
  permission: string;
  tokenNum: number;
  source: string;
  tenant_id?: string;
}

// Create knowledge base parameter type
export interface KnowledgeBaseCreateParams {
  name: string;
  description: string;
  source?: string;
  embeddingModel?: string;
  // Group permission and user groups for new knowledge bases
  ingroup_permission?: string;
  group_ids?: number[];
}

// Document type
export interface Document {
  id: string;
  kb_id: string;
  name: string;
  type: string;
  size: number;
  create_time: string;
  chunk_num: number;
  token_num: number;
  status: string;
  selected?: boolean; // For UI selection status
  latest_task_id: string; // For marking the latest celery task
  error_reason?: string; // Error reason for failed documents
  // Optional ingestion progress metrics
  processed_chunk_num?: number | null;
  total_chunk_num?: number | null;
}

// Document state interface
export interface DocumentState {
  documentsMap: Record<string, Document[]>;
  selectedIds: string[];
  uploadFiles: File[];
  isUploading: boolean;
  loadingKbIds: Set<string>;
  isLoadingDocuments: boolean;
  error: string | null;
}

// Document action type
export type DocumentAction =
  | {
      type: typeof DOCUMENT_ACTION_TYPES.FETCH_SUCCESS;
      payload: { kbId: string; documents: Document[] };
    }
  | { type: typeof DOCUMENT_ACTION_TYPES.SELECT_DOCUMENT; payload: string }
  | { type: typeof DOCUMENT_ACTION_TYPES.SELECT_DOCUMENTS; payload: string[] }
  | {
      type: typeof DOCUMENT_ACTION_TYPES.SELECT_ALL;
      payload: { kbId: string; selected: boolean };
    }
  | { type: typeof DOCUMENT_ACTION_TYPES.SET_UPLOAD_FILES; payload: File[] }
  | { type: typeof DOCUMENT_ACTION_TYPES.SET_UPLOADING; payload: boolean }
  | {
      type: typeof DOCUMENT_ACTION_TYPES.SET_LOADING_DOCUMENTS;
      payload: boolean;
    }
  | {
      type: typeof DOCUMENT_ACTION_TYPES.DELETE_DOCUMENT;
      payload: { kbId: string; docId: string };
    }
  | {
      type: typeof DOCUMENT_ACTION_TYPES.SET_LOADING_KB_ID;
      payload: { kbId: string; isLoading: boolean };
    }
  | { type: typeof DOCUMENT_ACTION_TYPES.CLEAR_DOCUMENTS; payload?: undefined }
  | { type: typeof DOCUMENT_ACTION_TYPES.ERROR; payload: string };

// Knowledge base state interface
export interface KnowledgeBaseState {
  knowledgeBases: KnowledgeBase[];
  selectedIds: string[];
  activeKnowledgeBase: KnowledgeBase | null;
  currentEmbeddingModel: string | null;
  isLoading: boolean;
  syncLoading: boolean;
  error: string | null;
  dataMateSyncError?: string;
}

// Knowledge base action type
export type KnowledgeBaseAction =
  | {
      type: typeof KNOWLEDGE_BASE_ACTION_TYPES.FETCH_SUCCESS;
      payload: KnowledgeBase[];
    }
  | {
      type: typeof KNOWLEDGE_BASE_ACTION_TYPES.SELECT_KNOWLEDGE_BASE;
      payload: string[];
    }
  | {
      type: typeof KNOWLEDGE_BASE_ACTION_TYPES.SET_ACTIVE;
      payload: KnowledgeBase | null;
    }
  | {
      type: typeof KNOWLEDGE_BASE_ACTION_TYPES.SET_MODEL;
      payload: string | null;
    }
  | {
      type: typeof KNOWLEDGE_BASE_ACTION_TYPES.DELETE_KNOWLEDGE_BASE;
      payload: string;
    }
  | {
      type: typeof KNOWLEDGE_BASE_ACTION_TYPES.ADD_KNOWLEDGE_BASE;
      payload: KnowledgeBase;
    }
  | { type: typeof KNOWLEDGE_BASE_ACTION_TYPES.LOADING; payload: boolean }
  | {
      type: typeof KNOWLEDGE_BASE_ACTION_TYPES.SET_SYNC_LOADING;
      payload: boolean;
    }
  | {
      type: typeof KNOWLEDGE_BASE_ACTION_TYPES.SET_DATA_MATE_SYNC_ERROR;
      payload: string | undefined;
    }
  | { type: typeof KNOWLEDGE_BASE_ACTION_TYPES.ERROR; payload: string };

// UI state interface
export interface UIState {
  isDragging: boolean;
  isCreateModalVisible: boolean;
  isDocModalVisible: boolean;
  notifications: {
    id: string;
    message: string;
    type:
      | typeof NOTIFICATION_TYPES.SUCCESS
      | typeof NOTIFICATION_TYPES.ERROR
      | typeof NOTIFICATION_TYPES.INFO
      | typeof NOTIFICATION_TYPES.WARNING;
  }[];
}

// UI action type
export type UIAction =
  | { type: typeof UI_ACTION_TYPES.SET_DRAGGING; payload: boolean }
  | { type: typeof UI_ACTION_TYPES.TOGGLE_CREATE_MODAL; payload: boolean }
  | { type: typeof UI_ACTION_TYPES.TOGGLE_DOC_MODAL; payload: boolean }
  | {
      type: typeof UI_ACTION_TYPES.ADD_NOTIFICATION;
      payload: {
        message: string;
        type:
          | typeof NOTIFICATION_TYPES.SUCCESS
          | typeof NOTIFICATION_TYPES.ERROR
          | typeof NOTIFICATION_TYPES.INFO
          | typeof NOTIFICATION_TYPES.WARNING;
      };
    }
  | { type: typeof UI_ACTION_TYPES.REMOVE_NOTIFICATION; payload: string };

// Abortable error type for upload operations
export interface AbortableError extends Error {
  name: string;
}

// Custom error type for DataMate sync failures
export class DataMateSyncError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DataMateSyncError";
  }
}

// Result type for knowledge base fetch with DataMate sync status
export interface KnowledgeBasesWithDataMateStatus {
  knowledgeBases: KnowledgeBase[];
  dataMateSyncError?: string;
}
