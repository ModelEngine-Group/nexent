"use client";

import type React from "react";
import {
  useState,
  useEffect,
  useRef,
  useLayoutEffect,
  useCallback,
  useMemo,
} from "react";
import { useTranslation } from "react-i18next";

import { App, Modal, theme, Button, Input } from "antd";
import {
  ArrowLeftOutlined,
  ExclamationCircleFilled,
  WarningFilled,
} from "@ant-design/icons";
import {
  DOCUMENT_ACTION_TYPES,
  KNOWLEDGE_BASE_ACTION_TYPES,
} from "@/const/knowledgeBase";
import { ErrorCode } from "@/const/errorCode";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import log from "@/lib/logger";
import { formatKnowledgeBaseDeleteError } from "@/lib/knowledgeBaseDeleteError";
import { createKnowledgeBaseFilterKey } from "@/lib/knowledgeBaseViewport";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import knowledgeBasePollingService from "@/services/knowledgeBasePollingService";
import { isKnowledgeBaseFileSizeValid } from "@/services/uploadService";
import { KnowledgeBase } from "@/types/knowledgeBase";
import { useConfig } from "@/hooks/useConfig";
import { useModelList } from "@/hooks/model/useModelList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { SETUP_PAGE_CONTAINER, STANDARD_CARD } from "@/const/layoutConstants";
import { QUOTA_USAGE_CHANGED_EVENT } from "@/lib/quotaEvents";
import quotaService from "@/services/quotaService";
import type { KBQuotaStatus, QuotaUsageResponse } from "@/types/quota";

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

const EMBEDDING_MODEL_OPTION_DELIMITER = "::";
const normalizeEmbeddingModelType = (type: string) =>
  (type || "").trim().toLowerCase();

const isApiErrorCode = (error: unknown, code: string | number): boolean =>
  typeof error === "object" &&
  error !== null &&
  "code" in error &&
  String((error as { code?: unknown }).code) === String(code);

const toEmbeddingModelOptionValue = (displayName: string, type: string) =>
  `${displayName}${EMBEDDING_MODEL_OPTION_DELIMITER}${type}`;

