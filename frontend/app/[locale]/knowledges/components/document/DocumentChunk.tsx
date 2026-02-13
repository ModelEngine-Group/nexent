"use client";

import React, { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  Tabs,
  Card,
  Badge,
  Button,
  App,
  Spin,
  Tag,
  Form,
  Modal,
  Pagination,
  Input,
} from "antd";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import {
  Download,
  ScanText,
  Trash2,
  SquarePen,
  Search,
  FilePlus2,
  Goal,
  X,
  Server,
  Database,
} from "lucide-react";
import { FieldNumberOutlined } from "@ant-design/icons";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { Document } from "@/types/knowledgeBase";
import log from "@/lib/logger";
import { formatScoreAsPercentage, getScoreColor } from "@/lib/utils";
import { Tooltip, TooltipProvider } from "@/components/ui/tooltip";

interface Chunk {
  id: string;
  content: string;
  title?: string;
  path_or_url?: string;
  filename?: string;
  create_time?: string;
  score?: number; // Search score (0-1 range) - only present in search results
  source_type?: string; // Source type: "file" (nexent) or "datamate"
}

interface ChunkFormValues {
  title?: string;
  filename?: string;
  content: string;
}

interface DocumentChunkProps {
  knowledgeBaseName: string; // User-facing knowledge base name (display name)
  knowledgeBaseId: string; // Internal knowledge base ID / Elasticsearch index name
  documents: Document[];
  getFileIcon: (type: string) => string;
  currentEmbeddingModel?: string | null;
  knowledgeBaseEmbeddingModel?: string;
  onChunkCountChange?: () => void; // Callback when chunk count changes (for updating KnowledgeBaseList)
}

const PAGE_SIZE = 10;

const TABS_ROOT_CLASS = "document-chunk-tabs";

const { TextArea } = Input;

