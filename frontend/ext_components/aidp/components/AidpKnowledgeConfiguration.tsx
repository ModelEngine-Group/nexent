"use client";

import React, {
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
} from "react";
import { useTranslation } from "react-i18next";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { App, Breadcrumb, Button, Modal, Tag } from "antd";
import { InfoCircleFilled } from "@ant-design/icons";

import { SETUP_PAGE_CONTAINER, STANDARD_CARD } from "@/const/layoutConstants";
import { KB_SEARCH_DEBOUNCE_MS } from "@/const/knowledgeBase";
import {
  AIDP_DOC_STATUS_POLL_MS,
  AIDP_DOC_UPLOAD_WATCH_TIMEOUT_MS,
  findPendingUploadIds,
} from "@/lib/aidpDocumentStatus";
import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import aidpKnowledgeService, {
  type AidpKbDetail,
  type AidpDocumentItem,
} from "@/ext_components/aidp/services/aidpKnowledgeService";
import log from "@/lib/logger";

import AidpKnowledgeList, {
  AIDP_KB_DEFAULT_COLUMNS,
  type AidpKbColumnKey,
  type AidpKbViewMode,
} from "./AidpKnowledgeList";
import AidpDocumentList from "./AidpDocumentList";
import AidpUpdateKbModal from "./AidpUpdateKbModal";

/**
 * Overview and file view orchestration for AIDP knowledge bases.
 *
 * The two views replace each other inside this component instead of using a
 * route: the overview state (search, page, view mode, column setting) lives
 * here, so returning from a file view restores it untouched. Entering a file
 * view clears the previous knowledge base documents and stops its upload
 * watch, so a late response can never land in another base.
 *
 * Creation is a separate page (`knowledges/create`); a knowledge base created
 * there is opened here through the `kb` query parameter.
 */
