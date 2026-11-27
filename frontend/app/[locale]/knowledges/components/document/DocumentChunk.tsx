// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  Card,
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
  Trash2,
  SquarePen,
  Search,
  FilePlus2,
  FileText,
  Goal,
  Layers,
  X,
} from "lucide-react";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { Document } from "@/types/knowledgeBase";
import log from "@/lib/logger";
import { formatScoreAsPercentage, getScoreColor } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

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
  initialDocumentId?: string;
  knowledgeBaseChunkCount?: number;
  onChunkCountChange?: () => void; // Callback when chunk count changes (for updating KnowledgeBaseList)
  permission?: string; // User's permission for this knowledge base (READ_ONLY, EDIT, etc.)
}

const PAGE_SIZE = 10;

const { TextArea } = Input;

const DocumentChunk: React.FC<DocumentChunkProps> = ({
  knowledgeBaseName,
  knowledgeBaseId,
  documents,
  initialDocumentId = "",
  knowledgeBaseChunkCount,
  onChunkCountChange,
  permission,
}) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { confirm } = useConfirmModal();
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [loading, setLoading] = useState(false);
  const [activeDocumentKey, setActiveDocumentKey] = useState(initialDocumentId);
  const [allChunkCount, setAllChunkCount] = useState<number>();
  const [loadError, setLoadError] = useState(false);
  const loadRequestId = useRef(0);
  const searchRequestId = useRef(0);
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
  const scrollToBottomAfterLoad = useRef(false);

  const resetChunkSearch = React.useCallback(() => {
    searchRequestId.current += 1;
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

  const effectiveIndexName = knowledgeBaseId || knowledgeBaseName;

  const isReadOnlyMode = permission === "READ_ONLY";
  useEffect(() => {
    return () => {
      searchRequestId.current += 1;
    };
  }, [effectiveIndexName]);

  // Return to the whole index if the selected document was removed.
  useEffect(() => {
    if (
      activeDocumentKey &&
      !documents.some((doc) => doc.id === activeDocumentKey)
    ) {
      setActiveDocumentKey("");
      setPagination((prev) => ({ ...prev, page: 1 }));
    }
  }, [documents, activeDocumentKey]);

  // Omit the document filter when browsing the whole knowledge base.
  const loadChunks = React.useCallback(async () => {
    if (!effectiveIndexName) return;

    const requestId = ++loadRequestId.current;
    setLoading(true);
    setLoadError(false);
    try {
      const result = await knowledgeBaseService.previewChunksPaginated(
        effectiveIndexName,
        pagination.page,
        pagination.pageSize,
        activeDocumentKey || undefined
      );

      if (requestId !== loadRequestId.current) return;
      const loadedChunks = result.chunks || [];
      const chunkTotal = result.total || 0;
      setTotal(chunkTotal);
      if (activeDocumentKey) {
        setDocumentChunkCounts((prev) => ({
          ...prev,
          [activeDocumentKey]: chunkTotal,
        }));
      } else {
        setAllChunkCount(chunkTotal);
      }
      const lastPage = Math.max(1, Math.ceil(chunkTotal / pagination.pageSize));
      if (pagination.page > lastPage) {
        setPagination((prev) => ({ ...prev, page: lastPage }));
        return;
      }

      setChunks(loadedChunks);

      // Scroll to bottom after loading if requested (e.g., after creating new chunk)
      if (scrollToBottomAfterLoad.current) {
        scrollToBottomAfterLoad.current = false;
        // Use setTimeout to ensure DOM is updated
        setTimeout(() => {
          if (contentScrollRef.current) {
            contentScrollRef.current.scrollTop =
              contentScrollRef.current.scrollHeight;
          }
        }, 100);
      }
    } catch (error) {
      if (requestId !== loadRequestId.current) return;
      setLoadError(true);
      log.error("Failed to load chunks:", error);
      message.error(t("document.chunk.error.loadFailed"));
    } finally {
      if (requestId === loadRequestId.current) setLoading(false);
    }
  }, [
    effectiveIndexName,
    activeDocumentKey,
    pagination.page,
    pagination.pageSize,
    message,
    t,
  ]);

  useEffect(() => {
    void loadChunks();
    return () => {
      loadRequestId.current += 1;
    };
  }, [loadChunks]);

  useEffect(() => {
    if (documents.length === 0) {
      setDocumentChunkCounts({});
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
    if (key === activeDocumentKey) return;
    loadRequestId.current += 1;
    setActiveDocumentKey(key);
    setChunks([]);
    setTotal(key ? (documentChunkCounts[key] ?? 0) : (allChunkCount ?? 0));
    setPagination((prev) => ({ ...prev, page: 1 }));
    if (contentScrollRef.current) contentScrollRef.current.scrollTop = 0;
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

    if (!effectiveIndexName) {
      message.error(t("document.chunk.error.searchFailed"));
      return;
    }

    const requestId = ++searchRequestId.current;
    setChunkSearchResult([]);
    setChunkSearchLoading(true);

    try {
      const response = await knowledgeBaseService.hybridSearch(
        effectiveIndexName,
        trimmedValue,
        {
          topK: pagination.pageSize,
        }
      );
      if (requestId !== searchRequestId.current) return;

      const parsedChunks = (response.results || [])
        .map((item) => {
          // Backend returns document fields at the top level
          return {
            id: item.id || "",
            content: item.content || "",
            path_or_url: item.path_or_url || item.url || item.pathOrUrl,
            filename: item.filename,
            create_time: item.create_time,
            score: item.score, // Preserve search score for display
            source_type:
              item.source_type === "local" || item.source_type === "minio"
                ? "file"
                : item.source_type, // Preserve source type for display
          };
        })
        .sort((left, right) => {
          const leftScore =
            typeof left.score === "number" && Number.isFinite(left.score)
              ? left.score
              : Number.NEGATIVE_INFINITY;
          const rightScore =
            typeof right.score === "number" && Number.isFinite(right.score)
              ? right.score
              : Number.NEGATIVE_INFINITY;
          if (rightScore === leftScore) {
            return 0;
          }
          return rightScore > leftScore ? 1 : -1;
        });

      setChunkSearchResult(parsedChunks);

      if (parsedChunks.length === 0) {
        message.info(t("document.chunk.search.noChunk"));
      }
    } catch (error) {
      if (requestId !== searchRequestId.current) return;
      log.error("Failed to search chunks:", error);
      message.error(t("document.chunk.error.searchFailed"));
      resetChunkSearch();
    } finally {
      if (requestId === searchRequestId.current) setChunkSearchLoading(false);
    }
  }, [
    effectiveIndexName,
    message,
    pagination.pageSize,
    resetChunkSearch,
    searchValue,
    t,
  ]);

  const refreshChunks = React.useCallback(async () => {
    await loadChunks();
    if (isChunkSearchActive && searchValue.trim()) {
      await handleSearch();
    }
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
    const filenameValue = activeDocument?.name || "";
    chunkForm.setFieldsValue({
      filename: filenameValue,
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
      filename: chunk.filename,
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
    if (!effectiveIndexName) {
      message.error(t("document.chunk.error.loadFailed"));
      return;
    }
    if (chunkModalMode === "create" && !activeDocumentKey) {
      message.warning(t("document.chunk.search.noActiveDocument"));
      return;
    }

    try {
      const values = await chunkForm.validateFields();
      setChunkSubmitting(true);
      if (chunkModalMode === "create") {
        const filenamePayload = values.filename?.trim() || undefined;
        await knowledgeBaseService.createChunk(effectiveIndexName, {
          content: values.content,
          filename: filenamePayload,
          path_or_url: activeDocumentKey,
        });
        message.success(t("document.chunk.success.create"));
        resetChunkSearch();

        // Navigate to the last page to show the new chunk at the bottom
        const lastPage = Math.ceil((total + 1) / pagination.pageSize);
        scrollToBottomAfterLoad.current = true;
        setAllChunkCount((current) =>
          current === undefined ? current : current + 1
        );
        // Notify parent to update knowledge base list (chunk count)
        onChunkCountChange?.();
        closeChunkModal();
        if (lastPage === pagination.page) await loadChunks();
        else setPagination((prev) => ({ ...prev, page: lastPage }));
        return;
      } else {
        if (!editingChunk?.id) {
          message.error(t("document.chunk.error.missingChunkId"));
          return;
        }
        await knowledgeBaseService.updateChunk(
          effectiveIndexName,
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
    if (!effectiveIndexName) {
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
          await knowledgeBaseService.deleteChunk(effectiveIndexName, chunk.id);
          message.success(t("document.chunk.success.delete"));
          forceCloseTooltips();
          setAllChunkCount((current) =>
            current === undefined ? current : Math.max(0, current - 1)
          );
          const documentId = chunk.path_or_url || activeDocumentKey;
          setDocumentChunkCounts((prev) =>
            documentId && prev[documentId] !== undefined
              ? { ...prev, [documentId]: Math.max(0, prev[documentId] - 1) }
              : prev
          );
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

  const displayedChunks = chunkSearchResult
    ? activeDocumentKey
      ? chunkSearchResult.filter(
          (chunk) => chunk.path_or_url === activeDocumentKey
        )
      : chunkSearchResult
    : chunks;
  const displayedTotal = chunkSearchResult ? displayedChunks.length : total;
  const showLoading = isChunkSearchActive ? chunkSearchLoading : loading;
  const searchCounts = new Map<string, number>();
  for (const chunk of chunkSearchResult ?? []) {
    if (chunk.path_or_url) {
      searchCounts.set(
        chunk.path_or_url,
        (searchCounts.get(chunk.path_or_url) ?? 0) + 1
      );
    }
  }
  const allDocumentsCount =
    chunkSearchResult?.length ??
    allChunkCount ??
    knowledgeBaseChunkCount ??
    documents.reduce(
      (count, doc) =>
        count +
        (documentChunkCounts[doc.id] ??
          doc.chunk_num ??
          doc.total_chunk_num ??
          0),
      0
    );

  return (
    <TooltipProvider key={tooltipResetKey}>
      <div className="flex h-full w-full min-h-0 flex-col gap-3">
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
          <Input
            aria-label={t("document.chunk.search.content")}
            placeholder={t("document.chunk.search.content")}
            value={searchValue}
            onChange={(event) => setSearchValue(event.target.value)}
            onPressEnter={() => void handleSearch()}
            className="!max-w-80"
            suffix={
              <div className="flex items-center gap-1">
                {searchValue && (
                  <Button
                    type="text"
                    aria-label={t("document.chunk.search.clear")}
                    icon={<X size={16} />}
                    onClick={handleClearSearch}
                    size="small"
                  />
                )}
                <Button
                  type="text"
                  aria-label={t("document.chunk.search.submit")}
                  icon={<Search size={16} />}
                  onClick={() => void handleSearch()}
                  size="small"
                  loading={chunkSearchLoading}
                />
              </div>
            }
          />
          {!isReadOnlyMode && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  icon={<FilePlus2 size={16} />}
                  aria-label={t("document.chunk.tooltip.create")}
                  onClick={openCreateChunkModal}
                  disabled={!activeDocument || loading}
                />
              </TooltipTrigger>
              <TooltipContent>
                {t("document.chunk.tooltip.create")}
              </TooltipContent>
            </Tooltip>
          )}
        </div>

        <div className="@container min-h-0 flex-1">
          <div className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-3 @min-[36rem]:grid-cols-[minmax(9rem,22%)_minmax(0,1fr)] @min-[36rem]:grid-rows-[minmax(0,1fr)]">
            <nav
              aria-label={t("document.chunk.documents")}
              className="max-h-36 space-y-1 overflow-auto @min-[36rem]:max-h-none"
            >
              <Button
                block
                type="text"
                aria-pressed={!activeDocumentKey}
                className={`!justify-start ${!activeDocumentKey ? "!bg-[var(--color-select)] !text-[var(--color-brand)]" : ""}`}
                icon={<Layers size={16} aria-hidden />}
                onClick={() => handleTabChange("")}
              >
                <span className="min-w-0 flex-1 truncate text-left">
                  {t("document.chunk.allDocuments")}
                </span>
                <span className="tabular-nums text-[var(--color-text-secondary)]">
                  {allDocumentsCount}
                </span>
              </Button>
              {documents.map((doc) => (
                <Button
                  key={doc.id}
                  block
                  type="text"
                  aria-pressed={activeDocumentKey === doc.id}
                  aria-label={doc.name}
                  title={doc.name}
                  className={`!justify-start ${activeDocumentKey === doc.id ? "!bg-[var(--color-select)] !text-[var(--color-brand)]" : ""}`}
                  icon={<FileText size={16} aria-hidden />}
                  onClick={() => handleTabChange(doc.id)}
                >
                  <span className="min-w-0 flex-1 truncate text-left">
                    {doc.name}
                  </span>
                  <span className="tabular-nums text-[var(--color-text-secondary)]">
                    {chunkSearchResult
                      ? (searchCounts.get(doc.id) ?? 0)
                      : (documentChunkCounts[doc.id] ??
                        doc.chunk_num ??
                        doc.total_chunk_num ??
                        0)}
                  </span>
                </Button>
              ))}
            </nav>

            <section className="flex min-h-0 min-w-0 flex-col gap-2">
              <p className="shrink-0 text-sm text-[var(--color-text-secondary)]">
                {t("document.chunk.total", { count: displayedTotal })}
              </p>
              <div
                ref={contentScrollRef}
                className="@container min-h-0 flex-1 overflow-y-auto"
              >
                {showLoading ? (
                  <div className="flex h-40 items-center justify-center">
                    <Spin />
                  </div>
                ) : loadError && !isChunkSearchActive ? (
                  <div
                    role="alert"
                    className="flex items-center justify-center gap-2 py-8"
                  >
                    <span>{t("document.chunk.error.loadFailed")}</span>
                    <Button onClick={() => void loadChunks()}>
                      {t("repository.common.retry")}
                    </Button>
                  </div>
                ) : displayedChunks.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-[var(--color-border)] p-8 text-center text-sm text-[var(--color-text-secondary)]">
                    {t(
                      isChunkSearchActive
                        ? "document.chunk.search.noChunk"
                        : "document.chunk.noChunks"
                    )}
                  </div>
                ) : (
                  <div className="grid grid-cols-1 items-start gap-3 @min-[34rem]:grid-cols-2">
                    {displayedChunks.map((chunk, index) => {
                      const offset = isChunkSearchActive
                        ? 0
                        : (pagination.page - 1) * pagination.pageSize;
                      const filename =
                        chunk.filename ||
                        documents.find((doc) => doc.id === chunk.path_or_url)
                          ?.name ||
                        activeDocument?.name;
                      return (
                        <Card
                          key={chunk.id || index}
                          size="small"
                          variant="outlined"
                          className="min-w-0"
                        >
                          <div className="mb-2 flex flex-wrap items-center gap-2">
                            <Tag className="!m-0 !border-0 !bg-[var(--color-select)] !text-[var(--color-brand)]">
                              #{String(offset + index + 1).padStart(3, "0")}
                            </Tag>
                            {filename && (
                              <span
                                title={filename}
                                className="min-w-0 flex-1 truncate text-xs text-[var(--color-text-secondary)]"
                              >
                                {filename}
                              </span>
                            )}
                            <span className="ml-auto shrink-0 text-xs tabular-nums text-[var(--color-text-secondary)]">
                              {t("document.chunk.characterCount", {
                                count: (chunk.content || "").length,
                              })}
                            </span>
                            {(chunk.source_type === "datamate" ||
                              chunk.source_type === "file") && (
                              <span className="text-xs text-[var(--color-text-secondary)]">
                                {t(
                                  chunk.source_type === "datamate"
                                    ? "document.chunk.source.datamate"
                                    : "document.chunk.source.nexent"
                                )}
                              </span>
                            )}
                            {chunk.score !== undefined && (
                              <Tag
                                className="!m-0"
                                style={{
                                  backgroundColor: getScoreColor(chunk.score),
                                }}
                              >
                                <span className="flex items-center gap-1">
                                  <Goal size={12} aria-hidden />
                                  {formatScoreAsPercentage(chunk.score)}
                                </span>
                              </Tag>
                            )}
                          </div>
                          <div className="max-h-40 overflow-y-auto whitespace-pre-wrap break-words text-sm leading-relaxed">
                            {chunk.content || ""}
                          </div>
                          <div className="mt-2 flex justify-end gap-1">
                            {!isReadOnlyMode && (
                              <Button
                                type="text"
                                size="small"
                                title={t("document.chunk.tooltip.edit")}
                                aria-label={t("document.chunk.tooltip.edit")}
                                icon={<SquarePen size={15} />}
                                onClick={() => openEditChunkModal(chunk)}
                              />
                            )}
                            <Button
                              type="text"
                              size="small"
                              title={t("document.chunk.tooltip.download")}
                              aria-label={t("document.chunk.tooltip.download")}
                              icon={<Download size={15} />}
                              onClick={() => handleDownloadChunk(chunk)}
                            />
                            {!isReadOnlyMode && (
                              <Button
                                type="text"
                                size="small"
                                danger
                                title={t("document.chunk.tooltip.delete")}
                                aria-label={t("document.chunk.tooltip.delete")}
                                icon={<Trash2 size={15} />}
                                onClick={() => handleDeleteChunk(chunk)}
                              />
                            )}
                          </div>
                        </Card>
                      );
                    })}
                  </div>
                )}
              </div>
              {!isChunkSearchActive && total > 0 && (
                <Pagination
                  className="justify-center"
                  current={pagination.page}
                  pageSize={pagination.pageSize}
                  total={total}
                  onChange={handlePaginationChange}
                  disabled={loading || loadError}
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
              )}
            </section>
          </div>
        </div>
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
              {getDisplayName(
                editingChunk
                  ? editingChunk.filename ||
                      documents.find(
                        (doc) => doc.id === editingChunk.path_or_url
                      )?.name ||
                      ""
                  : activeDocument?.name || ""
              )}
            </div>
          </Form.Item>
          {/* Hidden field to preserve filename value for form submission */}
          <Form.Item name="filename" hidden></Form.Item>
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
