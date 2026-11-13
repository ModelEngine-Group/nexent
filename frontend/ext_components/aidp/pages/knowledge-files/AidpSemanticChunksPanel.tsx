// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Checkbox,
  Dropdown,
  Empty,
  Input,
  Skeleton,
} from "antd";
import {
  DownOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
} from "@ant-design/icons";

import type { AidpChunk } from "@/ext_components/aidp/shared/types/chunks";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { isAidpChunkEditable } from "@/ext_components/aidp/shared/utils/aidpChunkType";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import log from "@/lib/logger";
import AidpChunkCard from "./AidpChunkCard";
import AidpChunkDrawer, { type AidpChunkDrawerMode } from "./AidpChunkDrawer";
import AidpChunkDetailDrawer from "./AidpChunkDetailDrawer";
import AidpChunkDeleteModal from "./AidpChunkDeleteModal";
import {
  useAidpChunkSearch,
  useAidpFileChunks,
} from "./hooks/useAidpFileChunks";
import styles from "./AidpSemanticChunks.module.css";

const AIDP_CHUNK_PAGE_SIZE_DEFAULT = 20;
const AIDP_CHUNK_PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;

interface AidpSemanticChunksPanelProps {
  kdsId: string;
  fileUuid: string;
  fileName: string;
  canEdit: boolean;
}

interface ChunkDrawerState {
  mode: AidpChunkDrawerMode;
  chunk: AidpChunk | null;
}

/**
 * Semantic chunk management for one file.
 *
 * List browsing uses AIDP's server-side paging and page-scoped selection.
 * Content search uses a dedicated backend FusionSearch proxy constrained by
 * the current file name; it does not reuse the model-facing aidp_search tool.
 */
