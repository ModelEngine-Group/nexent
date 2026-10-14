"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useRouter } from "next/navigation";

import { App, Modal } from "antd";

import { KB_SEARCH_DEBOUNCE_MS } from "./pages/knowledge-list/constants";
import type { AidpKnowledgeBaseItem } from "@/ext_components/aidp/shared/types/knowledge";
import { useErrorHandler } from "@/hooks/useErrorHandler";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { useAidpKnowledgeCache } from "@/ext_components/aidp/shared/hooks/useAidpKnowledgeCache";
import {
  useAidpKnowledgeList,
  useDeleteAidpKnowledgeBase,
} from "@/ext_components/aidp/pages/knowledge-list/hooks/useAidpKnowledgeList";

import AidpKnowledgeList from "./pages/knowledge-list/AidpKnowledgeList";
import {
  AIDP_KB_DEFAULT_COLUMNS,
  AIDP_KB_REQUIRED_COLUMNS,
} from "./pages/knowledge-list/constants";
import type {
  AidpKbColumnKey,
  AidpKbViewMode,
} from "./pages/knowledge-list/types";
import AidpImportDrawer from "@/ext_components/aidp/features/file-import/AidpImportDrawer";

const AidpKnowledgeConfiguration: React.FC = () => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const router = useRouter();
  const params = useParams();
  const locale = (params?.locale as string) || "zh";
  const { handleError } = useErrorHandler();
  const { refreshLists } = useAidpKnowledgeCache();
  const deleteMutation = useDeleteAidpKnowledgeBase();
  const [viewMode, setViewMode] = useState<AidpKbViewMode>("cards");
  const [visibleColumns, setVisibleColumns] = useState<AidpKbColumnKey[]>([
    ...AIDP_KB_DEFAULT_COLUMNS,
  ]);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      try {
        const savedView = window.sessionStorage.getItem(
          "aidpKnowledge.viewMode"
        );
        if (savedView === "cards" || savedView === "table")
          setViewMode(savedView);
        const savedColumns = window.sessionStorage.getItem(
          "aidpKnowledge.visibleColumns"
        );
        if (savedColumns) {
          const parsed = JSON.parse(savedColumns) as string[];
          if (Array.isArray(parsed))
            setVisibleColumns(
              AIDP_KB_DEFAULT_COLUMNS.filter(
                (key) =>
                  AIDP_KB_REQUIRED_COLUMNS.includes(key) || parsed.includes(key)
              )
            );
        }
      } catch {
        // Keep the defaults when saved preferences are unavailable or invalid.
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);
  const [listParams, setListParams] = useState({
    page: 1,
    pageSize: 10,
    keyword: "",
  });
  const { page: kbPage, pageSize: kbPageSize } = listParams;
  const [kbKeyword, setKbKeyword] = useState("");
  const [quickImportKb, setQuickImportKb] =
    useState<AidpKnowledgeBaseItem | null>(null);
  const listQuery = useAidpKnowledgeList(
    kbPage,
    kbPageSize,
    listParams.keyword,
    true,
    !!quickImportKb || deleteConfirmOpen
  );
  const kbs = listQuery.data?.value ?? [];
  const listErrorMessage = listQuery.error
    ? getAidpErrorMessage(listQuery.error, t, t("aidpKnowledge.listLoadFailed"))
    : undefined;

  useEffect(() => {
    const total = listQuery.data?.total_count;
    if (!listQuery.isSuccess || listQuery.isFetching || total === undefined)
      return;
    const lastPage = Math.max(1, Math.ceil(total / kbPageSize));
    if (kbPage <= lastPage) return;
    const frame = window.requestAnimationFrame(() =>
      setListParams((current) => ({ ...current, page: lastPage }))
    );
    return () => window.cancelAnimationFrame(frame);
  }, [
    listQuery.data?.total_count,
    listQuery.isSuccess,
    listQuery.isFetching,
    kbPage,
    kbPageSize,
  ]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const keyword = kbKeyword.trim();
      setListParams((current) =>
        current.keyword === keyword ? current : { ...current, keyword, page: 1 }
      );
    }, KB_SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [kbKeyword]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.removeItem("aidp_kb_server_url");
      window.localStorage.removeItem("aidp_kb_api_key");
    } catch {
      // The credentials were moved server-side; cleanup is best-effort.
    }
  }, []);

  // The dedicated detail route keeps the URL stable across refreshes and
  // deep links; the list stays mounted in its own route.
  const handleSelectKb = useCallback(
    (kb: AidpKnowledgeBaseItem) => {
      router.push(
        `/${locale}/knowledges/detail?kb=${encodeURIComponent(kb.kds_id)}`
      );
    },
    [locale, router]
  );

  const handleViewModeChange = useCallback((mode: AidpKbViewMode) => {
    setViewMode(mode);
    try {
      window.sessionStorage.setItem("aidpKnowledge.viewMode", mode);
    } catch {
      // Keep the in-memory preference when browser storage is unavailable.
    }
  }, []);

  const handleVisibleColumnsChange = useCallback(
    (columns: AidpKbColumnKey[]) => {
      setVisibleColumns(columns);
      try {
        window.sessionStorage.setItem(
          "aidpKnowledge.visibleColumns",
          JSON.stringify(columns)
        );
      } catch {
        // Keep the in-memory preference when browser storage is unavailable.
      }
    },
    []
  );

  const handleDeleteKb = useCallback(
    (kb: AidpKnowledgeBaseItem) => {
      setDeleteConfirmOpen(true);
      Modal.confirm({
        title: t("aidpKnowledge.confirmDeleteTitle"),
        content: t("aidpKnowledge.confirmDeleteContent", { name: kb.kds_name }),
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        centered: true,
        afterClose: () => setDeleteConfirmOpen(false),
        onOk: async () => {
          try {
            await deleteMutation.mutateAsync(kb.kds_id);
            message.success(t("aidpKnowledge.deleteKbSuccess"));
          } catch (error) {
            handleError(error, {
              showMessage: false,
              handleSession: false,
            });
            message.error(
              getAidpErrorMessage(error, t, t("aidpKnowledge.deleteKbFailed"))
            );
            throw error;
          }
        },
      });
    },
    [deleteMutation, handleError, message, t]
  );

  const handleCreateNew = useCallback(() => {
    router.push(`/${locale}/knowledges/create`);
  }, [locale, router]);

  return (
    <div className="flex h-full w-full min-w-0 flex-col">
      <div className="mt-4 min-h-0 flex-1 overflow-hidden">
        <AidpKnowledgeList
          kbs={kbs}
          isLoading={listQuery.isFetching}
          loadFailed={listQuery.isError}
          loadError={listErrorMessage}
          total={listQuery.data?.total_count ?? kbs.length}
          totalReliable={listQuery.data?.total_reliable !== false}
          hasMore={listQuery.data?.has_more ?? false}
          currentPage={kbPage}
          pageSize={kbPageSize}
          keyword={kbKeyword}
          viewMode={viewMode}
          visibleColumns={visibleColumns}
          onKeywordChange={setKbKeyword}
          onPageChange={(page) =>
            setListParams((current) => ({ ...current, page }))
          }
          onPageSizeChange={(pageSize) =>
            setListParams((current) => ({ ...current, pageSize, page: 1 }))
          }
          onViewModeChange={handleViewModeChange}
          onVisibleColumnsChange={handleVisibleColumnsChange}
          onSelect={handleSelectKb}
          onRefresh={() => void refreshLists()}
          onCreateNew={handleCreateNew}
          onImport={setQuickImportKb}
          onDelete={handleDeleteKb}
          onRetry={() => void listQuery.refetch()}
        />
      </div>

      {quickImportKb && (
        <AidpImportDrawer
          title={t("aidpKnowledge.importDrawerTitle")}
          open
          knowledgeBase={quickImportKb}
          onClose={() => {
            setQuickImportKb(null);
            void refreshLists();
          }}
        />
      )}
    </div>
  );
};

export default AidpKnowledgeConfiguration;
