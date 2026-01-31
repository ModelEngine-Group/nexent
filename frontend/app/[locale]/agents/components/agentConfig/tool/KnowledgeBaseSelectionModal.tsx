"use client";

import { useState, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Spin, message } from "antd";
import KnowledgeBaseList from "../../../../knowledges/components/knowledge/KnowledgeBaseList";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { KnowledgeBase } from "@/types/knowledgeBase";
import { ConfigStore } from "@/lib/config";

export interface KnowledgeBaseSelectionModalProps {
  isOpen: boolean;
  onCancel: () => void;
  onSave: (selectedIds: string[]) => void;
  initialSelectedIds: string[];
  toolName?: string;
  difyApiBase?: string;
  difyApiKey?: string;
}

export default function KnowledgeBaseSelectionModal({
  isOpen,
  onCancel,
  onSave,
  initialSelectedIds,
  toolName,
  difyApiBase,
  difyApiKey,
}: KnowledgeBaseSelectionModalProps) {
  const { t } = useTranslation("common");
  const [kbLoading, setKbLoading] = useState<boolean>(false);
  const [kbModalSelected, setKbModalSelected] =
    useState<string[]>(initialSelectedIds);
  const [kbRawList, setKbRawList] = useState<any[]>([]);

  const currentEmbeddingModel = useMemo(() => {
    return (
      ConfigStore.getInstance().getModelConfig().embedding?.modelName || null
    );
  }, []);

  const isKbSelectable = (kb: KnowledgeBase): boolean => {
    const docCount =
      typeof kb.documentCount === "number" ? kb.documentCount : 0;
    const chunkCount = typeof kb.chunkCount === "number" ? kb.chunkCount : 0;
    const hasContent = docCount + chunkCount > 0;

    const isModelCompatible =
      kb.source !== "nexent" ||
      kb.embeddingModel === "unknown" ||
      kb.embeddingModel === currentEmbeddingModel;

    return hasContent && isModelCompatible;
  };

  useEffect(() => {
    console.log("[KB Modal] isOpen:", isOpen, "toolName:", toolName);
    if (isOpen) {
      console.log("[KB Modal] Calling loadKnowledgeBases...");
      loadKnowledgeBases();
      setKbModalSelected(initialSelectedIds);
    }
  }, [isOpen, initialSelectedIds]);

  const loadKnowledgeBases = async () => {
    console.log("[KB Modal] loadKnowledgeBases started, toolName:", toolName);
    setKbLoading(true);
    try {
      let kbs: any[] = [];

      if (toolName === "datamate_search") {
        console.log("[KB Modal] Loading datamate_search...");
        try {
          const syncResult =
            await knowledgeBaseService.syncDataMateAndCreateRecords();
          console.log("[KB Modal] datamate sync result:", syncResult);
          if (syncResult && syncResult.indices_info) {
            kbs = syncResult.indices_info.map((indexInfo: any) => {
              const stats = indexInfo.stats?.base_info || {};
              const kbId = indexInfo.name;
              const kbName = indexInfo.display_name || indexInfo.name;
              return {
                id: kbId,
                name: kbName,
                description: "DataMate knowledge base",
                documentCount: stats.doc_count || 0,
                chunkCount: stats.chunk_count || 0,
                createdAt: stats.creation_date || null,
                updatedAt: stats.update_date || stats.creation_date || null,
                embeddingModel: stats.embedding_model || "unknown",
                source: "datamate",
              };
            });
          }
        } catch (e) {
          kbs = [];
        }
      } else if (toolName === "dify_search") {
        console.log(
          "[KB Modal] Loading dify_search, difyApiBase:",
          difyApiBase,
          "difyApiKey:",
          difyApiKey ? "***" : "empty"
        );
        // For dify_search, fetch datasets from Dify API using provided credentials
        if (difyApiBase && difyApiKey) {
          console.log("[KB Modal] Calling fetchDifyDatasets...");
          try {
            const difyResult = await knowledgeBaseService.fetchDifyDatasets(
              difyApiBase,
              difyApiKey,
              1,
              100 // Fetch up to 100 datasets for the dropdown
            );
            console.log("[KB Modal] difyResult:", difyResult);
            if (difyResult && difyResult.indices_info) {
              kbs = difyResult.indices_info.map((indexInfo: any) => {
                const stats = indexInfo.stats?.base_info || {};
                const kbId = indexInfo.name;
                const kbName = indexInfo.display_name || indexInfo.name;
                return {
                  id: kbId,
                  name: kbName,
                  description: "Dify knowledge base",
                  documentCount: stats.doc_count || 0,
                  chunkCount: stats.chunk_count || 0,
                  createdAt: stats.creation_date || null,
                  updatedAt: stats.update_date || stats.creation_date || null,
                  embeddingModel: stats.embedding_model || "unknown",
                  source: "dify",
                };
              });
            }
          } catch (e) {
            kbs = [];
          }
        } else {
          kbs = [];
        }
      } else {
        // Default: nexent knowledge bases - 直接调用 API 测试
        console.log("[KB Modal] 直接调用 /api/indices?include_stats=true");
        try {
          const response = await fetch("/api/indices?include_stats=true", {
            headers: {
              Authorization: "Bearer " + (localStorage.getItem("token") || ""),
            },
          });
          console.log("[KB Modal] API response status:", response.status);
          const data = await response.json();
          console.log("[KB Modal] API response data:", data);
          kbs = (data.indices_info || []).map((indexInfo: any) => ({
            id: indexInfo.name,
            name: indexInfo.display_name || indexInfo.name,
            description: "Local knowledge base",
            documentCount: indexInfo.stats?.base_info?.doc_count || 0,
            chunkCount: indexInfo.stats?.base_info?.chunk_count || 0,
            embeddingModel:
              indexInfo.stats?.base_info?.embedding_model || "unknown",
            source: "nexent",
          }));
        } catch (err) {
          console.error("[KB Modal] API Error:", err);
          kbs = [];
        }
      }

      setKbRawList(kbs);
    } catch (e) {
      message.error(
        t("toolConfig.message.kbRefreshFailed", "Failed to refresh KB list")
      );
    } finally {
      setKbLoading(false);
    }
  };

  const handleSave = () => {
    onSave(kbModalSelected);
  };

  return (
    <Modal
      getContainer={() => document.body}
      zIndex={1200}
      open={isOpen}
      // title={t("toolConfig.modal.selectKbTitle", "Select Knowledge Bases")}
      onCancel={onCancel}
      cancelText={t("common.button.cancel")}
      okText={t("common.confirm")}
      onOk={handleSave}
      width={800}
    >
      <div style={{ height: "50vh" }}>
        <KnowledgeBaseList
          knowledgeBases={kbRawList as KnowledgeBase[]}
          selectedIds={kbModalSelected}
          activeKnowledgeBase={null}
          currentEmbeddingModel={currentEmbeddingModel}
          isLoading={kbLoading}
          syncLoading={false}
          onSelect={(id: string) => {
            const exists = kbModalSelected.includes(id);
            const newSelected = exists
              ? kbModalSelected.filter((s) => s !== id)
              : [...kbModalSelected, id];
            setKbModalSelected(newSelected);
          }}
          onClick={() => {}}
          showDataMateConfig={false}
          isSelectable={isKbSelectable}
          getModelDisplayName={(m: string) => m}
          containerHeight="50vh"
        />
      </div>
    </Modal>
  );
}
