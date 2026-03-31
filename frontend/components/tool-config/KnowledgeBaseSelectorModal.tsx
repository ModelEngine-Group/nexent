"use client";

import React, { useState, useMemo, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";

import {
  Modal,
  Button,
  Input,
  Select,
  Spin,
  Checkbox,
  ConfigProvider,
} from "antd";
import {
  SearchOutlined,
  SyncOutlined,
  ExclamationCircleOutlined,
} from "@ant-design/icons";

import { KnowledgeBase } from "@/types/knowledgeBase";
import { KB_LAYOUT, KB_TAG_VARIANTS } from "@/const/knowledgeBaseLayout";
import {
  isEmbeddingModelCompatible as isEmbeddingModelCompatibleBase,
  isMultimodalConstraintMismatch as isMultimodalConstraintMismatchBase,
} from "@/lib/knowledgeBaseCompatibility";

interface KnowledgeBaseSelectorProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (selectedKnowledgeBases: KnowledgeBase[]) => void;
  selectedIds: string[];
  toolType: "knowledge_base_search" | "dify_search" | "datamate_search" | "idata_search";
  title?: string;
  maxSelect?: number;
  showCreateButton?: boolean;
  showDeleteButton?: boolean;
  showCheckbox?: boolean;
  // Dify/iData configuration for fetching knowledge bases
  difyConfig?: {
    serverUrl?: string;
    apiKey?: string;
    userId?: string;
    knowledgeSpaceId?: string;
  };
}

function getKnowledgeBaseSourcesForTool(
  toolType: "knowledge_base_search" | "dify_search" | "datamate_search" | "idata_search"
): string[] {
  switch (toolType) {
    case "knowledge_base_search":
      return ["nexent"];
    case "dify_search":
      return ["dify"];
    case "datamate_search":
      return ["datamate"];
    case "idata_search":
      return ["idata"];
    default:
      return ["nexent"];
  }
}

interface KnowledgeBaseSelectorModalProps extends KnowledgeBaseSelectorProps {
  knowledgeBases: KnowledgeBase[];
  isLoading?: boolean;
  getModelDisplayName?: (modelId: string) => string;
  onSync?: (
    toolType: string,
    difyConfig?: { serverUrl?: string; apiKey?: string }
  ) => void;
  showCheckbox?: boolean;
  onSyncComplete?: (knowledgeBases: KnowledgeBase[]) => void;
  syncLoading?: boolean; // Loading state for sync button
  // Selection validation props
  isSelectable?: (kb: KnowledgeBase) => boolean;
  currentEmbeddingModel?: string | null;
  currentMultiEmbeddingModel?: string | null;
  toolMultimodal?: boolean | null;
  // Dify/iData configuration for fetching knowledge bases
  difyConfig?: {
    serverUrl?: string;
    apiKey?: string;
    userId?: string;
    knowledgeSpaceId?: string;
  };
}

