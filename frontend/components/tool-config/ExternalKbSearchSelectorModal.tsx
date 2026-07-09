"use client";

/**
 * ExternalKbSearchSelectorModal — P3-A: cross-adapter KB selector.
 *
 * Used by ToolConfigModal when configuring an `ExternalKnowledgeSearchTool`
 * (tool name === "external_kb_search"). Lets the user:
 *   1. Pick 1+ adapters (local and/or external) — top section.
 *   2. Within each selected adapter, pick 1+ KBs — grouped per adapter below.
 *
 * Outputs: array of KbRef-like objects written into the tool's `kb_refs`
 * param, shape:
 *   [{ adapter_id: number, kb_id: string, display_name: string }]
 *
 * The backend accepts this as JSON-stringified under `params.kb_refs`
 * (create_agent_info.py has a backward-compat path for the older
 * {adapter_id, kb_ids, kb_display_names} schema too — see
 * P2-frontend-migration-plan.md §13 for Approach C context).
 */

import React, { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Empty,
  Input,
  Modal,
  Space,
  Spin,
  Tag,
  Tooltip,
} from "antd";
import {
  ApiOutlined,
  DatabaseOutlined,
  SearchOutlined,
} from "@ant-design/icons";

import {
  useKbAdapters,
  useKbsForAdapter,
} from "@/hooks/useKnowledgeBaseSelector";
import { KnowledgeBase } from "@/types/knowledgeBase";
import { UnifiedAdapter } from "@/types/unifiedKB";
import log from "@/lib/logger";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ExternalKbRef {
  adapter_id: number;
  kb_id: string;
  display_name: string;
}

interface ExternalKbSearchSelectorModalProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (refs: ExternalKbRef[]) => void;
  // Initial refs (when re-opening the modal for an existing tool config)
  initialRefs?: ExternalKbRef[];
  maxRefs?: number;
  title?: string;
}

// Per-adapter selection bundle built at render time.
interface PerAdapterState {
  adapter: UnifiedAdapter;
  kbs: KnowledgeBase[];
  isLoadingKbs: boolean;
  selectedKbIds: string[];
}

// ---------------------------------------------------------------------------
// Helper: per-adapter KB loader (uses react-query via the hook above)
// ---------------------------------------------------------------------------

/**
 * Component that watches a single adapter and renders its KB list + selection UX.
 * Pulls data via `useKbsForAdapter` so React Query handles caching/loading state.
 */
