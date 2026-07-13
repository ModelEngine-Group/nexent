"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
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
  // kbsRef mirrors `kbs` state so fetchKbs can read cached document_counts
  // without needing `kbs` in its useCallback deps (which would cause the
  // auto-fetch effect to re-trigger on every kbs change).
  const kbsRef = useRef<AidpKnowledgeBaseItem[]>([]);
  useEffect(() => {
    kbsRef.current = kbs;
  }, [kbs]);
  const [loadingKbs, setLoadingKbs] = useState(false);

  // ---- Active KB / document state ----
  const [activeKbId, setActiveKbId] = useState<string | null>(null);
  const [activeKbDetail, setActiveKbDetail] = useState<AidpKbDetail | null>(null);
  const [documents, setDocuments] = useState<AidpDocumentItem[]>([]);
  const [totalDocs, setTotalDocs] = useState(0);
  const [loadingDocs, setLoadingDocs] = useState(false);

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

  // ---- Fetch KB list ----
  const fetchKbs = useCallback(async () => {
    if (!serverUrl || !apiKey) return;
    setLoadingKbs(true);
    try {
      const result = await aidpKnowledgeService.listKbs(serverUrl, apiKey);
      const listFromApi = result.value;

      // Read cached document_counts from kbsRef (closure-safe, no re-render,
      // no need to add `kbs` to useCallback deps).
      const cachedCounts = new Map<string, number>();
      kbsRef.current.forEach((kb) => {
        if (typeof kb.document_count === "number") {
          cachedCounts.set(kb.kds_id, kb.document_count);
        }
      });

      // Identify KBs whose document_count is still unknown.
      const unknown = listFromApi.filter((kb) => {
        const hasApi =
          typeof kb.document_count === "number" && kb.document_count > 0;
        return !hasApi && !cachedCounts.has(kb.kds_id);
      });

      // Fetch counts for unknown KBs in parallel (cheap: page_size=1).
      // Awaited BEFORE setKbs so the list renders only once with accurate numbers.
      const fetchedCounts = new Map<string, number>();
      if (unknown.length > 0) {
        const settled = await Promise.allSettled(
          unknown.map((kb) =>
            aidpKnowledgeService.listDocs(
              serverUrl,
              apiKey,
              kb.kds_id,
              1,
              1
            )
          )
        );
        settled.forEach((r, i) => {
          if (r.status === "fulfilled") {
            const c = r.value.total_count ?? r.value.value.length;
            fetchedCounts.set(unknown[i].kds_id, c);
          }
        });
      }

      // Single setKbs — list renders once, never flashes "0".
      setKbs(
        listFromApi.map((kb) => {
          const apiValid =
            typeof kb.document_count === "number" && kb.document_count > 0;
          if (apiValid) return kb;
          const fetched = fetchedCounts.get(kb.kds_id);
          if (typeof fetched === "number")
            return { ...kb, document_count: fetched };
          const cached = cachedCounts.get(kb.kds_id);
          if (typeof cached === "number")
            return { ...kb, document_count: cached };
          return kb;
        })
      );
    } catch (error) {
      log.error("Failed to fetch AIDP knowledge bases:", error);
      appMessage.error(t("aidpKnowledge.fetchKbsFailed"));
      setKbs([]);
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

  // ---- Fetch documents for active KB ----
  const fetchDocs = useCallback(
    async (kbId: string) => {
      if (!serverUrl || !apiKey) return;
      setLoadingDocs(true);
      try {
        const result = await aidpKnowledgeService.listDocs(
          serverUrl,
          apiKey,
          kbId
        );
        const count = result.total_count ?? result.value.length;
        setDocuments(result.value);
        setTotalDocs(count);
        // Patch the matching KB's document_count in the list so the card badge
        // reflects the actual count (real AIDP list API does not return this field).
        setKbs((prev) =>
          prev.map((kb) =>
            kb.kds_id === kbId ? { ...kb, document_count: count } : kb
          )
        );
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
              onSelect={handleSelectKb}
              onRefresh={fetchKbs}
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