const AidpKnowledgeConfiguration: React.FC = () => {
  const { t } = useTranslation();
  const { message: appMessage } = App.useApp();
  const router = useRouter();
  const params = useParams();
  const searchParams = useSearchParams();
  const locale = (params?.locale as string) || "zh";

  // ---- KB list state ----
  const [kbs, setKbs] = useState<AidpKnowledgeBaseItem[]>([]);
  const [loadingKbs, setLoadingKbs] = useState(false);
  const [kbsLoadFailed, setKbsLoadFailed] = useState(false);
  const [kbTotal, setKbTotal] = useState(0);
  const [kbHasMore, setKbHasMore] = useState(false);
  const [kbTotalReliable, setKbTotalReliable] = useState(true);

  // ---- Overview presentation state (preserved across the file view) ----
  const [viewMode, setViewMode] = useState<AidpKbViewMode>("cards");
  const [visibleColumns, setVisibleColumns] = useState<AidpKbColumnKey[]>([
    ...AIDP_KB_DEFAULT_COLUMNS,
  ]);

  // ---- Active KB / document state ----
  // activeKbId is stored separately from the paginated `kbs` list, because
  // refetching the KB list (e.g. after upload) returns only the current page,
  // which may not contain the currently active KB. `selectedKb` is the item
  // itself — set on selection, kept stable across list refetches.
  const [activeKbId, setActiveKbId] = useState<string | null>(null);
  const [selectedKb, setSelectedKb] = useState<AidpKnowledgeBaseItem | null>(
    null
  );
  const [activeKbDetail, setActiveKbDetail] = useState<AidpKbDetail | null>(
    null
  );
  const [documents, setDocuments] = useState<AidpDocumentItem[]>([]);
  const [totalDocs, setTotalDocs] = useState(0);
  const [docHasMore, setDocHasMore] = useState(false);
  const [docTotalReliable, setDocTotalReliable] = useState(true);
  // Files still being processed across the whole knowledge base (not just the
  // visible page). Drives the status polling below.
  const [docProcessingCount, setDocProcessingCount] = useState(0);
  const [loadingDocs, setLoadingDocs] = useState(false);

  // ---- Pagination state ----
  const KB_PAGE_SIZE = 10;
  const DOC_PAGE_SIZE = 10;
  const [kbPage, setKbPage] = useState(1);
  const [kbPageSize, setKbPageSize] = useState(KB_PAGE_SIZE);
  const [docPage, setDocPage] = useState(1);

  // ---- Modal state ----
  const [updateModalOpen, setUpdateModalOpen] = useState(false);
  const [editingKb, setEditingKb] = useState<AidpKnowledgeBaseItem | null>(
    null
  );
  const [quickImportKb, setQuickImportKb] =
    useState<AidpKnowledgeBaseItem | null>(null);
  const [quickImportWatchKbId, setQuickImportWatchKbId] = useState<
    string | null
  >(null);
  const quickImportPendingIdsRef = useRef<string[]>([]);
  const quickImportWatchStartedAtRef = useRef(0);

  // ---- Keyword search state ----
  // `kbKeyword` is the raw input value and keeps the text field responsive;
  // `debouncedKbKeyword` is what actually drives requests. Splitting them means
  // typing never waits on the network, and a pause settles on one request.
  const [kbKeyword, setKbKeyword] = useState("");
  const [debouncedKbKeyword, setDebouncedKbKeyword] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedKbKeyword(kbKeyword.trim());
    }, KB_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [kbKeyword]);

  // ---- Fetch KB list (server-side pagination: each page fetches page_size items + Count total) ----
  const fetchKbs = useCallback(
    async (
      page: number = 1,
      keyword: string = "",
      pageSize: number = KB_PAGE_SIZE
    ) => {
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
        appMessage.error(t("aidpKnowledge.fetchKbsFailed"));
        setKbs([]);
        setKbTotal(0);
        setKbHasMore(false);
        setKbTotalReliable(false);
        setKbsLoadFailed(true);
      } finally {
        setLoadingKbs(false);
      }
    },
    [appMessage, t]
  );

  // Fetch on mount, and again whenever the debounced keyword settles.
  // Every keyword change restarts at page 1 on purpose: the previous page
  // number is meaningless against a different result set and would otherwise
  // render an empty list whenever the filtered set is shorter than that page.
  useEffect(() => {
    fetchKbs(1, debouncedKbKeyword, kbPageSize);
  }, [fetchKbs, debouncedKbKeyword, kbPageSize]);

  // ---- Cleanup legacy localStorage credentials on mount ----
  // v7.1: AIDP credentials moved backend-side; frontends that pre-date the
  // migration may still carry serverUrl / apiKey in localStorage. Remove
  // them on mount so a stale value cannot accidentally leak.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.removeItem("aidp_kb_server_url");
      window.localStorage.removeItem("aidp_kb_api_key");
    } catch {
      // localStorage may be unavailable in some test/SSR environments;
      // ignore — the cleanup is best-effort.
    }
  }, []);

  // ---- Fetch documents for active KB (server-side pagination) ----
  // `silent` refreshes are used by the status poller: the table keeps rendering
  // the previous page instead of flashing the loading placeholder, and a failed
  // poll stays out of the way (logged only) so a short upstream hiccup cannot
  // spam the user with a toast every interval. The manual refresh button always
  // runs a non-silent fetch, so errors stay visible when the user asks for them.
  const fetchDocs = useCallback(
    async (kbId: string, page: number = 1, options?: { silent?: boolean }) => {
      const silent = options?.silent === true;
      if (!silent) setLoadingDocs(true);
      try {
        const result = await aidpKnowledgeService.listDocs(
          kbId,
          page,
          DOC_PAGE_SIZE
        );
        const count = result.total_count ?? result.value.length;
        setDocuments(result.value);
        setTotalDocs(count);
        setDocHasMore(result.has_more ?? false);
        setDocTotalReliable(result.total_reliable !== false);
        setDocProcessingCount(result.processing_count ?? 0);
        setDocPage(page);

        // Settle the upload watch: a just-uploaded file counts as done only
        // once it is listed with a terminal status. Files AIDP has not listed
        // yet stay pending on purpose, so the refresh keeps running instead of
        // stopping while the list is still missing the upload.
        if (pendingUploadIdsRef.current.length > 0) {
          const stillPending = findPendingUploadIds(
            pendingUploadIdsRef.current,
            result.value
          );
          pendingUploadIdsRef.current = stillPending;
          if (stillPending.length === 0) setUploadWatchActive(false);
        }
      } catch (error) {
        log.error("Failed to fetch AIDP documents:", error);
        if (!silent) {
          appMessage.error(t("aidpKnowledge.fetchDocsFailed"));
          setDocuments([]);
          setTotalDocs(0);
          setDocHasMore(false);
          setDocTotalReliable(false);
          setDocProcessingCount(0);
        }
      } finally {
        if (!silent) setLoadingDocs(false);
      }
    },
    [appMessage, t]
  );

  // ---- Upload watch - state - ---
  // Files the user just uploaded and that are not settled yet. Kept in a ref
  // so `fetchDocs` can settle them without becoming a new function on every
  // watch update (which would restart the polling interval).
  const pendingUploadIdsRef = useRef<string[]>([]);
  const uploadWatchStartedAtRef = useRef(0);
  const [uploadWatchActive, setUploadWatchActive] = useState(false);

  /** Start refreshing until every just-uploaded file reaches a terminal state. */
  const startUploadWatch = useCallback((uploadedFileIds: string[]) => {
    if (uploadedFileIds.length === 0) return;
    pendingUploadIdsRef.current = uploadedFileIds;
    uploadWatchStartedAtRef.current = Date.now();
    setUploadWatchActive(true);
  }, []);

  /** Stop watching uploads (no upload in flight to wait for). */
  const stopUploadWatch = useCallback(() => {
    pendingUploadIdsRef.current = [];
    setUploadWatchActive(false);
  }, []);

  // ---- Poll the document list while work is outstanding ----
  // Two independent reasons to poll:
  //   * a file just uploaded by the user has not settled yet (`uploadWatchActive`),
  //     which covers the window where AIDP has accepted the upload but does not
  //     list it yet - polling on processing_count alone would never start there;
  //   * the knowledge base still reports files being ingested
  //     (`docProcessingCount`, counted across the whole KB, so a processing file
  //     on another page keeps the status column live).
  // Polling stops once neither holds: every file is COMPLETED or FAILED. The
  // upload watch additionally gives up after AIDP_DOC_UPLOAD_WATCH_TIMEOUT_MS so
  // a silently dropped upload cannot keep the list refreshing forever.
  const shouldPollDocs = uploadWatchActive || docProcessingCount > 0;
  useEffect(() => {
    if (!activeKbId || !shouldPollDocs) return;
    const tick = () => {
      if (
        uploadWatchActive &&
        Date.now() - uploadWatchStartedAtRef.current >
          AIDP_DOC_UPLOAD_WATCH_TIMEOUT_MS
      ) {
        stopUploadWatch();
        return;
      }
      void fetchDocs(activeKbId, docPage, { silent: true });
    };
    const timer = window.setInterval(tick, AIDP_DOC_STATUS_POLL_MS);
    return () => window.clearInterval(timer);
  }, [
    activeKbId,
    docPage,
    shouldPollDocs,
    uploadWatchActive,
    fetchDocs,
    stopUploadWatch,
  ]);

  // ---- Clear the file view state ----
  // Used on return to the overview and whenever another base is opened: the
  // previous documents and its upload watch must never survive into the next
  // knowledge base.
  const clearFileView = useCallback(() => {
    stopUploadWatch();
    setActiveKbId(null);
    setSelectedKb(null);
    setActiveKbDetail(null);
    setDocuments([]);
    setTotalDocs(0);
    setDocHasMore(false);
    setDocTotalReliable(true);
    setDocProcessingCount(0);
    setDocPage(1);
  }, [stopUploadWatch]);

  // ---- Handle KB selection (enter the full-page file view) ----
  const handleSelectKb = useCallback(
    (kb: AidpKnowledgeBaseItem) => {
      stopUploadWatch();
      setActiveKbId(kb.kds_id);
      setSelectedKb(kb);
      setDocPage(1);
      setDocHasMore(false);
      setDocTotalReliable(true);
      setDocProcessingCount(0);
      void fetchDocs(kb.kds_id, 1);
    },
    [fetchDocs, stopUploadWatch]
  );

  // ---- Open a knowledge base by id (used by the `kb` query parameter) ----
  // The creation page sends the user here right after a successful create, so
  // the files just uploaded are visible without a manual search.
  const openKbById = useCallback(
    async (kbId: string) => {
      try {
        const detail = await aidpKnowledgeService.getKb(kbId);
        const item = {
          ...detail,
          kds_id: kbId,
          kds_name: detail.kds_name || kbId,
        } as AidpKnowledgeBaseItem;
        handleSelectKb(item);
      } catch (error) {
        log.error("Failed to open AIDP knowledge base from query:", error);
      }
    },
    [handleSelectKb]
  );

  const requestedKbId = searchParams?.get("kb") || null;
  const openedRequestedKbRef = useRef<string | null>(null);
  useEffect(() => {
    // Only react to a new `kb` value; a manual return to the overview while
    // the parameter is still present must not reopen it.
    if (!requestedKbId) return;
    if (openedRequestedKbRef.current === requestedKbId) return;
    openedRequestedKbRef.current = requestedKbId;
    void openKbById(requestedKbId);
  }, [openKbById, requestedKbId]);

  // ---- Return to the overview ----
  const handleBackToList = useCallback(() => {
    clearFileView();
    if (requestedKbId && typeof window !== "undefined") {
      // Drop the parameter so a refresh does not reopen the file view.
      window.history.replaceState(null, "", `/${locale}/knowledges`);
    }
  }, [clearFileView, locale, requestedKbId]);

  // ---- Handle KB deletion ----
  const handleDeleteKb = useCallback(
    (kb: AidpKnowledgeBaseItem) => {
      Modal.confirm({
        title: t("aidpKnowledge.confirmDeleteTitle"),
        content: t("aidpKnowledge.confirmDeleteContent", {
          name: kb.kds_name,
        }),
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        okButtonProps: { danger: true },
        centered: true,
        onOk: async () => {
          try {
            await aidpKnowledgeService.deleteKb(kb.kds_id);
            appMessage.success(t("aidpKnowledge.deleteKbSuccess"));

            // If the deleted KB was open, leave the file view.
            if (activeKbId === kb.kds_id) {
              clearFileView();
            }

            // Refresh list, keeping the active search filter applied
            void fetchKbs(kbPage, debouncedKbKeyword, kbPageSize);
          } catch (error) {
            appMessage.error(t("aidpKnowledge.deleteKbFailed"));
          }
        },
      });
    },
    [
      activeKbId,
      appMessage,
      t,
      fetchKbs,
      kbPage,
      kbPageSize,
      debouncedKbKeyword,
      clearFileView,
    ]
  );

  // ---- Edit KB ----
  const handleEditKb = useCallback((kb: AidpKnowledgeBaseItem) => {
    setEditingKb(kb);
    setUpdateModalOpen(true);
  }, []);

  // ---- After update success ----
  // Apply the returned resource locally instead of reloading the full KB page.
  const handleUpdateKbSuccess = useCallback(
    (updatedKb: AidpKnowledgeBaseItem) => {
      setUpdateModalOpen(false);
      setEditingKb(null);
      setKbs((current) =>
        current.map((kb) => (kb.kds_id === updatedKb.kds_id ? updatedKb : kb))
      );
      if (activeKbId === updatedKb.kds_id) {
        setSelectedKb(updatedKb);
        setActiveKbDetail(updatedKb);
      }
    },
    [activeKbId]
  );

  // ---- Refresh the active KB metadata (counts / name) ----
  const refreshActiveKbDetail = useCallback(() => {
    if (!activeKbId) return;
    void aidpKnowledgeService
      .getKb(activeKbId)
      .then((detail) => {
        const refreshed = {
          ...selectedKb,
          ...detail,
          kds_id: activeKbId,
          kds_name: detail.kds_name || selectedKb?.kds_name || activeKbId,
        } as AidpKnowledgeBaseItem;
        setSelectedKb(refreshed);
        setActiveKbDetail(detail);
        setKbs((current) =>
          current.map((kb) => (kb.kds_id === activeKbId ? refreshed : kb))
        );
      })
      .catch((error) =>
        log.error("Failed to refresh active AIDP KB detail:", error)
      );
  }, [activeKbId, selectedKb]);

  // ---- After documents uploaded ----
  // Refresh immediately so the uploaded files show up without the user having
  // to press refresh, then watch them until AIDP reports a terminal status.
  const handleDocsUploaded = useCallback(
    (uploadedFileIds: string[]) => {
      startUploadWatch(uploadedFileIds);
      if (!activeKbId) return;
      // Reset doc pagination to page 1 so data and pagination UI stay in sync
      setDocPage(1);
      void fetchDocs(activeKbId, 1);
      refreshActiveKbDetail();
    },
    [activeKbId, fetchDocs, refreshActiveKbDetail, startUploadWatch]
  );

  // Quick imports run from the overview card menu. Keep their status polling
  // independent from the currently open document page so a late response can
  // never replace another knowledge base's documents.
  const handleQuickDocsUploaded = useCallback(
    (uploadedFileIds: string[]) => {
      if (!quickImportKb || uploadedFileIds.length === 0) return;
      quickImportPendingIdsRef.current = uploadedFileIds;
      quickImportWatchStartedAtRef.current = Date.now();
      setQuickImportWatchKbId(quickImportKb.kds_id);
      void fetchKbs(kbPage, debouncedKbKeyword, kbPageSize);
    },
    [quickImportKb, fetchKbs, kbPage, debouncedKbKeyword, kbPageSize]
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
        .listDocs(quickImportWatchKbId, 1, DOC_PAGE_SIZE)
        .then((result) => {
          quickImportPendingIdsRef.current = findPendingUploadIds(
            quickImportPendingIdsRef.current,
            result.value
          );
          if (
            quickImportPendingIdsRef.current.length === 0 &&
            (result.processing_count ?? 0) === 0
          ) {
            setQuickImportWatchKbId(null);
            void fetchKbs(kbPage, debouncedKbKeyword, kbPageSize);
          }
        })
        .catch((error) =>
          log.error("Failed to poll AIDP quick-import documents:", error)
        );
    }, AIDP_DOC_STATUS_POLL_MS);
    return () => window.clearInterval(timer);
  }, [quickImportWatchKbId, fetchKbs, kbPage, debouncedKbKeyword, kbPageSize]);

  const handleKbPageSizeChange = useCallback((pageSize: number) => {
    setKbPageSize(pageSize);
  }, []);

  // ---- Manual refresh (refresh button) ----
  // Refreshes the visible page and the KB metadata but never starts an upload
  // watch: the user is not waiting for a file they just added.
  const handleRefreshDocs = useCallback(() => {
    if (!activeKbId) return;
    void fetchDocs(activeKbId, docPage);
    refreshActiveKbDetail();
  }, [activeKbId, docPage, fetchDocs, refreshActiveKbDetail]);

  // ---- Navigate to the dedicated creation page ----
  const handleCreateNew = useCallback(() => {
    router.push(`/${locale}/knowledges/create`);
  }, [locale, router]);

  // Active KB item is stored in `selectedKb` state (not derived from `kbs`),
  // because the KB list is server-paginated and refetching it after upload
  // returns only the current page — which may not contain the active KB.
  const activeKbItem = selectedKb;

  const containerStyle = {
    maxWidth: SETUP_PAGE_CONTAINER.MAX_WIDTH,
    padding: `0 ${SETUP_PAGE_CONTAINER.HORIZONTAL_PADDING}`,
  };

  // ---- File view: one knowledge base, full page ----
  if (activeKbId && activeKbItem) {
    const isUnavailable =
      activeKbItem.resource_status === "UNAVAILABLE" ||
      activeKbItem.resource_status === "ORPHANED";
    return (
      <div
        className="w-full h-full mx-auto relative flex flex-col"
        style={containerStyle}
      >
        <div className="flex-1 min-h-0 w-full mt-4 overflow-y-auto">
          <div className="mb-3">
            <Breadcrumb
              items={[
                {
                  title: (
                    <button
                      type="button"
                      onClick={handleBackToList}
                      className="text-gray-500 hover:text-blue-500"
                    >
                      {t("aidpKnowledge.breadcrumbKnowledgeBase")}
                    </button>
                  ),
                },
                { title: t("aidpKnowledge.breadcrumbUploadFiles") },
              ]}
            />
            <div className="mt-2 flex items-center gap-2 flex-wrap">
              <h2 className="text-base font-semibold text-gray-800 truncate">
                {activeKbItem.kds_name}
              </h2>
              {isUnavailable && (
                <Tag color="default">{t("aidpKnowledge.kbUnavailable")}</Tag>
              )}
              {activeKbItem.permission === "READ_ONLY" && !isUnavailable && (
                <Tag color="default">{t("aidpKnowledge.kbReadOnly")}</Tag>
              )}
            </div>
          </div>
          <AidpDocumentList
            activeKb={activeKbItem}
            documents={documents}
            totalDocs={totalDocs}
            totalReliable={docTotalReliable}
            hasMore={docHasMore}
            isLoading={loadingDocs}
            currentPage={docPage}
            pageSize={DOC_PAGE_SIZE}
            onPageChange={(page) => {
              // The upload watch only makes sense on the page the upload
              // landed on; the status poller still covers other pages.
              stopUploadWatch();
              void fetchDocs(activeKbId, page);
            }}
            onDocsUploaded={handleDocsUploaded}
            onRefresh={handleRefreshDocs}
          />
        </div>
      </div>
    );
  }

  // ---- Overview: guide plus the card or table list ----
  return (
    <div
      className="w-full h-full mx-auto relative flex flex-col"
      style={containerStyle}
    >
      <div className="flex-1 min-h-0 w-full mt-4 overflow-hidden">
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
            fetchKbs(page, debouncedKbKeyword, kbPageSize)
          }
          onPageSizeChange={handleKbPageSizeChange}
          onViewModeChange={setViewMode}
          onVisibleColumnsChange={setVisibleColumns}
          onSelect={handleSelectKb}
          onRefresh={() => fetchKbs(kbPage, debouncedKbKeyword, kbPageSize)}
          onCreateNew={handleCreateNew}
          onImport={setQuickImportKb}
          onEdit={handleEditKb}
          onDelete={handleDeleteKb}
          onRetry={() => fetchKbs(kbPage, debouncedKbKeyword, kbPageSize)}
        />
      </div>

      <Modal
        title={t("aidpKnowledge.importFileTitle", {
          name: quickImportKb?.kds_name || "",
        })}
        open={Boolean(quickImportKb)}
        onCancel={() => setQuickImportKb(null)}
        footer={null}
        destroyOnClose
        width={760}
        centered
      >
        {quickImportKb && (
          <AidpDocumentList
            activeKb={quickImportKb}
            documents={[]}
            totalDocs={0}
            totalReliable={false}
            hasMore={false}
            isLoading={false}
            currentPage={1}
            pageSize={DOC_PAGE_SIZE}
            onPageChange={() => undefined}
            onDocsUploaded={handleQuickDocsUploaded}
            onRefresh={() => fetchKbs(kbPage, debouncedKbKeyword, kbPageSize)}
            uploadOnly
          />
        )}
      </Modal>

      {/* Update KB Modal */}
      <AidpUpdateKbModal
        open={updateModalOpen}
        knowledgeBase={editingKb}
        onCancel={() => {
          setUpdateModalOpen(false);
          setEditingKb(null);
        }}
        onSuccess={handleUpdateKbSuccess}
      />
    </div>
  );
};

export default AidpKnowledgeConfiguration;
