"use client";

/**
 * KnowledgeBaseTabs — Controlled tab + adapter-selector component.
 *
 * This is a PURE controlled component: it owns no state of its own.
 * The parent drives `activeTab`, `activeAdapterId`, and the adapter list;
 * this component only renders and fires `onTabChange` / `onSelectAdapter`
 * callbacks. It does NOT fetch data or call any service.
 *
 * Layout:
 *   - Top row: 3 tabs (All / Local / External) with badge counts.
 *   - Below the tabs (Local or External only): a Segmented control that
 *     lists the adapters of that category, so the user can pick one.
 *   - Empty states are shown when a category has zero adapters.
 */

import React, { useMemo } from "react";
import { Badge, Empty, Segmented, Tabs } from "antd";
import type { TabsProps } from "antd";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/** Platform discriminator for a knowledge-base adapter. */
export type AdapterPlatform =
  | "local"
  | "dify"
  | "aidp"
  | "datamate"
  | "haotian"
  | "custom";

/** Lifecycle status of an adapter. */
export type AdapterStatus = "running" | "error" | "stopped" | "placeholder";

/** Minimal adapter shape this component needs from the parent. */
export interface AdapterSummary {
  adapter_id: number;
  platform: AdapterPlatform;
  name: string;
  status: AdapterStatus;
}

/** Tab keys exposed by this component. */
export type TabKey = "all" | "local" | "external";

/** Props for {@link KnowledgeBaseTabs}. */
export interface KnowledgeBaseTabsProps {
  /** Full adapter list — the component filters it into local / external. */
  adapters: AdapterSummary[];
  /** Currently active tab, controlled by the parent. */
  activeTab: TabKey;
  /** Currently selected adapter id, or `null` when nothing is selected. */
  activeAdapterId: number | null;
  /** Fired when the user picks an adapter from the Segmented control. */
  onSelectAdapter: (adapterId: number) => void;
  /** Fired when the user switches between All / Local / External tabs. */
  onTabChange: (tab: TabKey) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Local type for Segmented options (antd does not export this type). */
type SegmentedOptionItem = {
  label: string;
  value: number | string;
  disabled?: boolean;
};

/**
 * Build Segmented options from an adapter list.
 * Non-running adapters are disabled so the user cannot select them.
 */
function buildSegmentedOptions(adapters: AdapterSummary[]): SegmentedOptionItem[] {
  return adapters.map((adapter) => ({
    label: `${adapter.name} (${adapter.platform})`,
    value: adapter.adapter_id,
    disabled: adapter.status !== "running",
  }));
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const KnowledgeBaseTabs: React.FC<KnowledgeBaseTabsProps> = ({
  adapters,
  activeTab,
  activeAdapterId,
  onSelectAdapter,
  onTabChange,
}) => {
  // Split adapters into local vs. external — memoised to avoid recomputation
  // on every render when the `adapters` reference is stable.
  const localAdapters = useMemo(
    () => adapters.filter((adapter) => adapter.platform === "local"),
    [adapters],
  );

  const externalAdapters = useMemo(
    () => adapters.filter((adapter) => adapter.platform !== "local"),
    [adapters],
  );

  const localAdapterOptions = useMemo(
    () => buildSegmentedOptions(localAdapters),
    [localAdapters],
  );

  const externalAdapterOptions = useMemo(
    () => buildSegmentedOptions(externalAdapters),
    [externalAdapters],
  );

  // --- Tab items ---------------------------------------------------------
  const tabItems: TabsProps["items"] = useMemo(
    () => [
      {
        key: "all",
        label: (
          <span>
            所有知识库 <Badge count={adapters.length} />
          </span>
        ),
      },
      {
        key: "local",
        label: (
          <span>
            本地知识库 <Badge count={localAdapters.length} />
          </span>
        ),
      },
      {
        key: "external",
        label: (
          <span>
            外部知识库 <Badge count={externalAdapters.length} />
          </span>
        ),
      },
    ],
    [adapters.length, localAdapters.length, externalAdapters.length],
  );

  // --- Render ------------------------------------------------------------

  // Global empty state: nothing to show at all.
  if (adapters.length === 0) {
    return <Empty description="暂无知识库适配器" />;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Top tabs */}
      <Tabs
        activeKey={activeTab}
        onChange={(key) => onTabChange(key as TabKey)}
        items={tabItems}
      />

      {/* Adapter Segmented control — only inside Local / External tabs */}
      {activeTab === "local" && (
        <>
          {localAdapters.length === 0 ? (
            <Empty description="暂无本地知识库适配器" />
          ) : (
            <Segmented
              options={localAdapterOptions}
              value={activeAdapterId}
              onChange={(value) => onSelectAdapter(value as number)}
            />
          )}
        </>
      )}

      {activeTab === "external" && (
        <>
          {externalAdapters.length === 0 ? (
            <Empty description="暂无外部适配器" />
          ) : (
            <Segmented
              options={externalAdapterOptions}
              value={activeAdapterId}
              onChange={(value) => onSelectAdapter(value as number)}
            />
          )}
        </>
      )}
    </div>
  );
};

export default KnowledgeBaseTabs;
