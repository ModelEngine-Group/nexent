"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useRouter } from "next/navigation";

import { App, Modal } from "antd";

import { KB_SEARCH_DEBOUNCE_MS } from "@/const/knowledgeBase";
import {
  AIDP_DOC_STATUS_POLL_MS,
  AIDP_DOC_UPLOAD_WATCH_TIMEOUT_MS,
} from "@/lib/aidpDocumentStatus";
import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";
import log from "@/lib/logger";

import AidpKnowledgeList, {
  AIDP_KB_DEFAULT_COLUMNS,
  type AidpKbColumnKey,
  type AidpKbViewMode,
} from "./AidpKnowledgeList";
import AidpImportDrawer from "./AidpImportDrawer";

const AidpKnowledgeConfiguration: React.FC = () => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const router = useRouter();
  const params = useParams();
  const locale = (params?.locale as string) || "zh";
  const [kbs, setKbs] = useState<AidpKnowledgeBaseItem[]>([]);
  const [loadingKbs, setLoadingKbs] = useState(false);
  const [kbsLoadFailed, setKbsLoadFailed] = useState(false);
  const [kbTotal, setKbTotal] = useState(0);
  const [kbHasMore, setKbHasMore] = useState(false);
  const [kbTotalReliable, setKbTotalReliable] = useState(true);
  const [viewMode, setViewMode] = useState<AidpKbViewMode>("cards");
  const [visibleColumns, setVisibleColumns] = useState<AidpKbColumnKey[]>([
    ...AIDP_KB_DEFAULT_COLUMNS,
  ]);
  const [kbPage, setKbPage] = useState(1);
  const [kbPageSize, setKbPageSize] = useState(10);
  const [kbKeyword, setKbKeyword] = useState("");
  const [debouncedKbKeyword, setDebouncedKbKeyword] = useState("");
  const [quickImportKb, setQuickImportKb] =
    useState<AidpKnowledgeBaseItem | null>(null);
  const [quickImportWatchKbId, setQuickImportWatchKbId] = useState<
    string | null
  >(null);
  const quickImportPendingIdsRef = useRef<string[]>([]);
  const quickImportWatchStartedAtRef = useRef(0);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedKbKeyword(kbKeyword.trim());
    }, KB_SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [kbKeyword]);

  const fetchKbs = useCallback(
    async (page = 1, keyword = debouncedKbKeyword, pageSize = kbPageSize) => {
      setLoadingKbs(true);
      setKbsLoadFailed(false);
      try {
        const result = await aidpKnowledgeService.listKbs(
          page,
          pageSize,
          keyword
        );
        setKbs(result.value);
        setKbTotal(result.total_count ?? result.value.length);
        setKbHasMore(result.has_more ?? false);
        setKbTotalReliable(result.total_reliable !== false);
        setKbPage(page);
      } catch (error) {
        log.error("Failed to fetch AIDP knowledge bases:", error);
        message.error(t("aidpKnowledge.fetchKbsFailed"));
        setKbs([]);
        setKbTotal(0);
        setKbHasMore(false);
        setKbTotalReliable(false);
        setKbsLoadFailed(true);
      } finally {
        setLoadingKbs(false);
      }
    },
    [debouncedKbKeyword, kbPageSize, message, t]
  );

  useEffect(() => {
    // Fetch the list when the debounced query or page size changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchKbs(1, debouncedKbKeyword, kbPageSize);
  }, [fetchKbs, debouncedKbKeyword, kbPageSize]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.removeItem("aidp_kb_server_url");
      window.localStorage.removeItem("aidp_kb_api_key");
    } catch {
      // The credentials were moved server-side; cleanup is best-effort.
    }
  }, []);

  const handleSelectKb = useCallback(
    (kb: AidpKnowledgeBaseItem) => {
      // The detail view lives on its own route so the URL survives refreshes.
      router.push(
        `/${locale}/knowledges/detail?kb=${encodeURIComponent(kb.kds_id)}`
      );
    },
    [locale, router]
  );

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
            await aidpKnowledgeService.deleteKb(kb.kds_id);
            message.success(t("aidpKnowledge.deleteKbSuccess"));
            void fetchKbs(kbPage, debouncedKbKeyword, kbPageSize);
          } catch {
            message.error(t("aidpKnowledge.deleteKbFailed"));
          }
        },
      });
    },
    [debouncedKbKeyword, fetchKbs, kbPage, kbPageSize, message, t]
  );

  const handleQuickDocsUploaded = useCallback(
    (uploadedFileIds: string[]) => {
      if (!quickImportKb || uploadedFileIds.length === 0) return;
      quickImportPendingIdsRef.current = uploadedFileIds;
      quickImportWatchStartedAtRef.current = Date.now();
      setQuickImportWatchKbId(quickImportKb.kds_id);
      void fetchKbs(kbPage, debouncedKbKeyword, kbPageSize);
    },
    [debouncedKbKeyword, fetchKbs, kbPage, kbPageSize, quickImportKb]
  );

  useEffect(() => {
    if (!quickImportWatchKbId) return;
    const timer = window.setInterval(() => {
      if (
        Date.now() - quickImportWatchStartedAtRef.current >
        AIDP_DOC_UPLOAD_WATCH_TIMEOUT_MS
      ) {
        quickImportPendingIdsRef.current = [];
        setQuickImportWatchKbId(null);
        void fetchKbs(kbPage, debouncedKbKeyword, kbPageSize);
        return;
      }
      void aidpKnowledgeService
        .listUploadTasks(quickImportWatchKbId, 1, 100, "", 0)
        .then((result) => {
          const stillPending = quickImportPendingIdsRef.current.filter((id) => {
            const task = result.value.find(
              (item) => String(item.file_ino_no) === id || item.file_uuid === id
            );
            if (!task) return true;
            const status = String(task.status ?? "").toUpperCase();
            return ![
              "1",
              "3",
              "5",
              "COMPLETED",
              "SUCCESS",
              "FAILED",
              "VECTOR_INGESTION_FAILED",
              "GRAPH_INGESTION_FAILED",
            ].includes(status);
          });
          quickImportPendingIdsRef.current = stillPending;
          if (stillPending.length === 0) {
            setQuickImportWatchKbId(null);
            void fetchKbs(kbPage, debouncedKbKeyword, kbPageSize);
          }
        })
        .catch((error) =>
          log.error("Failed to poll AIDP upload tasks:", error)
        );
    }, AIDP_DOC_STATUS_POLL_MS);
    return () => window.clearInterval(timer);
  }, [quickImportWatchKbId, fetchKbs, kbPage, kbPageSize, debouncedKbKeyword]);

  const handleCreateNew = useCallback(() => {
    router.push(`/${locale}/knowledges/create`);
  }, [locale, router]);

  return (
    <div className="flex h-full w-full min-w-0 flex-col">
      <div className="mt-4 min-h-0 flex-1 overflow-hidden">
        <AidpKnowledgeList
          kbs={kbs}
          isLoading={loadingKbs}
          loadFailed={kbsLoadFailed}
          total={kbTotal}
          totalReliable={kbTotalReliable}
          hasMore={kbHasMore}
          currentPage={kbPage}
          pageSize={kbPageSize}
          keyword={kbKeyword}
          viewMode={viewMode}
          visibleColumns={visibleColumns}
          onKeywordChange={setKbKeyword}
          onPageChange={(page) =>
            void fetchKbs(page, debouncedKbKeyword, kbPageSize)
          }
          onPageSizeChange={setKbPageSize}
          onViewModeChange={setViewMode}
          onVisibleColumnsChange={setVisibleColumns}
          onSelect={handleSelectKb}
          onRefresh={() =>
            void fetchKbs(kbPage, debouncedKbKeyword, kbPageSize)
          }
          onCreateNew={handleCreateNew}
          onImport={setQuickImportKb}
          onDelete={handleDeleteKb}
          onRetry={() => void fetchKbs(kbPage, debouncedKbKeyword, kbPageSize)}
        />
      </div>

      {quickImportKb && (
        <AidpImportDrawer
          title={t("aidpKnowledge.importDrawerTitle")}
          open
          knowledgeBase={quickImportKb}
          onClose={() => setQuickImportKb(null)}
          onDocsUploaded={handleQuickDocsUploaded}
          onRefresh={() =>
            void fetchKbs(kbPage, debouncedKbKeyword, kbPageSize)
          }
        />
      )}
    </div>
  );
};

export default AidpKnowledgeConfiguration;
