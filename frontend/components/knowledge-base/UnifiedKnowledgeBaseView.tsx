"use client";

/**
 * UnifiedKnowledgeBaseView — Phase 3 Container Component
 *
 * Top-level container that orchestrates all knowledge-base UI state and
 * integrates five child components: KnowledgeBaseTabs, KnowledgeBaseGrid,
 * CreateKBModal, KBDetailDrawer, and AdapterRegistrationModal.
 *
 * Responsibilities:
 * - Manage all UI state (active tab, selected adapter, modals, search)
 * - Fetch adapters and knowledge bases via react-query
 * - Wire callbacks between child components
 * - Provide unified error handling with antd message notifications
 * - Render the page layout: header + search + tabs + grid + modals/drawers
 */

import React, { useState, useEffect, useCallback } from "react";
import { Button, Input, Space, Typography, message } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import unifiedKbManager from "@/services/unifiedKnowledgeBaseService";
import type { AdapterInfo, KbSummary } from "@/types/unifiedKnowledgeBase";
import type { AdapterSummary, TabKey } from "./KnowledgeBaseTabs";
import KnowledgeBaseTabs from "./KnowledgeBaseTabs";
import KnowledgeBaseGrid from "./KnowledgeBaseGrid";
import type { KnowledgeBaseItem } from "./KnowledgeBaseGrid";
import CreateKBModal from "./CreateKBModal";
import KBDetailDrawer from "./KBDetailDrawer";
import AdapterRegistrationModal from "./AdapterRegistrationModal";

const { Title } = Typography;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Props for the UnifiedKnowledgeBaseView container component. */
export interface UnifiedKnowledgeBaseViewProps {
  /** Whether to show the "注册外部适配器" button. Defaults to true. */
  showRegisterButton?: boolean;
  /** Initial active tab. Defaults to 'all'. */
  defaultTab?: "all" | "local" | "external";
  /** Optional callback fired when a KB is selected or deselected. */
  onKbSelect?: (kb: KbSummary | null) => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const QUERY_KEY = ["unified-kb"] as const;

const headerStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
};

const searchStyle: React.CSSProperties = { maxWidth: 400 };

const gridWrapperStyle: React.CSSProperties = { marginTop: 16 };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Convert a KbSummary (from the service layer) to the KnowledgeBaseItem
 * shape expected by the KnowledgeBaseGrid presentational component.
 */
