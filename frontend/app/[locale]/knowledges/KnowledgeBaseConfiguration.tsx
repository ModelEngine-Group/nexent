"use client";

import type React from "react";
import {
  useState,
  useEffect,
  useRef,
  useLayoutEffect,
  useCallback,
} from "react";
import { useTranslation } from "react-i18next";

import { App, Modal, Row, Col, theme, Button, Input, Form } from "antd";
import {
  ExclamationCircleFilled,
  WarningFilled,
  InfoCircleFilled,
} from "@ant-design/icons";
import {
  DOCUMENT_ACTION_TYPES,
  KNOWLEDGE_BASE_ACTION_TYPES,
} from "@/const/knowledgeBase";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import log from "@/lib/logger";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import knowledgeBasePollingService from "@/services/knowledgeBasePollingService";
import { API_ENDPOINTS } from "@/services/api";
import { KnowledgeBase } from "@/types/knowledgeBase";
import { useConfig } from "@/hooks/useConfig";
import { ConfigStore } from "@/lib/config";
import { configService } from "@/services/configService";
import {
  SETUP_PAGE_CONTAINER,
  TWO_COLUMN_LAYOUT,
  STANDARD_CARD,
} from "@/const/layoutConstants";

import KnowledgeBaseList from "./components/knowledge/KnowledgeBaseList";
import DocumentList from "./components/document/DocumentList";
import {
  useKnowledgeBaseContext,
  KnowledgeBaseProvider,
} from "./contexts/KnowledgeBaseContext";
import {
  useDocumentContext,
  DocumentProvider,
} from "./contexts/DocumentContext";
import { useUIContext, UIProvider } from "./contexts/UIStateContext";

// EmptyState component defined directly in this file
interface EmptyStateProps {
  icon?: React.ReactNode | string;
  title: string;
  description?: string;
  action?: React.ReactNode;
  containerHeight?: string;
}

const EmptyState: React.FC<EmptyStateProps> = ({
  icon = "📋",
  title,
  description,
  action,
  containerHeight = "100%",
}) => {
  return (
    <div
      className="flex items-center justify-center p-4"
      style={{ height: containerHeight }}
    >
      <div className="text-center">
        {typeof icon === "string" ? (
          <div className="text-gray-400 text-3xl mb-2">{icon}</div>
        ) : (
          <div className="text-gray-400 mb-2">{icon}</div>
        )}
        <h3 className="text-base font-medium text-gray-700 mb-1">{title}</h3>
        {description && (
          <p className="text-gray-500 max-w-md text-xs mb-4">{description}</p>
        )}
        {action && <div className="mt-2">{action}</div>}
      </div>
    </div>
  );
};

// Combined AppProvider implementation
interface AppProviderProps {
  children: React.ReactNode;
}

/**
 * AppProvider - Provides global state management for the application
 *
 * Combines knowledge base, document and UI state management together for easy one-time import of all contexts
 */
const AppProvider: React.FC<AppProviderProps> = ({ children }) => {
  return (
    <KnowledgeBaseProvider>
      <DocumentProvider>
        <UIProvider>{children}</UIProvider>
      </DocumentProvider>
    </KnowledgeBaseProvider>
  );
};

// Update the wrapper component
interface DataConfigWrapperProps {
  isActive?: boolean;
}

export default function DataConfigWrapper({
  isActive = false,
}: DataConfigWrapperProps) {
  return (
    <AppProvider>
      <DataConfig isActive={isActive} />
    </AppProvider>
  );
}

interface DataConfigProps {
  isActive: boolean;
}