const parseEmbeddingModelOptionValue = (value: string) => {
  const normalizedValue = (value || "").trim();
  const delimiterIndex = normalizedValue.lastIndexOf(
    EMBEDDING_MODEL_OPTION_DELIMITER
  );
  if (delimiterIndex >= 0) {
    const displayName = normalizedValue.slice(0, delimiterIndex);
    const type = normalizedValue.slice(
      delimiterIndex + EMBEDDING_MODEL_OPTION_DELIMITER.length
    );
    return {
      displayName: displayName || "",
      type: (type || "").trim(),
      isMultimodal:
        normalizeEmbeddingModelType(type || "") === "multi_embedding",
    };
  }
  return {
    displayName: normalizedValue || "",
    type: "",
    isMultimodal: false,
  };
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
  const {
    modelConfig,
    data: configData,
    invalidateConfig,
    config,
    updateConfig,
    saveConfig,
  } = useConfig();
  const { token } = theme.useToken();
  const { user } = useAuthorizationContext();

  const [quotaUsage, setQuotaUsage] = useState<QuotaUsageResponse | null>(null);

  const loadQuotaUsage = useCallback(
    async (forceRefresh = false) => {
      if (!user?.tenantId) {
        setQuotaUsage(null);
        return;
      }

      try {
        const usage = await quotaService.getQuotaUsage(
          user.tenantId,
          forceRefresh,
          true
        );
        setQuotaUsage(usage);
      } catch (error) {
        log.warn("Failed to load knowledge base quota usage:", error);
      }
    },
    [user?.tenantId]
  );

  useEffect(() => {
    void loadQuotaUsage();
    const handleQuotaUsageChanged = () => {
      void loadQuotaUsage(true);
    };
    window.addEventListener(QUOTA_USAGE_CHANGED_EVENT, handleQuotaUsageChanged);
    return () =>
      window.removeEventListener(
        QUOTA_USAGE_CHANGED_EVENT,
        handleQuotaUsageChanged
      );
  }, [loadQuotaUsage]);

  // Get available embedding models for knowledge base creation
  const { models } = useModelList({ enabled: true });

  // Clear cache when component initializes
  useEffect(() => {
    localStorage.removeItem("preloaded_kb_data");
    localStorage.removeItem("kb_cache");
    loadDataMateConfig();
  }, []);

  // Load DataMate URL configuration from React Query cached data
  const loadDataMateConfig = () => {
    if (configData?.app && typeof configData.app.datamateUrl === "string") {
      setDataMateUrl(configData.app.datamateUrl);
    } else {
      setDataMateUrl("");
    }

    if (
      configData?.app &&
      typeof configData.app.modelEngineEnabled === "boolean"
    ) {
      setModelEngineEnabled(configData.app.modelEngineEnabled);
    }

    return configData?.app?.datamateUrl || "";
  };

  // Get context values
  const {
    state: kbState,
    fetchKnowledgeBases,
    loadMoreKnowledgeBases,
    listPagination,
    isLoadingMore,
    createKnowledgeBase,
    deleteKnowledgeBase,
    setActiveKnowledgeBase,
    updateKnowledgeBase,
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
  const [newKbDescription, setNewKbDescription] = useState("");
  const [newKbIngroupPermission, setNewKbIngroupPermission] =
    useState<string>("READ_ONLY");
  const [newKbGroupIds, setNewKbGroupIds] = useState<number[]>([]);
  const [newKbPreserveSourceFile, setNewKbPreserveSourceFile] =
    useState<boolean>(true);
  const [newKbQuotaBytes, setNewKbQuotaBytes] = useState<number | null>(null);
  const [newKbEmbeddingModel, setNewKbEmbeddingModel] = useState<string>(""); // Selected embedding model for new KB
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [hasClickedUpload, setHasClickedUpload] = useState(false);
  const [showEmbeddingWarning, setShowEmbeddingWarning] = useState(false);
  const [showAutoDeselectModal, setShowAutoDeselectModal] = useState(false);
  const [newlyCreatedKbId, setNewlyCreatedKbId] = useState<string | null>(null); // Track newly created KB waiting for documents

  // Search and filter state
  const [searchQuery, setSearchQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<string[]>([]);
  const [modelFilter, setModelFilter] = useState<string[]>([]);
  const lastRequestedFilterKeyRef = useRef(
    createKnowledgeBaseFilterKey(searchQuery, sourceFilter, modelFilter)
  );
  const initialLoadStartedRef = useRef(false);
  const initialCapacityRequestRef = useRef(false);
  const initialPageSizeRef = useRef(1);
  const [initialListPending, setInitialListPending] = useState(true);
  const contentRef = useRef<HTMLDivElement | null>(null);

  const handleViewportCapacityChange = useCallback(
    (capacity: number, hasMeasuredRows: boolean) => {
      const pageSize = Math.max(1, Math.ceil(capacity));
      initialPageSizeRef.current = pageSize;
      const loadedCount = kbState.knowledgeBases.length;
      if (initialLoadStartedRef.current && !listPagination.hasMore) {
        setInitialListPending(false);
        return;
      }
      if (
        kbState.isLoading ||
        isLoadingMore ||
        initialCapacityRequestRef.current ||
        (initialLoadStartedRef.current &&
          (!hasMeasuredRows || loadedCount >= pageSize))
      ) {
        return;
      }

      initialLoadStartedRef.current = true;
      initialCapacityRequestRef.current = true;
      setInitialListPending(true);
      void fetchKnowledgeBases(false, true, true, {
        keyword: searchQuery,
        sources: sourceFilter,
        models: modelFilter,
        limit: pageSize,
      }).finally(() => {
        initialCapacityRequestRef.current = false;
        setInitialListPending(false);
      });
    },
    [
      fetchKnowledgeBases,
      kbState.isLoading,
      kbState.knowledgeBases.length,
      isLoadingMore,
      listPagination.hasMore,
      modelFilter,
      searchQuery,
      sourceFilter,
    ]
  );

  useEffect(() => {
    const filterKey = createKnowledgeBaseFilterKey(
      searchQuery,
      sourceFilter,
      modelFilter
    );
    if (filterKey === lastRequestedFilterKeyRef.current) return;

    const timer = window.setTimeout(() => {
      lastRequestedFilterKeyRef.current = filterKey;
      fetchKnowledgeBases(true, false, false, {
        keyword: searchQuery,
        sources: sourceFilter,
        models: modelFilter,
        limit: initialPageSizeRef.current,
      });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [fetchKnowledgeBases, modelFilter, searchQuery, sourceFilter]);

  const availableEmbeddingModels = useMemo(() => {
    const embeddingRelatedModels = models.filter(
      (model) => model.type === "embedding" || model.type === "multi_embedding"
    );
    const availableKeys = new Set(
      embeddingRelatedModels
        .filter((model) => model.connect_status === "available")
        .map((model) => `${model.displayName}::${model.type}`)
    );

    return embeddingRelatedModels.filter((model) => {
      if (model.connect_status === "available") {
        return true;
      }

      // For paired records created from a multi-embedding model, mirror availability by display name.
      if (model.type === "embedding") {
        return availableKeys.has(`${model.displayName}::multi_embedding`);
      }
      if (model.type === "multi_embedding") {
        return availableKeys.has(`${model.displayName}::embedding`);
      }
      return false;
    });
  }, [models]);

  const resolveEmbeddingModelId = useCallback(
    ({
      displayName,
      modelType,
    }: {
      displayName?: string;
      modelType?: string;
    }) => {
      const normalizedDisplayName = (displayName || "").trim();
      const normalizedModelType = normalizeEmbeddingModelType(modelType || "");
      if (!normalizedDisplayName || !normalizedModelType) return undefined;

      return availableEmbeddingModels.find(
        (model) =>
          model.displayName === normalizedDisplayName &&
          model.type === normalizedModelType
      )?.id;
    },
    [availableEmbeddingModels]
  );

  // Open warning modal only when neither embedding nor multi-embedding is configured.
  useEffect(() => {
    const singleEmbeddingModelName =
      modelConfig?.embedding?.displayName?.trim();
    const multiEmbeddingModelName =
      modelConfig?.multiEmbedding?.displayName?.trim();
    setShowEmbeddingWarning(
      !singleEmbeddingModelName && !multiEmbeddingModelName
    );
  }, [
    modelConfig?.embedding?.displayName,
    modelConfig?.multiEmbedding?.displayName,
  ]);

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
  // Listen for isActive state changes
  useLayoutEffect(() => {
    // Clear cache that might affect state
    localStorage.removeItem("preloaded_kb_data");
    localStorage.removeItem("kb_cache");
  }, [isActive]);

  // Generate the default name from knowledge bases visible to the current user.
  const generateVisibleKbName = (existingKbs: KnowledgeBase[]): string => {
    const baseNamePrefix = t("knowledgeBase.name.new");
    const existingNames = new Set(existingKbs.map((kb) => kb.name));

    let counter = 1;
    while (true) {
      const candidate =
        counter === 1 ? baseNamePrefix : `${baseNamePrefix}${counter - 1}`;

      if (!existingNames.has(candidate)) {
        return candidate;
      }

      counter++;
    }
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
          log.error("鑾峰彇鐭ヨ瘑搴撴渶鏂版暟鎹け璐?", error);
        }
      }, 100);
    } catch (error) {
      log.error("鑾峰彇鏂囨。鍒楄〃澶辫触:", error);
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
      const validFiles = files.filter(isKnowledgeBaseFileSizeValid);
      if (validFiles.length !== files.length) {
        message.error(t("knowledgeBase.upload.fileTooLarge"));
      }
      if (validFiles.length > 0) {
        setUploadFiles(validFiles);
        if (!isCreatingMode) {
          void handleFileUpload(validFiles);
        }
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
          message.error(
            formatKnowledgeBaseDeleteError(
              error,
              t,
              "knowledgeBase.message.deleteError"
            )
          );
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
      const currentConfig = config;
      const updatedConfig = {
        ...currentConfig,
        app: {
          ...currentConfig.app,
          datamateUrl: dataMateUrl,
        },
      };

      updateConfig(updatedConfig);

      const ok = await saveConfig(updatedConfig as any);
      if (!ok) {
        message.error(t("knowledgeBase.message.dataMateConfigError"));
        return;
      }

      message.success(t("knowledgeBase.message.dataMateConfigSaved"));
      setDataMateUrl(dataMateUrl);
      await handleSync();
      setShowDataMateConfigModal(false);
    } catch (error) {
      log.error("Failed to save DataMate configuration:", error);
      message.error(t("knowledgeBase.message.dataMateConfigError"));
    }
  };

  // Handle new knowledge base creation
  const handleCreateNew = () => {
    // Clear active knowledge base selection when entering create mode
    // This prevents issues with chunk loading from previously selected KB
    setActiveKnowledgeBase(null);

    // Generate the default name without probing hidden tenant knowledge bases.
    const defaultName = generateVisibleKbName(kbState.knowledgeBases);
    setNewKbName(defaultName);
    setNewKbDescription("");
    setNewKbIngroupPermission("READ_ONLY");
    setNewKbGroupIds([]);
    setNewKbPreserveSourceFile(true);
    // Set default embedding model:
    // 1) configured embedding model, 2) configured multimodal model, 3) first available option.
    // Use displayName to match availableEmbeddingModels and KB embeddingModel.
    const configEmbeddingModel =
      modelConfig?.embedding?.displayName?.trim() || "";
    const configMultiEmbeddingModel =
      modelConfig?.multiEmbedding?.displayName?.trim() || "";
    const preferredModel = [
      { modelName: configEmbeddingModel, type: "embedding" },
      { modelName: configMultiEmbeddingModel, type: "multi_embedding" },
    ].find(
      ({ modelName, type }) =>
        !!modelName &&
        availableEmbeddingModels.some(
          (model) => model.displayName === modelName && model.type === type
        )
    );
    const defaultModel =
      (preferredModel &&
        toEmbeddingModelOptionValue(
          preferredModel.modelName,
          preferredModel.type
        )) ||
      (availableEmbeddingModels[0]
        ? toEmbeddingModelOptionValue(
            availableEmbeddingModels[0].displayName,
            availableEmbeddingModels[0].type
          )
        : "");
    setNewKbEmbeddingModel(defaultModel);
    setIsCreatingMode(true);
    setHasClickedUpload(false); // Reset upload button click state
    setUploadFiles([]); // Reset upload files array, clear all pending upload files
  };

  // Handle document deletion
  const handleDeleteDocument = (docId: string, fileId?: string) => {
    const kbId = kbState.activeKnowledgeBase?.id;
    if (!kbId) return;
    if (kbState.activeKnowledgeBase?.permission === "READ_ONLY") {
      message.error(t("errorCode.000202", "Access forbidden."));
      return;
    }

    confirm({
      title: t("document.modal.deleteConfirm.title"),
      content: t("document.modal.deleteConfirm.content"),
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
      danger: true,
      onOk: async () => {
        try {
          await deleteDocument(kbId, docId, fileId);
          message.success(t("document.message.deleteSuccess"));
        } catch (error) {
          message.error(t("document.message.deleteError"));
        }
      },
    });
  };

  // Create the knowledge base from the modal, then upload the selected files if any.
  const handleFileUpload = async (selectedFiles: File[] = uploadFiles) => {
    if (
      !isCreatingMode &&
      kbState.activeKnowledgeBase?.permission === "READ_ONLY"
    ) {
      message.error(t("errorCode.000202", "Access forbidden."));
      return;
    }
    if (!isCreatingMode && !selectedFiles.length) {
      message.warning(t("document.message.noFiles"));
      return;
    }
    const filesToUpload = selectedFiles;

    if (isCreatingMode) {
      if (!newKbName || newKbName.trim() === "") {
        message.warning(t("knowledgeBase.message.nameRequired"));
        return;
      }
      if (!newKbEmbeddingModel) {
        message.warning(t("knowledgeBase.message.embeddingModelRequired"));
        return;
      }
      if (!selectedFiles.length) {
        message.warning(t("knowledgeBase.message.noFiles"));
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

        const parsedSelectedModel =
          parseEmbeddingModelOptionValue(newKbEmbeddingModel);
        const selectedModelId = resolveEmbeddingModelId({
          displayName: parsedSelectedModel.displayName,
          modelType: parsedSelectedModel.type,
        });
        if (selectedModelId === undefined) {
          throw new Error("Selected embedding model could not be resolved");
        }

        const newKB = await createKnowledgeBase(
          newKbName.trim(),
          newKbDescription.trim() || t("knowledgeBase.description.default"),
          "elasticsearch",
          newKbIngroupPermission,
          newKbGroupIds,
          selectedModelId,
          newKbPreserveSourceFile,
          newKbQuotaBytes
        );

        setIsCreatingMode(false);
        setActiveKnowledgeBase(newKB);
        knowledgeBasePollingService.setActiveKnowledgeBase(newKB.id);
        setHasClickedUpload(false);
        setNewlyCreatedKbId(filesToUpload.length > 0 ? newKB.id : null); // Mark this KB as newly created when files need processing

        if (!filesToUpload.length) {
          setUploadFiles([]);
          knowledgeBasePollingService.triggerKnowledgeBaseListUpdate(true);
          return;
        }

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
        message.error(
          isApiErrorCode(error, 409)
            ? t("knowledgeBase.message.nameExists", {
                name: newKbName.trim(),
              })
            : isApiErrorCode(error, ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED)
              ? t("quota.personalKbUploadBlocked")
              : isApiErrorCode(
                    error,
                    ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE
                  )
                ? t(
                    `errorCode.${ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE}`
                  )
                : isApiErrorCode(error, 413)
                  ? t("quota.uploadBlocked")
                  : t("knowledgeBase.message.createUploadError")
        );
        setHasClickedUpload(false);
        // Clear the waiting flag so a failed upload cannot leave the page
        // stuck on "waiting for task creation".
        setNewlyCreatedKbId(null);
        throw error;
      }
      return;
    }

    const kbId = kbState.activeKnowledgeBase?.id;
    if (!kbId) {
      message.warning(t("knowledgeBase.message.selectFirst"));
      return;
    }

    try {
      const activeKbModelId = resolveEmbeddingModelId({
        displayName: kbState.activeKnowledgeBase?.embeddingModel,
        modelType: kbState.activeKnowledgeBase?.is_multimodal
          ? "multi_embedding"
          : "embedding",
      });

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
      message.error(
        isApiErrorCode(error, ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED)
          ? t("quota.personalKbUploadBlocked")
          : isApiErrorCode(
                error,
                ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE
              )
            ? t(`errorCode.${ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE}`)
            : isApiErrorCode(error, 413)
              ? t("quota.uploadBlocked")
              : t("document.message.uploadError")
      );
      throw error;
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

  const activeKnowledgeBaseQuota: KBQuotaStatus | undefined = useMemo(() => {
    const activeKnowledgeBase = kbState.activeKnowledgeBase;
    if (!activeKnowledgeBase) return undefined;

    const indexName = activeKnowledgeBase.index_name || activeKnowledgeBase.id;
    return quotaUsage?.breakdown?.find(
      (quota) => quota.index_name === indexName
    );
  }, [kbState.activeKnowledgeBase, quotaUsage]);

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

  const handleCloseCreateModal = () => {
    setIsCreatingMode(false);
    setHasClickedUpload(false);
    setUploadFiles([]);
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
        <div className="w-full h-full">
          {!kbState.activeKnowledgeBase ? (
            <>
              <KnowledgeBaseList
                knowledgeBases={kbState.knowledgeBases}
                activeKnowledgeBase={kbState.activeKnowledgeBase}
                isLoading={kbState.isLoading}
                isLoadingMore={isLoadingMore}
                syncLoading={kbState.syncLoading}
                totalCount={listPagination.total}
                hasMore={listPagination.hasMore}
                estimatedRowHeight={listPagination.estimatedRowHeight}
                estimatedItemHeights={listPagination.estimatedItemHeights}
                availableSources={listPagination.facets.sources}
                availableModels={listPagination.facets.models}
                quotaUsage={quotaUsage}
                onLoadMore={loadMoreKnowledgeBases}
                serverFiltered
                initialLoadPending={initialListPending}
                onViewportCapacityChange={handleViewportCapacityChange}
                onClick={handleKnowledgeBaseClick}
                onDelete={handleDelete}
                onSync={handleSync}
                onCreateNew={handleCreateNew}
                onDataMateConfig={handleDataMateConfig}
                showDataMateConfig={modelEngineEnabled}
                getModelDisplayName={(modelId) => modelId}
                containerHeight={SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT}
                onKnowledgeBaseChange={() => {}} // No need to trigger repeatedly here as it's already handled in handleKnowledgeBaseClick
                onKnowledgeBaseUpdate={(updatedKnowledgeBase) => {
                  // Update knowledge base in list and active knowledge base
                  updateKnowledgeBase(updatedKnowledgeBase);
                  if (
                    kbState.activeKnowledgeBase &&
                    kbState.activeKnowledgeBase.id === updatedKnowledgeBase.id
                  ) {
                    setActiveKnowledgeBase(updatedKnowledgeBase);
                  }
                }}
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
              <Modal
                open={isCreatingMode}
                title={null}
                footer={
                  <div className="flex justify-end gap-3">
                    <Button
                      onClick={handleCloseCreateModal}
                      disabled={hasClickedUpload || docState.isUploading}
                    >
                      {t("common.cancel")}
                    </Button>
                    <Button
                      type="primary"
                      loading={hasClickedUpload || docState.isUploading}
                      disabled={
                        !newKbName.trim() ||
                        !newKbEmbeddingModel ||
                        !uploadFiles.length ||
                        hasClickedUpload ||
                        docState.isUploading
                      }
                      onClick={() => void handleFileUpload(uploadFiles)}
                    >
                      {t("knowledgeBase.create.submit")}
                    </Button>
                  </div>
                }
                width={640}
                centered
                maskClosable={false}
                destroyOnHidden
                onCancel={handleCloseCreateModal}
                styles={{
                  container: { padding: 0 },
                  body: { padding: 0 },
                  footer: {
                    margin: 0,
                    padding: "12px 20px 16px",
                    borderTop: "1px solid #f0f0f0",
                  },
                }}
                getContainer={() => contentRef.current || document.body}
              >
                <div className="overflow-visible">
                  <DocumentList
                    key="create-mode"
                    documents={[]}
                    onDelete={() => {}}
                    knowledgeBaseSource=""
                    isCreatingMode={true}
                    knowledgeBaseId=""
                    knowledgeBaseName={newKbName}
                    onNameChange={handleNameChange}
                    knowledgeBaseDescription={newKbDescription}
                    onDescriptionChange={setNewKbDescription}
                    selectedFiles={uploadFiles}
                    containerHeight={SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT}
                    hasDocuments={hasClickedUpload || docState.isUploading}
                    // Group permission and user groups for create mode
                    ingroupPermission={newKbIngroupPermission}
                    onIngroupPermissionChange={setNewKbIngroupPermission}
                    selectedGroupIds={newKbGroupIds}
                    onSelectedGroupIdsChange={setNewKbGroupIds}
                    preserveSourceFile={newKbPreserveSourceFile}
                    onPreserveSourceFileChange={setNewKbPreserveSourceFile}
                    quotaLimitBytes={newKbQuotaBytes}
                    onQuotaLimitBytesChange={setNewKbQuotaBytes}
                    // Embedding model for create mode
                    availableEmbeddingModels={availableEmbeddingModels}
                    selectedEmbeddingModel={newKbEmbeddingModel}
                    onEmbeddingModelChange={setNewKbEmbeddingModel}
                    // Upload related props
                    isDragging={uiState.isDragging}
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    onFileSelect={handleFileSelect}
                    onUpload={handleFileUpload}
                    isUploading={docState.isUploading}
                  />
                </div>
              </Modal>
            </>
          ) : (
            <div className="flex h-full min-h-0 flex-col gap-3">
              <div className="flex shrink-0 items-center">
                <Button
                  type="text"
                  className="!px-1 text-gray-500 hover:!text-blue-600"
                  icon={<ArrowLeftOutlined />}
                  onClick={() => {
                    setActiveKnowledgeBase(null);
                    setIsCreatingMode(false);
                    setHasClickedUpload(false);
                    setUploadFiles([]);
                  }}
                >
                  {t("knowledgeBase.page.back")}
                </Button>
              </div>
              <div className="min-h-0 flex-1">
                <DocumentList
                  key={`kb-${kbState.activeKnowledgeBase.id}`}
                  documents={viewingDocuments}
                  onDelete={handleDeleteDocument}
                  knowledgeBaseSource={kbState.activeKnowledgeBase?.source}
                  knowledgeBaseId={kbState.activeKnowledgeBase.id}
                  knowledgeBaseName={viewingKbName}
                  quotaStatus={activeKnowledgeBaseQuota}
                  knowledgeBaseModel={
                    kbState.activeKnowledgeBase.embeddingModel
                  }
                  containerHeight={SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT}
                  hasDocuments={viewingDocuments.length > 0}
                  isNewlyCreatedAndWaiting={isNewlyCreatedAndWaiting}
                  onChunkCountChange={() => {
                    // Trigger knowledge base list update to refresh chunk count
                    knowledgeBasePollingService.triggerKnowledgeBaseListUpdate(
                      true
                    );
                  }}
                  onRefresh={() => {
                    if (kbState.activeKnowledgeBase) {
                      void fetchDocuments(
                        kbState.activeKnowledgeBase.id,
                        true,
                        kbState.activeKnowledgeBase.source
                      );
                    }
                  }}
                  permission={kbState.activeKnowledgeBase?.permission}
                  summaryFrequency={
                    kbState.activeKnowledgeBase?.summaryFrequency
                  }
                  onSummaryFrequencyChange={(frequency) => {
                    if (kbState.activeKnowledgeBase) {
                      knowledgeBaseService
                        .updateSummaryFrequency(
                          kbState.activeKnowledgeBase.id,
                          frequency
                        )
                        .then(() => {
                          const updatedKB: KnowledgeBase = {
                            ...kbState.activeKnowledgeBase!,
                            summaryFrequency: frequency,
                          };
                          updateKnowledgeBase(updatedKB);
                          setActiveKnowledgeBase(updatedKB);
                        })
                        .catch((error) => {
                          log.error(
                            "Failed to update summary frequency:",
                            error
                          );
                        });
                    }
                  }}
                  // Upload related props
                  isDragging={uiState.isDragging}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  onFileSelect={handleFileSelect}
                  onUpload={handleFileUpload}
                  isUploading={docState.isUploading}
                />
              </div>
            </div>
          )}
        </div>
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
          <div className="space-y-3">
            <label className="block text-sm font-medium text-gray-700">
              {t("knowledgeBase.modal.dataMateConfig.urlLabel")}
            </label>
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
            {dataMateUrlError && (
              <div className="text-sm text-red-600">{dataMateUrlError}</div>
            )}
          </div>
        </div>
      </Modal>
    </>
  );
}
