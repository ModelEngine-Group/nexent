// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import React, {
  useState,
  useRef,
  forwardRef,
  useImperativeHandle,
  useEffect,
  useMemo,
  useCallback,
} from "react";
import { useTranslation } from "react-i18next";

import {
  Input,
  Button,
  App,
  Card,
  Select,
  Popover,
  Progress,
  Modal,
  Spin,
  Tabs,
  Tooltip,
  Pagination,
} from "antd";
const { TextArea } = Input;
import { FilterOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  Clock3,
  FileText,
  FolderOpen,
  Layers,
  Search,
  Sparkles,
  Trash2,
  Upload,
  Pencil,
  AlertCircle,
  Settings2,
  Tag,
} from "lucide-react";
import { NAME_CHECK_STATUS } from "@/const/agentConfig";
import { MarkdownRenderer } from "@/components/common/markdownRenderer";
import { FilePreviewDrawer } from "@/components/common/filePreviewDrawer";

import {
  UI_CONFIG,
  COLUMN_WIDTHS,
  DOCUMENT_NAME_CONFIG,
  LAYOUT,
  DOCUMENT_STATUS,
} from "@/const/knowledgeBase";
import { FrequencyOption } from "@/const/scheduler";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { modelService } from "@/services/modelService";
import { getTenantDefaultGroupId } from "@/services/groupService";
import { extractObjectNameFromUrl } from "@/services/storageService";
import type { Document, KnowledgeBase } from "@/types/knowledgeBase";
import type { KBQuotaStatus } from "@/types/quota";
import type {
  TagDocumentPredicate,
  TagDocumentBatchStatusEntry,
} from "@/types/tagManagement";
import { ModelOption } from "@/types/modelConfig";
import { formatFileSize } from "@/lib/utils";
import { formatDateOrFallback } from "@/lib/date";
import { getKnowledgeBaseQuotaDisplay } from "@/lib/knowledgeBaseQuota";
import { unwrapKnowledgeBaseSummary } from "@/lib/knowledgeBaseSummary";
import log from "@/lib/logger";
import { useInferenceFieldSpecs } from "@/hooks/model/useInferenceFieldSpecs";
import {
  ModelAdvancedSettings,
  ModelAdvancedSettingsValue,
  advancedSettingsValueFromRecord,
  buildModelOverrideEntry,
} from "../../../models/components/model/ModelAdvancedSettings";
import { useConfig } from "@/hooks/useConfig";
import { useGroupDetails, useGroupList } from "@/hooks/group/useGroupList";

import DocumentStatus from "./DocumentStatus";
import DocumentChunk from "./DocumentChunk";
import UploadArea from "../upload/UploadArea";
import ResourceTagAssignmentModal from "@/components/tag/ResourceTagAssignmentModal";
import TagChips from "@/components/tag/TagChips";
import TagDefinitionManagementModal from "@/components/tag/TagDefinitionManagementModal";
import TagFilterControls from "@/components/tag/TagFilterControls";
import KnowledgeBaseDetailTags from "../knowledge/KnowledgeBaseDetailTags";
import { KnowledgeBaseEditModal } from "../knowledge/KnowledgeBaseEditModal";
import KnowledgeBaseAccessCard from "../knowledge/KnowledgeBaseAccessCard";
import KnowledgeBaseCreateSettings from "../knowledge/KnowledgeBaseCreateSettings";

import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";
import { tagManagementApi } from "@/services/tagManagementService";
import { useDocumentContext } from "../../contexts/DocumentContext";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { Can } from "@/components/permission/Can";

interface DocumentListProps {
  documents: Document[];
  onDelete: (id: string, fileId?: string) => void;
  // Knowledge base source, e.g. "nexent" or "datamate"
  knowledgeBaseSource?: string;
  // User-facing knowledge base name (display name)
  knowledgeBaseName?: string;
  catalogKnowledgeBase?: KnowledgeBase;
  onDeleteKnowledgeBase?: () => void;
  onCatalogKnowledgeBaseChange?: (knowledgeBase: KnowledgeBase) => void;
  onCatalogRefresh?: () => void;
  // Internal knowledge base ID / Elasticsearch index name
  knowledgeBaseId?: string;
  modelMismatch?: boolean;
  currentModel?: string;
  knowledgeBaseModel?: string;
  embeddingModelInfo?: string;
  isCreatingMode?: boolean;
  onNameChange?: (name: string) => void;
  hasDocuments?: boolean;
  isNewlyCreatedAndWaiting?: boolean; // New prop to track newly created KB waiting for documents
  onChunkCountChange?: () => void; // Callback when chunk count changes
  onRefresh?: () => void;

  // Group permission and user groups for create mode
  ingroupPermission?: string;
  onIngroupPermissionChange?: (value: string) => void;
  selectedGroupIds?: number[];
  onSelectedGroupIdsChange?: (values: number[]) => void;
  // Embedding model for create mode
  availableEmbeddingModels?: ModelOption[];
  selectedEmbeddingModel?: string;
  onEmbeddingModelChange?: (value: string) => void;
  // v2.6.0: per-KB embedding model params override
  // Shape: { "<model_id>": { temperature?, top_p?, extra_params? } }
  embeddingModelParamsOverride?: Record<
    string,
    {
      temperature?: number | null;
      top_p?: number | null;
      extra_params?: Record<string, unknown> | null;
    }
  >;
  onEmbeddingModelParamsOverrideChange?: (
    value: Record<
      string,
      {
        temperature?: number | null;
        top_p?: number | null;
        extra_params?: Record<string, unknown> | null;
      }
    >
  ) => void;
  isMultimodal?: boolean;
  quotaLimitBytes?: number | null;
  onQuotaLimitBytesChange?: (value: number | null) => void;
  quotaStatus?: KBQuotaStatus;
  onMultimodalChange?: (value: boolean) => void;
  permission?: string; // User's permission for this knowledge base (READ_ONLY, EDIT, etc.)
  preserveSourceFile?: boolean;
  onPreserveSourceFileChange?: (value: boolean) => void;

  // Auto-summary frequency
  summaryFrequency?: string | null;
  onSummaryFrequencyChange?: (frequency: string | null) => void;

  // Upload related props
  isDragging?: boolean;
  onDragOver?: (e: React.DragEvent) => void;
  onDragLeave?: (e: React.DragEvent) => void;
  onDrop?: (e: React.DragEvent) => void;
  onFileSelect: (files: File[]) => void;
  selectedFiles?: File[];
  onUpload?: (files: File[]) => Promise<void>;
  isUploading?: boolean;
  // Tenant storage quota, derived by the parent so this view never re-reads it.
  uploadStorageBlocked?: boolean;
  uploadStorageBlockedMessage?: string;
}

export interface DocumentListRef {
  uppy: any;
}