const DocumentChunk: React.FC<DocumentChunkProps> = ({
  knowledgeBaseName,
  knowledgeBaseId,
  documents,
  getFileIcon,
  currentEmbeddingModel = null,
  knowledgeBaseEmbeddingModel = "",
  onChunkCountChange,
}) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { confirm } = useConfirmModal();
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [loading, setLoading] = useState(false);
  const [activeDocumentKey, setActiveDocumentKey] = useState<string>("");
  const [documentChunkCounts, setDocumentChunkCounts] = useState<
    Record<string, number>
  >({});
  const [pagination, setPagination] = useState<{
    page: number;
    pageSize: number;
  }>({
    page: 1,
    pageSize: PAGE_SIZE,
  });
  const [searchValue, setSearchValue] = useState<string>("");
  const [chunkSearchResult, setChunkSearchResult] = useState<Chunk[] | null>(
    null
  );
  const [chunkSearchLoading, setChunkSearchLoading] = useState(false);
  const [isChunkModalOpen, setIsChunkModalOpen] = useState(false);
  const [chunkModalMode, setChunkModalMode] = useState<"create" | "edit">(
    "create"
  );
  const [chunkSubmitting, setChunkSubmitting] = useState(false);
  const [editingChunk, setEditingChunk] = useState<Chunk | null>(null);
  const [chunkForm] = Form.useForm<ChunkFormValues>();
  const [tooltipResetKey, setTooltipResetKey] = useState(0);
  // Ref for scrolling to bottom after creating new chunk
  const contentScrollRef = useRef<HTMLDivElement>(null);
  const [scrollToBottomAfterLoad, setScrollToBottomAfterLoad] = useState(false);

  const resetChunkSearch = React.useCallback(() => {
    setChunkSearchResult(null);
    setChunkSearchLoading(false);
  }, []);

  const isChunkSearchActive = chunkSearchResult !== null;
  const activeDocument = React.useMemo(
    () => documents.find((doc) => doc.id === activeDocumentKey),
    [documents, activeDocumentKey]
  );

  const forceCloseTooltips = React.useCallback(() => {
    setTooltipResetKey((prev) => prev + 1);
  }, []);

  // Determine if embedding models mismatch (specific condition for tooltip)
  const isEmbeddingModelMismatch = React.useMemo(() => {
    if (!currentEmbeddingModel || !knowledgeBaseEmbeddingModel) {
      return false;
    }
    if (knowledgeBaseEmbeddingModel === "unknown") {
      return false;
    }
    return currentEmbeddingModel !== knowledgeBaseEmbeddingModel;
  }, [currentEmbeddingModel, knowledgeBaseEmbeddingModel]);

  // Determine if in read-only mode (embedding model mismatch OR other read-only reasons)
  // Note: isReadOnlyMode is broader, includes model mismatch and other conditions
  const isReadOnlyMode = React.useMemo(() => {
    if (!currentEmbeddingModel || !knowledgeBaseEmbeddingModel) {
      return false;
    }
    if (knowledgeBaseEmbeddingModel === "unknown") {
      return false;
    }
    return currentEmbeddingModel !== knowledgeBaseEmbeddingModel;
  }, [currentEmbeddingModel, knowledgeBaseEmbeddingModel]);

  // Disabled tooltip message when embedding model mismatch
  const disabledTooltipMessage = React.useMemo(() => {
    if (isEmbeddingModelMismatch && currentEmbeddingModel && knowledgeBaseEmbeddingModel && knowledgeBaseEmbeddingModel !== "unknown") {
      return t("document.chunk.tooltip.disabledDueToModelMismatch", {
        currentModel: currentEmbeddingModel,
        knowledgeBaseModel: knowledgeBaseEmbeddingModel
      });
    }
    return "";
  }, [isEmbeddingModelMismatch, currentEmbeddingModel, knowledgeBaseEmbeddingModel, t]);

  // Set active document when documents change
  useEffect(() => {
    if (documents.length === 0) {
      if (activeDocumentKey) {
        setActiveDocumentKey("");
      }
      setChunks([]);
      setTotal(0);
      return;
    }

    const hasActiveDocument = documents.some(
      (doc) => doc.id === activeDocumentKey
    );

    if (!hasActiveDocument) {
      setActiveDocumentKey(documents[0].id);
      setPagination((prev) => ({ ...prev, page: 1 }));
    }
  }, [documents, activeDocumentKey]);

  // Load chunks for active document with server-side pagination
  const loadChunks = React.useCallback(async () => {
    if (!knowledgeBaseName || !activeDocumentKey) {
      return;
    }

    setLoading(true);
    try {
      const result = await knowledgeBaseService.previewChunksPaginated(
        knowledgeBaseName,
        pagination.page,
        pagination.pageSize,
        activeDocumentKey
      );

      const loadedChunks = result.chunks || [];
      setTotal(result.total || 0);
      setDocumentChunkCounts((prev) => ({
        ...prev,
        [activeDocumentKey]: result.total || 0,
      }));

      setChunks(loadedChunks);

      // Scroll to bottom after loading if requested (e.g., after creating new chunk)
      if (scrollToBottomAfterLoad) {
        setScrollToBottomAfterLoad(false);
        // Use setTimeout to ensure DOM is updated
        setTimeout(() => {
          if (contentScrollRef.current) {
            contentScrollRef.current.scrollTop = contentScrollRef.current.scrollHeight;
          }
        }, 100);
      }
    } catch (error) {
      log.error("Failed to load chunks:", error);
      message.error(t("document.chunk.error.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [
    knowledgeBaseName,
    activeDocumentKey,
    pagination.page,
    pagination.pageSize,
    scrollToBottomAfterLoad,
    message,
    t,
  ]);

  useEffect(() => {
    void loadChunks();
  }, [loadChunks]);

  useEffect(() => {
    if (documents.length === 0) {
      setDocumentChunkCounts({});
      setActiveDocumentKey("");
      return;
    }

    setDocumentChunkCounts((prev) => {
      const next = { ...prev };
      const docIds = new Set<string>();

      documents.forEach((doc) => {
        docIds.add(doc.id);

        if (
          typeof doc.chunk_num === "number" &&
          doc.chunk_num >= 0 &&
          next[doc.id] !== doc.chunk_num
        ) {
          next[doc.id] = doc.chunk_num;
        }
      });

      Object.keys(next).forEach((docId) => {
        if (!docIds.has(docId)) {
          delete next[docId];
        }
      });

      return next;
    });
  }, [documents]);

  // Handle document tab change
  const handleTabChange = (key: string) => {
    setActiveDocumentKey(key);
    setChunks([]);
    setTotal(documentChunkCounts[key] ?? 0);
    setPagination((prev) => ({ ...prev, page: 1 }));
  };

  // Handle pagination change
  const handlePaginationChange = (page: number, pageSize: number) => {
    setPagination({ page, pageSize });
  };

  const getDisplayName = React.useCallback((name: string): string => {
    const lastDotIndex = name.lastIndexOf(".");
    if (lastDotIndex <= 0) {
      return name;
    }
    return name.substring(0, lastDotIndex);
  }, []);

  // Clear search input and reset all search states
  const handleClearSearch = React.useCallback(() => {
    setSearchValue("");
    resetChunkSearch();
  }, [resetChunkSearch]);

  const handleSearch = React.useCallback(async () => {
    const trimmedValue = searchValue.trim();

    if (!trimmedValue) {
      resetChunkSearch();
      return;
    }

    // Check embedding model consistency before searching
    if (isEmbeddingModelMismatch && currentEmbeddingModel && knowledgeBaseEmbeddingModel && knowledgeBaseEmbeddingModel !== "unknown") {
      message.error(t("document.chunk.error.searchFailed", {
        currentModel: currentEmbeddingModel,
        knowledgeBaseModel: knowledgeBaseEmbeddingModel
      }));
      return;
    }

    if (!knowledgeBaseName) {
      message.error(t("document.chunk.error.searchFailed"));
      return;
    }

    setChunkSearchResult([]);
    setChunkSearchLoading(true);

    try {
      const response = await knowledgeBaseService.hybridSearch(
        knowledgeBaseId,
        trimmedValue,
        {
          topK: pagination.pageSize,
        }
      );

      const parsedChunks = (response.results || []).map((item) => {
        // Backend returns document fields at the top level
        return {
          id: item.id || "",
          content: item.content || "",
          path_or_url: item.path_or_url,
          filename: item.filename,
          create_time: item.create_time,
          score: item.score, // Preserve search score for display
          source_type: item.source_type, // Preserve source type for display
        };
      });

      setChunkSearchResult(parsedChunks);

      if (parsedChunks.length === 0) {
        message.info(t("document.chunk.search.noChunk"));
      }
    } catch (error) {
      log.error("Failed to search chunks:", error);
      message.error(t("document.chunk.error.searchFailed"));
      resetChunkSearch();
    } finally {
      setChunkSearchLoading(false);
    }
  }, [
    knowledgeBaseName,
    knowledgeBaseId,
    message,
    pagination.pageSize,
    resetChunkSearch,
    searchValue,
    t,
    isEmbeddingModelMismatch,
    currentEmbeddingModel,
    knowledgeBaseEmbeddingModel,
  ]);

  const refreshChunks = React.useCallback(async () => {
    if (isChunkSearchActive && searchValue.trim()) {
      await handleSearch();
      return;
    }
    await loadChunks();
  }, [handleSearch, isChunkSearchActive, loadChunks, searchValue]);

  // Download chunk as txt file
  const handleDownloadChunk = (chunk: Chunk) => {
    try {
      const content = chunk.content || "";
      const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${chunk.id}.txt`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (error) {
      log.error("Failed to download chunk:", error);
      message.error(t("document.chunk.error.downloadFailed"));
    }
  };

  const openCreateChunkModal = () => {
    if (!activeDocumentKey) {
      message.warning(t("document.chunk.search.noActiveDocument"));
      return;
    }
    forceCloseTooltips();
    setChunkModalMode("create");
    setEditingChunk(null);
    chunkForm.resetFields();
    chunkForm.setFieldsValue({
      filename: activeDocument?.name || "",
      content: "",
    });
    setIsChunkModalOpen(true);
  };

  const openEditChunkModal = (chunk: Chunk) => {
    if (!chunk.id) {
      message.error(t("document.chunk.error.missingChunkId"));
      return;
    }

    forceCloseTooltips();
    setChunkModalMode("edit");
    setEditingChunk(chunk);
    chunkForm.resetFields();
    chunkForm.setFieldsValue({
      filename: chunk.filename || activeDocument?.name || "",
      content: chunk.content || "",
    });
    setIsChunkModalOpen(true);
  };

  const closeChunkModal = () => {
    setIsChunkModalOpen(false);
    setEditingChunk(null);
    chunkForm.resetFields();
    forceCloseTooltips();
  };

  const handleChunkSubmit = async () => {
    if (!knowledgeBaseName) {
      message.error(t("document.chunk.error.loadFailed"));
      return;
    }
    if (!activeDocumentKey) {
      message.warning(t("document.chunk.search.noActiveDocument"));
      return;
    }

    // Check embedding model consistency before creating chunk
    if (chunkModalMode === "create") {
      if (knowledgeBaseEmbeddingModel &&
        knowledgeBaseEmbeddingModel !== "unknown" &&
        currentEmbeddingModel &&
        currentEmbeddingModel !== knowledgeBaseEmbeddingModel) {
        message.error(t("document.chunk.error.createFailed", {
          currentModel: currentEmbeddingModel,
          knowledgeBaseModel: knowledgeBaseEmbeddingModel
        }));
        return;
      }
    }

    try {
      const values = await chunkForm.validateFields();
      setChunkSubmitting(true);
      if (chunkModalMode === "create") {
        await knowledgeBaseService.createChunk(knowledgeBaseName, {
          content: values.content,
          filename: values.filename?.trim() || undefined,
          path_or_url: activeDocumentKey,
        });
        message.success(t("document.chunk.success.create"));
        resetChunkSearch();

        // Navigate to the last page to show the new chunk at the bottom
        const lastPage = Math.ceil((total + 1) / pagination.pageSize);
        setPagination((prev) => ({ ...prev, page: lastPage }));
        // Trigger scroll to bottom after data loads
        setScrollToBottomAfterLoad(true);
        // Notify parent to update knowledge base list (chunk count)
        onChunkCountChange?.();
      } else {
        if (!editingChunk?.id) {
          message.error(t("document.chunk.error.missingChunkId"));
          return;
        }
        await knowledgeBaseService.updateChunk(
          knowledgeBaseName,
          editingChunk.id,
          {
            content: values.content,
            filename: values.filename?.trim() || undefined,
          }
        );
        message.success(t("document.chunk.success.update"));
      }
      closeChunkModal();
      await refreshChunks();
    } catch (error) {
      if (error instanceof Error) {
        log.error("Failed to submit chunk:", error);
      }
      if (chunkModalMode === "create") {
        message.error(
          error instanceof Error && error.message
            ? error.message
            : t("document.chunk.error.createFailed")
        );
      } else {
        message.error(
          error instanceof Error && error.message
            ? error.message
            : t("document.chunk.error.updateFailed")
        );
      }
    } finally {
      setChunkSubmitting(false);
    }
  };

  const handleDeleteChunk = (chunk: Chunk) => {
    if (!chunk.id) {
      message.error(t("document.chunk.error.missingChunkId"));
      return;
    }
    if (!knowledgeBaseName) {
      message.error(t("document.chunk.error.deleteFailed"));
      return;
    }

    forceCloseTooltips();

    confirm({
      title: t("document.chunk.confirm.deleteTitle"),
      content: t("document.chunk.confirm.deleteContent"),
      okText: t("common.delete"),
      cancelText: t("common.cancel"),
      danger: true,
      onOk: async () => {
        try {
          await knowledgeBaseService.deleteChunk(knowledgeBaseName, chunk.id);
          message.success(t("document.chunk.success.delete"));
          forceCloseTooltips();
          // Update chunk count immediately for better UX
          setTotal((prevTotal) => Math.max(0, prevTotal - 1));
          setDocumentChunkCounts((prev) => ({
            ...prev,
            [chunk.path_or_url || activeDocumentKey]: Math.max(
              0,
              (prev[chunk.path_or_url || activeDocumentKey] || 1) - 1
            ),
          }));
          // Notify parent to update knowledge base list (chunk count)
          onChunkCountChange?.();
          await refreshChunks();
        } catch (error) {
          log.error("Failed to delete chunk:", error);
          message.error(
            error instanceof Error && error.message
              ? error.message
              : t("document.chunk.error.deleteFailed")
          );
        }
      },
      onCancel: () => {
        forceCloseTooltips();
      },
    });
  };

  const renderDocumentLabel = (doc: Document, chunkCount: number) => {
    const displayName = getDisplayName(doc.name || "");

    return (
      <Tooltip title={displayName} placement="top">
        <div className="flex w-full items-center justify-between gap-2 min-w-0">
          <div className="flex items-center gap-1.5 min-w-0">
            <span>{getFileIcon(doc.type)}</span>
            <span className="truncate text-sm font-medium text-gray-800 max-w-[150px]">
              {displayName}
            </span>
          </div>
          <Badge
            color="#1677ff"
            showZero
            count={chunkCount}
            className="flex-shrink-0 chunk-count-badge"
          />
        </div>
      </Tooltip>
    );
  };

  const chunkSearchResultMap = React.useMemo(() => {
    if (!chunkSearchResult) {
      return null;
    }

    return chunkSearchResult.reduce<Record<string, Chunk[]>>((acc, chunk) => {
      const docId = chunk.path_or_url;
      if (!docId) {
        return acc;
      }
      if (!acc[docId]) {
        acc[docId] = [];
      }
      acc[docId].push(chunk);
      return acc;
    }, {});
  }, [chunkSearchResult]);

  const tabItems = documents.map((doc) => {
    const chunkCount = isChunkSearchActive
      ? chunkSearchResultMap?.[doc.id]?.length ?? 0
      : documentChunkCounts[doc.id] ?? doc.chunk_num ?? 0;
    const isActive = doc.id === activeDocumentKey;
    const chunkSearchChunks = chunkSearchResultMap?.[doc.id] ?? [];
    const docChunksData = isActive
      ? isChunkSearchActive
        ? {
            chunks: chunkSearchChunks,
            total: chunkSearchChunks.length,
            paginatedChunks: chunkSearchChunks,
          }
        : { chunks, total, paginatedChunks: chunks }
      : { chunks: [], total: 0, paginatedChunks: [] };

    const showLoadingState = isActive
      ? isChunkSearchActive
        ? chunkSearchLoading && docChunksData.paginatedChunks.length === 0
        : loading && docChunksData.paginatedChunks.length === 0
      : false;

    return {
      key: doc.id,
      label: renderDocumentLabel(doc, chunkCount),
      children: (
        <div className="flex h-full flex-col min-h-0 overflow-hidden">
          <div ref={contentScrollRef} className="flex-1 min-h-0 overflow-y-auto p-4 pb-8">
            {showLoadingState ? (
              <div className="flex h-52 items-center justify-center">
                <Spin size="large" />
              </div>
            ) : docChunksData.total === 0 ? (
              <div className="rounded-md border border-dashed border-gray-200 p-10 text-center text-sm text-gray-500">
                {t("document.chunk.noChunks")}
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {docChunksData.paginatedChunks.map((chunk, index) => (
                  <Card
                    key={chunk.id || index}
                    size="small"
                    className="w-full"
                    title={
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex flex-wrap gap-1">
                          <Tag className="inline-flex items-center px-1.5 py-0.5 text-xs font-medium bg-gray-200 text-gray-800 border border-gray-200 rounded-md">
                            <FieldNumberOutlined className="text-[12px]" />
                            <span>
                              {(pagination.page - 1) * pagination.pageSize +
                                index +
                                1}
                            </span>
                          </Tag>
                          <Tag className="inline-flex items-center gap-1 px-1.5 py-0.5 text-xs font-medium bg-gray-200 text-gray-800 border border-gray-200 rounded-md">
                            <ScanText size={14} />
                            <span>
                              {t("document.chunk.characterCount", {
                                count: (chunk.content || "").length,
                              })}
                            </span>
                          </Tag>
                          {chunk.score !== undefined && (
                            <Tag
                              className="inline-flex items-center gap-1 px-1.5 py-0.5 text-xs font-medium border rounded-md"
                              style={{
                                backgroundColor: getScoreColor(chunk.score),
                                color: "#000",
                                borderColor: getScoreColor(chunk.score),
                              }}
                            >
                              <Goal size={14} />
                              <span>
                                {formatScoreAsPercentage(chunk.score)}
                              </span>
                            </Tag>
                          )}
                        </div>
                        <div className="flex items-center gap-1">
                          {!isReadOnlyMode && (
                            <Tooltip title={t("document.chunk.tooltip.edit")}>
                              <Button
                                type="text"
                                icon={<SquarePen size={16} />}
                                onClick={() => openEditChunkModal(chunk)}
                                size="small"
                                className="self-center"
                              />
                            </Tooltip>
                          )}
                          <Tooltip title={t("document.chunk.tooltip.download")}>
                            <Button
                              type="text"
                              icon={<Download size={16} />}
                              onClick={() => handleDownloadChunk(chunk)}
                              size="small"
                              className="self-center"
                            />
                          </Tooltip>
                          {!isReadOnlyMode && (
                            <Tooltip title={t("document.chunk.tooltip.delete")}>
                              <Button
                                type="text"
                                danger
                                icon={<Trash2 size={16} />}
                                onClick={() => handleDeleteChunk(chunk)}
                                size="small"
                                className="self-center"
                              />
                            </Tooltip>
                          )}
                        </div>
                      </div>
                    }
                  >
                    {/* Display filename and source type if available */}
                    {chunk.filename && (
                      <div className="mb-2 pb-2 border-b border-gray-200">
                        <div className="flex flex-col">
                          <div className="flex items-center">
                            <div className="w-3 h-3 flex-shrink-0 mr-1">
                              <Database className="w-full h-full" />
                            </div>
                            <div className="text-sm font-medium text-gray-700">
                              {chunk.filename}
                            </div>
                          </div>
                          {chunk.source_type && (
                            <div className="flex items-center mt-0.5">
                              <div className="w-3 h-3 flex-shrink-0 mr-1">
                                <Server className="w-full h-full" />
                              </div>
                              <div className="text-xs text-gray-500">
                                {chunk.source_type === "datamate"
                                  ? t("document.chunk.source.datamate", "来源: Datamate")
                                  : chunk.source_type === "file" ||
                                    chunk.source_type === "minio" ||
                                    chunk.source_type === "local"
                                  ? t("document.chunk.source.nexent", "来源: Nexent")
                                  : ""}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                    <div className="max-h-[150px] overflow-y-auto break-words whitespace-pre-wrap text-sm">
                      {chunk.content || ""}
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </div>
        </div>
      ),
    };
  });

  if (!isChunkSearchActive && loading && chunks.length === 0) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <Spin size="large" />
      </div>
    );
  }

  const activeDocumentTotal = isChunkSearchActive
    ? chunkSearchResultMap?.[activeDocumentKey]?.length ?? 0
    : documentChunkCounts[activeDocumentKey] ?? total ?? 0;
  const shouldShowPagination = !isChunkSearchActive && activeDocumentTotal > 0;

  return (
    <TooltipProvider key={tooltipResetKey}>
      <div className="flex h-full w-full flex-col min-h-0 overflow-hidden">
        {/* Search and Add Button Bar */}
        <div className="flex items-center justify-end gap-2 px-2 py-3 border-b border-gray-200 shrink-0">
          <div className="flex items-center gap-2">
            {/* Wrap search input with tooltip when model mismatch */}
            {isEmbeddingModelMismatch ? (
              <Tooltip title={disabledTooltipMessage}>
                <span className="inline-block">
                  <Input
                    placeholder={t("document.chunk.search.placeholder")}
                    value={searchValue}
                    onChange={(e) => setSearchValue(e.target.value)}
                    onPressEnter={() => {
                      void handleSearch();
                    }}
                    style={{ width: 320 }}
                    disabled={true}
                  />
                </span>
              </Tooltip>
            ) : (
                <Input
                  placeholder={t("document.chunk.search.placeholder")}
                  value={searchValue}
                  onChange={(e) => setSearchValue(e.target.value)}
                  onPressEnter={() => {
                    void handleSearch();
                  }}
                  style={{ width: 320 }}
                  disabled={isReadOnlyMode}
                  suffix={
                    <div className="flex items-center gap-1">
                      {searchValue && (
                        <Button
                          type="text"
                          icon={<X size={16} />}
                          onClick={handleClearSearch}
                          size="small"
                          className="text-gray-500 hover:text-gray-700"
                        />
                      )}
                      <Button
                        type="text"
                        icon={<Search size={16} />}
                        onClick={() => {
                          void handleSearch();
                        }}
                        size="small"
                        loading={chunkSearchLoading}
                        disabled={isReadOnlyMode}
                      />
                    </div>
                  }
                />
            )}
          </div>
          {/* Show Create Chunk button with tooltip only when model mismatch; hide in other read-only scenarios */}
          {!isReadOnlyMode || isEmbeddingModelMismatch ? (
            <Tooltip title={isEmbeddingModelMismatch ? disabledTooltipMessage : undefined}>
              <Button
                type="text"
                icon={<FilePlus2 size={16} />}
                onClick={openCreateChunkModal}
                disabled={isEmbeddingModelMismatch}
              ></Button>
            </Tooltip>
          ) : null}
        </div>

        <Tabs
          tabPosition="left"
          activeKey={activeDocumentKey}
          onChange={handleTabChange}
          items={tabItems}
          className={`h-full w-full min-h-0 ${TABS_ROOT_CLASS}`}
          rootClassName="h-full"
        />
        {shouldShowPagination && (
          <div className="sticky bottom-0 left-0 z-10 flex w-full justify-center bg-white px-8 pb-4 pt-2 shadow-[0_-4px_12px_rgba(15,23,42,0.04)]">
            <Pagination
              current={pagination.page}
              pageSize={pagination.pageSize}
              total={activeDocumentTotal}
              onChange={handlePaginationChange}
              disabled={loading}
              showQuickJumper
              locale={{
                jump_to: t("document.chunk.pagination.jumpTo"),
                page: t("document.chunk.pagination.page"),
              }}
              showTotal={(pageTotal, range) =>
                t("document.chunk.pagination.range", {
                  defaultValue: "{{start}}-{{end}} of {{total}}",
                  start: range[0],
                  end: range[1],
                  total: pageTotal,
                })
              }
            />
          </div>
        )}
      </div>
      <Modal
        centered
        destroyOnHidden
        open={isChunkModalOpen}
        title={
          chunkModalMode === "create"
            ? t("document.chunk.form.createTitle")
            : t("document.chunk.form.editTitle")
        }
        onCancel={closeChunkModal}
        onOk={() => {
          void handleChunkSubmit();
        }}
        okText={t("common.save")}
        cancelText={t("common.cancel")}
        confirmLoading={chunkSubmitting}
      >
        <Form form={chunkForm} layout="vertical">
          <Form.Item
            label={
              <span className="font-semibold ml-1">
                {t("document.chunk.form.documentName")}
              </span>
            }
          >
            <div className="pl-4 text-gray-700">
              {getDisplayName(activeDocument?.name || "")}
            </div>
          </Form.Item>
          <Form.Item
            label={
              <span className="font-semibold ml-1">
                {t("document.chunk.form.content")}
              </span>
            }
            name="content"
          >
            <TextArea
              style={{ height: "40vh", resize: "vertical" }}
              placeholder={t("document.chunk.form.contentPlaceholder", {
                defaultValue: "Enter chunk content",
              })}
            />
          </Form.Item>
        </Form>
      </Modal>

    </TooltipProvider>
  );
};

export default DocumentChunk;