function DataConfig({ isActive }: DataConfigProps) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { confirm } = useConfirmModal();
  const { modelConfig } = useConfig();
  const { token } = theme.useToken();

  // Clear cache when component initializes
  useEffect(() => {
    localStorage.removeItem("preloaded_kb_data");
    localStorage.removeItem("kb_cache");

    // Load DataMate URL configuration
    const loadConfig = async () => {
      try {
        await loadDataMateConfig();
      } catch (error) {
        console.error("Failed to load DataMate configuration on mount:", error);
        // Set default values if loading fails
        setDataMateUrl("");
      }
    };
    loadConfig();
  }, []);

  // Load DataMate URL configuration
  const loadDataMateConfig = async () => {
    try {
      const response = await fetch(API_ENDPOINTS.config.load, {
        method: "GET",
        headers: getAuthHeaders(),
      });

      if (response.ok) {
        const result = await response.json();
        const config = result.config;
        console.log("Loaded config:", config);
        // DataMate URL would be in the app config section
        if (
          config &&
          config.app &&
          typeof config.app.datamateUrl === "string"
        ) {
          console.log("Setting DataMate URL to:", config.app.datamateUrl);
          setDataMateUrl(config.app.datamateUrl);
        } else {
          console.log("No DataMate URL found in config, setting to empty");
          setDataMateUrl("");
        }

        if (
          config &&
          config.app &&
          typeof config.app.modelEngineEnabled === "boolean"
        ) {
          setModelEngineEnabled(config.app.modelEngineEnabled);
        }

        // Return the DataMate URL for verification
        return config.app?.datamateUrl || "";
      } else {
        console.error(
          "Failed to load config, response status:",
          response.status,
          response.statusText
        );
        throw new Error(
          `Failed to load config: ${response.status} ${response.statusText}`
        );
      }
    } catch (error) {
      log.error("Failed to load DataMate configuration:", error);
      throw error; // Re-throw so the calling function can handle it
    }
  };

  // Get context values
  const {
    state: kbState,
    fetchKnowledgeBases,
    createKnowledgeBase,
    deleteKnowledgeBase,
    setActiveKnowledgeBase,
    hasKnowledgeBaseModelMismatch,
    refreshKnowledgeBaseData,
    refreshKnowledgeBaseDataWithDataMate,
    dispatch: kbDispatch,
  } = useKnowledgeBaseContext();

  const {
    state: docState,
    fetchDocuments,
    uploadDocuments,
    deleteDocument,
    dispatch: docDispatch,
  } = useDocumentContext();

  const { state: uiState, setDragging, dispatch: uiDispatch } = useUIContext();

  // Check if ModelEngine is enabled (from config API)
  const [modelEngineEnabled, setModelEngineEnabled] = useState(false);

  // Create mode state
  const [isCreatingMode, setIsCreatingMode] = useState(false);
  const [newKbName, setNewKbName] = useState("");
  const [newKbIngroupPermission, setNewKbIngroupPermission] = useState<string>("READ_ONLY");
  const [newKbGroupIds, setNewKbGroupIds] = useState<number[]>([]);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [hasClickedUpload, setHasClickedUpload] = useState(false);
  const [showEmbeddingWarning, setShowEmbeddingWarning] = useState(false);
  const [showAutoDeselectModal, setShowAutoDeselectModal] = useState(false);
  const [newlyCreatedKbId, setNewlyCreatedKbId] = useState<string | null>(null); // Track newly created KB waiting for documents

  // Search and filter state
  const [searchQuery, setSearchQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<string[]>([]);
  const [modelFilter, setModelFilter] = useState<string[]>([]);
  const contentRef = useRef<HTMLDivElement | null>(null);

  // Open warning modal when single Embedding model is not configured (ignore multi-embedding)
  useEffect(() => {
    const singleEmbeddingModelName = modelConfig?.embedding?.modelName;
    setShowEmbeddingWarning(!singleEmbeddingModelName);
  }, [modelConfig?.embedding?.modelName]);

  // Add event listener for selecting new knowledge base
  useEffect(() => {
    const handleSelectNewKnowledgeBase = (e: CustomEvent) => {
      const { knowledgeBase } = e.detail;
      if (knowledgeBase) {
        setIsCreatingMode(false);
        setHasClickedUpload(false);
        setActiveKnowledgeBase(knowledgeBase);
        fetchDocuments(knowledgeBase.id, false, knowledgeBase.source);
      }
    };

    window.addEventListener(
      "selectNewKnowledgeBase",
      handleSelectNewKnowledgeBase as EventListener
    );

    return () => {
      window.removeEventListener(
        "selectNewKnowledgeBase",
        handleSelectNewKnowledgeBase as EventListener
      );
    };
  }, [
    kbState.knowledgeBases,
    setActiveKnowledgeBase,
    fetchDocuments,
    setIsCreatingMode,
    setHasClickedUpload,
  ]);

  // User configuration loading and saving logic based on isActive state
  const prevIsActiveRef = useRef<boolean | null>(null); // Initialize as null to distinguish first render
  const hasLoadedRef = useRef(false); // Track whether configuration has been loaded
  const hasCleanedRef = useRef(false); // Ensure auto-deselect runs only once per entry

  // Listen for isActive state changes
  useLayoutEffect(() => {
    // Clear cache that might affect state
    localStorage.removeItem("preloaded_kb_data");
    localStorage.removeItem("kb_cache");

    const prevIsActive = prevIsActiveRef.current;

    // Mark ready to load when entering second page
    if ((prevIsActive === null || !prevIsActive) && isActive) {
      hasLoadedRef.current = false; // Reset loading state
      hasCleanedRef.current = false; // Reset auto-clean flag on entering
    }

    // Update ref
    prevIsActiveRef.current = isActive;
  }, [isActive]);

  // Helper function to get authorization headers
  const getAuthHeaders = () => {
    const session =
      typeof window !== "undefined" ? localStorage.getItem("session") : null;
    const sessionObj = session ? JSON.parse(session) : null;
    return {
      "Content-Type": "application/json",
      "User-Agent": "AgentFrontEnd/1.0",
      ...(sessionObj?.access_token && {
        Authorization: `Bearer ${sessionObj.access_token}`,
      }),
    };
  };

  // Separately listen for knowledge base loading state, load user configuration when knowledge base loading is complete and in active state
  useEffect(() => {
    // Only execute when second page is active, knowledge base is loaded, and user configuration hasn't been loaded yet
    if (
      isActive &&
      kbState.knowledgeBases.length > 0 &&
      !kbState.isLoading &&
      !hasLoadedRef.current
    ) {
      hasLoadedRef.current = true;
    }
  }, [isActive, kbState.knowledgeBases.length, kbState.isLoading]);

  // Auto-deselect incompatible knowledge bases once after selections are loaded and page is active
  useEffect(() => {
    if (!isActive) return;
    if (!hasLoadedRef.current) return; // ensure user selections loaded
    if (kbState.isLoading) return; // avoid running during list loading
    if (hasCleanedRef.current) return; // run once per entry

    const embeddingName = modelConfig?.embedding?.modelName?.trim() || "";
    const multiEmbeddingName =
      modelConfig?.multiEmbedding?.modelName?.trim() || "";

    const allowedModels = new Set<string>();
    if (embeddingName) allowedModels.add(embeddingName);
    if (multiEmbeddingName) allowedModels.add(multiEmbeddingName);

    hasCleanedRef.current = true;
  }, [
    isActive,
    kbState.isLoading,
    kbState.knowledgeBases,
    modelConfig?.embedding?.modelName,
    modelConfig?.multiEmbedding?.modelName,
    kbDispatch,
  ]);

  // Generate unique knowledge base name
  const generateUniqueKbName = (existingKbs: KnowledgeBase[]): string => {
    const baseNamePrefix = t("knowledgeBase.name.new");
    const existingNames = new Set(existingKbs.map((kb) => kb.name));

    // If base name is not used, return directly
    if (!existingNames.has(baseNamePrefix)) {
      return baseNamePrefix;
    }

    // Otherwise try adding numeric suffix until finding unused name
    let counter = 1;
    while (existingNames.has(`${baseNamePrefix}${counter}`)) {
      counter++;
    }

    return `${baseNamePrefix}${counter}`;
  };

  // Handle knowledge base click logic, set current active knowledge base
  const handleKnowledgeBaseClick = (
    kb: KnowledgeBase,
    fromUserClick: boolean = true
  ) => {
    // Only reset creation mode when user clicks
    if (fromUserClick) {
      setIsCreatingMode(false); // Reset creating mode
      setHasClickedUpload(false); // Reset upload button click state
    }

    // Whether switching knowledge base or not, need to get latest document information
    const isChangingKB =
      !kbState.activeKnowledgeBase || kb.id !== kbState.activeKnowledgeBase.id;

    // If switching knowledge base, update active state and clear newly created flag
    if (isChangingKB) {
      setActiveKnowledgeBase(kb);
      // Clear newly created flag when switching to a different knowledge base
      if (newlyCreatedKbId !== null && newlyCreatedKbId !== kb.id) {
        setNewlyCreatedKbId(null);
      }
    }

    // Set active knowledge base ID to polling service
    knowledgeBasePollingService.setActiveKnowledgeBase(kb.id);

    // Call knowledge base switch handling function
    handleKnowledgeBaseChange(kb);
  };

  // Handle knowledge base change event
  const handleKnowledgeBaseChange = async (kb: KnowledgeBase) => {
    try {
      // Set loading state before fetching documents
      docDispatch({
        type: DOCUMENT_ACTION_TYPES.SET_LOADING_DOCUMENTS,
        payload: true,
      });

      // Get latest document data
      const documents = await knowledgeBaseService.getAllFiles(
        kb.id,
        kb.source
      );

      // Trigger document update event
      knowledgeBasePollingService.triggerDocumentsUpdate(kb.id, documents);

      // Background update knowledge base statistics, but don't duplicate document fetching
      setTimeout(async () => {
        try {
          // Directly call fetchKnowledgeBases to update knowledge base list data
          await fetchKnowledgeBases(false, true);
        } catch (error) {
          log.error("获取知识库最新数据失败:", error);
        }
      }, 100);
    } catch (error) {
      log.error("获取文档列表失败:", error);
      message.error(t("knowledgeBase.message.getDocumentsFailed"));
      docDispatch({
        type: "ERROR",
        payload: t("knowledgeBase.message.getDocumentsFailed"),
      });
    }
  };

  // Add a drag and drop upload related handler function
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(true);
  };

  const handleDragLeave = () => {
    setDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);

    // If in creation mode or has active knowledge base, process files
    // Do not allow uploads when active KB source is datamate
    if (
      kbState.activeKnowledgeBase &&
      kbState.activeKnowledgeBase.source === "datamate" &&
      !isCreatingMode
    ) {
      message.warning(t("document.message.uploadDisabledForDataMate"));
      return;
    }

    if (isCreatingMode || kbState.activeKnowledgeBase) {
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) {
        setUploadFiles(files);
        handleFileUpload();
      }
    } else {
      message.warning(t("knowledgeBase.message.selectFirst"));
    }
  };

  // Handle knowledge base deletion
  const handleDelete = (id: string) => {
    // Find the knowledge base to check its source
    const kb = kbState.knowledgeBases.find((kb) => kb.id === id);

    if (kb?.source === "datamate") {
      // Show informational message for DataMate knowledge bases
      Modal.info({
        title: t("knowledgeBase.modal.deleteDataMate.title", { name: kb.name }),
        content: t("knowledgeBase.modal.deleteDataMate.content"),
        okText: t("common.confirm"),
        centered: true,
      });
      return;
    }

    // Normal delete confirmation for local knowledge bases
    confirm({
      title: t("knowledgeBase.modal.deleteConfirm.title"),
      content: t("knowledgeBase.modal.deleteConfirm.content"),
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
      danger: true,
      onOk: async () => {
        try {
          await deleteKnowledgeBase(id);

          // Clear preloaded data, force fetch latest data from server
          localStorage.removeItem("preloaded_kb_data");

          // Delay 1 second before refreshing knowledge base list to ensure backend processing is complete
          setTimeout(async () => {
            await fetchKnowledgeBases(false, false);
            message.success(t("knowledgeBase.message.deleteSuccess"));
          }, 1000);
        } catch (error) {
          message.error(t("knowledgeBase.message.deleteError"));
        }
      },
    });
  };

  // Handle knowledge base sync (includes both indices and DataMate sync and create records)
  const handleSync = async () => {
    // Set sync loading state
    kbDispatch({
      type: KNOWLEDGE_BASE_ACTION_TYPES.SET_SYNC_LOADING,
      payload: true,
    });

    try {
      // Check if ModelEngine is enabled to determine sync behavior
      if (modelEngineEnabled) {
        // When ModelEngine is enabled, sync both local and DataMate knowledge bases
        await refreshKnowledgeBaseDataWithDataMate();
      } else {
        // When ModelEngine is disabled, only sync local knowledge bases
        await refreshKnowledgeBaseData(true);
      }

      // Use unified success message
      message.success(t("knowledgeBase.message.syncSuccess"));
    } catch (error) {
      // Check if it's a DataMate sync error
      if (error instanceof Error && error.name === "DataMateSyncError") {
        // Show DataMate-specific friendly error message
        message.error(t("knowledgeBase.message.syncDataMateError"));
      } else {
        // Use unified error message
        message.error(t("knowledgeBase.message.syncError"));
      }
    } finally {
      // Clear sync loading state
      kbDispatch({
        type: KNOWLEDGE_BASE_ACTION_TYPES.SET_SYNC_LOADING,
        payload: false,
      });
    }
  };

  // Handle DataMate configuration
  const [showDataMateConfigModal, setShowDataMateConfigModal] = useState(false);
  const [dataMateUrl, setDataMateUrl] = useState("");
  const [dataMateUrlError, setDataMateUrlError] = useState<string | null>(null);
  const configStore = ConfigStore.getInstance();

  /**
   * Validate DataMate URL format
   * @param url URL to validate
   * @returns Error message if invalid, null if valid
   */
  const validateDataMateUrl = useCallback(
    (url: string): string | null => {
      if (!url || url.trim() === "") {
        return null; // Empty URL is valid (optional field)
      }

      // Check if URL has http:// or https:// protocol
      if (!url.startsWith("http://") && !url.startsWith("https://")) {
        return t("knowledgeBase.error.invalidUrlProtocol");
      }

      // Check if URL is a valid format (has hostname)
      try {
        const urlObj = new URL(url);
        if (!urlObj.hostname || urlObj.hostname.trim() === "") {
          return t("knowledgeBase.error.invalidUrlFormat");
        }
      } catch {
        return t("knowledgeBase.error.invalidUrlFormat");
      }

      return null; // Valid URL
    },
    [t]
  );

  // Monitor DataMate URL changes and validate
  useEffect(() => {
    // Clear error when URL changes
    if (dataMateUrlError) {
      setDataMateUrlError(null);
    }
  }, [dataMateUrl]);

  const handleDataMateConfig = () => {
    setShowDataMateConfigModal(true);
  };

  const handleDataMateConfigSave = async () => {
    // Validate URL format before saving
    const urlError = validateDataMateUrl(dataMateUrl);
    if (urlError) {
      setDataMateUrlError(urlError);
      return;
    }

    // Test connection and sync if URL is provided (non-empty)
    if (dataMateUrl.trim() !== "") {
      setDataMateUrlError(t("knowledgeBase.message.testingConnection"));
      try {
        // First test basic connection
        const connectionResult =
          await knowledgeBaseService.testDataMateConnection(dataMateUrl);
        if (!connectionResult.success) {
          setDataMateUrlError(t("knowledgeBase.error.connectionFailed"));
          return;
        }

        // Then test the actual sync endpoint (sync_datamate_knowledge)
        // This is the actual operation that will be used when syncing knowledge bases
        setDataMateUrlError(t("knowledgeBase.message.testingSync"));
        await knowledgeBaseService.syncDataMateAndCreateRecords(dataMateUrl);
      } catch (error) {
        setDataMateUrlError(t("knowledgeBase.error.syncFailed"));
        return;
      }
    }

    // Clear any previous error and proceed with saving
    setDataMateUrlError(null);

    try {
      console.log("Saving DataMate URL:", dataMateUrl);

      // Update global configuration with DataMate URL
      const currentConfig = configStore.getConfig();
      const updatedConfig = {
        ...currentConfig,
        app: {
          ...currentConfig.app,
          datamateUrl: dataMateUrl,
        },
      };

      // Save to backend using global config API
      const success = await configService.saveConfigToBackend(updatedConfig);

      if (!success) {
        throw new Error("Failed to save configuration to backend");
      }

      message.success(t("knowledgeBase.message.dataMateConfigSaved"));

      // Update local config store
      configStore.updateConfig(updatedConfig);

      // Update local state
      setDataMateUrl(dataMateUrl);

      try {
        await configService.loadConfigToFrontend();
        console.log("Configuration reloaded from backend successfully");
      } catch (reloadError) {
        console.warn(
          "Failed to reload configuration from backend, but save was successful:",
          reloadError
        );
        // Don't fail the entire operation if reload fails
      }

      // Trigger knowledge base sync with the new configuration
      await handleSync();

      setShowDataMateConfigModal(false);
    } catch (error) {
      log.error("Failed to save DataMate configuration:", error);
      message.error(t("knowledgeBase.message.dataMateConfigError"));
    }
  };

  // Handle new knowledge base creation
  const handleCreateNew = () => {
    // Generate default knowledge base name
    const defaultName = generateUniqueKbName(kbState.knowledgeBases);
    setNewKbName(defaultName);
    setNewKbIngroupPermission("READ_ONLY");
    setNewKbGroupIds([]);
    setIsCreatingMode(true);
    setHasClickedUpload(false); // Reset upload button click state
    setUploadFiles([]); // Reset upload files array, clear all pending upload files
  };

  // Handle document deletion
  const handleDeleteDocument = (docId: string) => {
    const kbId = kbState.activeKnowledgeBase?.id;
    if (!kbId) return;

    confirm({
      title: t("document.modal.deleteConfirm.title"),
      content: t("document.modal.deleteConfirm.content"),
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
      danger: true,
      onOk: async () => {
        try {
          await deleteDocument(kbId, docId);
          message.success(t("document.message.deleteSuccess"));
        } catch (error) {
          message.error(t("document.message.deleteError"));
        }
      },
    });
  };

  // Handle file upload - in creation mode create knowledge base first then upload, in normal mode upload directly
  const handleFileUpload = async () => {
    if (!uploadFiles.length) {
      message.warning(t("document.message.noFiles"));
      return;
    }
    const filesToUpload = uploadFiles;

    if (isCreatingMode) {
      if (!newKbName || newKbName.trim() === "") {
        message.warning(t("knowledgeBase.message.nameRequired"));
        return;
      }

      setHasClickedUpload(true);

      try {
        const nameExistsResult =
          await knowledgeBaseService.checkKnowledgeBaseNameExists(
            newKbName.trim()
          );

        if (nameExistsResult) {
          message.error(
            t("knowledgeBase.message.nameExists", { name: newKbName.trim() })
          );
          setHasClickedUpload(false);
          return;
        }

        const newKB = await createKnowledgeBase(
          newKbName.trim(),
          t("knowledgeBase.description.default"),
          "elasticsearch",
          newKbIngroupPermission,
          newKbGroupIds
        );

        if (!newKB) {
          message.error(t("knowledgeBase.message.createError"));
          setHasClickedUpload(false);
          return;
        }

        setIsCreatingMode(false);
        setActiveKnowledgeBase(newKB);
        knowledgeBasePollingService.setActiveKnowledgeBase(newKB.id);
        setHasClickedUpload(false);
        setNewlyCreatedKbId(newKB.id); // Mark this KB as newly created

        await uploadDocuments(newKB.id, filesToUpload);
        setUploadFiles([]);

        knowledgeBasePollingService
          .handleNewKnowledgeBaseCreation(
            newKB.id,
            newKB.name,
            0,
            filesToUpload.length,
            (populatedKB) => {
              setActiveKnowledgeBase(populatedKB);
              knowledgeBasePollingService.triggerKnowledgeBaseListUpdate(true);
              // Clear the newly created flag when documents are ready
              setNewlyCreatedKbId(null);
            }
          )
          .catch((pollingError) => {
            log.error("Knowledge base creation polling failed:", pollingError);
            // Clear the flag even on error to avoid stuck loading state
            setNewlyCreatedKbId(null);
          });
      } catch (error) {
        log.error(t("knowledgeBase.error.createUpload"), error);
        message.error(t("knowledgeBase.message.createUploadError"));
        setHasClickedUpload(false);
      }
      return;
    }

    const kbId = kbState.activeKnowledgeBase?.id;
    if (!kbId) {
      message.warning(t("knowledgeBase.message.selectFirst"));
      return;
    }

    try {
      await uploadDocuments(kbId, filesToUpload);
      setUploadFiles([]);

      knowledgeBasePollingService.triggerKnowledgeBaseListUpdate(true);

      knowledgeBasePollingService.startDocumentStatusPolling(
        kbId,
        (documents) => {
          knowledgeBasePollingService.triggerDocumentsUpdate(kbId, documents);
          window.dispatchEvent(
            new CustomEvent("documentsUpdated", {
              detail: { kbId, documents },
            })
          );
        }
      );
    } catch (error) {
      log.error(t("document.error.upload"), error);
      message.error(t("document.message.uploadError"));
    }
  };

  // File selection handling
  const handleFileSelect = (files: File[]) => {
    if (files && files.length > 0) {
      setUploadFiles(files);
    }
  };

  // Get current viewing knowledge base documents
  const viewingDocuments = (() => {
    // In creation mode return empty array because new knowledge base has no documents yet
    if (isCreatingMode) {
      return [];
    }

    // In normal mode, use activeKnowledgeBase
    return kbState.activeKnowledgeBase
      ? docState.documentsMap[kbState.activeKnowledgeBase.id] || []
      : [];
  })();

  // Get current knowledge base name
  const viewingKbName =
    kbState.activeKnowledgeBase?.name || (isCreatingMode ? newKbName : "");

  // Check if current knowledge base is newly created and waiting for documents
  const isNewlyCreatedAndWaiting =
    newlyCreatedKbId !== null &&
    kbState.activeKnowledgeBase?.id === newlyCreatedKbId &&
    viewingDocuments.length === 0;

  // As long as any document upload succeeds, immediately switch creation mode to false
  useEffect(() => {
    if (isCreatingMode && viewingDocuments.length > 0) {
      setIsCreatingMode(false);
    }
  }, [isCreatingMode, viewingDocuments.length]);

  // Clear newly created flag when documents arrive
  useEffect(() => {
    if (newlyCreatedKbId !== null && viewingDocuments.length > 0) {
      setNewlyCreatedKbId(null);
    }
  }, [newlyCreatedKbId, viewingDocuments.length]);

  // Update active knowledge base ID in polling service when component initializes or active knowledge base changes
  useEffect(() => {
    if (kbState.activeKnowledgeBase) {
      knowledgeBasePollingService.setActiveKnowledgeBase(
        kbState.activeKnowledgeBase.id
      );
    } else {
      knowledgeBasePollingService.setActiveKnowledgeBase(null);
    }
  }, [kbState.activeKnowledgeBase, isCreatingMode, newKbName]);

  // Clean up polling when component unmounts
  useEffect(() => {
    return () => {
      // Stop all polling
      knowledgeBasePollingService.stopAllPolling();
    };
  }, []);

  // In creation mode, reset "name already exists" state when knowledge base name changes
  const handleNameChange = (name: string) => {
    setNewKbName(name);
  };

  // If Embedding model is not configured, show warning container instead of content
  if (showEmbeddingWarning) {
    return (
      <div
        className="w-full h-full mx-auto relative"
        style={{
          maxWidth: SETUP_PAGE_CONTAINER.MAX_WIDTH,
          padding: `0 ${SETUP_PAGE_CONTAINER.HORIZONTAL_PADDING}`,
        }}
      >
        <div
          className={STANDARD_CARD.BASE_CLASSES}
          style={{
            height: SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT,
            padding: STANDARD_CARD.PADDING,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <div className="text-center">
            <WarningFilled
              className="text-yellow-500 mb-4"
              style={{ fontSize: 48 }}
            />
            <div className="text-base text-gray-800 font-semibold">
              {t("embedding.knowledgeBaseDisabledWarningModal.title")}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      <div
        className="w-full h-full mx-auto relative"
        style={{
          maxWidth: SETUP_PAGE_CONTAINER.MAX_WIDTH,
          padding: `0 ${SETUP_PAGE_CONTAINER.HORIZONTAL_PADDING}`,
        }}
        ref={contentRef}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <Row className="h-full w-full" gutter={TWO_COLUMN_LAYOUT.GUTTER}>
          <Col
            className="h-full"
            xs={TWO_COLUMN_LAYOUT.LEFT_COLUMN.xs}
            md={TWO_COLUMN_LAYOUT.LEFT_COLUMN.md}
            lg={TWO_COLUMN_LAYOUT.LEFT_COLUMN.lg}
            xl={TWO_COLUMN_LAYOUT.LEFT_COLUMN.xl}
            xxl={TWO_COLUMN_LAYOUT.LEFT_COLUMN.xxl}
          >
            <KnowledgeBaseList
              knowledgeBases={kbState.knowledgeBases}
              activeKnowledgeBase={kbState.activeKnowledgeBase}
              currentEmbeddingModel={kbState.currentEmbeddingModel}
              isLoading={kbState.isLoading}
              syncLoading={kbState.syncLoading}
              onClick={handleKnowledgeBaseClick}
              onDelete={handleDelete}
              onSync={handleSync}
              onCreateNew={handleCreateNew}
              onDataMateConfig={handleDataMateConfig}
              showDataMateConfig={modelEngineEnabled}
              getModelDisplayName={(modelId) => modelId}
              containerHeight={SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT}
              onKnowledgeBaseChange={() => {}} // No need to trigger repeatedly here as it's already handled in handleKnowledgeBaseClick
              // Search and filter props
              searchQuery={searchQuery}
              onSearchChange={setSearchQuery}
              sourceFilter={sourceFilter}
              onSourceFilterChange={(values) =>
                setSourceFilter(
                  Array.isArray(values) ? values : values ? [values] : []
                )
              }
              modelFilter={modelFilter}
              onModelFilterChange={(values) =>
                setModelFilter(
                  Array.isArray(values) ? values : values ? [values] : []
                )
              }
            />
          </Col>

          <Col
            className="h-full"
            xs={TWO_COLUMN_LAYOUT.RIGHT_COLUMN.xs}
            md={TWO_COLUMN_LAYOUT.RIGHT_COLUMN.md}
            lg={TWO_COLUMN_LAYOUT.RIGHT_COLUMN.lg}
            xl={TWO_COLUMN_LAYOUT.RIGHT_COLUMN.xl}
            xxl={TWO_COLUMN_LAYOUT.RIGHT_COLUMN.xxl}
          >
            {isCreatingMode ? (
              <DocumentList
                documents={[]}
                onDelete={() => {}}
                knowledgeBaseSource={""}
                isCreatingMode={true}
                knowledgeBaseId={""}
                knowledgeBaseName={newKbName}
                onNameChange={handleNameChange}
                containerHeight={SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT}
                hasDocuments={hasClickedUpload || docState.isUploading}
                // Group permission and user groups for create mode
                ingroupPermission={newKbIngroupPermission}
                onIngroupPermissionChange={setNewKbIngroupPermission}
                selectedGroupIds={newKbGroupIds}
                onSelectedGroupIdsChange={setNewKbGroupIds}
                // Upload related props
                isDragging={uiState.isDragging}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onFileSelect={handleFileSelect}
                onUpload={() => handleFileUpload()}
                isUploading={docState.isUploading}
              />
            ) : kbState.activeKnowledgeBase ? (
              <DocumentList
                documents={viewingDocuments}
                onDelete={handleDeleteDocument}
                knowledgeBaseSource={kbState.activeKnowledgeBase?.source}
                knowledgeBaseId={kbState.activeKnowledgeBase.id}
                knowledgeBaseName={viewingKbName}
                modelMismatch={hasKnowledgeBaseModelMismatch(
                  kbState.activeKnowledgeBase
                )}
                currentModel={kbState.currentEmbeddingModel || ""}
                knowledgeBaseModel={kbState.activeKnowledgeBase.embeddingModel}
                embeddingModelInfo={
                  hasKnowledgeBaseModelMismatch(kbState.activeKnowledgeBase)
                    ? t("document.modelMismatch.withModels", {
                        currentModel: kbState.currentEmbeddingModel || "",
                        knowledgeBaseModel:
                          kbState.activeKnowledgeBase.embeddingModel,
                      })
                    : undefined
                }
                containerHeight={SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT}
                hasDocuments={viewingDocuments.length > 0}
                isNewlyCreatedAndWaiting={isNewlyCreatedAndWaiting}
                onChunkCountChange={() => {
                  // Trigger knowledge base list update to refresh chunk count
                  knowledgeBasePollingService.triggerKnowledgeBaseListUpdate(true);
                }}
                // Upload related props
                isDragging={uiState.isDragging}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onFileSelect={handleFileSelect}
                onUpload={() => handleFileUpload()}
                isUploading={docState.isUploading}
              />
            ) : (
              <div
                className={`${STANDARD_CARD.BASE_CLASSES} flex flex-col h-full w-full`}
                style={{
                  padding: STANDARD_CARD.PADDING,
                }}
              >
                <EmptyState
                  title={t("knowledgeBase.empty.title")}
                  description={t("knowledgeBase.empty.description")}
                  icon={
                    <InfoCircleFilled
                      style={{ fontSize: 36, color: "#1677ff" }}
                    />
                  }
                  containerHeight="100%"
                />
              </div>
            )}
          </Col>
        </Row>
      </div>

      <Modal
        open={showAutoDeselectModal}
        title={null}
        onOk={() => setShowAutoDeselectModal(false)}
        onCancel={() => setShowAutoDeselectModal(false)}
        okText={t("common.confirm")}
        cancelButtonProps={{ style: { display: "none" } }}
        centered
        okButtonProps={{ type: "primary", danger: true }}
        getContainer={() => contentRef.current || document.body}
      >
        <div className="flex items-start gap-4">
          <ExclamationCircleFilled
            style={{
              color: token.colorWarning,
              fontSize: "22px",
              marginTop: "2px",
            }}
          />
          <div className="flex-1">
            <div className="text-base font-medium mb-3">
              {t("embedding.knowledgeBaseAutoDeselectModal.title")}
            </div>
            <div className="text-sm leading-6">
              {t("embedding.knowledgeBaseAutoDeselectModal.content")}
            </div>
          </div>
        </div>
      </Modal>

      <Modal
        open={showDataMateConfigModal}
        title={t("knowledgeBase.modal.dataMateConfig.title")}
        onOk={handleDataMateConfigSave}
        onCancel={() => {
          setShowDataMateConfigModal(false);
          // Clear error state
          setDataMateUrlError(null);
          // Reload config to ensure we have the latest values
          loadDataMateConfig();
        }}
        okText={t("common.save")}
        cancelText={t("common.cancel")}
        centered
        getContainer={() => contentRef.current || document.body}
        confirmLoading={kbState.syncLoading}
      >
        <div className="space-y-4">
          <div className="text-sm text-gray-600">
            {t("knowledgeBase.modal.dataMateConfig.description")}
          </div>
          <Form layout="vertical">
            <Form.Item
              label={t("knowledgeBase.modal.dataMateConfig.urlLabel")}
              help={dataMateUrlError}
              validateStatus={dataMateUrlError ? "error" : undefined}
            >
              <Input
                value={dataMateUrl}
                onChange={(e) => setDataMateUrl(e.target.value)}
                onBlur={() => {
                  // Validate on blur
                  const error = validateDataMateUrl(dataMateUrl);
                  setDataMateUrlError(error);
                }}
                placeholder={t(
                  "knowledgeBase.modal.dataMateConfig.urlPlaceholder"
                )}
              />
            </Form.Item>
          </Form>
        </div>
      </Modal>
    </>
  );
}