function AdapterKbSection({
  adapter,
  selectedKbIds,
  onToggleKb,
  searchFilter,
}: {
  adapter: UnifiedAdapter;
  selectedKbIds: string[];
  onToggleKb: (adapterId: number, kbId: string) => void;
  searchFilter: string;
}) {
  const { t } = useTranslation();
  const { data: kbs = [], isLoading } = useKbsForAdapter(adapter.adapter_id);

  const filtered = useMemo(() => {
    if (!searchFilter.trim()) return kbs;
    const kw = searchFilter.trim().toLowerCase();
    return kbs.filter(
      (kb) =>
        kb.name.toLowerCase().includes(kw) ||
        (kb.description || "").toLowerCase().includes(kw)
    );
  }, [kbs, searchFilter]);

  const icon =
    adapter.platform === "local" ? <DatabaseOutlined /> : <ApiOutlined />;
  const tagColor = adapter.platform === "local" ? "blue" : "purple";

  return (
    <Card
      size="small"
      style={{ marginBottom: 8 }}
      title={
        <Space size={6}>
          <span style={{ color: "#888" }}>{icon}</span>
          <span>{adapter.name}</span>
          <Tag color={tagColor}>{adapter.platform}</Tag>
          <span style={{ color: "#999", fontSize: 12 }}>
            {t("kb.external.selectedKbs", {
              count: selectedKbIds.length,
              defaultValue: "{{count}} selected",
            })}
          </span>
        </Space>
      }
    >
      <Spin spinning={isLoading}>
        {filtered.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              isLoading
                ? undefined
                : searchFilter.trim()
                ? t("kb.external.noKbsMatch", "No knowledge bases match the filter.")
                : t("kb.external.noKbs", "No knowledge bases in this adapter.")
            }
          />
        ) : (
          <div
            style={{
              maxHeight: 220,
              overflowY: "auto",
              border: "1px solid #f0f0f0",
              borderRadius: 4,
              padding: 2,
            }}
          >
            {filtered.map((kb) => {
              const checked = selectedKbIds.includes(kb.id);
              return (
                <div
                  key={kb.id}
                  onClick={() => onToggleKb(adapter.adapter_id, kb.id)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "6px 8px",
                    cursor: "pointer",
                    borderRadius: 4,
                    background: checked ? "#e6f4ff" : "transparent",
                  }}
                >
                  <Checkbox checked={checked} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        fontWeight: 500,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                      title={kb.name}
                    >
                      {kb.name}
                    </div>
                    {kb.description && (
                      <div
                        style={{ fontSize: 12, color: "#888" }}
                        title={kb.description}
                      >
                        {kb.description}
                      </div>
                    )}
                  </div>
                  {kb.documentCount != null && kb.documentCount > 0 && (
                    <Tooltip
                      title={t("kb.external.documentCount", {
                        defaultValue: "{{count}} documents",
                        count: kb.documentCount,
                      })}
                    >
                      <span style={{ fontSize: 12, color: "#999" }}>
                        {kb.documentCount}
                      </span>
                    </Tooltip>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Spin>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main modal component
// ---------------------------------------------------------------------------

export default function ExternalKbSearchSelectorModal({
  open,
  onClose,
  onConfirm,
  initialRefs = [],
  maxRefs = 20,
  title,
}: ExternalKbSearchSelectorModalProps) {
  const { t } = useTranslation();

  // Adapter list (React Query cached)
  const { data: adapters = [], isLoading: adaptersLoading } = useKbAdapters();

  // Local state (reset when modal opens)
  const [selectedAdapterIds, setSelectedAdapterIds] = useState<number[]>([]);
  const [perAdapter, setPerAdapter] = useState<
    Record<number, { selectedKbIds: string[] }>
  >({});
  const [search, setSearch] = useState("");

  // Reset state when modal opens / initialRefs change
  useEffect(() => {
    if (!open) return;
    const adapterIdsSet = new Set<number>(
      initialRefs.map((r) => r.adapter_id).filter((id) => typeof id === "number")
    );
    setSelectedAdapterIds(Array.from(adapterIdsSet));

    const next: Record<number, { selectedKbIds: string[] }> = {};
    for (const r of initialRefs) {
      if (typeof r.adapter_id !== "number") continue;
      if (!next[r.adapter_id]) next[r.adapter_id] = { selectedKbIds: [] };
      if (r.kb_id && !next[r.adapter_id].selectedKbIds.includes(r.kb_id)) {
        next[r.adapter_id].selectedKbIds.push(r.kb_id);
      }
    }
    setPerAdapter(next);
    setSearch("");
  }, [open, initialRefs]);

  // Build the flat list of refs the user has currently chosen (used for count + confirm)
  const currentRefs: ExternalKbRef[] = useMemo(() => {
    const out: ExternalKbRef[] = [];
    for (const adapterId of selectedAdapterIds) {
      const adapter = adapters.find((a) => a.adapter_id === adapterId);
      if (!adapter) continue;
      const sel = perAdapter[adapterId]?.selectedKbIds ?? [];
      for (const kbId of sel) {
        out.push({
          adapter_id: adapterId,
          kb_id: kbId,
          display_name: kbId, // fallback — may be enriched by parent on confirm
        });
      }
    }
    return out;
  }, [selectedAdapterIds, perAdapter, adapters]);

  // Toggle adapter checkbox
  const toggleAdapter = (adapterId: number) => {
    setSelectedAdapterIds((prev) => {
      if (prev.includes(adapterId)) {
        return prev.filter((id) => id !== adapterId);
      }
      return [...prev, adapterId];
    });
  };

  // Toggle KB within an adapter (respects maxRefs ceiling)
  const toggleKb = (adapterId: number, kbId: string) => {
    setPerAdapter((prev) => {
      const prevForAdapter = prev[adapterId]?.selectedKbIds ?? [];
      const nextForAdapter = prevForAdapter.includes(kbId)
        ? prevForAdapter.filter((id) => id !== kbId)
        : prevForAdapter.length >= maxRefs
        ? prevForAdapter
        : [...prevForAdapter, kbId];
      return { ...prev, [adapterId]: { selectedKbIds: nextForAdapter } };
    });
  };

  // Confirm: enrich refs with display names from parent-known KB data
  const handleConfirm = () => {
    if (currentRefs.length === 0) return;
    onConfirm(currentRefs);
    onClose();
  };

  const clearAll = () => {
    setSelectedAdapterIds([]);
    setPerAdapter({});
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      onOk={handleConfirm}
      okButtonProps={{ disabled: currentRefs.length === 0 }}
      title={title ?? t("kb.external.title", "Select Knowledge Bases (cross-adapter)")}
      okText={t("common.confirm", "Confirm")}
      cancelText={t("common.cancel", "Cancel")}
      width={840}
      destroyOnClose
    >
      <Space style={{ width: "100%" }} direction="vertical" size="middle">
        <Alert
          type="info"
          showIcon
          message={t(
            "kb.external.helper",
            "Pick one or more adapters, then pick knowledge bases within each. Results from selected KBs will be merged at search time."
          )}
        />

        {/* --- Adapter picker (top section) --- */}
        <div>
          <div
            style={{
              fontWeight: 500,
              marginBottom: 6,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span>
              {t("kb.external.pickAdapters", "Step 1: pick adapters")}
            </span>
            <span style={{ fontSize: 12, color: "#666" }}>
              {t("kb.external.adapterCount", {
                count: selectedAdapterIds.length,
                defaultValue: "{{count}} adapter(s) selected",
              })}
            </span>
          </div>
          <Spin spinning={adaptersLoading}>
            {adapters.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t(
                  "kb.external.noAdapters",
                  "No adapters registered. Register one from Knowledge Base Management first."
                )}
              />
            ) : (
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 8,
                  padding: 8,
                  border: "1px solid #f0f0f0",
                  borderRadius: 6,
                }}
              >
                {adapters.map((adapter) => {
                  const checked = selectedAdapterIds.includes(
                    adapter.adapter_id
                  );
                  const icon =
                    adapter.platform === "local" ? (
                      <DatabaseOutlined />
                    ) : (
                      <ApiOutlined />
                    );
                  const tagColor =
                    adapter.platform === "local" ? "blue" : "purple";
                  return (
                    <div
                      key={adapter.adapter_id}
                      onClick={() => toggleAdapter(adapter.adapter_id)}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "6px 10px",
                        border: `1px solid ${
                          checked ? "#1677ff" : "#d9d9d9"
                        }`,
                        borderRadius: 4,
                        cursor: "pointer",
                        background: checked ? "#e6f4ff" : "white",
                      }}
                    >
                      <Checkbox checked={checked} />
                      <span style={{ color: "#888" }}>{icon}</span>
                      <span>{adapter.name}</span>
                      <Tag color={tagColor} style={{ margin: 0 }}>
                        {adapter.platform}
                      </Tag>
                    </div>
                  );
                })}
              </div>
            )}
          </Spin>
        </div>

        {/* --- Per-adapter KB lists (bottom section) --- */}
        <div>
          <div
            style={{
              fontWeight: 500,
              marginBottom: 6,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span>
              {t("kb.external.pickKbs", "Step 2: pick knowledge bases")}
            </span>
            <Space>
              <Input
                prefix={<SearchOutlined />}
                allowClear
                placeholder={t("common.search", "Search")}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{ width: 200 }}
                size="small"
                disabled={selectedAdapterIds.length === 0}
              />
              <span style={{ fontSize: 12, color: "#666" }}>
                {t("kb.external.totalRefCount", {
                  count: currentRefs.length,
                  defaultValue: "{{count}} KB(s) selected",
                })}
              </span>
            </Space>
          </div>

          {selectedAdapterIds.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t(
                "kb.external.pickAdapterFirst",
                "Pick at least one adapter above to see its knowledge bases."
              )}
            />
          ) : (
            <div
              style={{
                maxHeight: 420,
                overflowY: "auto",
                padding: 2,
              }}
            >
              {selectedAdapterIds.map((adapterId) => {
                const adapter = adapters.find(
                  (a) => a.adapter_id === adapterId
                );
                if (!adapter) return null;
                return (
                  <AdapterKbSection
                    key={adapterId}
                    adapter={adapter}
                    selectedKbIds={
                      perAdapter[adapterId]?.selectedKbIds ?? []
                    }
                    onToggleKb={toggleKb}
                    searchFilter={search}
                  />
                );
              })}
            </div>
          )}
        </div>

        {/* --- Footer --- */}
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <Button
            size="small"
            disabled={currentRefs.length === 0}
            onClick={clearAll}
          >
            {t("common.clear", "Clear")}
          </Button>
        </div>
      </Space>
    </Modal>
  );
}
