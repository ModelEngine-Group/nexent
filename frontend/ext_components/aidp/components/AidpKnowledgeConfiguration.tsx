"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { App, Modal } from "antd";

import { KB_SEARCH_DEBOUNCE_MS } from "@/const/knowledgeBase";
import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import log from "@/lib/logger";
import { ApiError } from "@/services/api";
import { useErrorHandler } from "@/hooks/useErrorHandler";
import {
  useAidpKnowledgeCache,
  useAidpKnowledgeList,
  useDeleteAidpKnowledgeBase,
} from "../hooks/useAidpKnowledgeQueries";

import AidpKnowledgeFilesPage from "./AidpKnowledgeFilesPage";
import AidpKnowledgeList, {
  AIDP_KB_DEFAULT_COLUMNS,
  AIDP_KB_REQUIRED_COLUMNS,
  type AidpKbColumnKey,
  type AidpKbViewMode,
} from "./AidpKnowledgeList";
import AidpImportDrawer from "./AidpImportDrawer";

const AidpKnowledgeConfiguration: React.FC = () => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const router = useRouter();
  const params = useParams();
  const searchParams = useSearchParams();
  const locale = (params?.locale as string) || "zh";
  const { getI18nErrorMessage, handleError } = useErrorHandler();
  const { refreshLists, updateKnowledgeBase, fetchKnowledgeBase } =
    useAidpKnowledgeCache();
  const deleteMutation = useDeleteAidpKnowledgeBase();
  const [viewMode, setViewMode] = useState<AidpKbViewMode>("cards");
  const [visibleColumns, setVisibleColumns] = useState<AidpKbColumnKey[]>([
    ...AIDP_KB_DEFAULT_COLUMNS,
  ]);
  const [selectedKb, setSelectedKb] = useState<AidpKnowledgeBaseItem | null>(
    null
  );

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
          const allowed = new Set<AidpKbColumnKey>([
            ...AIDP_KB_DEFAULT_COLUMNS,
          ]);
          if (Array.isArray(parsed))
            setVisibleColumns(
              AIDP_KB_DEFAULT_COLUMNS.filter(
                (key) =>
                  AIDP_KB_REQUIRED_COLUMNS.includes(key) ||
                  (allowed.has(key) && parsed.includes(key))
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
  const openedRequestedKbRef = useRef<string | null>(null);
  const listQuery = useAidpKnowledgeList(
    kbPage,
    kbPageSize,
    listParams.keyword,
    !selectedKb
  );
  const kbs = listQuery.isError ? [] : (listQuery.data?.value ?? []);
  const listErrorMessage =
    listQuery.error instanceof ApiError
      ? getI18nErrorMessage(listQuery.error.code)
      : listQuery.error?.message;

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

  const handleSelectKb = useCallback((kb: AidpKnowledgeBaseItem) => {
    setSelectedKb(kb);
  }, []);

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

  const openKbById = useCallback(
    async (kbId: string) => {
      try {
        const detail = await fetchKnowledgeBase(kbId);
        const item = {
          ...detail,
          kds_id: kbId,
          kds_name: detail.kds_name || kbId,
        } as AidpKnowledgeBaseItem;
        setSelectedKb(item);
      } catch (error) {
        log.error("Failed to open AIDP knowledge base from query:", error);
        const result = handleError(error, {
          showMessage: false,
          handleSession: false,
        });
        message.error(result.message);
      }
    },
    [fetchKnowledgeBase, handleError, message]
  );

  const requestedKbId = searchParams?.get("kb") || null;
  useEffect(() => {
    if (!requestedKbId || openedRequestedKbRef.current === requestedKbId)
      return;
    openedRequestedKbRef.current = requestedKbId;
    void openKbById(requestedKbId);
  }, [openKbById, requestedKbId]);

  const handleBackToList = useCallback(() => {
    setSelectedKb(null);
    if (requestedKbId && typeof window !== "undefined") {
      window.history.replaceState(null, "", `/${locale}/knowledges`);
      openedRequestedKbRef.current = null;
    }
  }, [locale, requestedKbId]);

  const handleDeleteKb = useCallback(
    (kb: AidpKnowledgeBaseItem) => {
      Modal.confirm({
        title: t("aidpKnowledge.confirmDeleteTitle"),
        content: t("aidpKnowledge.confirmDeleteContent", { name: kb.kds_name }),
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        okButtonProps: { danger: true },
        centered: true,
        onOk: async () => {
          try {
            await deleteMutation.mutateAsync(kb.kds_id);
            message.success(t("aidpKnowledge.deleteKbSuccess"));
            setSelectedKb(null);
          } catch (error) {
            const result = handleError(error, {
              showMessage: false,
              handleSession: false,
            });
            message.error(result.message);
            throw error;
          }
        },
      });
    },
    [deleteMutation, handleError, message, t]
  );

  const handleUpdatedKb = useCallback(
    (updatedKb: AidpKnowledgeBaseItem) => {
      setSelectedKb(updatedKb);
      updateKnowledgeBase(updatedKb);
    },
    [updateKnowledgeBase]
  );

  const handleCreateNew = useCallback(() => {
    router.push(`/${locale}/knowledges/create`);
  }, [locale, router]);

  if (selectedKb) {
    return (
      <div className="flex h-full w-full min-w-0 flex-col">
        <div className="mt-4 min-h-0 flex-1 overflow-hidden">
          <AidpKnowledgeFilesPage
            key={selectedKb.kds_id}
            knowledgeBase={selectedKb}
            onBack={handleBackToList}
            onDelete={handleDeleteKb}
            onUpdated={handleUpdatedKb}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full min-w-0 flex-col">
      <div className="mt-4 min-h-0 flex-1 overflow-hidden">
        <AidpKnowledgeList
          kbs={kbs}
          isLoading={listQuery.isFetching}
          loadFailed={listQuery.isError}
          loadError={listErrorMessage}
          total={
            listQuery.isError ? 0 : (listQuery.data?.total_count ?? kbs.length)
          }
          totalReliable={
            !listQuery.isError && listQuery.data?.total_reliable !== false
          }
          hasMore={!listQuery.isError && (listQuery.data?.has_more ?? false)}
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
          onDocsUploaded={() => undefined}
          onRefresh={() => undefined}
        />
      )}
    </div>
  );
};

export default AidpKnowledgeConfiguration;
