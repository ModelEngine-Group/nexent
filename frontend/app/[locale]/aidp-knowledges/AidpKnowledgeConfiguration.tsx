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
} from "@/services/aidpKnowledgeService";
import log from "@/lib/logger";

import AidpConnectionConfig from "./components/AidpConnectionConfig";
import AidpKnowledgeList from "./components/AidpKnowledgeList";
import AidpDocumentList from "./components/AidpDocumentList";
import AidpCreateKbModal from "./components/AidpCreateKbModal";
import AidpUpdateKbModal from "./components/AidpUpdateKbModal";

const AidpKnowledgeConfiguration: React.FC = () => {
  const { t } = useTranslation();
  const { message: appMessage } = App.useApp();

  // ---- Connection state (localStorage-backed) ----
  const [serverUrl, setServerUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [isConnected, setIsConnected] = useState(false);

  // ---- KB list state ----
  const [kbs, setKbs] = useState<AidpKnowledgeBaseItem[]>([]);
  const [loadingKbs, setLoadingKbs] = useState(false);
  const [kbTotal, setKbTotal] = useState(0);

  // ---- Active KB / document state ----
  const [activeKbId, setActiveKbId] = useState<string | null>(null);
  const [activeKbDetail, setActiveKbDetail] = useState<AidpKbDetail | null>(null);
  const [documents, setDocuments] = useState<AidpDocumentItem[]>([]);
  const [totalDocs, setTotalDocs] = useState(0);
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

  // ---- Load credentials from localStorage on mount ----
  useEffect(() => {
    const savedUrl = localStorage.getItem("aidp_kb_server_url") || "";
    const savedKey = localStorage.getItem("aidp_kb_api_key") || "";
    if (savedUrl && savedKey) {
      setServerUrl(savedUrl);
      setApiKey(savedKey);
      setIsConnected(true);
    }
  }, []);

  // ---- Fetch KB list (server-side pagination: each page fetches page_size items + Count total) ----
  const fetchKbs = useCallback(async (page: number = 1) => {
    if (!serverUrl || !apiKey) return;
    setLoadingKbs(true);
    try {
      const result = await aidpKnowledgeService.listKbs(
        serverUrl,
        apiKey,
        page,
        KB_PAGE_SIZE,
      );
      setKbs(result.value);
      setKbTotal(result.total_count ?? result.value.length);
      setKbPage(page);
    } catch (error) {
      log.error("Failed to fetch AIDP knowledge bases:", error);
      appMessage.error(t("aidpKnowledge.fetchKbsFailed"));
      setKbs([]);
      setKbTotal(0);
    } finally {
      setLoadingKbs(false);
    }
  }, [serverUrl, apiKey, appMessage, t]);

  // Auto-fetch when credentials become available
  useEffect(() => {
    if (isConnected && serverUrl && apiKey) {
      fetchKbs();
    }
  }, [isConnected, serverUrl, apiKey, fetchKbs]);

  // ---- Fetch documents for active KB (server-side pagination) ----
  const fetchDocs = useCallback(
    async (kbId: string, page: number = 1) => {
      if (!serverUrl || !apiKey) return;
      setLoadingDocs(true);
      try {
        const result = await aidpKnowledgeService.listDocs(
          serverUrl,
          apiKey,
          kbId,
          page,
          DOC_PAGE_SIZE,
        );
        const count = result.total_count ?? result.value.length;
        setDocuments(result.value);
        setTotalDocs(count);
        setDocPage(page);
      } catch (error) {
        log.error("Failed to fetch AIDP documents:", error);
        appMessage.error(t("aidpKnowledge.fetchDocsFailed"));
        setDocuments([]);
        setTotalDocs(0);
      } finally {
        setLoadingDocs(false);
      }
    },
    [serverUrl, apiKey, appMessage, t]
  );

  // ---- Handle KB selection ----
  const handleSelectKb = useCallback(
    (kb: AidpKnowledgeBaseItem) => {
      setActiveKbId(kb.kds_id);
      fetchDocs(kb.kds_id);
    },
    [fetchDocs]
  );

  // ---- Handle connection change ----
  const handleConnectionChange = useCallback(
    (newUrl: string, newKey: string) => {
      setServerUrl(newUrl);
      setApiKey(newKey);
      setIsConnected(true);
      setActiveKbId(null);
      setActiveKbDetail(null);
      setDocuments([]);
      setTotalDocs(0);
      setKbTotal(0);
      setKbPage(1);
      setDocPage(1);
    },
    []
  );

  // ---- Handle connection clear ----
  const handleConnectionClear = useCallback(() => {
    setServerUrl("");
    setApiKey("");
    setIsConnected(false);
    setKbs([]);
    setActiveKbId(null);
    setActiveKbDetail(null);
    setDocuments([]);
    setTotalDocs(0);
    setKbTotal(0);
    setKbPage(1);
    setDocPage(1);
  }, []);

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
            await aidpKnowledgeService.deleteKb(
              serverUrl,
              apiKey,
              kb.kds_id
            );
            appMessage.success(t("aidpKnowledge.deleteKbSuccess"));

            // If the deleted KB was active, clear selection
            if (activeKbId === kb.kds_id) {
              setActiveKbId(null);
              setActiveKbDetail(null);
              setDocuments([]);
              setTotalDocs(0);
              setDocPage(1);
            }

            // Refresh list
            fetchKbs();
          } catch (error) {
            appMessage.error(t("aidpKnowledge.deleteKbFailed"));
          }
        },
      });
    },
    [serverUrl, apiKey, activeKbId, appMessage, t, fetchKbs]
  );

  // ---- Edit KB ----
  const handleEditKb = useCallback((kb: AidpKnowledgeBaseItem) => {
    setEditingKb(kb);
    setUpdateModalOpen(true);
  }, []);

  // ---- After create/update success ----
  const handleKbMutationSuccess = useCallback(() => {
    setCreateModalOpen(false);
    setUpdateModalOpen(false);
    setEditingKb(null);
    fetchKbs();
  }, [fetchKbs]);

  // ---- After documents uploaded ----
  const handleDocsUploaded = useCallback(() => {
    if (activeKbId) {
      fetchDocs(activeKbId);
      // Also refresh the KB list to update document_count
      fetchKbs();
    }
  }, [activeKbId, fetchDocs, fetchKbs]);

  // Find the currently active KB item
  const activeKbItem = kbs.find((kb) => kb.kds_id === activeKbId) || null;

  return (
    <div
      className="w-full h-full mx-auto relative"
      style={{
        maxWidth: SETUP_PAGE_CONTAINER.MAX_WIDTH,
        padding: `0 ${SETUP_PAGE_CONTAINER.HORIZONTAL_PADDING}`,
      }}
    >
      {/* Connection config card (full width) */}
      <AidpConnectionConfig
        serverUrl={serverUrl}
        apiKey={apiKey}
        isConnected={isConnected}
        onConnectionChange={handleConnectionChange}
        onConnectionClear={handleConnectionClear}
      />

      {/* Two-column layout */}
      <div className="w-full h-full">
        <Row className="h-full w-full" gutter={TWO_COLUMN_LAYOUT.GUTTER}>
          {/* Left column: KB list */}
          <Col
            className="h-full"
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
            className="h-full"
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
                isLoading={loadingDocs}
                serverUrl={serverUrl}
                apiKey={apiKey}
                currentPage={docPage}
                pageSize={DOC_PAGE_SIZE}
                onPageChange={(page) => fetchDocs(activeKbId!, page)}
                onDocsUploaded={handleDocsUploaded}
                onRefresh={handleDocsUploaded}
              />
            ) : (
              <div
                className={`${STANDARD_CARD.BASE_CLASSES} flex flex-col h-full w-full`}
                style={{ padding: STANDARD_CARD.PADDING }}
              >
                <div
                  className="flex items-center justify-center p-4 h-full"
                >
                  <div className="text-center">
                    <div className="text-gray-400 mb-2">
                      <InfoCircleFilled
                        style={{ fontSize: 36, color: "#1677ff" }}
                      />
                    </div>
                    <h3 className="text-base font-medium text-gray-700 mb-1">
                      {!isConnected
                        ? t("aidpKnowledge.notConnectedTitle")
                        : t("aidpKnowledge.selectKbTitle")}
                    </h3>
                    <p className="text-gray-500 max-w-md text-xs">
                      {!isConnected
                        ? t("aidpKnowledge.notConnectedHint")
                        : t("aidpKnowledge.selectKbHint")}
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
        serverUrl={serverUrl}
        apiKey={apiKey}
        existingKbs={kbs}
        onCancel={() => setCreateModalOpen(false)}
        onSuccess={handleKbMutationSuccess}
      />

      {/* Update KB Modal */}
      <AidpUpdateKbModal
        open={updateModalOpen}
        knowledgeBase={editingKb}
        serverUrl={serverUrl}
        apiKey={apiKey}
        onCancel={() => {
          setUpdateModalOpen(false);
          setEditingKb(null);
        }}
        onSuccess={handleKbMutationSuccess}
      />
    </div>
  );
};

export default AidpKnowledgeConfiguration;
