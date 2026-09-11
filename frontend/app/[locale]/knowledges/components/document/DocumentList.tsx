import React, {
  useState,
  useRef,
  forwardRef,
  useImperativeHandle,
  useEffect,
  useMemo,
} from "react";
import { useTranslation } from "react-i18next";

import {
  Input,
  InputNumber,
  Button,
  App,
  Select,
  Popover,
  Progress,
  Segmented,
  Tooltip,
} from "antd";
import { useStorageQuotaBlocked } from "@/hooks/useStorageQuotaBlocked";
const { TextArea } = Input;
import {
  FileTextOutlined,
  FilterOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import {
  BookText,
  Pilcrow,
  PencilRuler,
  Eye,
  Glasses,
  CircleOff,
  AlertCircle,
  Tag,
  SlidersHorizontal,
  ChevronDown,
  ChevronUp,
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
import { Document } from "@/types/knowledgeBase";
import type { KBQuotaStatus } from "@/types/quota";
import type {
  TagDocumentPredicate,
  TagDocumentBatchStatusEntry,
} from "@/types/tagManagement";
import { ModelOption } from "@/types/modelConfig";
import { formatFileSize } from "@/lib/utils";
import log from "@/lib/logger";
import { useConfig } from "@/hooks/useConfig";
import { useGroupDetails, useGroupList } from "@/hooks/group/useGroupList";

import DocumentStatus from "./DocumentStatus";
import DocumentChunk from "./DocumentChunk";
import UploadArea from "../upload/UploadArea";
import ResourceTagAssignmentModal from "@/components/tag/ResourceTagAssignmentModal";
import ResourceTagChips from "@/components/tag/ResourceTagChips";
import TagDefinitionManagementModal from "@/components/tag/TagDefinitionManagementModal";
import TagFilterControls from "@/components/tag/TagFilterControls";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";
import { tagManagementApi } from "@/services/tagManagementService";
import { useDocumentContext } from "../../contexts/DocumentContext";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { Can } from "@/components/permission/Can";

const CONTAINER_HEIGHT_CLASS_MAP: Record<string, string> = {
  "83vh": "h-[83vh]",
  "70vh": "h-[70vh]",
  "57vh": "h-[57vh]",
  "100%": "h-full",
};

const TITLE_BAR_HEIGHT_CLASS_MAP: Record<string, string> = {
  "56.8px": "min-h-[56.8px]",
};

interface DocumentListProps {
  documents: Document[];
  onDelete: (id: string, fileId?: string) => void;
  // Knowledge base source, e.g. "nexent" or "datamate"
  knowledgeBaseSource?: string;
  // User-facing knowledge base name (display name)
  knowledgeBaseName?: string;
  knowledgeBaseDescription?: string;
  onDescriptionChange?: (description: string) => void;
  // Internal knowledge base ID / Elasticsearch index name
  knowledgeBaseId?: string;
  modelMismatch?: boolean;
  currentModel?: string;
  knowledgeBaseModel?: string;
  embeddingModelInfo?: string;
  containerHeight?: string;
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
      knowledgeBaseDescription = "",
      onDescriptionChange,
      modelMismatch = false,
      currentModel = "",
      knowledgeBaseModel = "",
      embeddingModelInfo = "",
      containerHeight = "57vh",
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
    },
    ref
  ) => {
    const { message } = App.useApp();
    const uploadAreaRef = useRef<any>(null);
    const { state: docState } = useDocumentContext();
    const { modelConfig } = useConfig();
    const { user, getAccessibleGroupIds } = useAuthorizationContext();
    const tenantId = user?.tenantId || null;
    const storageQuota = useStorageQuotaBlocked(tenantId);

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

    const groupOptions = groups.map((group) => ({
      label: group.group_name,
      value: group.group_id,
    }));

    // Preview drawer state
    const [quotaUnit, setQuotaUnit] = useState<"GB" | "MB">("GB");

    const [selectedFile, setSelectedFile] = useState<{
      objectName: string;
      fileName: string;
      fileType?: string;
      fileSize?: number;
    } | null>(null);

    // Use fixed height instead of percentage
    const titleBarHeight = UI_CONFIG.TITLE_BAR_HEIGHT;
    const uploadHeight = UI_CONFIG.UPLOAD_COMPONENT_HEIGHT;
    const [isAdvancedSettingsOpen, setIsAdvancedSettingsOpen] = useState(false);
    const [assignTarget, setAssignTarget] = useState<{
      docId: string;
      canEdit: boolean;
    } | null>(null);
    const [documentTagRefreshKey, setDocumentTagRefreshKey] = useState(0);
    const { data: tagLibraries } = useTagLibraries();
    const documentLibrary =
      tagLibraries?.find((lib) => lib.bucket_key === "knowledge_content") ??
      null;
    const { data: assignDefinitions, refresh: refreshAssignDefinitions } =
      useTagDefinitions(documentLibrary?.bucket_id ?? null);

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

    // Batch-fetch document tag assignment and projection status for the
    // currently visible knowledge base; empty when no library context exists.
    useEffect(() => {
      const visibleIds = documents.map((doc) => doc.id);
      if (
        isCreatingMode ||
        !knowledgeBaseId ||
        !documentLibrary ||
        visibleIds.length === 0
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

    // Get permission icon for dropdown options
    const getPermissionIcon = (permission: string) => {
      const iconProps = {
        size: 16,
        className: "text-gray-500",
      };

      switch (permission) {
        case "EDIT":
          return <PencilRuler {...iconProps} />;
        case "READ_ONLY":
          return <Eye {...iconProps} />;
        case "PRIVATE":
          return <Glasses {...iconProps} />;
        default:
          return <CircleOff {...iconProps} />;
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
    const [showDetail, setShowDetail] = React.useState(false);
    const [showChunk, setShowChunk] = React.useState(false);
    const [nameStatus, setNameStatus] = useState<string>("available");
    const [summary, setSummary] = useState("");
    const [isSummarizing, setIsSummarizing] = useState(false);
    const [isEditing, setIsEditing] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [selectedModel, setSelectedModel] = useState<number>(0);
    const [availableModels, setAvailableModels] = useState<ModelOption[]>([]);
    const [isLoadingModels, setIsLoadingModels] = useState(false);
    const [frequencyOptions, setFrequencyOptions] = useState<FrequencyOption[]>(
      []
    );
    const { t } = useTranslation();
    const isDataMate = (knowledgeBaseSource || "").toLowerCase() === "datamate";
    const hasQuota = quotaStatus?.soft_quota_bytes != null;
    const quotaAvailable = quotaStatus
      ? hasQuota
        ? formatFileSize(
            Math.max(
              quotaStatus.soft_quota_bytes! - quotaStatus.actual_bytes,
              0
            )
          )
        : t("knowledgeBase.capacity.unlimited")
      : "-";
    const quotaTotal = quotaStatus
      ? hasQuota
        ? quotaStatus.soft_quota_readable ||
          formatFileSize(quotaStatus.soft_quota_bytes!)
        : t("knowledgeBase.capacity.unlimited")
      : "-";
    const quotaUsagePercent = quotaStatus
      ? Math.min(
          100,
          Math.max(
            0,
            quotaStatus.usage_pct ??
              (hasQuota && quotaStatus.soft_quota_bytes! > 0
                ? (quotaStatus.actual_bytes / quotaStatus.soft_quota_bytes!) *
                  100
                : quotaStatus.actual_bytes > 0
                  ? 100
                  : 0)
          )
        )
      : 0;

    // Determine if user has read-only permission
    const isReadOnlyMode = permission === "READ_ONLY";
    const canToggleMultimodal =
      isCreatingMode && typeof onMultimodalChange === "function";

    // Permission options with icons shown inside dropdown
    const permissionOptions = [
      {
        value: "EDIT",
        label: (
          <span className="flex items-center gap-2">
            {getPermissionIcon("EDIT")}
            <span>{t("tenantResources.knowledgeBase.permission.EDIT")}</span>
          </span>
        ),
      },
      {
        value: "READ_ONLY",
        label: (
          <span className="flex items-center gap-2">
            {getPermissionIcon("READ_ONLY")}
            <span>
              {t("tenantResources.knowledgeBase.permission.READ_ONLY")}
            </span>
          </span>
        ),
      },
      {
        value: "PRIVATE",
        label: (
          <span className="flex items-center gap-2">
            {getPermissionIcon("PRIVATE")}
            <span>{t("tenantResources.knowledgeBase.permission.PRIVATE")}</span>
          </span>
        ),
      },
    ];

    // Reset showDetail and showChunk state when knowledge base name changes
    React.useEffect(() => {
      setShowDetail(false);
      setShowChunk(false);
      setSummary("");
    }, [knowledgeBaseName]);

    // Initialize default group ID when entering create mode
    React.useEffect(() => {
      if (isCreatingMode && tenantId && onSelectedGroupIdsChange) {
        const initDefaultGroup = async () => {
          try {
            const defaultGroupId = await getTenantDefaultGroupId(tenantId);
            if (defaultGroupId && accessibleGroupIds.includes(defaultGroupId)) {
              onSelectedGroupIdsChange([defaultGroupId]);
            }
          } catch (error) {
            log.error("Failed to get tenant default group:", error);
          }
        };
        initDefaultGroup();
      }
    }, [
      isCreatingMode,
      tenantId,
      accessibleGroupIds,
      onSelectedGroupIdsChange,
    ]);

    // Clear group IDs when permission is set to PRIVATE
    React.useEffect(() => {
      if (ingroupPermission === "PRIVATE" && onSelectedGroupIdsChange) {
        onSelectedGroupIdsChange([]);
      }
    }, [ingroupPermission, onSelectedGroupIdsChange]);

    // Check if group select should be disabled (when permission is PRIVATE)
    const isGroupSelectDisabled = ingroupPermission === "PRIVATE";
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
        if (showDetail && frequencyOptions.length === 0) {
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
    }, [showDetail, frequencyOptions.length, t]);

    // Load available models when showing detail
    useEffect(() => {
      const loadModels = async () => {
        if (showDetail && availableModels.length === 0) {
          setIsLoadingModels(true);
          try {
            const models = await modelService.getLLMModels();
            setAvailableModels(
              models.filter((m) => m.connect_status === "available")
            );

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
    }, [showDetail]);

    // Get summary when showing detailed content
    React.useEffect(() => {
      const fetchSummary = async () => {
        if (showDetail && knowledgeBaseId) {
          try {
            const result =
              await knowledgeBaseService.getSummary(knowledgeBaseId);
            setSummary(result);
          } catch (error) {
            log.error(t("knowledgeBase.error.getSummary"), error);
            message.error(t("document.summary.error"));
          }
        }
      };
      fetchSummary();
    }, [showDetail, knowledgeBaseName]);

    // Handle auto summary
    const handleAutoSummary = async () => {
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
        // Only show success message if summary was actually generated
        if (result && result.trim()) {
          message.success(t("document.summary.completed"));
        } else {
          // If no summary was generated, show error message
          message.error(t("knowledgeBase.summary.notGenerated"));
        }
      } catch (error) {
        message.error(t("document.summary.error"));
        log.error(t("document.summary.error"), error);
      } finally {
        setIsSummarizing(false);
      }
    };

    // Handle save summary
    const handleSaveSummary = async () => {
      if (!knowledgeBaseId) {
        message.warning(t("document.summary.selectKnowledgeBase"));
        return;
      }

      if (!summary.trim()) {
        message.warning(t("document.summary.emptyContent"));
        return;
      }

      setIsSaving(true);
      try {
        await knowledgeBaseService.changeSummary(knowledgeBaseId, summary);
        message.success(t("document.summary.saveSuccess"));
      } catch (error: any) {
        log.error(t("document.summary.saveError"), error);
        const errorMessage =
          error?.message || error?.detail || t("document.summary.saveFailed");
        message.error(errorMessage);
      } finally {
        setIsSaving(false);
        setShowDetail(false);
      }
    };

    const filteredDocuments = activeDocumentIds
      ? sortedDocuments.filter((doc) => activeDocumentIds.has(doc.id))
      : sortedDocuments;

    const containerHeightClass =
      CONTAINER_HEIGHT_CLASS_MAP[containerHeight] ?? "h-full";
    const titleBarHeightClass =
      TITLE_BAR_HEIGHT_CLASS_MAP[titleBarHeight] ?? "min-h-[56px]";

    return (
      <div
        className={`relative flex w-full flex-col overflow-x-hidden shadow-sm ${
          isCreatingMode
            ? "overflow-hidden rounded-2xl border border-gray-200 bg-white"
            : "h-full overflow-hidden rounded-2xl border border-gray-200 bg-white"
        }`}
      >
        {/* Title bar */}
        <div
          className={`${
            isCreatingMode
              ? "border-b border-gray-200 px-5 pb-5 pt-6"
              : "border-b border-gray-100 px-6 pb-5 pt-6"
          } flex-shrink-0 flex items-start ${titleBarHeightClass}`}
        >
          <div
            className="flex w-full items-start justify-between gap-4"
            style={{ width: "100%" }}
          >
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-5 gap-y-2 overflow-hidden">
              {isCreatingMode ? (
                <div className="w-full">
                  <h2 className="text-xl font-semibold tracking-tight text-gray-900">
                    {t("document.title.createNew")}
                  </h2>
                  <p className="mt-1 text-sm text-gray-500">
                    {t("knowledgeBase.create.subtitle")}
                  </p>
                </div>
              ) : (
                <>
                  <div className="flex min-w-0 flex-[1_1_260px] items-center gap-3">
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                      <FileTextOutlined />
                    </div>
                    <div className="min-w-0">
                      <h3 className="truncate text-xl font-semibold tracking-tight text-blue-600">
                        {knowledgeBaseName}
                      </h3>
                      <div className="mt-1 flex min-w-0 flex-wrap items-center gap-2 text-sm text-gray-500">
                        <span>
                          {t("knowledgeBase.tag.documents", {
                            count: documents.length,
                          })}
                        </span>
                        {modelMismatch && (
                          <span
                            className="max-w-full truncate rounded-md border border-yellow-200 bg-yellow-50 px-2 py-1 text-xs font-medium text-yellow-800"
                            title={getMismatchInfo()}
                          >
                            {getMismatchInfo()}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  {quotaStatus && (
                    <div className="min-w-[240px] max-w-[420px] flex-[1_1_300px] rounded-lg border border-gray-100 bg-gray-50/80 px-3 py-2">
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
                        <span className="font-medium text-gray-600">
                          {t("knowledgeBase.capacity.title")}
                        </span>
                        <span className="text-gray-500">
                          {t("knowledgeBase.capacity.available")}:{" "}
                          {quotaAvailable}
                        </span>
                        <span className="text-gray-500">
                          {t("knowledgeBase.capacity.total")}: {quotaTotal}
                        </span>
                        {hasQuota && (
                          <span className="text-gray-400">
                            {Math.round(quotaUsagePercent)}%
                          </span>
                        )}
                      </div>
                      {hasQuota && (
                        <Progress
                          className="!mb-0 !mt-1"
                          percent={quotaUsagePercent}
                          showInfo={false}
                          size="small"
                          status={
                            quotaStatus.kb_warning_level === "exceeded"
                              ? "exception"
                              : "normal"
                          }
                        />
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
            {/* Right: tag filter, Tag Management, overview and detail buttons */}
            {!isCreatingMode && !isDataMate && (
              <div className="ml-3 flex shrink-0 flex-wrap items-center justify-end gap-2">
                {documentLibrary && assignDefinitions && (
                  <Popover
                    trigger="click"
                    placement="bottomRight"
                    title={t("document.tagFilter.placeholder")}
                    content={
                      <div className="w-64">
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
                )}
                {!isReadOnlyMode && (
                  <Button
                    icon={<Tag size={16} />}
                    onClick={() => setTagManagementOpen(true)}
                  >
                    {t("knowledgeBase.button.tagManagement")}
                  </Button>
                )}
                <Button
                  type={showDetail ? "primary" : "default"}
                  size="middle"
                  icon={<BookText size={16} />}
                  onClick={() => {
                    if (showDetail) {
                      // Close detail view and reset summary
                      setShowDetail(false);
                      setSummary("");
                    } else {
                      setShowDetail(true);
                      setShowChunk(false);
                    }
                  }}
                >
                  {t("document.button.overview")}
                </Button>
                <Button
                  type={showChunk ? "primary" : "default"}
                  size="middle"
                  icon={<Pilcrow size={16} />}
                  onClick={() => {
                    if (showChunk) {
                      setShowChunk(false);
                    } else {
                      setShowChunk(true);
                      setShowDetail(false);
                    }
                  }}
                >
                  {t("document.button.detail")}
                </Button>
                {onRefresh && (
                  <Tooltip title={t("common.refresh")}>
                    <Button
                      aria-label={t("common.refresh")}
                      className="!h-10 !w-10 !rounded-lg !p-0"
                      icon={<ReloadOutlined spin={isUploading} />}
                      onClick={onRefresh}
                      disabled={isUploading || docState.isLoadingDocuments}
                    />
                  </Tooltip>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Document list */}

        <div
          className={
            isCreatingMode
              ? "w-full bg-white p-2"
              : showChunk
                ? "flex-grow min-h-0 overflow-hidden px-6 pt-5"
                : "flex-grow min-h-0 overflow-auto px-6 py-5"
          }
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
            <div className="flex h-full min-h-0 flex-col">
              <div className="min-h-0 flex-1">
                <DocumentChunk
                  knowledgeBaseName={knowledgeBaseName}
                  knowledgeBaseId={knowledgeBaseId || knowledgeBaseName}
                  documents={documents}
                  getFileIcon={getFileIcon}
                  onChunkCountChange={onChunkCountChange}
                  permission={permission}
                />
              </div>
              <div className="flex shrink-0 justify-end py-3">
                <Button
                  size="large"
                  onClick={() => {
                    setShowChunk(false);
                  }}
                >
                  {t("common.back")}
                </Button>
              </div>
            </div>
          ) : showDetail ? (
            <div className="flex h-full flex-col">
              <div className="flex items-center justify-between mb-5">
                <span className="font-bold text-lg">
                  {t("document.summary.title")}
                </span>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-gray-600">
                      {t("document.summary.modelLabel")}:
                    </span>
                    <Select
                      value={selectedModel}
                      onChange={setSelectedModel}
                      loading={isLoadingModels}
                      disabled={isSummarizing}
                      style={{ width: 200 }}
                      placeholder={t("document.summary.modelPlaceholder")}
                      options={availableModels.map((model) => ({
                        value: model.id,
                        label: model.displayName,
                        disabled: model.connect_status === "unavailable",
                      }))}
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-gray-600">
                      {t("knowledgeBase.tag.autoSummary.label")}
                    </span>
                    <Select
                      value={summaryFrequency || "disabled"}
                      onChange={(value) => {
                        const freq = value === "disabled" ? null : value;
                        if (onSummaryFrequencyChange) {
                          onSummaryFrequencyChange(freq);
                        }
                      }}
                      disabled={isReadOnlyMode}
                      style={{ width: 85 }}
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
                  <Button
                    type="default"
                    onClick={handleAutoSummary}
                    loading={isSummarizing}
                    disabled={
                      !knowledgeBaseName ||
                      isSummarizing ||
                      !selectedModel ||
                      isReadOnlyMode
                    }
                  >
                    {t("document.button.autoSummary")}
                  </Button>
                </div>
              </div>
              <div className="flex-1 min-h-0 mb-5 border border-gray-300 rounded-md overflow-auto">
                {isReadOnlyMode ? (
                  <div className="p-5 text-lg leading-[1.7] whitespace-pre-wrap">
                    <MarkdownRenderer content={summary} />
                  </div>
                ) : isSummarizing ? (
                  <div className="p-5 text-lg leading-[1.7] whitespace-pre-wrap">
                    <MarkdownRenderer content={summary} />
                  </div>
                ) : (
                  <div
                    className="w-full h-full cursor-text hover:bg-gray-50"
                    onClick={() => {
                      if (!isSummarizing) {
                        setIsEditing(true);
                      }
                    }}
                  >
                    {isEditing ? (
                      <TextArea
                        value={summary}
                        onChange={(e) => setSummary(e.target.value)}
                        onBlur={() => setIsEditing(false)}
                        className="w-full h-full border-0 resize-none focus:shadow-none"
                        style={{
                          height: "100%",
                          padding: "20px",
                          fontSize: "18px",
                          lineHeight: "1.7",
                          whiteSpace: "pre-wrap",
                        }}
                        autoFocus
                        placeholder={t("document.summary.placeholder")}
                      />
                    ) : (
                      <div className="p-5 text-lg leading-[1.7] whitespace-pre-wrap">
                        <MarkdownRenderer content={summary} />
                      </div>
                    )}
                  </div>
                )}
              </div>
              <div className="flex gap-3 justify-end">
                {!isReadOnlyMode && (
                  <Button
                    type="primary"
                    size="large"
                    onClick={handleSaveSummary}
                    loading={isSaving}
                    disabled={!summary || isSaving}
                  >
                    {t("common.save")}
                  </Button>
                )}
                <Button
                  size="large"
                  onClick={() => {
                    setShowDetail(false);
                    setSummary("");
                  }}
                >
                  {t("common.back")}
                </Button>
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
              {hasDocuments || isUploading || docState.isLoadingDocuments ? (
                <div className="flex min-h-[220px] items-center justify-center rounded-md border border-gray-200">
                  <div className="text-center">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-2"></div>
                    <p className="text-sm text-gray-600">
                      {t("document.status.waitingForTask")}
                    </p>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col gap-3 px-3 py-4">
                  <div className="shrink-0">
                    <label className="mb-2 block text-sm font-medium text-gray-900">
                      {t("knowledgeBase.create.field.name")}{" "}
                      <span className="text-red-500">*</span>
                    </label>
                    <Input
                      value={knowledgeBaseName}
                      onChange={(e) =>
                        onNameChange && onNameChange(e.target.value)
                      }
                      placeholder={t(
                        "knowledgeBase.create.namePlaceholder",
                        "例如：产品知识中心"
                      )}
                      className="!rounded-xl"
                      size="large"
                      status={
                        nameStatus === NAME_CHECK_STATUS.EXISTS_IN_TENANT ||
                        nameStatus === NAME_CHECK_STATUS.EXISTS_IN_OTHER_TENANT
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

                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-900">
                      {t("knowledgeBase.create.field.description")}{" "}
                      <span className="font-normal text-gray-500">
                        {t("knowledgeBase.create.optional")}
                      </span>
                    </label>
                    <TextArea
                      value={knowledgeBaseDescription}
                      onChange={(e) => onDescriptionChange?.(e.target.value)}
                      placeholder={t(
                        "knowledgeBase.create.descriptionPlaceholder",
                        "简要说明这个知识库包含什么内容"
                      )}
                      autoSize={{ minRows: 2, maxRows: 3 }}
                      className="!rounded-xl"
                    />
                  </div>

                  <div className="shrink-0">
                    <div className="mb-1 text-xs font-medium text-gray-900">
                      {t("knowledgeBase.create.uploadTitle")}{" "}
                      <span className="text-red-500">*</span>
                    </div>
                    <div className="h-[146px]">
                      <UploadArea
                        ref={uploadAreaRef}
                        onFileSelect={onFileSelect}
                        onUpload={onUpload || (async () => {})}
                        isUploading={isUploading}
                        isDragging={isDragging}
                        onDragOver={onDragOver}
                        onDragLeave={onDragLeave}
                        onDrop={onDrop}
                        disabled={storageQuota.isBlocked || isReadOnlyMode}
                        disabledMessage={
                          storageQuota.isBlocked
                            ? storageQuota.message ||
                              t(
                                "quota.uploadBlocked",
                                "Uploads are blocked - storage limit reached"
                              )
                            : undefined
                        }
                        componentHeight={uploadHeight}
                        isCreatingMode
                        indexName={knowledgeBaseId || "new-knowledge-base"}
                        newKnowledgeBaseName={knowledgeBaseName}
                        modelMismatch={modelMismatch}
                        onNameStatusChange={setNameStatus}
                        selectedFiles={selectedFiles}
                        autoUpload={false}
                      />
                    </div>
                  </div>

                  {onEmbeddingModelChange && (
                    <div>
                      <label className="mb-1 block text-sm font-medium text-gray-900">
                        {t("knowledgeBase.create.field.embeddingModel")}{" "}
                        <span className="text-red-500">*</span>
                      </label>
                      <Select
                        value={selectedEmbeddingModel}
                        onChange={onEmbeddingModelChange}
                        className="w-full"
                        size="large"
                        placeholder={
                          t("knowledgeBase.create.embeddingModelPlaceholder") ||
                          "Select embedding model"
                        }
                        allowClear={false}
                        options={[
                          {
                            label: t("modelConfig.option.embeddingModel"),
                            options: embeddingModelsForOptions
                              .filter((model) => model.type === "embedding")
                              .map((model) => ({
                                value: [model.displayName, model.type].join(
                                  "::"
                                ),
                                label: model.displayName,
                                disabled: !isEmbeddingModelSelectable(model),
                              })),
                          },
                          {
                            label: t("modelConfig.option.multiEmbeddingModel"),
                            options: embeddingModelsForOptions
                              .filter(
                                (model) => model.type === "multi_embedding"
                              )
                              .map((model) => ({
                                value: [model.displayName, model.type].join(
                                  "::"
                                ),
                                label: model.displayName,
                                disabled: !isEmbeddingModelSelectable(model),
                              })),
                          },
                        ].filter((group) => group.options.length > 0)}
                      />
                    </div>
                  )}

                  <button
                    type="button"
                    className={
                      isAdvancedSettingsOpen
                        ? "flex w-full items-center justify-between rounded-xl border-2 border-blue-300 bg-gray-50 px-4 py-3 text-left transition-colors"
                        : "flex w-full items-center justify-between rounded-xl border-2 border-gray-200 bg-gray-50 px-4 py-3 text-left transition-colors hover:border-blue-300"
                    }
                    onClick={() =>
                      setIsAdvancedSettingsOpen((isOpen) => !isOpen)
                    }
                  >
                    <span className="flex items-center gap-2 text-base font-medium text-gray-900">
                      <SlidersHorizontal size={16} />
                      {t("knowledgeBase.create.advancedSettings")}
                    </span>
                    {isAdvancedSettingsOpen ? (
                      <ChevronUp size={18} />
                    ) : (
                      <ChevronDown size={18} />
                    )}
                  </button>

                  {isAdvancedSettingsOpen && (
                    <div className="grid grid-cols-1 gap-2 rounded-2xl border border-gray-200 bg-gray-50/60 p-3">
                      <Can permission="kb.groups:update">
                        <div>
                          <label className="mb-1 block text-xs font-medium text-gray-900">
                            {t("knowledgeBase.create.field.permission")}
                          </label>
                          <Select
                            value={ingroupPermission}
                            onChange={onIngroupPermissionChange}
                            className="w-full"
                            size="middle"
                            placeholder={t(
                              "knowledgeBase.ingroup.permission.DEFAULT"
                            )}
                            options={permissionOptions}
                          />
                        </div>
                      </Can>

                      <Can permission="kb.groups:update">
                        <div>
                          <label className="mb-1 block text-xs font-medium text-gray-900">
                            {t("knowledgeBase.create.field.groups")}
                          </label>
                          <Select
                            mode="multiple"
                            showSearch={{ optionFilterProp: "label" }}
                            value={
                              isGroupSelectDisabled ? [] : selectedGroupIds
                            }
                            onChange={onSelectedGroupIdsChange}
                            className="w-full"
                            size="middle"
                            placeholder={t(
                              "knowledgeBase.create.permission.groupPlaceholder"
                            )}
                            options={groupOptions}
                            maxTagCount={2}
                            allowClear
                            disabled={isGroupSelectDisabled}
                          />
                        </div>
                      </Can>

                      {onPreserveSourceFileChange && (
                        <div>
                          <label className="mb-1 block text-xs font-medium text-gray-900">
                            {t("knowledgeBase.create.field.preserve")}
                          </label>
                          <Select
                            value={preserveSourceFile}
                            onChange={onPreserveSourceFileChange}
                            className="w-full"
                            size="middle"
                            allowClear={false}
                            options={[
                              {
                                value: true,
                                label: t(
                                  "knowledgeBase.create.preserveSourceFile"
                                ),
                              },
                              {
                                value: false,
                                label: t(
                                  "knowledgeBase.tag.noPreserveSourceFile"
                                ),
                              },
                            ]}
                          />
                        </div>
                      )}

                      {onQuotaLimitBytesChange && (
                        <div>
                          <label className="mb-2 block text-sm font-medium text-gray-900">
                            {t("knowledgeBase.create.field.quota")}
                          </label>
                          <div className="flex items-center gap-2">
                            <InputNumber
                              value={
                                quotaLimitBytes != null
                                  ? quotaUnit === "GB"
                                    ? Math.round(
                                        quotaLimitBytes / (1024 * 1024 * 1024)
                                      )
                                    : Math.round(
                                        quotaLimitBytes / (1024 * 1024)
                                      )
                                  : null
                              }
                              onChange={(v) => {
                                if (v == null) {
                                  onQuotaLimitBytesChange(null);
                                } else if (quotaUnit === "GB") {
                                  onQuotaLimitBytesChange(
                                    v * 1024 * 1024 * 1024
                                  );
                                } else {
                                  onQuotaLimitBytesChange(v * 1024 * 1024);
                                }
                              }}
                              addonAfter={quotaUnit}
                              placeholder={t("quota.unlimited", "无限制")}
                              min={0}
                              precision={0}
                              className="min-w-0 flex-1"
                              size="middle"
                            />
                            <Segmented
                              size="middle"
                              options={["GB", "MB"]}
                              value={quotaUnit}
                              onChange={(val) =>
                                setQuotaUnit(val as "GB" | "MB")
                              }
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : filteredDocuments.length > 0 ? (
            <div className="h-full overflow-hidden rounded-xl border border-gray-200">
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
                  {filteredDocuments.map((doc) => (
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
                            const entry = projectionByDocument.get(doc.id);
                            const status = entry?.projection_status?.status;
                            if (status === "pending" || status === "failed") {
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
                          {knowledgeBaseId ? (
                            <ResourceTagChips
                              resourceType="knowledge_document"
                              resourceId={doc.id}
                              max={5}
                              overflowLabel="..."
                              singleLine
                              refreshKey={documentTagRefreshKey}
                              options={{
                                provider: "local",
                                knowledgeBaseId,
                              }}
                              emptyText={
                                <span className="text-sm text-gray-400">—</span>
                              }
                            />
                          ) : (
                            <span className="text-sm text-gray-400">—</span>
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
                        <td className="px-4 py-3 text-sm text-gray-600">
                          {formatFileSize(doc.size)}
                        </td>
                      )}
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {new Date(doc.create_time).toLocaleString()}
                      </td>
                      {!isDataMate && (
                        <td className="px-4 py-3">
                          <div className="flex gap-2">
                            <button
                              onClick={() => {
                                const objectName =
                                  extractObjectNameFromUrl(doc.id) || undefined;
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
                                onClick={() => onDelete(doc.id, doc.file_id)}
                                className={LAYOUT.ACTION_DELETE_TEXT}
                                title={
                                  doc.status === DOCUMENT_STATUS.PROCESSING ||
                                  doc.status === DOCUMENT_STATUS.FORWARDING
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
          ) : (
            <div className="flex h-full min-h-[180px] items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50/40 text-center text-sm text-gray-400">
              {t("document.hint.noDocuments")}
            </div>
          )}
        </div>

        {/* Upload area */}
        {!showDetail && !showChunk && !isCreatingMode && (
          <div className="shrink-0 px-6 pb-5 pt-2">
            {isDataMate ? (
              <div className="flex min-h-[150px] items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50/60 px-6 text-center">
                <span className="text-sm font-medium leading-[1.7] text-gray-500">
                  {t("knowledgeBase.datamate.editDisabled")}
                </span>
              </div>
            ) : (
              <UploadArea
                key={
                  isCreatingMode
                    ? `create-${knowledgeBaseName}`
                    : `view-${knowledgeBaseName}`
                }
                ref={uploadAreaRef}
                onFileSelect={onFileSelect}
                onUpload={onUpload || (async () => {})}
                isUploading={isUploading}
                isDragging={isDragging}
                onDragOver={onDragOver}
                onDragLeave={onDragLeave}
                onDrop={onDrop}
                disabled={
                  storageQuota.isBlocked ||
                  isReadOnlyMode ||
                  (!isCreatingMode && !knowledgeBaseId)
                }
                disabledMessage={
                  storageQuota.isBlocked
                    ? storageQuota.message ||
                      t(
                        "quota.uploadBlocked",
                        "Uploads are blocked - storage limit reached"
                      )
                    : undefined
                }
                componentHeight={uploadHeight}
                isCreatingMode={isCreatingMode}
                // Use internal ID for backend operations; fall back to name in creation mode
                indexName={knowledgeBaseId || knowledgeBaseName}
                newKnowledgeBaseName={isCreatingMode ? knowledgeBaseName : ""}
                modelMismatch={modelMismatch}
                onNameStatusChange={setNameStatus}
              />
            )}
          </div>
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
          onSaved={() => setDocumentTagRefreshKey((current) => current + 1)}
          onManageDefinitions={() => {
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
            onClose={() => setSelectedFile(null)}
          />
        )}
      </div>
    );
  }
);

export default DocumentListContainer;
