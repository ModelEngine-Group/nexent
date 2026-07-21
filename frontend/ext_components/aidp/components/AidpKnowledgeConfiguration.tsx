"use client";

import React, { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";

import { App, Row, Col, Modal } from "antd";
import { InfoCircleFilled } from "@ant-design/icons";

import {
  SETUP_PAGE_CONTAINER,
  TWO_COLUMN_LAYOUT,
  STANDARD_CARD,
} from "@/const/layoutConstants";
import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import aidpKnowledgeService, {
  type AidpKbDetail,
  type AidpDocumentItem,
} from "@/ext_components/aidp/services/aidpKnowledgeService";
import log from "@/lib/logger";

import AidpKnowledgeList from "./AidpKnowledgeList";
import AidpDocumentList from "./AidpDocumentList";
import AidpCreateKbModal from "./AidpCreateKbModal";
import AidpUpdateKbModal from "./AidpUpdateKbModal";

const AidpKnowledgeConfiguration: React.FC = () => {
  const { t } = useTranslation();
  const { message: appMessage } = App.useApp();

  // ---- KB list state ----
  const [kbs, setKbs] = useState<AidpKnowledgeBaseItem[]>([]);
  const [loadingKbs, setLoadingKbs] = useState(false);
  const [kbTotal, setKbTotal] = useState(0);
  const [kbHasMore, setKbHasMore] = useState(false);
  const [kbTotalReliable, setKbTotalReliable] = useState(true);

  // ---- Active KB / document state ----
  // activeKbId is stored separately from the paginated `kbs` list, because
  // refetching the KB list (e.g. after upload) returns only the current page,
  // which may not contain the currently active KB. `selectedKb` is the item
  // itself — set on selection, kept stable across list refetches.
  const [activeKbId, setActiveKbId] = useState<string | null>(null);
  const [selectedKb, setSelectedKb] = useState<AidpKnowledgeBaseItem | null>(null);
  const [activeKbDetail, setActiveKbDetail] = useState<AidpKbDetail | null>(null);
  const [documents, setDocuments] = useState<AidpDocumentItem[]>([]);
  const [totalDocs, setTotalDocs] = useState(0);
  const [docHasMore, setDocHasMore] = useState(false);
  const [docTotalReliable, setDocTotalReliable] = useState(true);
  const [loadingDocs, setLoadingDocs] = useState(false);

  // ---- Pagination state ----
  const KB_PAGE_SIZE = 10;
  const DOC_PAGE_SIZE = 10;
  const [kbPage, setKbPage] = useState(1);
  const [docPage, setDocPage] = useState(1);

  // ---- Modal state ----
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [updateModalOpen, setUpdateModalOpen] = useState(false);
  const [editingKb, setEditingKb] = useState<AidpKnowledgeBaseItem | null>(null);

  // ---- Fetch KB list (server-side pagination: each page fetches page_size items + Count total) ----
  const fetchKbs = useCallback(async (page: number = 1) => {
    setLoadingKbs(true);
    try {
      const result = await aidpKnowledgeService.listKbs(
        page,
        KB_PAGE_SIZE,
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
    } finally {
      setLoadingKbs(false);
    }
  }, [appMessage, t]);

  // Auto-fetch on mount
  useEffect(() => {
    fetchKbs();
  }, [fetchKbs]);

  // ---- Fetch documents for active KB (server-side pagination) ----
  const fetchDocs = useCallback(
    async (kbId: string, page: number = 1) => {
      setLoadingDocs(true);
      try {
        const result = await aidpKnowledgeService.listDocs(
          kbId,
          page,
          DOC_PAGE_SIZE,
        );
        const count = result.total_count ?? result.value.length;
        setDocuments(result.value);
        setTotalDocs(count);
        setDocHasMore(result.has_more ?? false);
        setDocTotalReliable(result.total_reliable !== false);
        setDocPage(page);
      } catch (error) {
        log.error("Failed to fetch AIDP documents:", error);
        appMessage.error(t("aidpKnowledge.fetchDocsFailed"));
        setDocuments([]);
        setTotalDocs(0);
        setDocHasMore(false);
        setDocTotalReliable(false);
      } finally {
        setLoadingDocs(false);
      }
    },
    [appMessage, t]
  );

  // ---- Handle KB selection ----
  const handleSelectKb = useCallback(
    (kb: AidpKnowledgeBaseItem) => {
      setActiveKbId(kb.kds_id);
      setSelectedKb(kb);
      setDocPage(1);
      setDocHasMore(false);
      setDocTotalReliable(true);
      fetchDocs(kb.kds_id, 1);
    },
    [fetchDocs]
  );

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

            // If the deleted KB was active, clear selection
            if (activeKbId === kb.kds_id) {
              setActiveKbId(null);
              setSelectedKb(null);
              setActiveKbDetail(null);
              setDocuments([]);
              setTotalDocs(0);
              setDocHasMore(false);
              setDocTotalReliable(true);
              setDocPage(1);
            }

            // Refresh list
            fetchKbs(kbPage);
          } catch (error) {
            appMessage.error(t("aidpKnowledge.deleteKbFailed"));
          }
        },
      });
    },
    [activeKbId, appMessage, t, fetchKbs, kbPage]
  );

  // ---- Edit KB ----
  const handleEditKb = useCallback((kb: AidpKnowledgeBaseItem) => {
    setEditingKb(kb);
    setUpdateModalOpen(true);
  }, []);

  // ---- After update success ----
  // Simply refresh the current KB page; selected KB stays put because it's
  // tracked independently of the paginated `kbs` list.
  const handleUpdateKbSuccess = useCallback(() => {
    setUpdateModalOpen(false);
    setEditingKb(null);
    fetchKbs(kbPage);
    // If the edited KB is the one currently selected, refresh its cached item
    // by re-fetching it via KB detail (name/description may have changed).
    if (selectedKb && activeKbId === selectedKb.kds_id) {
      aidpKnowledgeService
        .listKbs(kbPage, KB_PAGE_SIZE)
        .then((r) => {
          const refreshed = r.value.find((kb) => kb.kds_id === selectedKb.kds_id);
          if (refreshed) setSelectedKb(refreshed);
        })
        .catch(() => { /* non-fatal; stale item remains visible */ });
    }
  }, [fetchKbs, kbPage, selectedKb, activeKbId]);

  // ---- After create success ----
  // Scan the paginated KB list to find which page the new KB landed on,
  // switch to that page, and auto-select it so the user stays on their
  // newly created knowledge base.
  const handleCreateKbSuccess = useCallback(
    async (newKdsId: string) => {
      setCreateModalOpen(false);
      if (!newKdsId) {
        fetchKbs(kbPage);
        return;
      }

      const MAX_PAGES = 50; // safety cap to prevent infinite scan
      for (let p = 1; p <= MAX_PAGES; p++) {
        try {
          const result = await aidpKnowledgeService.listKbs(
            p,
            KB_PAGE_SIZE,
          );
          const found = result.value.find((kb) => kb.kds_id === newKdsId);
          if (found) {
            // Switch KB list to the page containing the new KB
            setKbs(result.value);
            setKbTotal(result.total_count ?? result.value.length);
            setKbHasMore(result.has_more ?? false);
            setKbTotalReliable(result.total_reliable !== false);
            setKbPage(p);
            // Auto-select the new KB
            setActiveKbId(found.kds_id);
            setSelectedKb(found);
            // Load its docs (will be empty or pre-uploaded docs)
            setDocPage(1);
            setDocHasMore(false);
            setDocTotalReliable(true);
            fetchDocs(found.kds_id, 1);
            return;
          }
          // Page didn't contain it — stop if no more pages
          if (!result.has_more && !result.next_link) break;
          if (result.value.length < KB_PAGE_SIZE) break;
        } catch (err) {
          log.error("Failed scanning KB pages after create:", err);
          break;
        }
      }
      // Fallback: refresh current KB page if we couldn't locate the new one
      fetchKbs(kbPage);
    },
    [kbPage, fetchDocs]
  );

  // ---- After documents uploaded ----
  const handleDocsUploaded = useCallback(() => {
    if (activeKbId) {
      // Reset doc pagination to page 1 so data and pagination UI stay in sync
      setDocPage(1);
      fetchDocs(activeKbId, 1);
      // Also refresh the KB list to update document_count, but stay on the
      // current KB page (otherwise user would be jumped back to page 1).
      fetchKbs(kbPage);
    }
  }, [activeKbId, fetchDocs, fetchKbs, kbPage]);

  // Active KB item is stored in `selectedKb` state (not derived from `kbs`),
  // because the KB list is server-paginated and refetching it after upload
  // returns only the current page — which may not contain the active KB.
  const activeKbItem = selectedKb;

  return (
    <div
      className="w-full h-full mx-auto relative flex flex-col"
      style={{
        maxWidth: SETUP_PAGE_CONTAINER.MAX_WIDTH,
        padding: `0 ${SETUP_PAGE_CONTAINER.HORIZONTAL_PADDING}`,
      }}
    >
      {/* Two-column layout — content-sized cards with a single
          scroll container; no card stretches to viewport height. */}
      <div className="flex-1 min-h-0 w-full mt-4 overflow-y-auto">
        <Row className="w-full" gutter={TWO_COLUMN_LAYOUT.GUTTER}>
          {/* Left column: KB list */}
          <Col
            xs={TWO_COLUMN_LAYOUT.LEFT_COLUMN.xs}
            md={TWO_COLUMN_LAYOUT.LEFT_COLUMN.md}
            lg={TWO_COLUMN_LAYOUT.LEFT_COLUMN.lg}
            xl={TWO_COLUMN_LAYOUT.LEFT_COLUMN.xl}
            xxl={TWO_COLUMN_LAYOUT.LEFT_COLUMN.xxl}
          >
            <AidpKnowledgeList
              kbs={kbs}
              activeKbId={activeKbId}
              isLoading={loadingKbs}
              total={kbTotal}
              totalReliable={kbTotalReliable}
              hasMore={kbHasMore}
              currentPage={kbPage}
              pageSize={KB_PAGE_SIZE}
              onPageChange={(page) => fetchKbs(page)}
              onSelect={handleSelectKb}
              onRefresh={() => fetchKbs(kbPage)}
              onCreateNew={() => setCreateModalOpen(true)}
              onEdit={handleEditKb}
              onDelete={handleDeleteKb}
            />
          </Col>

          {/* Right column: Document list or empty state */}
          <Col
            xs={TWO_COLUMN_LAYOUT.RIGHT_COLUMN.xs}
            md={TWO_COLUMN_LAYOUT.RIGHT_COLUMN.md}
            lg={TWO_COLUMN_LAYOUT.RIGHT_COLUMN.lg}
            xl={TWO_COLUMN_LAYOUT.RIGHT_COLUMN.xl}
            xxl={TWO_COLUMN_LAYOUT.RIGHT_COLUMN.xxl}
          >
            {activeKbItem ? (
              <AidpDocumentList
                activeKb={activeKbItem}
                documents={documents}
                totalDocs={totalDocs}
                totalReliable={docTotalReliable}
                hasMore={docHasMore}
                isLoading={loadingDocs}
                currentPage={docPage}
                pageSize={DOC_PAGE_SIZE}
                onPageChange={(page) => fetchDocs(activeKbId!, page)}
                onDocsUploaded={handleDocsUploaded}
                onRefresh={handleDocsUploaded}
              />
            ) : (
              <div
                className={`${STANDARD_CARD.BASE_CLASSES} w-full`}
                style={{ padding: STANDARD_CARD.PADDING }}
              >
                <div className="flex items-center justify-center py-12">
                  <div className="text-center">
                    <div className="text-gray-400 mb-2">
                      <InfoCircleFilled
                        style={{ fontSize: 36, color: "#1677ff" }}
                      />
                    </div>
                    <h3 className="text-base font-medium text-gray-700 mb-1">
                      {t("aidpKnowledge.selectKbTitle")}
                    </h3>
                    <p className="text-gray-500 max-w-md text-xs">
                      {t("aidpKnowledge.selectKbHint")}
                    </p>
                  </div>
                </div>
              </div>
            )}
          </Col>
        </Row>
      </div>

      {/* Create KB Modal */}
      <AidpCreateKbModal
        open={createModalOpen}
        existingKbs={kbs}
        onCancel={() => setCreateModalOpen(false)}
        onSuccess={handleCreateKbSuccess}
      />

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