const AidpSemanticChunksPanel: React.FC<AidpSemanticChunksPanelProps> = ({
  kdsId,
  fileUuid,
  fileName,
  canEdit,
}) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const scope = useAidpQueryScope();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(AIDP_CHUNK_PAGE_SIZE_DEFAULT);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [drawer, setDrawer] = useState<ChunkDrawerState | null>(null);
  // Set when editing was opened from the detail drawer: after save or cancel
  // the read-only detail comes back instead of dropping the user on the list.
  const [detailReturnId, setDetailReturnId] = useState<number | null>(null);
  const [deleteTargets, setDeleteTargets] = useState<number[] | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const chunksQuery = useAidpFileChunks(kdsId, fileUuid, page, pageSize);
  const searchQuery = useAidpChunkSearch(
    kdsId,
    fileUuid,
    fileName,
    debouncedSearch
  );
  const chunks = useMemo(
    () => chunksQuery.data?.value ?? [],
    [chunksQuery.data]
  );
  const total = chunksQuery.data?.total_count ?? chunks.length;
  const hasMore = chunksQuery.data?.has_more ?? false;
  const totalReliable = chunksQuery.data?.total_reliable !== false;
  const searchActive = debouncedSearch.trim().length > 0;
  const activeQuery = searchActive ? searchQuery : chunksQuery;
  const { refetch } = activeQuery;
  const displayChunks = useMemo(
    () => activeQuery.data?.value ?? [],
    [activeQuery.data]
  );
  const offset = searchActive ? 0 : (page - 1) * pageSize;

  // The input is local; only a settled query reaches AIDP FusionSearch.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(search);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const activeErrorMessage = activeQuery.isError
    ? getAidpErrorMessage(
        activeQuery.error,
        t,
        t(
          searchActive
            ? "aidpKnowledge.chunksSearchFailed"
            : "aidpKnowledge.chunksLoadFailed"
        )
      )
    : undefined;

  // Selection belongs to the visible page only: a new page or file starts
  // with nothing selected instead of carrying an invisible range forward.
  // A file switch remounts this panel, so only page changes are handled here.
  const handlePageChange = useCallback((nextPage: number) => {
    setSelectedIds([]);
    setSearch("");
    setPage(nextPage);
  }, []);
  const handlePageSizeChange = useCallback((size: number) => {
    setSelectedIds([]);
    setSearch("");
    setPageSize(size);
    setPage(1);
  }, []);

  // Deleting the last chunks of a page must not leave the user on an empty
  // page when earlier chunks still exist.
  useEffect(() => {
    if (
      !chunksQuery.isSuccess ||
      chunksQuery.isFetching ||
      chunks.length ||
      page <= 1
    )
      return;
    const lastPage = totalReliable
      ? Math.max(1, Math.ceil(total / pageSize))
      : page - 1;
    // A microtask, not requestAnimationFrame: the correction must also run when
    // the tab is in the background and no animation frames are being painted.
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      setSelectedIds([]);
      setPage(Math.min(page - 1, lastPage));
    });
    return () => {
      cancelled = true;
    };
  }, [
    chunksQuery.isSuccess,
    chunksQuery.isFetching,
    chunks.length,
    page,
    pageSize,
    total,
    totalReliable,
  ]);

  const displayedChunkIds = useMemo(
    () => displayChunks.map((chunk) => chunk.chunk_id),
    [displayChunks]
  );
  const allSelected =
    displayedChunkIds.length > 0 &&
    displayedChunkIds.every((chunkId) => selectedIds.includes(chunkId));
  const someSelected = selectedIds.length > 0 && !allSelected;

  const toggleChunk = useCallback((chunkId: number, selected: boolean) => {
    setSelectedIds((current) =>
      selected
        ? current.includes(chunkId)
          ? current
          : [...current, chunkId]
        : current.filter((id) => id !== chunkId)
    );
  }, []);

  const toggleAll = useCallback(
    (selected: boolean) => {
      setSelectedIds(selected ? displayedChunkIds : []);
    },
    [displayedChunkIds]
  );

  const refreshAfterWrite = useCallback(
    async (reconcileSelection = false) => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: [...scope.key, "chunks", kdsId, fileUuid],
          refetchType: "none",
        }),
        queryClient.invalidateQueries({
          queryKey: [...scope.key, "chunk-search", kdsId, fileUuid],
          refetchType: "none",
        }),
      ]);
      const refreshed = await refetch();
      if (reconcileSelection && refreshed.isSuccess) {
        const remainingIds = new Set(
          refreshed.data.value.map((chunk) => chunk.chunk_id)
        );
        setSelectedIds((current) =>
          current.filter((id) => remainingIds.has(id))
        );
      }
    },
    [fileUuid, kdsId, queryClient, refetch, scope.key]
  );

  const handleSave = useCallback(
    async (text: string) => {
      if (!drawer) return;
      const targetId = drawer.chunk?.chunk_id;
      setSubmitting(true);
      try {
        if (drawer.mode === "create") {
          await aidpKnowledgeService.createChunk(kdsId, {
            file_uuid: fileUuid,
            chunk_text: text,
          });
        } else if (targetId !== undefined) {
          await aidpKnowledgeService.updateChunk(kdsId, targetId, {
            chunk_text: text,
          });
        }
      } catch (error) {
        message.error(
          getAidpErrorMessage(error, t, t("aidpKnowledge.chunkSaveFailed"))
        );
        throw error;
      } finally {
        if (targetId !== undefined) {
          await queryClient.invalidateQueries({
            queryKey: [...scope.key, "chunk-detail", kdsId, targetId],
          });
        }
        await refreshAfterWrite(true);
        setSubmitting(false);
      }

      setDrawer(null);
      setDetailReturnId(null);
      if (detailReturnId !== null) setDetailId(detailReturnId);
      message.success(t("aidpKnowledge.chunkSaveSuccess"));

      if (drawer.mode === "create" && !searchActive) {
        try {
          const firstPage = await aidpKnowledgeService.listChunks(
            kdsId,
            fileUuid,
            1,
            1
          );
          if (firstPage.total_reliable) {
            setSelectedIds([]);
            setPage(Math.max(1, Math.ceil(firstPage.total_count / pageSize)));
          }
        } catch (error) {
          log.warn("Could not determine the last AIDP chunk page:", error);
        }
      }
    },
    [
      detailReturnId,
      drawer,
      fileUuid,
      kdsId,
      message,
      pageSize,
      queryClient,
      refreshAfterWrite,
      scope.key,
      searchActive,
      t,
    ]
  );

  const handleDelete = useCallback(async () => {
    if (!deleteTargets?.length) return;
    setSubmitting(true);
    try {
      await aidpKnowledgeService.removeChunks(kdsId, deleteTargets);
      message.success(t("aidpKnowledge.chunkDeleteSuccess"));
      setSelectedIds((current) =>
        current.filter((id) => !deleteTargets.includes(id))
      );
      if (detailId !== null && deleteTargets.includes(detailId)) {
        setDetailId(null);
      }
    } catch (error) {
      message.error(
        getAidpErrorMessage(error, t, t("aidpKnowledge.chunkDeleteFailed"))
      );
    } finally {
      await Promise.all([
        refreshAfterWrite(true),
        ...deleteTargets.map((id) =>
          queryClient.invalidateQueries({
            queryKey: [...scope.key, "chunk-detail", kdsId, id],
            refetchType: "none",
          })
        ),
      ]);
      setDeleteTargets(null);
      setSubmitting(false);
    }
  }, [
    deleteTargets,
    detailId,
    kdsId,
    message,
    queryClient,
    refreshAfterWrite,
    scope.key,
    t,
  ]);

  const openCreate = useCallback(() => {
    setDetailReturnId(null);
    setDrawer({ mode: "create", chunk: null });
  }, []);
  const openEdit = useCallback((chunk: AidpChunk) => {
    // Only TEXT chunks carry editable text; TABLE/IMAGE stay read-only and
    // never expose an edit entry in the UI.
    if (!isAidpChunkEditable(chunk)) return;
    setDetailReturnId(null);
    setDrawer({ mode: "edit", chunk });
  }, []);
  const openEditFromDetail = useCallback((chunk: AidpChunk) => {
    if (!isAidpChunkEditable(chunk)) return;
    setDetailReturnId(chunk.chunk_id);
    setDetailId(null);
    setDrawer({ mode: "edit", chunk });
  }, []);
  const closeDrawer = useCallback(() => {
    setDrawer(null);
    if (detailReturnId !== null) {
      setDetailId(detailReturnId);
      setDetailReturnId(null);
    }
  }, [detailReturnId]);
  const closeDetail = useCallback(() => {
    setDetailId(null);
    setDetailReturnId(null);
  }, []);

  const loadingFirstPage = activeQuery.isPending;
  const refreshing = activeQuery.isFetching && !loadingFirstPage;
  const moreMenuItems = [
    {
      key: "refresh",
      label: t("aidpKnowledge.refresh"),
      icon: <ReloadOutlined spin={refreshing} />,
    },
  ];
  const handleMoreMenuClick = ({ key }: { key: string }) => {
    if (key === "refresh") {
      void refetch();
    }
  };
  const handleSearchChange = (value: string) => {
    setSearch(value);
    setSelectedIds([]);
  };

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          {canEdit && (
            <Checkbox
              checked={allSelected}
              indeterminate={someSelected}
              disabled={displayChunks.length === 0}
              onChange={(event) => toggleAll(event.target.checked)}
            >
              {t("aidpKnowledge.chunksSelectAll")}
            </Checkbox>
          )}
        </div>
        <Input
          allowClear
          className={styles.searchInput}
          prefix={<SearchOutlined />}
          placeholder={t("aidpKnowledge.chunkSearchPlaceholder")}
          value={search}
          onChange={(event) => handleSearchChange(event.target.value)}
          aria-label={t("aidpKnowledge.chunkSearchPlaceholder")}
        />
        <div className={styles.toolbarActions}>
          {canEdit && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              {t("aidpKnowledge.chunkAdd")}
            </Button>
          )}
          {canEdit && (
            <Button
              disabled={selectedIds.length === 0}
              onClick={() => setDeleteTargets(selectedIds)}
            >
              {t("aidpKnowledge.chunkDelete")}
            </Button>
          )}
          <Dropdown
            trigger={["click"]}
            menu={{
              items: moreMenuItems,
              onClick: handleMoreMenuClick,
            }}
          >
            <Button>
              <span className={styles.moreLabel}>
                {t("aidpKnowledge.chunkMore")}
                <DownOutlined />
              </span>
            </Button>
          </Dropdown>
        </div>
      </div>

      {activeErrorMessage && (
        <Alert
          type="error"
          showIcon
          title={activeErrorMessage}
          className="mb-2"
          action={
            <Button size="small" onClick={() => void refetch()}>
              {t("aidpKnowledge.chunksRetry")}
            </Button>
          }
        />
      )}

      <div className={styles.list}>
        {loadingFirstPage ? (
          <div className="py-2">
            <Skeleton active paragraph={{ rows: 4 }} />
          </div>
        ) : displayChunks.length === 0 ? (
          <div className={styles.emptyState}>
            {!activeErrorMessage && (
              <Empty
                description={t(
                  searchActive
                    ? "aidpKnowledge.chunksSearchEmpty"
                    : "aidpKnowledge.chunksEmpty"
                )}
              />
            )}
          </div>
        ) : (
          displayChunks.map((chunk, index) => (
            <AidpChunkCard
              key={chunk.chunk_id}
              chunk={chunk}
              index={offset + index + 1}
              selected={selectedIds.includes(chunk.chunk_id)}
              canEdit={canEdit}
              onSelectChange={(selected) =>
                toggleChunk(chunk.chunk_id, selected)
              }
              onOpen={() => setDetailId(chunk.chunk_id)}
              onEdit={() => openEdit(chunk)}
              onDelete={() => setDeleteTargets([chunk.chunk_id])}
            />
          ))
        )}
      </div>

      {!searchActive && !loadingFirstPage && chunks.length > 0 && (
        <div className={styles.pagination}>
          <AidpPagination
            currentPage={page}
            pageSize={pageSize}
            pageSizeOptions={[...AIDP_CHUNK_PAGE_SIZE_OPTIONS]}
            total={total}
            totalReliable={totalReliable}
            hasMore={hasMore}
            onPageChange={handlePageChange}
            onPageSizeChange={handlePageSizeChange}
          />
        </div>
      )}

      <AidpChunkDrawer
        open={drawer !== null}
        mode={drawer?.mode ?? "create"}
        chunk={drawer?.chunk ?? null}
        submitting={submitting}
        onClose={closeDrawer}
        onSubmit={handleSave}
      />

      <AidpChunkDetailDrawer
        open={detailId !== null}
        kdsId={kdsId}
        chunkId={detailId}
        pageChunks={displayChunks}
        offset={offset}
        canEdit={canEdit}
        onClose={closeDetail}
        onNavigate={setDetailId}
        onEdit={openEditFromDetail}
      />

      <AidpChunkDeleteModal
        open={deleteTargets !== null}
        count={deleteTargets?.length ?? 0}
        submitting={submitting}
        onCancel={() => setDeleteTargets(null)}
        onConfirm={() => void handleDelete()}
      />
    </div>
  );
};

export default AidpSemanticChunksPanel;