export default function KnowledgeBaseSelectorModal({
  isOpen,
  onClose,
  onConfirm,
  selectedIds,
  toolType,
  title,
  maxSelect,
  knowledgeBases,
  isLoading = false,
  getModelDisplayName = (modelId: string) => modelId,
  onSync,
  showCheckbox = true,
  onSyncComplete,
  syncLoading = false,
  isSelectable,
  currentEmbeddingModel = null,
  currentMultiEmbeddingModel = null,
  toolMultimodal = null,
  difyConfig,
}: KnowledgeBaseSelectorModalProps) {
  const { t } = useTranslation("common");

  // Selection state (kept for internal logic but not displayed)
  const [tempSelectedIds, setTempSelectedIds] = useState<string[]>([]);
  // Search and filter state
  const [searchKeyword, setSearchKeyword] = useState("");
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  // Track the embedding model from selected knowledge bases for auto-filtering
  const [selectedEmbeddingModel, setSelectedEmbeddingModel] = useState<string | null>(null);
  // Model mismatch confirmation modal state
  const [pendingSelection, setPendingSelection] = useState<{ id: string; kb: KnowledgeBase } | null>(null);
  const [confirmModalOpen, setConfirmModalOpen] = useState(false);
  const [modelMismatchInfo, setModelMismatchInfo] = useState<{
    existingModel: string;
    newModel: string;
    existingKBName: string;
    newKBName: string;
  } | null>(null);

  // Initialize selection state when modal opens
  useEffect(() => {
    if (isOpen) {
      setTempSelectedIds(selectedIds);
      setSearchKeyword("");
      setSelectedSources([]);
      setSelectedModels([]);
    }
  }, [isOpen]);

  // Sync tempSelectedIds whenever selectedIds changes while modal is open
  // This ensures selected knowledge bases are always shown correctly
  // especially when URL/API key changes in the parent component
  useEffect(() => {
    if (isOpen) {
      setTempSelectedIds(selectedIds);
    }
  }, [isOpen, selectedIds]);

  // Clear selection when knowledge bases list becomes empty
  // This handles cases where the URL/API key is changed and no knowledge bases are available
  useEffect(() => {
    if (isOpen && knowledgeBases.length === 0 && selectedIds.length > 0) {
      setTempSelectedIds([]);
    }
  }, [isOpen, knowledgeBases, selectedIds]);

  // Get allowed sources for the tool type
  const allowedSources = useMemo(() => {
    return getKnowledgeBaseSourcesForTool(toolType);
  }, [toolType]);

  // Calculate available filter options based on actual knowledge bases
  const availableSources = useMemo(() => {
    const sources = new Set(knowledgeBases.map((kb) => kb.source));
    return Array.from(sources)
      .filter((source) => source && allowedSources.includes(source))
      .sort();
  }, [knowledgeBases, allowedSources]);

  const availableModels = useMemo(() => {
    const models = new Set(knowledgeBases.map((kb) => kb.embeddingModel));
    return Array.from(models)
      .filter((model) => model && model !== "unknown")
      .sort();
  }, [knowledgeBases]);

  // Format date function, only keep date part
  const formatDate = useCallback((dateValue: any) => {
    try {
      const date =
        typeof dateValue === "number"
          ? new Date(dateValue)
          : new Date(dateValue);
      return isNaN(date.getTime())
        ? String(dateValue ?? "")
        : date.toISOString().split("T")[0];
    } catch (e) {
      return String(dateValue ?? "");
    }
  }, []);

  const isMultimodalConstraintMismatch = useCallback(
    (kb: KnowledgeBase) => {
      return isMultimodalConstraintMismatchBase(kb, toolMultimodal);
    },
    [toolMultimodal]
  );

  const isEmbeddingModelCompatible = useCallback(
    (kb: KnowledgeBase) => {
      return isEmbeddingModelCompatibleBase(
        kb,
        currentEmbeddingModel,
        currentMultiEmbeddingModel
      );
    },
    [currentEmbeddingModel, currentMultiEmbeddingModel]
  );

  // Check if a knowledge base can be selected
  const checkCanSelect = useCallback(
    (kb: KnowledgeBase): boolean => {
      // If custom isSelectable function is provided, use it
      if (isSelectable) {
        return isSelectable(kb);
      }

      // Default selection logic:
      // Only empty knowledge bases (0 documents AND 0 chunks) cannot be selected
      const isEmpty =
        (kb.documentCount || 0) === 0 && (kb.chunkCount || 0) === 0;
      if (isEmpty) {
        return false;
      }

      // For nexent source, check model matching against current tenant config and tool multimodal constraint.
      if (kb.source === "nexent") {
        if (isMultimodalConstraintMismatch(kb)) {
          return false;
        }
        return isEmbeddingModelCompatible(kb);
      }

      return true;
    },
    [
      isSelectable,
      isEmbeddingModelCompatible,
      isMultimodalConstraintMismatch,
    ]
  );

  const getModelMismatch = useCallback(
    (kb: KnowledgeBase): boolean => {
      if (kb.source !== "nexent") {
        return false;
      }

      const hasMultimodalConstraintMismatch =
        isMultimodalConstraintMismatchBase(kb, toolMultimodal);
      if (hasMultimodalConstraintMismatch) {
        return true;
      }

      const embeddingModel = kb.embeddingModel;
      if (!embeddingModel || embeddingModel === "unknown") {
        return false;
      }

      if (kb.is_multimodal) {
        if (!currentMultiEmbeddingModel) {
          return true;
        }
        return embeddingModel !== currentMultiEmbeddingModel;
      }

      if (!currentEmbeddingModel) {
        return false;
      }
      return embeddingModel !== currentEmbeddingModel;
    },
    [currentEmbeddingModel, currentMultiEmbeddingModel, toolMultimodal]
  );

  // Filter knowledge bases based on tool type, search, and filters
  const filteredKnowledgeBases = useMemo(() => {
    let filtered = knowledgeBases.filter((kb) => {
      // Filter by tool type source
      if (!allowedSources.includes(kb.source)) {
        return false;
      }

      // Keyword search
      const keyword = searchKeyword.trim();
      if (keyword) {
        const matchesSearch =
          kb.name.toLowerCase().includes(keyword.toLowerCase()) ||
          (kb.description &&
            kb.description.toLowerCase().includes(keyword.toLowerCase())) ||
          (kb.nickname &&
            kb.nickname.toLowerCase().includes(keyword.toLowerCase()));
        if (!matchesSearch) return false;
      }

      // Source filter
      if (selectedSources.length > 0 && !selectedSources.includes(kb.source)) {
        return false;
      }

      // Model filter
      if (
        selectedModels.length > 0 &&
        !selectedModels.includes(kb.embeddingModel)
      ) {
        return false;
      }

      return true;
    });

    // Sort by update time (latest first)
    filtered = [...filtered].sort((a, b) => {
      const aTime = a.updatedAt ? new Date(a.updatedAt).getTime() : 0;
      const bTime = b.updatedAt ? new Date(b.updatedAt).getTime() : 0;
      return bTime - aTime;
    });

    return filtered;
  }, [
    knowledgeBases,
    allowedSources,
    searchKeyword,
    selectedSources,
    selectedModels,
  ]);

  // Toggle selection (still needed for confirm)
  const toggleSelection = useCallback(
    (id: string) => {
      // Find the knowledge base
      const kb = knowledgeBases.find((k) => k.id === id);
      if (!kb) return;

      // Check if can be selected
      if (!checkCanSelect(kb)) {
        return;
      }

        setTempSelectedIds((prev) => {
        if (prev.includes(id)) {
          // When deselecting, check if we need to clear the model filter
          const newSelected = prev.filter((itemId) => itemId !== id);
          // If no more selections, clear the model filter
          if (newSelected.length === 0) {
            setSelectedEmbeddingModel(null);
            setSelectedModels([]); // Clear the model filter dropdown as well
          } else {
            // Check if remaining selected nexent KBs have consistent models
          const remainingKBs = knowledgeBases.filter((k) => newSelected.includes(k.id) && k.source === "nexent");
            const remainingModels = [...new Set(remainingKBs.map((k) => k.embeddingModel).filter((m) => m && m !== "unknown"))];
            if (remainingModels.length === 1) {
              setSelectedEmbeddingModel(remainingModels[0]);
              setSelectedModels([remainingModels[0]]);
            } else if (remainingModels.length === 0) {
              setSelectedEmbeddingModel(null);
              setSelectedModels([]);
            }
          }
          return newSelected;
        }

        // Check max select limit
        if (maxSelect && prev.length >= maxSelect) {
          return prev;
        }

        // Check model consistency when adding new selection (only for nexent source)
        // Only apply model consistency check when adding nexent KBs
        const isNewKBNexent = kb.source === "nexent";

        if (isNewKBNexent && kb.embeddingModel && kb.embeddingModel !== "unknown") {
          // Get existing nexent KBs from selection
          const existingNexentKBs = knowledgeBases.filter((k) => prev.includes(k.id) && k.source === "nexent");
          const existingNexentModels = [...new Set(existingNexentKBs.map((k) => k.embeddingModel).filter((m) => m && m !== "unknown"))];

          // If there are existing nexent selections and the new KB has a different model, show confirmation
          if (
            existingNexentModels.length > 0 &&
            !existingNexentModels.includes(kb.embeddingModel)
          ) {
            // Store the pending selection and show confirmation modal
            setModelMismatchInfo({
              existingModel: existingNexentModels[0],
              newModel: kb.embeddingModel,
              existingKBName: existingNexentKBs[0]?.name || "",
              newKBName: kb.name,
            });
            setPendingSelection({ id, kb });
            setConfirmModalOpen(true);
            return prev;
          }
        }

        // Auto-filter by the selected knowledge base's embedding model
        // Only for nexent source with valid embedding model
        if (kb.source === "nexent" && kb.embeddingModel && kb.embeddingModel !== "unknown") {
          setSelectedEmbeddingModel(kb.embeddingModel);
          setSelectedModels([kb.embeddingModel]);
        }

        return [...prev, id];
      });
    },
    [knowledgeBases, maxSelect, checkCanSelect]
  );

  // Clear all selections
  const clearAllSelections = useCallback(() => {
    setTempSelectedIds([]);
    setSelectedEmbeddingModel(null);
    setSelectedModels([]); // Clear the model filter as well
  }, []);

  // Handle confirm
  const handleConfirm = useCallback(() => {
    const selectedKnowledgeBases = knowledgeBases.filter((kb) =>
      tempSelectedIds.includes(kb.id)
    );
    onConfirm(selectedKnowledgeBases);
    onClose();
  }, [knowledgeBases, tempSelectedIds, onConfirm, onClose]);

  // Handle cancel
  const handleCancel = useCallback(() => {
    setTempSelectedIds(selectedIds);
    onClose();
  }, [selectedIds, onClose]);

  // Default title based on tool type
  const defaultTitle = useMemo(() => {
    const titles: Record<string, string> = {
      knowledge_base_search: t("toolConfig.knowledgeBaseSelector.title.local"),
      dify_search: t("toolConfig.knowledgeBaseSelector.title.dify"),
      datamate_search: t("toolConfig.knowledgeBaseSelector.title.datamate"),
    };
    return (
      titles[toolType] || t("toolConfig.knowledgeBaseSelector.title.default")
    );
  }, [toolType, t]);

  return (
    <Modal
      title={title || defaultTitle}
      open={isOpen}
      onCancel={handleCancel}
      onOk={handleConfirm}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      width={800}
      className="knowledge-base-selector-modal"
      styles={{
        body: {
          maxHeight: "70vh",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          padding: 0,
        },
      }}
    >
      {/* Fixed header area - consistent with KnowledgeBaseList */}
      <div
        className={`${KB_LAYOUT.HEADER_PADDING} border-b border-gray-200 shrink-0 bg-white`}
      >
        <div className="flex items-center justify-between">
          <div>
            <h3
              className={`${KB_LAYOUT.TITLE_MARGIN} ${KB_LAYOUT.TITLE_TEXT} text-gray-800`}
            >
              {t("knowledgeBase.list.title")}
            </h3>
          </div>
          <div className="flex items-center" style={{ gap: "8px" }}>
            <Button
              style={{
                padding: "4px 15px",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "8px",
                backgroundColor: "#1677ff",
                color: "white",
                border: "none",
              }}
              className="hover:!bg-blue-600"
              type="primary"
              onClick={() => {
                // Call the onSync callback with difyConfig and notify parent when complete
                const syncResult = onSync?.(toolType, difyConfig);
                // Check if the result is a Promise-like object
                if (
                  syncResult &&
                  typeof (syncResult as Promise<void>).then === "function"
                ) {
                  (syncResult as Promise<void>).then(() => {
                    // After sync completes, trigger onSyncComplete if provided
                    // The parent will refresh the knowledgeBases list
                    onSyncComplete?.(knowledgeBases);
                  });
                } else {
                  // If onSync doesn't return a promise, still call onSyncComplete
                  onSyncComplete?.(knowledgeBases);
                }
              }}
            >
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: "14px",
                  height: "14px",
                }}
              >
                <SyncOutlined spin={syncLoading} style={{ color: "white" }} />
              </span>
              <span>{t("knowledgeBase.button.sync")}</span>
            </Button>
          </div>
        </div>

        {/* Search and filter area */}
        <div className="mt-3 flex items-center gap-3">
          <Input
            placeholder={t("knowledgeBase.search.placeholder")}
            prefix={<SearchOutlined />}
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            style={{ width: 250 }}
            allowClear
          />

          {availableSources.length > 0 && (
            <Select
              mode="multiple"
              placeholder={t("knowledgeBase.filter.source.placeholder")}
              value={selectedSources}
              onChange={setSelectedSources}
              style={{ minWidth: 150 }}
              allowClear
              maxTagCount={2}
            >
              {availableSources.map((source) => (
                <Select.Option key={source} value={source}>
                  {t(`knowledgeBase.source.${source}`, {
                    defaultValue: source,
                  })}
                </Select.Option>
              ))}
            </Select>
          )}

          {availableModels.length > 0 && (
            <Select
              mode="multiple"
              placeholder={t("knowledgeBase.filter.model.placeholder")}
              value={selectedModels}
              onChange={setSelectedModels}
              style={{ minWidth: 180 }}
              allowClear
              maxTagCount={2}
            >
              {availableModels.map((model) => (
                <Select.Option key={model} value={model}>
                  {getModelDisplayName(model)}
                </Select.Option>
              ))}
            </Select>
          )}
        </div>
      </div>

      {/* Fixed selection status area */}
      <div className="border-b border-gray-200 shrink-0 relative z-10 shadow-md">
        <div className="px-5 py-2 bg-blue-50">
          <div className="flex items-center justify-between">
            <div className="flex items-center">
              <span className="font-medium text-blue-700">
                {t("knowledgeBase.selected.prefix")}{" "}
              </span>
              <span className="mx-1 text-blue-600 font-bold text-lg">
                {tempSelectedIds.length}
              </span>
              <span className="font-medium text-blue-700">
                {t("knowledgeBase.selected.suffix")}
              </span>
            </div>
            <div className="flex items-center gap-2">
              {/* Select All button */}
              {filteredKnowledgeBases.length > 0 &&
                tempSelectedIds.length < filteredKnowledgeBases.length && (
                  <Button
                    type="link"
                    size="small"
                    className="text-blue-600 font-medium p-0 h-auto"
                    onClick={() => {
                      // Only select knowledge bases that can be selected
                      const selectableIds = filteredKnowledgeBases
                        .filter((kb) => checkCanSelect(kb))
                        .map((kb) => kb.id);

                      // Apply maxSelect limit if set
                      if (maxSelect) {
                        const remainingSlots =
                          maxSelect - tempSelectedIds.length;
                        if (remainingSlots > 0) {
                          // Add selectable IDs that aren't already selected
                          const availableToAdd = selectableIds.filter(
                            (id) => !tempSelectedIds.includes(id)
                          );
                          // Limit to remaining slots
                          const newIds = availableToAdd.slice(
                            0,
                            remainingSlots
                          );
                          setTempSelectedIds([...tempSelectedIds, ...newIds]);
                          return;
                        }
                      }

                      setTempSelectedIds(selectableIds);
                    }}
                  >
                    {t("knowledgeBase.button.selectAll")}
                  </Button>
                )}
              {/* Clear Selection button */}
              {tempSelectedIds.length > 0 && (
                <Button
                  type="link"
                  size="small"
                  danger
                  className="font-medium p-0 h-auto"
                  onClick={clearAllSelections}
                >
                  {t("knowledgeBase.button.clearSelection")}
                </Button>
              )}
            </div>
          </div>

          {tempSelectedIds.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2 mb-1">
              {tempSelectedIds.map((id) => {
                const kb = knowledgeBases.find((kb) => kb.id === id);
                return kb ? (
                  <span
                    key={id}
                    className="inline-flex items-center justify-center bg-blue-100 text-blue-800 rounded text-sm font-medium group"
                    style={{ maxWidth: "fit-content", padding: "2px 6px" }}
                  >
                    <span
                      className="truncate"
                      style={{
                        maxWidth: "150px",
                        ...KB_LAYOUT.KB_NAME_OVERFLOW,
                      }}
                      title={kb.name}
                    >
                      {kb.name}
                    </span>
                    <button
                      className="ml-1.5 text-blue-600 hover:text-blue-800 flex-shrink-0 text-sm leading-none"
                      onClick={() => toggleSelection(id)}
                      aria-label={t("knowledgeBase.button.removeKb", {
                        name: kb.name,
                      })}
                    >
                      ×
                    </button>
                  </span>
                ) : null;
              })}
            </div>
          )}
        </div>
      </div>

      {/* Knowledge base list - consistent with KnowledgeBaseList */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden bg-white">
        {isLoading ? (
          <div className="flex items-center justify-center h-full">
            <Spin tip={t("common.loading")} />
          </div>
        ) : filteredKnowledgeBases.length > 0 ? (
          <div className="divide-y-0">
            {filteredKnowledgeBases.map((kb, index) => {
              // Use a more robust ID comparison to handle potential format differences
              const isSelected = tempSelectedIds.some(
                (selectedId) =>
                  String(selectedId).trim() === String(kb.id).trim()
              );
              const canSelect = checkCanSelect(kb);
              const hasModelMismatch = getModelMismatch(kb);

              return (
                <div
                  key={kb.id}
                  className={`${KB_LAYOUT.ROW_PADDING} px-2 hover:bg-gray-50 transition-colors ${!canSelect ? "opacity-60" : ""}`}
                  onClick={() => canSelect && toggleSelection(kb.id)}
                >
                  <div className="flex items-start">
                    {showCheckbox && (
                      <div
                        className="kb-checkbox-wrapper px-2"
                        onClick={(e) => {
                          e.stopPropagation();
                        }}
                        style={{
                          minWidth: "40px",
                          minHeight: "40px",
                          display: "flex",
                          alignItems: "flex-start",
                          justifyContent: "center",
                        }}
                      >
                        <ConfigProvider
                          theme={{
                            token: {
                              colorPrimary:
                                canSelect || isSelected ? "#1677ff" : "#90caf9",
                            },
                          }}
                        >
                          <Checkbox
                            checked={isSelected}
                            disabled={!canSelect && !isSelected}
                            onChange={(e) => {
                              e.stopPropagation();
                              toggleSelection(kb.id);
                            }}
                            style={{
                              cursor:
                                canSelect || isSelected
                                  ? "pointer"
                                  : "not-allowed",
                              transform: "scale(1.5)",
                            }}
                          />
                        </ConfigProvider>
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      {/* First row: Name */}
                      <div className="flex items-center justify-between">
                        <p
                          className={`${KB_LAYOUT.KB_NAME_TEXT} ${!canSelect ? "text-gray-400" : "text-gray-800"} truncate`}
                          style={{
                            maxWidth: KB_LAYOUT.KB_NAME_MAX_WIDTH,
                            ...KB_LAYOUT.KB_NAME_OVERFLOW,
                          }}
                          title={kb.name}
                        >
                          {kb.name}
                        </p>
                      </div>

                      {/* First row: Basic info tags */}
                      <div
                        className={`flex flex-wrap items-center ${KB_LAYOUT.TAG_MARGIN} ${KB_LAYOUT.TAG_SPACING}`}
                      >
                        {/* Document count tag */}
                        <span
                          className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_TAG_VARIANTS.default} mr-1`}
                        >
                          {t("knowledgeBase.tag.documents", {
                            count: kb.documentCount || 0,
                          })}
                        </span>

                        {/* Chunk count tag */}
                        <span
                          className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_TAG_VARIANTS.default} mr-1`}
                        >
                          {t("knowledgeBase.tag.chunks", {
                            count: kb.chunkCount || 0,
                          })}
                        </span>

                        {/* Source tag */}
                        <span
                          className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_TAG_VARIANTS.default} mr-1`}
                        >
                          {t("knowledgeBase.tag.source", {
                            source: t(`knowledgeBase.source.${kb.source}`, {
                              defaultValue: kb.source,
                            }),
                          })}
                        </span>

                        {/* Creation date - only show when there are documents or chunks */}
                        {((kb.documentCount || 0) > 0 ||
                          (kb.chunkCount || 0) > 0) && (
                          <span
                            className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_TAG_VARIANTS.default} mr-1`}
                          >
                            {t("knowledgeBase.tag.createdAt", {
                              date: formatDate(kb.createdAt),
                            })}
                          </span>
                        )}
                      </div>

                      {/* Second row: Model tags */}
                      <div
                        className={`flex flex-wrap items-center ${KB_LAYOUT.SECOND_ROW_TAG_MARGIN} ${KB_LAYOUT.TAG_SPACING}`}
                      >
                        {/* Model tag - only show when model is not "unknown" and there are documents or chunks */}
                        {((kb.documentCount || 0) > 0 ||
                          (kb.chunkCount || 0) > 0) &&
                          kb.embeddingModel &&
                          kb.embeddingModel !== "unknown" && (
                            <span
                              className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_TAG_VARIANTS.model} mr-1`}
                            >
                              {getModelDisplayName(kb.embeddingModel)}
                              {t("knowledgeBase.tag.model", {
                                model: "",
                              })}
                            </span>
                          )}
                        {kb.is_multimodal && (
                          <span
                            className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_TAG_VARIANTS.red} mr-1`}
                          >
                            multimodal
                          </span>
                        )}
                        {hasModelMismatch && (
                          <span
                            className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_TAG_VARIANTS.warning} mr-1`}
                          >
                            {t("knowledgeBase.tag.modelMismatch")}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div
            className={`${KB_LAYOUT.EMPTY_STATE_PADDING} text-center text-gray-500`}
          >
            {searchKeyword || selectedSources.length > 0
              ? t("knowledgeBase.list.noResults")
              : t("knowledgeBase.list.empty")}
          </div>
        )}
      </div>

      {/* Model mismatch confirmation modal */}
      <Modal
        title={
          <div className="flex items-center gap-2">
            <ExclamationCircleOutlined style={{ color: "#faad14", fontSize: 20 }} />
            <span>{t("toolConfig.knowledgeBaseSelector.modelMismatch.title", "模型不匹配")}</span>
          </div>
        }
        open={confirmModalOpen}
        onCancel={() => {
          setConfirmModalOpen(false);
          setPendingSelection(null);
          setModelMismatchInfo(null);
        }}
        footer={[
          <Button
            key="cancel"
            onClick={() => {
              setConfirmModalOpen(false);
              setPendingSelection(null);
              setModelMismatchInfo(null);
            }}
          >
            {t("common.cancel")}
          </Button>,
          <Button
            key="confirm"
            type="primary"
            danger
            onClick={() => {
              if (pendingSelection) {
                setTempSelectedIds((prev) => {
                  // Remove all KBs with the old model
                  const existingKBs = knowledgeBases.filter((k) => prev.includes(k.id));
                  const existingModels = [...new Set(existingKBs.map((k) => k.embeddingModel).filter((m) => m && m !== "unknown"))];
                  const idsToRemove = existingKBs
                    .filter((k) => existingModels.includes(k.embeddingModel))
                    .map((k) => k.id);

                  // Update model filter
                  if (pendingSelection.kb.embeddingModel && pendingSelection.kb.embeddingModel !== "unknown") {
                    setSelectedEmbeddingModel(pendingSelection.kb.embeddingModel);
                    setSelectedModels([pendingSelection.kb.embeddingModel]);
                  }

                  // Return new selection (only the new KB with different model)
                  return [pendingSelection.id];
                });
              }
              setConfirmModalOpen(false);
              setPendingSelection(null);
              setModelMismatchInfo(null);
            }}
          >
            {t("toolConfig.knowledgeBaseSelector.modelMismatch.switchModel", "切换模型")}
          </Button>,
        ]}
      >
        <div className="py-4">
          <p className="mb-4 text-gray-600">
            {t(
              "toolConfig.knowledgeBaseSelector.modelMismatch.description",
              "所选知识库的向量化模型与其他已选知识库不一致。"
            )}
          </p>
          {modelMismatchInfo && (
            <div className="bg-gray-50 p-4 rounded-lg space-y-3">
              <div className="flex items-start">
                <span className="text-gray-500 w-20 flex-shrink-0">
                  {t("toolConfig.knowledgeBaseSelector.modelMismatch.existing", "已选知识库")}:
                </span>
                <div className="flex-1">
                  <div className="text-gray-800 font-medium">{modelMismatchInfo.existingKBName}</div>
                  <div className="text-gray-500 text-sm">
                    {t("toolConfig.knowledgeBaseSelector.modelMismatch.model", "模型")}: {modelMismatchInfo.existingModel}
                  </div>
                </div>
              </div>
              <div className="flex items-start">
                <span className="text-gray-500 w-20 flex-shrink-0">
                  {t("toolConfig.knowledgeBaseSelector.modelMismatch.new", "新选择")}:
                </span>
                <div className="flex-1">
                  <div className="text-gray-800 font-medium">{modelMismatchInfo.newKBName}</div>
                  <div className="text-gray-500 text-sm">
                    {t("toolConfig.knowledgeBaseSelector.modelMismatch.model", "模型")}: {modelMismatchInfo.newModel}
                  </div>
                </div>
              </div>
            </div>
          )}
          <p className="mt-4 text-gray-500 text-sm">
            {t(
              "toolConfig.knowledgeBaseSelector.modelMismatch.hint",
              "提示：向量化模型不一致的知识库可能无法同时用于检索，建议选择相同模型的知识库。"
            )}
          </p>
        </div>
      </Modal>
    </Modal>
  );
}