const DocumentListContainer = forwardRef<DocumentListRef, DocumentListProps>(
  (
    {
      documents,
      onDelete,
      knowledgeBaseSource = "",
      knowledgeBaseId = "",
      knowledgeBaseName = "",
      catalogKnowledgeBase,
      onDeleteKnowledgeBase,
      onCatalogKnowledgeBaseChange,
      onCatalogRefresh,
      modelMismatch = false,
      currentModel = "",
      knowledgeBaseModel = "",
      embeddingModelInfo = "",
      isCreatingMode = false,
      onNameChange,
      hasDocuments = false,
      isNewlyCreatedAndWaiting = false, // New prop
      onChunkCountChange,
      onRefresh,
      // Group permission and user groups for create mode
      ingroupPermission,
      onIngroupPermissionChange,
      selectedGroupIds,
      onSelectedGroupIdsChange,
      // Embedding model for create mode
      availableEmbeddingModels,
      selectedEmbeddingModel,
      onEmbeddingModelChange,
      // v2.6.0: per-KB embedding model params override
      embeddingModelParamsOverride,
      onEmbeddingModelParamsOverrideChange,
      isMultimodal = false,
      onMultimodalChange,
      permission,
      preserveSourceFile = true,
      onPreserveSourceFileChange,
      quotaLimitBytes = null,
      onQuotaLimitBytesChange,
      quotaStatus,
      // Auto-summary frequency
      summaryFrequency,
      onSummaryFrequencyChange,

      // Upload related props
      isDragging = false,
      onDragOver,
      onDragLeave,
      onDrop,
      onFileSelect,
      selectedFiles = [],
      onUpload,
      isUploading = false,
      uploadStorageBlocked = false,
      uploadStorageBlockedMessage,
    },
    ref
  ) => {
    const { message } = App.useApp();
    const uploadAreaRef = useRef<any>(null);
    const isDataMate = (knowledgeBaseSource || "").toLowerCase() === "datamate";
    const { state: docState } = useDocumentContext();
    const { modelConfig } = useConfig();
    const { user, getAccessibleGroupIds } = useAuthorizationContext();
    const tenantId = user?.tenantId || null;

    // Fetch tenant groups and limit selections to accessible groups (all for admin roles).
    const { data: groupData } = useGroupList(tenantId);
    const accessibleGroupIds = useMemo(
      () => getAccessibleGroupIds(),
      [getAccessibleGroupIds]
    );
    const { groups } = useGroupDetails(
      groupData?.groups ?? [],
      accessibleGroupIds
    );

    // Preview drawer state

    const [selectedFile, setSelectedFile] = useState<{
      objectName: string;
      fileName: string;
      fileType?: string;
      fileSize?: number;
    } | null>(null);
    const handlePreviewClose = useCallback(() => {
      setSelectedFile(null);
    }, []);

    // Use fixed height instead of percentage
    const uploadHeight = UI_CONFIG.UPLOAD_COMPONENT_HEIGHT;
    const groupsEdited = useRef(false);
    const [assignTarget, setAssignTarget] = useState<{
      docId: string;
      canEdit: boolean;
    } | null>(null);
    // Tag metadata is only read after the user opens a tag-related UI.
    const [tagsUiRequested, setTagsUiRequested] = useState(false);
    const {
      data: tagLibraries,
      loading: tagLibrariesLoading,
      error: tagLibrariesError,
      refresh: refreshTagLibraries,
    } = useTagLibraries({ enabled: tagsUiRequested });
    const documentLibrary =
      tagLibraries?.find((lib) => lib.bucket_key === "knowledge_content") ??
      null;
    const {
      data: assignDefinitions,
      loading: assignDefinitionsLoading,
      refresh: refreshAssignDefinitions,
    } = useTagDefinitions(documentLibrary?.bucket_id ?? null, {
      enabled: tagsUiRequested,
    });
    const [documentPage, setDocumentPage] = useState(1);
    const [documentPageSize, setDocumentPageSize] = useState(10);
    const [documentSearch, setDocumentSearch] = useState("");
    const [chunkDocumentId, setChunkDocumentId] = useState<string>();
    const [editingKnowledgeBase, setEditingKnowledgeBase] = useState(false);

    const [tagManagementOpen, setTagManagementOpen] = useState(false);
    const [documentPredicates, setDocumentPredicates] = useState<
      TagDocumentPredicate[]
    >([]);
    const [documentBatchStatus, setDocumentBatchStatus] = useState<
      TagDocumentBatchStatusEntry[]
    >([]);

    const activeDocumentIds = useMemo(() => {
      if (documentPredicates.length === 0) return null;
      return new Set(documentBatchStatus.map((entry) => entry.document_id));
    }, [documentBatchStatus, documentPredicates]);

    const projectionByDocument = useMemo(() => {
      const map = new Map<string, TagDocumentBatchStatusEntry>();
      for (const entry of documentBatchStatus) {
        map.set(entry.document_id, entry);
      }
      return map;
    }, [documentBatchStatus]);

    // A new knowledge base or a new tag filter starts from the first page.
    useEffect(() => {
      setDocumentPage(1);
    }, [knowledgeBaseId, documentPredicates]);

    // Batch-fetch document tag assignment and projection status for the
    // currently visible knowledge base. Local documents do not need the tag
    // metadata to render their projection badges.
    useEffect(() => {
      const visibleIds = documents.map((doc) => doc.id);
      if (
        isCreatingMode ||
        !knowledgeBaseId ||
        visibleIds.length === 0 ||
        (isDataMate && !documentLibrary)
      ) {
        setDocumentBatchStatus([]);
        return;
      }
      let cancelled = false;
      const timeoutId = window.setTimeout(() => {
        void tagManagementApi
          .getDocumentBatchStatus(
            {
              provider: "local",
              knowledgeBaseId,
              documentIds: visibleIds.slice(0, 200),
            },
            documentPredicates
          )
          .then((entries) => {
            if (!cancelled) setDocumentBatchStatus(entries);
          })
          .catch((error) => {
            if (!cancelled) {
              log.error("Failed to load document tag status:", error);
              setDocumentBatchStatus([]);
            }
          });
      }, 250);
      return () => {
        cancelled = true;
        window.clearTimeout(timeoutId);
      };
    }, [
      documentLibrary,
      documentPredicates,
      documents,
      isCreatingMode,
      isDataMate,
      knowledgeBaseId,
    ]);

    // Sort documents by create_time (latest first)
    const sortedDocuments = [...documents].sort((a, b) => {
      const aTime = new Date(a.create_time).getTime();
      const bTime = new Date(b.create_time).getTime();
      const safeA = Number.isNaN(aTime) ? 0 : aTime;
      const safeB = Number.isNaN(bTime) ? 0 : bTime;
      return safeB - safeA;
    });

    // Get file icon
    const getFileIcon = (type: string): string => {
      switch (type.toLowerCase()) {
        case "pdf":
          return "📄";
        case "word":
          return "📝";
        case "excel":
          return "📊";
        case "powerpoint":
          return "📑";
        default:
          return "📃";
      }
    };

    // Build model mismatch info
    const getMismatchInfo = (): string => {
      if (embeddingModelInfo) return embeddingModelInfo;
      if (currentModel && knowledgeBaseModel) {
        return t("document.modelMismatch.withModels", {
          currentModel,
          knowledgeBaseModel,
        });
      }
      return t("document.modelMismatch.general");
    };

    // Expose uppy instance to parent component
    useImperativeHandle(ref, () => ({
      uppy: uploadAreaRef.current?.uppy,
    }));
    const showSummary =
      !isCreatingMode &&
      !isDataMate &&
      Boolean(catalogKnowledgeBase && knowledgeBaseId);
    const [showChunk, setShowChunk] = React.useState(false);
    const [nameStatus, setNameStatus] = useState<string>("available");
    const [summary, setSummary] = useState("");
    const [savedSummary, setSavedSummary] = useState("");
    const [isLoadingSummary, setIsLoadingSummary] = useState(showSummary);
    const [isSummarizing, setIsSummarizing] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [summarySaveFailed, setSummarySaveFailed] = useState(false);
    const summarySavePending = useRef(false);
    const [selectedModel, setSelectedModel] = useState<number>(0);
    const [availableModels, setAvailableModels] = useState<ModelOption[]>([]);
    const [isLoadingModels, setIsLoadingModels] = useState(false);
    const [frequencyOptions, setFrequencyOptions] = useState<FrequencyOption[]>(
      []
    );
    // v2.6.0: embedding model advanced settings modal state
    const [embeddingAdvancedOpen, setEmbeddingAdvancedOpen] = useState(false);
    const [embeddingAdvancedValue, setEmbeddingAdvancedValue] =
      useState<ModelAdvancedSettingsValue>({});
    const { t } = useTranslation();
    const { specs: inferenceSpecs } = useInferenceFieldSpecs({
      enabled: embeddingAdvancedOpen,
    });
    const {
      hasQuota,
      totalCapacity: quotaTotal,
      usagePercent: quotaUsagePercent,
    } = getKnowledgeBaseQuotaDisplay(quotaStatus, t);
    const documentListClassName = isCreatingMode ? "w-full" : "min-w-0";

    // Determine if user has read-only permission
    const isReadOnlyMode = permission === "READ_ONLY";
    const canToggleMultimodal =
      isCreatingMode && typeof onMultimodalChange === "function";

    // v2.6.0: resolve the currently selected embedding model to a ModelOption
    // for the advanced settings modal. The Select value is "displayName::type".
    const selectedEmbeddingModelOption = React.useMemo<
      ModelOption | undefined
    >(() => {
      if (!selectedEmbeddingModel || !availableEmbeddingModels)
        return undefined;
      const delimiterIndex = selectedEmbeddingModel.lastIndexOf("::");
      if (delimiterIndex < 0) return undefined;
      const displayName = selectedEmbeddingModel.slice(0, delimiterIndex);
      const modelType = selectedEmbeddingModel.slice(delimiterIndex + 2);
      return availableEmbeddingModels.find(
        (m) => m.displayName === displayName && m.type === modelType
      );
    }, [selectedEmbeddingModel, availableEmbeddingModels]);

    // Sync the advanced settings form value when opening the modal or switching models
    React.useEffect(() => {
      if (!embeddingAdvancedOpen) return;
      if (!selectedEmbeddingModelOption) {
        setEmbeddingAdvancedValue({});
        return;
      }
      const existingOverride =
        embeddingModelParamsOverride?.[
          String(selectedEmbeddingModelOption.id)
        ] ?? {};
      const hasOverride = Object.keys(existingOverride).length > 0;
      // When no per-KB override exists yet, fall back to the model-level defaults
      // (temperature/top_p/extra_params, including __custom__) so the user can
      // see the currently effective values. Once an override exists, it takes
      // precedence.
      const formRecord = hasOverride
        ? existingOverride
        : {
            temperature: selectedEmbeddingModelOption.temperature,
            top_p: selectedEmbeddingModelOption.topP,
            extra_params: selectedEmbeddingModelOption.extraParams,
          };
      setEmbeddingAdvancedValue(
        advancedSettingsValueFromRecord(
          formRecord,
          inferenceSpecs,
          selectedEmbeddingModelOption.type
        )
      );
    }, [
      embeddingAdvancedOpen,
      selectedEmbeddingModelOption,
      embeddingModelParamsOverride,
      inferenceSpecs,
    ]);

    const handleEmbeddingAdvancedChange = (
      next: ModelAdvancedSettingsValue
    ) => {
      setEmbeddingAdvancedValue(next);
      if (
        !selectedEmbeddingModelOption ||
        !onEmbeddingModelParamsOverrideChange
      )
        return;
      const entry = buildModelOverrideEntry(next);
      const current = embeddingModelParamsOverride ?? {};
      const updated = { ...current };
      if (Object.keys(entry).length === 0) {
        delete updated[String(selectedEmbeddingModelOption.id)];
      } else {
        updated[String(selectedEmbeddingModelOption.id)] = entry;
      }
      onEmbeddingModelParamsOverrideChange(updated);
    };

    // Initialize default group ID when entering create mode
    React.useEffect(() => {
      if (
        !isCreatingMode ||
        !tenantId ||
        !onSelectedGroupIdsChange ||
        groupsEdited.current
      )
        return;
      let active = true;
      void getTenantDefaultGroupId(tenantId)
        .then((defaultGroupId) => {
          if (
            active &&
            !groupsEdited.current &&
            defaultGroupId &&
            accessibleGroupIds.includes(defaultGroupId)
          ) {
            onSelectedGroupIdsChange([defaultGroupId]);
          }
        })
        .catch((error) =>
          log.error("Failed to get tenant default group:", error)
        );
      return () => {
        active = false;
      };
    }, [
      isCreatingMode,
      tenantId,
      accessibleGroupIds,
      onSelectedGroupIdsChange,
    ]);

    const embeddingModelsForOptions = availableEmbeddingModels || [];
    const availableEmbeddingModelKeys = new Set(
      embeddingModelsForOptions
        .filter((model) => model.connect_status === "available")
        .map((model) => `${model.displayName}::${model.type}`)
    );
    const isEmbeddingModelSelectable = (model: ModelOption): boolean => {
      if (model.connect_status === "available") return true;
      if (model.type === "embedding") {
        return availableEmbeddingModelKeys.has(
          `${model.displayName}::multi_embedding`
        );
      }
      if (model.type === "multi_embedding") {
        return availableEmbeddingModelKeys.has(
          `${model.displayName}::embedding`
        );
      }
      return false;
    };

    // Load frequency options from backend API
    useEffect(() => {
      const loadFrequencyOptions = async () => {
        if (showSummary && frequencyOptions.length === 0) {
          try {
            const options =
              await knowledgeBaseService.fetchSummaryFrequencyOptions();
            setFrequencyOptions(options);
          } catch (error) {
            log.error("Failed to load frequency options:", error);
            // Fallback to default options if API fails
            setFrequencyOptions([
              {
                value: "disabled",
                label: t("knowledgeBase.tag.autoSummary.off"),
              },
            ]);
          }
        }
      };
      loadFrequencyOptions();
    }, [showSummary, frequencyOptions.length, t]);

    // Load available models when showing detail
    useEffect(() => {
      const loadModels = async () => {
        if (showSummary && availableModels.length === 0) {
          setIsLoadingModels(true);
          try {
            const models = (await modelService.getLLMModels()).filter(
              (model) => model.connect_status === "available"
            );
            setAvailableModels(models);

            // Determine initial selection order:
            // 1) Knowledge base's own configured model (server-side config)
            // 2) Globally configured default LLM from quick setup (create mode or no KB model)
            // 3) First available model

            let initialModelId: number | null = null;

            // 1) Knowledge base model (if provided)
            if (knowledgeBaseModel) {
              const matchedByName = models.find(
                (m) => m.name === knowledgeBaseModel
              );
              const matchedByDisplay = matchedByName
                ? null
                : models.find((m) => m.displayName === knowledgeBaseModel);
              if (matchedByName) {
                initialModelId = matchedByName.id;
              } else if (matchedByDisplay) {
                initialModelId = matchedByDisplay.id;
              }
            }

            // 2) Fallback to globally configured default LLM
            if (initialModelId === null) {
              const configuredDisplayName = modelConfig?.llm?.displayName || "";
              const configuredModelName = modelConfig?.llm?.modelName || "";

              const matchedByDisplay = models.find(
                (m) =>
                  m.displayName === configuredDisplayName &&
                  configuredDisplayName !== ""
              );
              const matchedByName = matchedByDisplay
                ? null
                : models.find(
                    (m) =>
                      m.name === configuredModelName &&
                      configuredModelName !== ""
                  );

              if (matchedByDisplay) {
                initialModelId = matchedByDisplay.id;
              } else if (matchedByName) {
                initialModelId = matchedByName.id;
              }
            }

            // 3) Final fallback to first available model
            if (initialModelId === null) {
              if (models.length > 0) {
                initialModelId = models[0].id;
              }
            }

            if (initialModelId !== null) {
              setSelectedModel(initialModelId);
            } else {
              message.warning(
                t("businessLogic.config.error.noAvailableModels")
              );
            }
          } catch (error) {
            log.error("Failed to load models:", error);
            message.error(t("modelConfig.error.loadListFailed"));
          } finally {
            setIsLoadingModels(false);
          }
        }
      };
      loadModels();
    }, [showSummary]);

    useEffect(() => {
      if (!showSummary) return;
      let cancelled = false;
      void knowledgeBaseService
        .getSummary(knowledgeBaseId)
        .then((result) => {
          if (cancelled) return;
          const editorText = unwrapKnowledgeBaseSummary(result);
          setSummary(editorText);
          setSavedSummary(editorText);
        })
        .catch((error) => {
          if (cancelled) return;
          log.error(t("knowledgeBase.error.getSummary"), error);
          message.error(t("document.summary.error"));
        })
        .finally(() => {
          if (!cancelled) setIsLoadingSummary(false);
        });
      return () => {
        cancelled = true;
      };
    }, [showSummary, knowledgeBaseId, message, t]);

    const persistSummary = async (
      content: string,
      successMessage = t("document.summary.saveSuccess")
    ) => {
      if (summarySavePending.current) return;
      summarySavePending.current = true;
      setIsSaving(true);
      setSummarySaveFailed(false);
      try {
        await knowledgeBaseService.changeSummary(knowledgeBaseId, content);
        setSavedSummary(content);
        onCatalogRefresh?.();
        message.success(successMessage);
      } catch (error) {
        setSummarySaveFailed(true);
        log.error(t("document.summary.saveError"), error);
        message.error(
          error instanceof Error
            ? error.message
            : t("document.summary.saveFailed")
        );
      } finally {
        summarySavePending.current = false;
        setIsSaving(false);
      }
    };

    // Generate a new summary and save it only after the stream finishes.
    const handleAutoSummary = async () => {
      if (summarySavePending.current || isSummarizing) return;
      if (!knowledgeBaseId) {
        message.warning(t("document.summary.selectKnowledgeBase"));
        return;
      }

      setIsSummarizing(true);
      setSummary("");

      try {
        const result = await knowledgeBaseService.summaryIndex(
          knowledgeBaseId,
          1000,
          (newText) => {
            setSummary((prev) => prev + newText);
          },
          selectedModel
        );
        const editorText = unwrapKnowledgeBaseSummary(result);
        if (
          !editorText.trim() ||
          /^Failed to generate summary(?::| for )/m.test(editorText)
        ) {
          throw new Error(t("knowledgeBase.summary.notGenerated"));
        }
        setSummary(editorText);
        await persistSummary(
          editorText,
          t("document.summary.generatedAndSaved")
        );
      } catch (error) {
        setSummary(summary);
        message.error(t("document.summary.error"));
        log.error(t("document.summary.error"), error);
      } finally {
        setIsSummarizing(false);
      }
    };

    const saveEditedSummary = async (content: string) => {
      if (
        !knowledgeBaseId ||
        isReadOnlyMode ||
        isSummarizing ||
        (content === savedSummary && !summarySaveFailed)
      )
        return;
      if (!content.trim()) {
        setSummary(savedSummary);
        setSummarySaveFailed(false);
        message.warning(t("document.summary.emptyContent"));
        return;
      }

      await persistSummary(content);
    };

    const normalizedDocumentSearch = documentSearch.trim().toLocaleLowerCase();
    const filteredDocuments = sortedDocuments.filter(
      (doc) =>
        (!activeDocumentIds || activeDocumentIds.has(doc.id)) &&
        (!normalizedDocumentSearch ||
          doc.name.toLocaleLowerCase().includes(normalizedDocumentSearch))
    );
    const filteredDocumentCount = filteredDocuments.length;
    const documentPageCount = Math.max(
      1,
      Math.ceil(filteredDocumentCount / documentPageSize)
    );
    const currentDocumentPage = Math.min(documentPage, documentPageCount);
    const pagedDocuments = isDataMate
      ? filteredDocuments
      : filteredDocuments.slice(
          (currentDocumentPage - 1) * documentPageSize,
          currentDocumentPage * documentPageSize
        );

    // Deleting or filtering can shrink the list; converge on the last page
    // without resetting the page while polling refreshes documents.
    useEffect(() => {
      if (documentPage > documentPageCount) setDocumentPage(documentPageCount);
    }, [documentPage, documentPageCount]);

    return (
      <div
        className={`relative flex w-full flex-col overflow-x-hidden shadow-sm ${
          isCreatingMode ? "" : "h-full min-h-0 overflow-y-auto p-1"
        }`}
      >
        {!isCreatingMode && (
          <header className="mb-4 flex flex-wrap items-start justify-between gap-4 border-b border-[var(--color-border-separator)] pb-4">
            <div className="flex min-w-0 gap-3">
              <span className="flex size-12 shrink-0 items-center justify-center rounded-lg bg-[var(--color-select)] text-[var(--color-brand)]">
                <FolderOpen size={24} aria-hidden />
              </span>
              <div className="min-w-0 space-y-2">
                <div className="flex flex-wrap items-center gap-1">
                  <h2 className="break-words text-xl font-semibold text-[var(--color-text-primary)]">
                    {knowledgeBaseName}
                  </h2>
                  {showSummary &&
                    !isReadOnlyMode &&
                    onCatalogKnowledgeBaseChange &&
                    (!knowledgeBaseSource ||
                      knowledgeBaseSource === "nexent" ||
                      knowledgeBaseSource === "elasticsearch") && (
                      <Can permission="kb:update">
                        <Button
                          type="text"
                          size="small"
                          aria-label={t("tenantResources.knowledgeBase.edit")}
                          title={t("tenantResources.knowledgeBase.edit")}
                          icon={<Pencil size={16} aria-hidden />}
                          onClick={() => setEditingKnowledgeBase(true)}
                        />
                      </Can>
                    )}
                </div>
                {catalogKnowledgeBase && (
                  <div className="flex items-center gap-1 text-xs text-[var(--color-text-secondary)]">
                    <Clock3 size={14} aria-hidden />
                    {t("knowledgeBase.tag.updatedAt", {
                      date: formatDateOrFallback(
                        catalogKnowledgeBase.updatedAt ??
                          catalogKnowledgeBase.createdAt
                      ),
                    })}
                  </div>
                )}
                {knowledgeBaseModel && (
                  <div className="flex flex-wrap gap-x-3 text-sm">
                    <span className="text-[var(--color-text-secondary)]">
                      {t("knowledgeBase.create.field.embeddingModel")}
                    </span>
                    <span className="break-all">{knowledgeBaseModel}</span>
                  </div>
                )}
                {quotaStatus && (
                  <div className="max-w-md text-sm">
                    <div className="flex flex-wrap gap-x-3">
                      <span className="text-[var(--color-text-secondary)]">
                        {t("knowledgeBase.capacity.title")}
                      </span>
                      <span>
                        {quotaStatus.actual_readable ||
                          formatFileSize(quotaStatus.actual_bytes)}{" "}
                        / {quotaTotal}
                      </span>
                    </div>
                    {hasQuota && (
                      <Progress
                        percent={quotaUsagePercent}
                        size="small"
                        showInfo={false}
                        status={
                          quotaStatus.kb_warning_level === "exceeded"
                            ? "exception"
                            : "normal"
                        }
                      />
                    )}
                  </div>
                )}
                {modelMismatch && (
                  <div className="text-sm text-[var(--color-warning)]">
                    {getMismatchInfo()}
                  </div>
                )}
                {catalogKnowledgeBase && (
                  <KnowledgeBaseDetailTags
                    knowledgeBaseId={knowledgeBaseId}
                    readOnly={isReadOnlyMode}
                    onChange={onCatalogRefresh}
                  />
                )}
              </div>
            </div>
            {!isDataMate && (
              <div className="flex flex-wrap items-center gap-2">
                {!isReadOnlyMode && (
                  <UploadArea
                    indexName={knowledgeBaseId || knowledgeBaseName}
                    onFileSelect={onFileSelect}
                    onUpload={onUpload}
                    isUploading={isUploading}
                    disabled={uploadStorageBlocked || !knowledgeBaseId}
                    modelMismatch={modelMismatch}
                    renderTrigger={({ disabled, loading }) => (
                      <Tooltip
                        title={
                          uploadStorageBlocked
                            ? uploadStorageBlockedMessage ||
                              t("quota.uploadBlocked")
                            : undefined
                        }
                      >
                        <span className="inline-flex">
                          <Button
                            type="primary"
                            icon={<Upload size={16} aria-hidden />}
                            disabled={disabled}
                            loading={loading}
                            onClick={() => setShowChunk(false)}
                          >
                            {t("knowledgeBase.detail.upload")}
                          </Button>
                        </span>
                      </Tooltip>
                    )}
                  />
                )}
                {onRefresh && (
                  <Button
                    icon={<ReloadOutlined spin={isUploading} />}
                    onClick={onRefresh}
                    disabled={isUploading || docState.isLoadingDocuments}
                  >
                    {t("common.refresh")}
                  </Button>
                )}
                {!isReadOnlyMode && onDeleteKnowledgeBase && (
                  <Can permission="kb:delete">
                    <Button
                      danger
                      icon={<Trash2 size={16} aria-hidden />}
                      onClick={onDeleteKnowledgeBase}
                    >
                      {t("knowledgeBase.detail.delete")}
                    </Button>
                  </Can>
                )}
              </div>
            )}
          </header>
        )}
        <div
          className={
            showSummary
              ? "grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(280px,28%)]"
              : undefined
          }
        >
          <div className="min-w-0">
            {!isCreatingMode && !isDataMate && (
              <>
                <Tabs
                  activeKey={showChunk ? "chunks" : "documents"}
                  onChange={(key) => {
                    setChunkDocumentId(undefined);
                    setShowChunk(key === "chunks");
                  }}
                  items={[
                    {
                      key: "documents",
                      label: t("knowledgeBase.tag.documents", {
                        count: documents.length,
                      }),
                      icon: <FileText size={16} aria-hidden />,
                    },
                    {
                      key: "chunks",
                      label:
                        `${t("document.button.detail")} ${catalogKnowledgeBase?.chunkCount ?? ""}`.trim(),
                      icon: <Layers size={16} aria-hidden />,
                    },
                  ]}
                  tabBarExtraContent={
                    !showChunk && (
                      <Input
                        aria-label={t("knowledgeBase.detail.documentSearch")}
                        placeholder={t("knowledgeBase.detail.documentSearch")}
                        prefix={<Search size={16} aria-hidden />}
                        allowClear
                        value={documentSearch}
                        onChange={(event) => {
                          setDocumentSearch(event.target.value);
                          setDocumentPage(1);
                        }}
                        className="!max-w-56"
                      />
                    )
                  }
                />
                {!showChunk && (
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <Popover
                      trigger="click"
                      placement="bottomRight"
                      title={t("document.tagFilter.placeholder")}
                      onOpenChange={(open) => {
                        if (open) setTagsUiRequested(true);
                      }}
                      content={
                        <div className="w-64">
                          {assignDefinitions ? (
                            <>
                              <TagFilterControls
                                definitions={assignDefinitions}
                                value={documentPredicates}
                                onChange={setDocumentPredicates}
                              />
                              {documentPredicates.length > 0 && (
                                <Button
                                  size="small"
                                  block
                                  className="mt-2"
                                  onClick={() => setDocumentPredicates([])}
                                >
                                  {t("document.tagFilter.clear")}
                                </Button>
                              )}
                            </>
                          ) : tagLibrariesLoading ||
                            assignDefinitionsLoading ? (
                            <div className="flex justify-center py-2">
                              <Spin size="small" />
                            </div>
                          ) : (
                            <Button
                              size="small"
                              block
                              onClick={() => {
                                if (tagLibrariesError)
                                  void refreshTagLibraries();
                                else void refreshAssignDefinitions();
                              }}
                            >
                              {t("repository.common.retry")}
                            </Button>
                          )}
                        </div>
                      }
                    >
                      <Button
                        icon={<FilterOutlined />}
                        onClick={(event) => event.stopPropagation()}
                      >
                        {t("document.tagFilter.placeholder")}
                      </Button>
                    </Popover>
                    {!isReadOnlyMode && (
                      <Button
                        icon={<Tag size={16} />}
                        onClick={() => {
                          setTagsUiRequested(true);
                          setTagManagementOpen(true);
                        }}
                      >
                        {t("knowledgeBase.button.tagManagement")}
                      </Button>
                    )}
                  </div>
                )}
              </>
            )}

            {/* Document list */}

            <div
              className={documentListClassName}
              onDragOver={(e) => {
                if (!isCreatingMode && knowledgeBaseName) {
                  return;
                }
                e.preventDefault();
                e.stopPropagation();
              }}
              onDrop={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
              onDragEnter={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
              onDragLeave={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
            >
              {showChunk ? (
                <div className="flex h-[65vh] min-h-96 flex-col">
                  <div className="min-h-0 flex-1">
                    <DocumentChunk
                      knowledgeBaseName={knowledgeBaseName}
                      knowledgeBaseId={knowledgeBaseId || knowledgeBaseName}
                      documents={documents}
                      initialDocumentId={chunkDocumentId}
                      knowledgeBaseChunkCount={catalogKnowledgeBase?.chunkCount}
                      onChunkCountChange={onChunkCountChange}
                      permission={permission}
                    />
                  </div>
                </div>
              ) : docState.isLoadingDocuments || isNewlyCreatedAndWaiting ? (
                <div className="flex items-center justify-center h-full border border-gray-200 rounded-md">
                  <div className="text-center">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-2"></div>
                    <p className="text-sm text-gray-600">
                      {isNewlyCreatedAndWaiting
                        ? t("document.status.waitingForTask")
                        : t("document.status.loadingList")}
                    </p>
                  </div>
                </div>
              ) : isCreatingMode ? (
                <div className="flex flex-col">
                  {hasDocuments ||
                  isUploading ||
                  docState.isLoadingDocuments ? (
                    <div className="flex min-h-[220px] items-center justify-center rounded-md border border-gray-200">
                      <div className="text-center">
                        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-2"></div>
                        <p className="text-sm text-gray-600">
                          {t("document.status.waitingForTask")}
                        </p>
                      </div>
                    </div>
                  ) : (
                    <div>
                      <section className="space-y-5 px-6 py-5">
                        <h3 className="text-base font-semibold">
                          {t("knowledgeBase.create.basicInfo")}
                        </h3>
                        <div>
                          <label
                            htmlFor="kb-create-name"
                            className="mb-2 block text-sm font-medium"
                          >
                            {t("knowledgeBase.create.field.name")}{" "}
                            <span className="text-red-500">*</span>
                          </label>
                          <Input
                            id="kb-create-name"
                            value={knowledgeBaseName}
                            onChange={(e) =>
                              onNameChange && onNameChange(e.target.value)
                            }
                            placeholder={t(
                              "knowledgeBase.create.namePlaceholder",
                              "例如：产品知识中心"
                            )}
                            size="large"
                            status={
                              nameStatus ===
                                NAME_CHECK_STATUS.EXISTS_IN_TENANT ||
                              nameStatus ===
                                NAME_CHECK_STATUS.EXISTS_IN_OTHER_TENANT
                                ? "error"
                                : undefined
                            }
                            autoFocus
                            disabled={
                              hasDocuments ||
                              isUploading ||
                              docState.isLoadingDocuments
                            }
                          />
                          {(nameStatus === NAME_CHECK_STATUS.EXISTS_IN_TENANT ||
                            nameStatus ===
                              NAME_CHECK_STATUS.EXISTS_IN_OTHER_TENANT) && (
                            <div className="mt-2 flex items-center gap-1 text-xs text-red-500">
                              <AlertCircle size={14} />
                              <span>
                                {t("tenantResources.knowledgeBase.nameExists")}
                              </span>
                            </div>
                          )}
                        </div>

                        {onEmbeddingModelChange && (
                          <div>
                            <label
                              htmlFor="kb-create-model"
                              className="mb-2 block text-sm font-medium"
                            >
                              {t("knowledgeBase.create.field.embeddingModel")}{" "}
                              <span className="text-red-500">*</span>
                            </label>
                            <div className="flex flex-wrap items-center gap-2">
                              <Select
                                id="kb-create-model"
                                value={selectedEmbeddingModel}
                                onChange={onEmbeddingModelChange}
                                className="min-w-40 flex-1"
                                size="large"
                                placeholder={
                                  t(
                                    "knowledgeBase.create.embeddingModelPlaceholder"
                                  ) || "Select embedding model"
                                }
                                allowClear={false}
                                options={[
                                  {
                                    label: t(
                                      "modelConfig.option.embeddingModel"
                                    ),
                                    options: embeddingModelsForOptions
                                      .filter(
                                        (model) => model.type === "embedding"
                                      )
                                      .map((model) => ({
                                        value: [
                                          model.displayName,
                                          model.type,
                                        ].join("::"),
                                        label: model.displayName,
                                        disabled:
                                          !isEmbeddingModelSelectable(model),
                                      })),
                                  },
                                  {
                                    label: t(
                                      "modelConfig.option.multiEmbeddingModel"
                                    ),
                                    options: embeddingModelsForOptions
                                      .filter(
                                        (model) =>
                                          model.type === "multi_embedding"
                                      )
                                      .map((model) => ({
                                        value: [
                                          model.displayName,
                                          model.type,
                                        ].join("::"),
                                        label: model.displayName,
                                        disabled:
                                          !isEmbeddingModelSelectable(model),
                                      })),
                                  },
                                ].filter((group) => group.options.length > 0)}
                              />
                              <Button
                                icon={<Settings2 size={14} />}
                                onClick={() => setEmbeddingAdvancedOpen(true)}
                                disabled={
                                  !selectedEmbeddingModel ||
                                  !availableEmbeddingModels ||
                                  availableEmbeddingModels.length === 0
                                }
                              >
                                {t("knowledgeBase.create.modelParameters")}
                              </Button>
                            </div>
                            {selectedEmbeddingModelOption && (
                              <dl className="mt-2 grid grid-cols-2 gap-px overflow-hidden rounded-lg bg-[var(--color-select)] sm:grid-cols-4">
                                {[
                                  [
                                    "knowledgeBase.create.vectorDimension",
                                    selectedEmbeddingModelOption.maxTokens,
                                  ],
                                  [
                                    "modelConfig.slider.expectedChunkSize",
                                    selectedEmbeddingModelOption.expectedChunkSize,
                                  ],
                                  [
                                    "modelConfig.slider.maximumChunkSize",
                                    selectedEmbeddingModelOption.maximumChunkSize,
                                  ],
                                  [
                                    "modelConfig.input.chunkingBatchSize",
                                    selectedEmbeddingModelOption.chunkingBatchSize,
                                  ],
                                ].map(([label, value]) => (
                                  <div
                                    key={label}
                                    className="min-w-0 px-3 py-2"
                                  >
                                    <dt className="text-xs text-[var(--color-text-secondary)]">
                                      {t(String(label))}
                                    </dt>
                                    <dd className="text-sm font-medium">
                                      {value || "—"}
                                    </dd>
                                  </div>
                                ))}
                              </dl>
                            )}
                            <p className="mt-2 text-sm text-[var(--color-text-secondary)]">
                              {t(
                                selectedEmbeddingModelOption?.type ===
                                  "multi_embedding"
                                  ? "knowledgeBase.create.multimodalModelHint"
                                  : "knowledgeBase.create.modelHint"
                              )}
                            </p>
                          </div>
                        )}

                        <div className="shrink-0">
                          <div className="mb-2 text-sm font-medium">
                            {t("knowledgeBase.create.uploadTitle")}{" "}
                            <span className="text-red-500">*</span>
                          </div>
                          <div className="min-h-36">
                            <UploadArea
                              ref={uploadAreaRef}
                              onFileSelect={onFileSelect}
                              onUpload={onUpload || (async () => {})}
                              isUploading={isUploading}
                              isDragging={isDragging}
                              onDragOver={onDragOver}
                              onDragLeave={onDragLeave}
                              onDrop={onDrop}
                              disabled={uploadStorageBlocked || isReadOnlyMode}
                              disabledMessage={
                                uploadStorageBlocked
                                  ? uploadStorageBlockedMessage ||
                                    t(
                                      "quota.uploadBlocked",
                                      "Uploads are blocked - storage limit reached"
                                    )
                                  : undefined
                              }
                              componentHeight={uploadHeight}
                              isCreatingMode
                              indexName={
                                knowledgeBaseId || "new-knowledge-base"
                              }
                              newKnowledgeBaseName={knowledgeBaseName}
                              modelMismatch={modelMismatch}
                              onNameStatusChange={setNameStatus}
                              selectedFiles={selectedFiles}
                              autoUpload={false}
                            />
                          </div>
                          <p className="mt-2 text-sm text-[var(--color-text-secondary)]">
                            {t("knowledgeBase.create.uploadHint")}
                          </p>
                        </div>
                      </section>
                      <KnowledgeBaseCreateSettings
                        preserveSourceFile={preserveSourceFile}
                        onPreserveSourceFileChange={onPreserveSourceFileChange}
                        quotaLimitBytes={quotaLimitBytes}
                        onQuotaLimitBytesChange={onQuotaLimitBytesChange}
                        permission={ingroupPermission}
                        onPermissionChange={(value) => {
                          if (value === "PRIVATE") {
                            groupsEdited.current = true;
                            onSelectedGroupIdsChange?.([]);
                          }
                          onIngroupPermissionChange?.(value);
                        }}
                        groups={groups}
                        selectedGroupIds={selectedGroupIds ?? []}
                        onGroupsChange={(ids) => {
                          groupsEdited.current = true;
                          onSelectedGroupIdsChange?.(ids);
                        }}
                      />
                    </div>
                  )}
                </div>
              ) : filteredDocuments.length > 0 ? (
                <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-gray-200">
                  <div className="min-h-0 flex-1 overflow-auto">
                    <table className="min-w-full bg-white">
                      <thead className="sticky top-0 z-10 bg-gray-50">
                        <tr>
                          <th
                            className={`px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500 w-[${COLUMN_WIDTHS.NAME}]`}
                          >
                            {t("document.table.header.name")}
                          </th>
                          {!isDataMate && (
                            <th className="min-w-[180px] px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                              {t("document.table.header.tags")}
                            </th>
                          )}
                          <th
                            className={`px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500 w-[${COLUMN_WIDTHS.STATUS}]`}
                          >
                            {t("document.table.header.status")}
                          </th>
                          {!isDataMate && (
                            <th className="px-4 py-3 text-right text-xs font-medium text-gray-500">
                              {t("knowledgeBase.detail.chunkCount")}
                            </th>
                          )}
                          {!isDataMate && (
                            <th
                              className={`px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500 w-[${COLUMN_WIDTHS.SIZE}]`}
                            >
                              {t("document.table.header.size")}
                            </th>
                          )}
                          <th
                            className={`px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500 w-[${COLUMN_WIDTHS.DATE}]`}
                          >
                            {t("document.table.header.date")}
                          </th>
                          {!isDataMate && (
                            <th
                              className={`px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500 w-[${COLUMN_WIDTHS.ACTION}]`}
                            >
                              {t("document.table.header.action")}
                            </th>
                          )}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {pagedDocuments.map((doc) => (
                          <tr
                            key={doc.id}
                            className="transition-colors hover:bg-gray-50"
                          >
                            <td className="px-4 py-3">
                              <div className="flex items-center">
                                <span
                                  className={`${LAYOUT.ICON_MARGIN} ${LAYOUT.ICON_SIZE}`}
                                >
                                  {getFileIcon(doc.type)}
                                </span>
                                <span
                                  className={`${LAYOUT.TEXT_SIZE} font-medium text-gray-800 truncate max-w-[${DOCUMENT_NAME_CONFIG.MAX_WIDTH}] whitespace-${DOCUMENT_NAME_CONFIG.WHITE_SPACE} overflow-${DOCUMENT_NAME_CONFIG.OVERFLOW} text-${DOCUMENT_NAME_CONFIG.TEXT_OVERFLOW}`}
                                  title={doc.name}
                                >
                                  {doc.name}
                                </span>
                                {(() => {
                                  const entry = projectionByDocument.get(
                                    doc.id
                                  );
                                  const status =
                                    entry?.projection_status?.status;
                                  if (
                                    status === "pending" ||
                                    status === "failed"
                                  ) {
                                    return (
                                      <Tooltip
                                        title={t(
                                          status === "failed"
                                            ? "document.tagProjection.failed"
                                            : "document.tagProjection.pending"
                                        )}
                                      >
                                        <span
                                          className={`ml-1 inline-flex items-center rounded px-1 text-[10px] leading-4 ${
                                            status === "failed"
                                              ? "bg-red-100 text-red-700"
                                              : "bg-amber-100 text-amber-700"
                                          }`}
                                        >
                                          {status}
                                        </span>
                                      </Tooltip>
                                    );
                                  }
                                  return null;
                                })()}
                              </div>
                            </td>
                            {!isDataMate && (
                              <td className="px-4 py-3 align-top">
                                {knowledgeBaseId &&
                                (doc.tags ?? []).length > 0 ? (
                                  <TagChips
                                    assignments={doc.tags ?? []}
                                    max={5}
                                    overflowLabel="..."
                                    singleLine
                                  />
                                ) : (
                                  <span className="text-sm text-gray-400">
                                    —
                                  </span>
                                )}
                              </td>
                            )}
                            <td className="px-4 py-3">
                              <div className="flex items-center">
                                <DocumentStatus
                                  status={doc.status}
                                  showIcon={true}
                                  errorCode={doc.error_code}
                                  errorReason={doc.error_reason}
                                  kbId={knowledgeBaseId}
                                  docId={doc.id}
                                  fileId={doc.file_id}
                                  processedChunkNum={doc.processed_chunk_num}
                                  totalChunkNum={doc.total_chunk_num}
                                />
                              </div>
                            </td>
                            {!isDataMate && (
                              <td className="px-4 py-3 text-right text-sm tabular-nums text-gray-600">
                                {doc.chunk_num ?? doc.total_chunk_num ?? "—"}
                              </td>
                            )}
                            {!isDataMate && (
                              <td className="px-4 py-3 text-sm text-gray-600">
                                {formatFileSize(doc.size)}
                              </td>
                            )}
                            <td className="px-4 py-3 text-sm text-gray-600">
                              {new Date(doc.create_time).toLocaleString()}
                            </td>
                            {!isDataMate && (
                              <td className="px-4 py-3">
                                <div className="flex flex-wrap gap-2">
                                  {(doc.chunk_num ?? doc.total_chunk_num ?? 0) >
                                    0 && (
                                    <button
                                      type="button"
                                      className={LAYOUT.ACTION_PREVIEW_TEXT}
                                      onClick={() => {
                                        setChunkDocumentId(doc.id);
                                        setShowChunk(true);
                                      }}
                                    >
                                      {t("knowledgeBase.detail.viewChunks")}
                                    </button>
                                  )}
                                  <button
                                    onClick={() => {
                                      const objectName =
                                        extractObjectNameFromUrl(doc.id) ||
                                        undefined;
                                      if (!objectName) {
                                        message.warning(
                                          t("filePreview.previewFailed")
                                        );
                                        return;
                                      }

                                      setSelectedFile({
                                        objectName,
                                        fileName: doc.name,
                                        fileType: doc.type,
                                        fileSize: doc.size,
                                      });
                                    }}
                                    className={LAYOUT.ACTION_PREVIEW_TEXT}
                                    title={t("common.preview")}
                                  >
                                    {t("common.preview")}
                                  </button>
                                  <button
                                    onClick={() => {
                                      if (!knowledgeBaseId) return;
                                      setTagsUiRequested(true);
                                      setAssignTarget({
                                        docId: doc.id,
                                        canEdit: !isReadOnlyMode,
                                      });
                                    }}
                                    className={LAYOUT.ACTION_PREVIEW_TEXT}
                                    title={t("document.action.assignTags")}
                                  >
                                    {t("document.action.assignTags")}
                                  </button>
                                  {!isReadOnlyMode && (
                                    <button
                                      onClick={() =>
                                        onDelete(doc.id, doc.file_id)
                                      }
                                      className={LAYOUT.ACTION_DELETE_TEXT}
                                      title={
                                        doc.status ===
                                          DOCUMENT_STATUS.PROCESSING ||
                                        doc.status ===
                                          DOCUMENT_STATUS.FORWARDING
                                          ? t("document.delete.terminateTask")
                                          : undefined
                                      }
                                    >
                                      {t("common.delete")}
                                    </button>
                                  )}
                                </div>
                              </td>
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {!isDataMate && (
                    <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-gray-100 px-4 py-2 text-xs">
                      <span>
                        {t("agentConfig.list.total", {
                          count: filteredDocumentCount,
                        })}
                      </span>
                      <div className="flex items-center gap-2">
                        <Select
                          aria-label={t("agentConfig.list.pageSize")}
                          value={documentPageSize}
                          options={[10, 20, 50].map((size) => ({
                            value: size,
                            label: t("agentConfig.list.perPage", {
                              count: size,
                            }),
                          }))}
                          onChange={(size) => {
                            setDocumentPageSize(size);
                            setDocumentPage(1);
                          }}
                          className="!h-8 !w-[116px]"
                        />
                        <Pagination
                          current={currentDocumentPage}
                          pageSize={documentPageSize}
                          total={filteredDocumentCount}
                          showSizeChanger={false}
                          onChange={setDocumentPage}
                        />
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="flex h-full min-h-[180px] items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50/40 text-center text-sm text-gray-400">
                  {normalizedDocumentSearch || documentPredicates.length > 0
                    ? t("knowledgeBase.detail.noMatchingDocuments")
                    : t("document.hint.noDocuments")}
                </div>
              )}
            </div>

            {!isCreatingMode && isDataMate && (
              <p className="pt-3 text-sm text-[var(--color-text-secondary)]">
                {t("knowledgeBase.datamate.editDisabled")}
              </p>
            )}
          </div>
          {showSummary && (
            <aside className="min-w-0 space-y-4">
              <Card size="small" variant="outlined">
                <div className="flex min-w-0 flex-col">
                  <div className="mb-3 space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="flex items-center gap-2 font-semibold">
                        <Sparkles
                          size={16}
                          className="text-[var(--color-brand)]"
                          aria-hidden
                        />
                        {t("document.summary.title")}
                      </h3>
                      <Button
                        icon={<Sparkles size={16} aria-hidden />}
                        data-summary-action
                        onClick={handleAutoSummary}
                        loading={isSummarizing}
                        disabled={
                          !knowledgeBaseId ||
                          isSummarizing ||
                          isLoadingSummary ||
                          isSaving ||
                          !selectedModel ||
                          isReadOnlyMode
                        }
                      >
                        {t("document.button.autoSummary")}
                      </Button>
                    </div>
                    <div className="grid grid-cols-[minmax(0,1fr)_minmax(6rem,25%)] gap-2">
                      <div className="flex min-w-0 flex-col gap-1">
                        <span className="text-sm text-[var(--color-text-secondary)]">
                          {t("document.summary.modelLabel")}
                        </span>
                        <Select
                          value={selectedModel || undefined}
                          onChange={setSelectedModel}
                          loading={isLoadingModels}
                          disabled={isReadOnlyMode || isSummarizing}
                          aria-label={t("document.summary.modelLabel")}
                          className="w-full min-w-0"
                          placeholder={t("document.summary.modelPlaceholder")}
                          options={availableModels.map((model) => ({
                            value: model.id,
                            label: model.displayName,
                            disabled: model.connect_status === "unavailable",
                          }))}
                        />
                      </div>
                      <div className="flex min-w-0 flex-col gap-1">
                        <span className="text-sm text-[var(--color-text-secondary)]">
                          {t("knowledgeBase.tag.autoSummary.label")}
                        </span>
                        <Select
                          value={summaryFrequency || "disabled"}
                          aria-label={t("knowledgeBase.tag.autoSummary.label")}
                          onChange={(value) => {
                            const freq = value === "disabled" ? null : value;
                            if (onSummaryFrequencyChange) {
                              onSummaryFrequencyChange(freq);
                            }
                          }}
                          disabled={isReadOnlyMode}
                          className="w-full"
                          placeholder={t("knowledgeBase.tag.autoSummary.off")}
                          options={frequencyOptions.map((opt) => ({
                            value: opt.value,
                            label:
                              opt.value === "disabled"
                                ? t("knowledgeBase.tag.autoSummary.off")
                                : opt.label,
                          }))}
                        />
                      </div>
                    </div>
                  </div>
                  {isLoadingSummary || isReadOnlyMode || isSummarizing ? (
                    <div className="min-h-48 max-h-96 overflow-auto rounded-lg border border-[var(--color-border)]">
                      {isLoadingSummary ? (
                        <div className="flex justify-center py-10">
                          <Spin />
                        </div>
                      ) : (
                        <div className="p-3 text-sm leading-relaxed whitespace-pre-wrap">
                          <MarkdownRenderer content={summary} />
                        </div>
                      )}
                    </div>
                  ) : (
                    <TextArea
                      aria-label={t("document.summary.title")}
                      value={summary}
                      disabled={isSaving}
                      onChange={(event) => setSummary(event.target.value)}
                      onBlur={(event) => {
                        if (
                          !(event.relatedTarget instanceof Element) ||
                          !event.relatedTarget.closest("[data-summary-action]")
                        ) {
                          void saveEditedSummary(event.currentTarget.value);
                        }
                      }}
                      className="!min-h-48"
                      rows={8}
                      placeholder={t("document.summary.placeholder")}
                    />
                  )}
                  <div className="mt-3 space-y-1">
                    <p className="text-xs text-[var(--color-text-secondary)]">
                      {t("document.summary.retrievalHint")}
                    </p>
                    {!isReadOnlyMode && (
                      <div
                        className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)]"
                        role="status"
                      >
                        {isSaving ? (
                          t("common.saving")
                        ) : summarySaveFailed && !isSummarizing ? (
                          <>
                            {t("document.summary.saveFailed")}
                            <Button
                              type="link"
                              size="small"
                              data-summary-action
                              disabled={!summary.trim()}
                              onClick={() => void saveEditedSummary(summary)}
                            >
                              {t("repository.common.retry")}
                            </Button>
                          </>
                        ) : (
                          t("document.summary.editAutosave")
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </Card>
              {catalogKnowledgeBase && (
                <KnowledgeBaseAccessCard
                  knowledgeBase={catalogKnowledgeBase}
                  groups={groups}
                  allGroups={groupData?.groups ?? []}
                  onChange={
                    isReadOnlyMode ? undefined : onCatalogKnowledgeBaseChange
                  }
                />
              )}
            </aside>
          )}
        </div>
        {editingKnowledgeBase &&
          catalogKnowledgeBase &&
          onCatalogKnowledgeBaseChange && (
            <KnowledgeBaseEditModal
              open
              knowledgeBase={catalogKnowledgeBase}
              tenantId={tenantId}
              onCancel={() => setEditingKnowledgeBase(false)}
              onSuccess={onCatalogKnowledgeBaseChange}
            />
          )}
        {/* File preview drawer */}
        <TagDefinitionManagementModal
          open={tagManagementOpen}
          onClose={() => {
            setTagManagementOpen(false);
            void refreshAssignDefinitions();
          }}
          bucketId={documentLibrary?.bucket_id ?? 0}
          bucketName={documentLibrary?.bucket_name ?? ""}
          canManage={!isReadOnlyMode}
        />

        <ResourceTagAssignmentModal
          open={assignTarget !== null}
          onClose={() => setAssignTarget(null)}
          resourceType="knowledge_document"
          resourceId={assignTarget?.docId ?? ""}
          definitions={assignDefinitions ?? []}
          canEdit={assignTarget?.canEdit ?? false}
          provider="local"
          knowledgeBaseId={knowledgeBaseId}
          definitionsLoading={assignDefinitionsLoading}
          onSaved={() => onRefresh?.()}
          onManageDefinitions={() => {
            setTagsUiRequested(true);
            setTagManagementOpen(true);
          }}
        />

        {selectedFile && (
          <FilePreviewDrawer
            open={!!selectedFile}
            objectName={selectedFile.objectName}
            fileName={selectedFile.fileName}
            fileType={selectedFile.fileType}
            fileSize={selectedFile.fileSize}
            previewContext="knowledgeBase"
            onClose={handlePreviewClose}
          />
        )}

        {/* v2.6.0: Embedding model advanced settings modal */}
        <Modal
          open={embeddingAdvancedOpen}
          onCancel={() => setEmbeddingAdvancedOpen(false)}
          onOk={() => setEmbeddingAdvancedOpen(false)}
          title={t("knowledgeBase.create.embeddingAdvancedSettings", {
            defaultValue: "Embedding 模型高级设置",
          })}
          okText={t("common.confirm", { defaultValue: "确定" })}
          cancelText={t("common.cancel", { defaultValue: "取消" })}
          width={720}
          centered
          destroyOnHidden={false}
          styles={{ body: { maxHeight: "70vh", overflowY: "auto" } }}
        >
          {selectedEmbeddingModelOption ? (
            <ModelAdvancedSettings
              modelType={selectedEmbeddingModelOption.type}
              specs={inferenceSpecs}
              value={embeddingAdvancedValue}
              onChange={handleEmbeddingAdvancedChange}
              mode="override"
            />
          ) : (
            <div className="text-gray-500 text-sm">
              {t("knowledgeBase.create.noEmbeddingModelSelected", {
                defaultValue: "请先选择 Embedding 模型",
              })}
            </div>
          )}
        </Modal>
      </div>
    );
  }
);

export default DocumentListContainer;
