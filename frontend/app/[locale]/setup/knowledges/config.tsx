"use client";

import type React from "react";
import { useState, useEffect, useRef, useLayoutEffect } from "react";
import { useTranslation } from "react-i18next";

import { App, Modal } from "antd";
import { InfoCircleFilled, WarningFilled } from "@ant-design/icons";
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
import {
  SETUP_PAGE_CONTAINER,
  FLEX_TWO_COLUMN_LAYOUT,
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

  // Clear cache when component initializes
  useEffect(() => {
    localStorage.removeItem("preloaded_kb_data");
    localStorage.removeItem("kb_cache");
  }, []);

  // Get context values
  const {
    state: kbState,
    fetchKnowledgeBases,
    createKnowledgeBase,
    deleteKnowledgeBase,
    selectKnowledgeBase,
    setActiveKnowledgeBase,
    isKnowledgeBaseSelectable,
    refreshKnowledgeBaseData,
    loadUserSelectedKnowledgeBases,
    saveUserSelectedKnowledgeBases,
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

  // Create mode state
  const [isCreatingMode, setIsCreatingMode] = useState(false);
  const [newKbName, setNewKbName] = useState("");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [hasClickedUpload, setHasClickedUpload] = useState(false);
  const [showEmbeddingWarning, setShowEmbeddingWarning] = useState(false);
  const [showAutoDeselectModal, setShowAutoDeselectModal] = useState(false);
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
        fetchDocuments(knowledgeBase.id);
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
  const savedSelectedIdsRef = useRef<string[]>([]); // Save currently selected knowledge base IDs
  const savedKnowledgeBasesRef = useRef<any[]>([]); // Save current knowledge base list
  const hasUserInteractedRef = useRef(false); // Track whether user has interacted (prevent saving empty state during initial load)
  const hasCleanedRef = useRef(false); // Ensure auto-deselect runs only once per entry
  const shouldPersistSelectionRef = useRef(false); // Flag to persist selection after change

  // Listen for isActive state changes
  useLayoutEffect(() => {
    // Clear cache that might affect state
    localStorage.removeItem("preloaded_kb_data");
    localStorage.removeItem("kb_cache");

    const prevIsActive = prevIsActiveRef.current;

    // Mark ready to load when entering second page
    if ((prevIsActive === null || !prevIsActive) && isActive) {
      hasLoadedRef.current = false; // Reset loading state
      hasUserInteractedRef.current = false; // Reset interaction state to prevent incorrect saving
      hasCleanedRef.current = false; // Reset auto-clean flag on entering
    }

    // Save user configuration when leaving second page
    if (prevIsActive === true && !isActive) {
      // Only save after user has interacted to prevent saving empty state during initial load
      if (hasUserInteractedRef.current) {
        const saveConfig = async () => {
          localStorage.removeItem("preloaded_kb_data");
          localStorage.removeItem("kb_cache");

          try {
            await saveUserSelectedKnowledgeBases();
          } catch (error) {
            log.error("保存用户配置失败:", error);
          }
        };

        saveConfig();
      }

      hasLoadedRef.current = false; // Reset loading state
    }

    // Update ref
    prevIsActiveRef.current = isActive;
  }, [isActive]);

  // Save current state to ref in real-time to ensure access during unmount
  useEffect(() => {
    savedSelectedIdsRef.current = kbState.selectedIds;
    savedKnowledgeBasesRef.current = kbState.knowledgeBases;
  }, [kbState.selectedIds, kbState.knowledgeBases]);

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

  // Save logic when component unmounts
  useEffect(() => {
    return () => {
      // When component unmounts, if previously active and user has interacted, execute save
      if (prevIsActiveRef.current === true && hasUserInteractedRef.current) {
        // Use saved state instead of current potentially cleared state
        const selectedKbNames = savedKnowledgeBasesRef.current
          .filter((kb) => savedSelectedIdsRef.current.includes(kb.id))
          .map((kb) => kb.name);

        try {
          // Use fetch with keepalive to ensure request can be sent during page unload
          fetch(API_ENDPOINTS.tenantConfig.updateKnowledgeList, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...getAuthHeaders(),
            },
            body: JSON.stringify(selectedKbNames),
            keepalive: true,
          }).catch((error) => {
            log.error("卸载时保存失败:", error);
          });
        } catch (error) {
          log.error("卸载时保存请求异常:", error);
        }
      }
    };
  }, []);

  // Separately listen for knowledge base loading state, load user configuration when knowledge base loading is complete and in active state
  useEffect(() => {
    // Only execute when second page is active, knowledge base is loaded, and user configuration hasn't been loaded yet
    if (
      isActive &&
      kbState.knowledgeBases.length > 0 &&
      !kbState.isLoading &&
      !hasLoadedRef.current
    ) {
      const loadConfig = async () => {
        try {
          await loadUserSelectedKnowledgeBases();
          hasLoadedRef.current = true;
        } catch (error) {
          log.error("加载用户配置失败:", error);
        }
      };

      loadConfig();
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

    const currentSelected = kbState.selectedIds;
    if (currentSelected.length === 0) {
      hasCleanedRef.current = true;
      return;
    }

    // If both empty, clear all
    if (allowedModels.size === 0) {
      shouldPersistSelectionRef.current = true;
      kbDispatch({
        type: KNOWLEDGE_BASE_ACTION_TYPES.SELECT_KNOWLEDGE_BASE,
        payload: [],
      });
      hasUserInteractedRef.current = true;
      setShowAutoDeselectModal(true);
      hasCleanedRef.current = true;
      return;
    }

    const filtered = currentSelected.filter((id) => {
      const kb = kbState.knowledgeBases.find((k) => k.id === id);
      if (!kb) return false;
      return allowedModels.has(kb.embeddingModel);
    });

    if (filtered.length !== currentSelected.length) {
      shouldPersistSelectionRef.current = true;
      kbDispatch({
        type: KNOWLEDGE_BASE_ACTION_TYPES.SELECT_KNOWLEDGE_BASE,
        payload: filtered,
      });
      hasUserInteractedRef.current = true;
      setShowAutoDeselectModal(true);
    }

    hasCleanedRef.current = true;
  }, [
    isActive,
    kbState.isLoading,
    kbState.selectedIds,
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
      hasUserInteractedRef.current = true; // Mark user interaction
      setIsCreatingMode(false); // Reset creating mode
      setHasClickedUpload(false); // Reset upload button click state
    }

    // Whether switching knowledge base or not, need to get latest document information
    const isChangingKB =
      !kbState.activeKnowledgeBase || kb.id !== kbState.activeKnowledgeBase.id;

    // If switching knowledge base, update active state
    if (isChangingKB) {
      setActiveKnowledgeBase(kb);
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
      const documents = await knowledgeBaseService.getAllFiles(kb.id);

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
    hasUserInteractedRef.current = true; // Mark user interaction
    confirm({
      title: t("knowledgeBase.modal.deleteConfirm.title"),
      content: t("knowledgeBase.modal.deleteConfirm.content"),
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
      danger: true,
      onConfirm: async () => {
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

  // Handle knowledge base sync
  const handleSync = () => {
    // When manually syncing, force fetch latest data from server
    refreshKnowledgeBaseData(true)
      .then(() => {
        message.success(t("knowledgeBase.message.syncSuccess"));
      })
      .catch((error) => {
        message.error(
          t("knowledgeBase.message.syncError", {
            error: error.message || t("common.unknownError"),
          })
        );
      });
  };

  // Handle new knowledge base creation
  const handleCreateNew = () => {
    hasUserInteractedRef.current = true; // Mark user interaction
    // Generate default knowledge base name
    const defaultName = generateUniqueKbName(kbState.knowledgeBases);
    setNewKbName(defaultName);
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
      onConfirm: async () => {
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
          "elasticsearch"
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

        await uploadDocuments(newKB.id, filesToUpload);
        setUploadFiles([]);

        knowledgeBasePollingService
          .handleNewKnowledgeBaseCreation(
            newKB.name,
            0,
            filesToUpload.length,
            (populatedKB) => {
              setActiveKnowledgeBase(populatedKB);
              knowledgeBasePollingService.triggerKnowledgeBaseListUpdate(true);
            }
          )
          .catch((pollingError) => {
            log.error("Knowledge base creation polling failed:", pollingError);
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

  // As long as any document upload succeeds, immediately switch creation mode to false
  useEffect(() => {
    if (isCreatingMode && viewingDocuments.length > 0) {
      setIsCreatingMode(false);
    }
  }, [isCreatingMode, viewingDocuments.length]);

  // Handle knowledge base selection
  const handleSelectKnowledgeBase = (id: string) => {
    hasUserInteractedRef.current = true; // Mark user interaction
    selectKnowledgeBase(id);
    // Persist selection immediately after reducer updates state
    shouldPersistSelectionRef.current = true;

    // When selecting knowledge base also get latest data (low priority background operation)
    setTimeout(async () => {
      try {
        // Use lower priority to refresh data as this is not a critical operation
        await refreshKnowledgeBaseData(true);
      } catch (error) {
        log.error("刷新知识库数据失败:", error);
        // Error doesn't affect user experience
      }
    }, 500); // Delay execution, lower priority
  };

  // Persist user selection changes immediately when flagged
  useEffect(() => {
    if (!isActive) return;
    if (!shouldPersistSelectionRef.current) return;
    let cancelled = false;
    (async () => {
      try {
        await saveUserSelectedKnowledgeBases();
      } catch (error) {
        log.error("保存用户选择的知识库失败:", error);
      } finally {
        if (!cancelled) {
          shouldPersistSelectionRef.current = false;
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [kbState.selectedIds, isActive, saveUserSelectedKnowledgeBases]);

  // Update active knowledge base ID in polling service when component initializes or active knowledge base changes
  useEffect(() => {
    if (kbState.activeKnowledgeBase) {
      knowledgeBasePollingService.setActiveKnowledgeBase(
        kbState.activeKnowledgeBase.id
      );
    } else if (isCreatingMode && newKbName) {
      knowledgeBasePollingService.setActiveKnowledgeBase(newKbName);
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

  return (
    <>
      <div
        className="w-full mx-auto relative"
        style={{
          maxWidth: SETUP_PAGE_CONTAINER.MAX_WIDTH,
          padding: `0 ${SETUP_PAGE_CONTAINER.HORIZONTAL_PADDING}`,
        }}
        ref={contentRef}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {showEmbeddingWarning && (
          <div className="absolute inset-0 bg-gray-500/45 z-40" />
        )}
        <Modal
          open={showEmbeddingWarning && !!contentRef.current}
          title={null}
          footer={null}
          closable={false}
          maskClosable={false}
          mask={false}
          centered
          getContainer={() => contentRef.current || document.body}
          styles={{ body: { padding: 0 } }}
          rootClassName="kb-embedding-warning"
        >
          <div className="py-2">
            <div className="flex items-center">
              <WarningFilled className="text-yellow-500 mt-1 mr-2 text-3xl" />
              <div className="ml-3 mt-2">
                <div className="text-base text-gray-800 font-semibold">
                  {t("embedding.knowledgeBaseDisabledWarningModal.title")}
                </div>
              </div>
            </div>
          </div>
        </Modal>
        <Modal
          open={showAutoDeselectModal}
          title={t("embedding.knowledgeBaseAutoDeselectModal.title")}
          onOk={() => setShowAutoDeselectModal(false)}
          onCancel={() => setShowAutoDeselectModal(false)}
          okText={t("common.confirm")}
          cancelButtonProps={{ style: { display: "none" } }}
          centered
          getContainer={() => contentRef.current || document.body}
        >
          <div className="py-2">
            <div className="flex items-center px-4">
              <InfoCircleFilled
                className="text-blue-500 mt-1 mr-2"
                style={{ fontSize: "48px" }}
              />
              <div className="ml-3 mt-2">
                <div className="text-sm leading-6">
                  {t("embedding.knowledgeBaseAutoDeselectModal.content")}
                </div>
              </div>
            </div>
          </div>
        </Modal>
        <div
          className="flex h-full"
          style={{ gap: FLEX_TWO_COLUMN_LAYOUT.GAP }}
        >
          {/* Left knowledge base list - occupies 1/3 space */}
          <div style={{ width: FLEX_TWO_COLUMN_LAYOUT.LEFT_WIDTH }}>
            <KnowledgeBaseList
              knowledgeBases={kbState.knowledgeBases}
              selectedIds={kbState.selectedIds}
              activeKnowledgeBase={kbState.activeKnowledgeBase}
              currentEmbeddingModel={kbState.currentEmbeddingModel}
              isLoading={kbState.isLoading}
              onSelect={handleSelectKnowledgeBase}
              onClick={handleKnowledgeBaseClick}
              onDelete={handleDelete}
              onSync={handleSync}
              onCreateNew={handleCreateNew}
              isSelectable={isKnowledgeBaseSelectable}
              getModelDisplayName={(modelId) => modelId}
              containerHeight={SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT}
              onKnowledgeBaseChange={() => {}} // No need to trigger repeatedly here as it's already handled in handleKnowledgeBaseClick
            />
          </div>

          {/* Right content area - occupies 2/3 space, now unified with config.tsx style */}
          <div style={{ width: FLEX_TWO_COLUMN_LAYOUT.RIGHT_WIDTH }}>
            {isCreatingMode ? (
              <DocumentList
                documents={[]}
                onDelete={() => {}}
                isCreatingMode={true}
                knowledgeBaseName={newKbName}
                onNameChange={handleNameChange}
                containerHeight={SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT}
                hasDocuments={hasClickedUpload || docState.isUploading}
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
                knowledgeBaseName={viewingKbName}
                modelMismatch={
                  !isKnowledgeBaseSelectable(kbState.activeKnowledgeBase)
                }
                currentModel={kbState.currentEmbeddingModel || ""}
                knowledgeBaseModel={kbState.activeKnowledgeBase.embeddingModel}
                embeddingModelInfo={
                  !isKnowledgeBaseSelectable(kbState.activeKnowledgeBase)
                    ? t("document.modelMismatch.withModels", {
                        currentModel: kbState.currentEmbeddingModel || "",
                        knowledgeBaseModel:
                          kbState.activeKnowledgeBase.embeddingModel,
                      })
                    : undefined
                }
                containerHeight={SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT}
                hasDocuments={viewingDocuments.length > 0}
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
                className={STANDARD_CARD.BASE_CLASSES}
                style={{
                  height: SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT,
                  padding: STANDARD_CARD.PADDING,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
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
          </div>
        </div>
      </div>
    </>
  );
}