function toGridItem(kb: KbSummary): KnowledgeBaseItem {
  return {
    kb_id: kb.id,
    adapter_id: kb.adapter_id,
    adapter_platform: kb.adapter_platform,
    name: kb.name,
    description: kb.description,
    document_count: kb.document_count,
    chunk_count: kb.chunk_count,
    embedding_model: kb.embedding_model,
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Container component that manages all knowledge-base UI state and
 * integrates tabs, grid, create modal, detail drawer, and adapter
 * registration modal into a single cohesive view.
 */
const UnifiedKnowledgeBaseView: React.FC<UnifiedKnowledgeBaseViewProps> = ({
  showRegisterButton = true,
  defaultTab = "all",
  onKbSelect,
}) => {
  const queryClient = useQueryClient();

  // =========================================================================
  // UI State
  // =========================================================================

  const [activeAdapterId, setActiveAdapterId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>(defaultTab);
  const [keyword, setKeyword] = useState("");

  // Create KB modal
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [createModalDefaultAdapterId, setCreateModalDefaultAdapterId] =
    useState<number | null>(null);

  // Detail drawer — driven by selectedKbId presence (null = closed)
  const [selectedKbId, setSelectedKbId] = useState<string | null>(null);
  const [selectedAdapterId, setSelectedAdapterId] = useState<number | null>(
    null,
  );

  // Adapter registration modal
  const [isRegModalOpen, setIsRegModalOpen] = useState(false);

  // =========================================================================
  // Data Fetching
  // =========================================================================

  /** Fetch all enabled adapters. */
  const adaptersQuery = useQuery({
    queryKey: [...QUERY_KEY, "adapters"],
    queryFn: () => unifiedKbManager.listAllAdapters(),
  });

  /**
   * Fetch knowledge bases — scope depends on active tab:
   * - 'all': aggregate from every enabled adapter
   * - 'local' / 'external': scoped to the selected adapter
   *
   * Returns a unified shape: { kbs: KbSummary[], total: number }
   */
  const kbsQuery = useQuery<{ kbs: KbSummary[]; total: number }, Error>({
    queryKey: [...QUERY_KEY, "kbs-in-adapter", activeAdapterId, activeTab, keyword],
    queryFn: async () => {
      if (activeTab === "all") {
        const kbs = await unifiedKbManager.listAllKbs({ keyword });
        return { kbs, total: kbs.length };
      }
      const result = await unifiedKbManager.listKbsInAdapter(activeAdapterId!, { keyword });
      return { kbs: result.kbs, total: result.total };
    },
    enabled: !!activeAdapterId || activeTab === "all",
  });

  // =========================================================================
  // Side Effects
  // =========================================================================

  /**
   * Auto-select a default adapter once the adapter list loads.
   * Prefers the 'local' platform adapter; falls back to the first adapter.
   */
  useEffect(() => {
    if (adaptersQuery.data && activeAdapterId === null) {
      const localAdapter = adaptersQuery.data.find(
        (a) => a.platform === "local",
      );
      if (localAdapter) {
        setActiveAdapterId(localAdapter.adapter_id);
      } else if (adaptersQuery.data.length > 0) {
        setActiveAdapterId(adaptersQuery.data[0].adapter_id);
      }
    }
  }, [adaptersQuery.data, activeAdapterId]);

  // =========================================================================
  // Event Handlers
  // =========================================================================

  /** Switch between All / Local / External tabs. */
  const handleTabChange = useCallback(
    (tab: TabKey) => {
      setActiveTab(tab);
      if (tab === "all") {
        setActiveAdapterId(null);
        return;
      }
      // Switch to the first adapter of the selected category
      const adaptersOfType = adaptersQuery.data?.filter((a) =>
        tab === "local" ? a.platform === "local" : a.platform !== "local",
      );
      if (adaptersOfType && adaptersOfType.length > 0) {
        setActiveAdapterId(adaptersOfType[0].adapter_id);
      }
    },
    [adaptersQuery.data],
  );

  /** Select a specific adapter from the Segmented control. */
  const handleAdapterSelect = useCallback((adapterId: number) => {
    setActiveAdapterId(adapterId);
  }, []);

  /** Open the detail drawer for a clicked KB. */
  const handleKbClick = useCallback(
    (kbId: string, adapterId: number) => {
      setSelectedKbId(kbId);
      setSelectedAdapterId(adapterId);
      // Notify parent about the selection
      const kb = kbsQuery.data?.kbs.find((k: KbSummary) => k.id === kbId) ?? null;
      onKbSelect?.(kb);
    },
    [kbsQuery.data, onKbSelect],
  );

  /** Delete a KB and refresh all queries on success. */
  const handleKbDelete = useCallback(
    async (kbId: string, adapterId: number) => {
      try {
        await unifiedKbManager.deleteKb(adapterId, kbId);
        message.success("KB 删除成功");
        queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      } catch (err) {
        message.error("KB 删除失败：" + (err as Error).message);
      }
    },
    [queryClient],
  );

  /** Open the create-KB modal, optionally pre-selecting an adapter. */
  const handleCreateClick = useCallback((adapterId?: number) => {
    setCreateModalDefaultAdapterId(adapterId ?? null);
    setIsCreateModalOpen(true);
  }, []);

  /** Handle successful KB creation — refresh queries and close modal. */
  const handleCreated = useCallback(() => {
    message.success("KB 创建成功");
    queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    setIsCreateModalOpen(false);
  }, [queryClient]);

  /** Close the detail drawer and clear selection. */
  const handleDetailClose = useCallback(() => {
    setSelectedKbId(null);
    setSelectedAdapterId(null);
    onKbSelect?.(null);
  }, [onKbSelect]);

  /** Refresh queries after the detail drawer updates (doc upload/delete). */
  const handleDetailUpdated = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: QUERY_KEY });
  }, [queryClient]);

  /** Open the adapter registration modal. */
  const handleRegAdapter = useCallback(() => {
    setIsRegModalOpen(true);
  }, []);

  /** Handle successful adapter registration — refresh queries and close. */
  const handleRegistered = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    setIsRegModalOpen(false);
  }, [queryClient]);

  /** Update the search keyword (drives the kbsQuery refetch). */
  const handleSearch = useCallback((value: string) => {
    setKeyword(value);
  }, []);

  // =========================================================================
  // Derived Data
  // =========================================================================

  /** Adapt AdapterInfo[] to the AdapterSummary[] shape for the tabs component. */
  const adapterSummaries: AdapterSummary[] =
    adaptersQuery.data?.map((a: AdapterInfo) => ({
      adapter_id: a.adapter_id,
      platform: a.platform,
      name: a.name,
      status: a.status,
    })) ?? [];

  /** Convert KbSummary[] to KnowledgeBaseItem[] for the grid component. */
  const gridItems: KnowledgeBaseItem[] =
    (kbsQuery.data?.kbs ?? []).map(toGridItem);

  // =========================================================================
  // Render
  // =========================================================================

  return (
    <div>
      {/* Header */}
      <Space direction="vertical" style={{ width: "100%" }} size="large">
        <div style={headerStyle}>
          <Title level={2}>知识库管理</Title>
          {showRegisterButton && (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleRegAdapter}
            >
              注册外部适配器
            </Button>
          )}
        </div>

        {/* Search bar */}
        <Input.Search
          placeholder="搜索知识库名称..."
          value={keyword}
          onChange={(e) => handleSearch(e.target.value)}
          onSearch={handleSearch}
          allowClear
          style={searchStyle}
        />
      </Space>

      {/* Tabs + adapter selector */}
      <KnowledgeBaseTabs
        adapters={adapterSummaries}
        activeTab={activeTab}
        activeAdapterId={activeAdapterId}
        onSelectAdapter={handleAdapterSelect}
        onTabChange={handleTabChange}
      />

      {/* KB grid */}
      <div style={gridWrapperStyle}>
        <KnowledgeBaseGrid
          kbs={gridItems}
          loading={kbsQuery.isLoading}
          showCreateButton={activeTab !== "all"}
          onCreateClick={() =>
            handleCreateClick(activeAdapterId ?? undefined)
          }
          onKbClick={handleKbClick}
          onKbDelete={handleKbDelete}
        />
      </div>

      {/* Create KB modal */}
      <CreateKBModal
        visible={isCreateModalOpen}
        onCancel={() => setIsCreateModalOpen(false)}
        onCreated={() => handleCreated()}
        adapters={adaptersQuery.data ?? []}
      />

      {/* KB detail drawer */}
      <KBDetailDrawer
        visible={selectedKbId !== null}
        kbId={selectedKbId}
        adapterId={selectedAdapterId}
        onUpdated={handleDetailUpdated}
        onClosed={handleDetailClose}
      />

      {/* Adapter registration modal */}
      <AdapterRegistrationModal
        visible={isRegModalOpen}
        onCancel={() => setIsRegModalOpen(false)}
        onRegistered={() => handleRegistered()}
      />
    </div>
  );
};

export default UnifiedKnowledgeBaseView;
