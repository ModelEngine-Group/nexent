// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Empty, Spin } from "antd";
import { Bot } from "lucide-react";

import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/date";
import type { A2AExternalAgent } from "@/services/a2aService";
import { ResourceDrawer } from "./ResourceDrawer";
import type { AgentCardItem, SelectedItem } from "./types";
import { useResourceTagFilter } from "@/hooks/useResourceTagFilter";
import { ResourceTagFilterControl } from "./ResourceTagFilterControl";
import { AgentSelectionCard, AgentSelectionGrid } from "./AgentSelectionCard";
import { AuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useResourceTagAssignments } from "@/hooks/useResourceTagAssignments";

import styles from "./ResourcePickerDrawer.module.css";

export { toLocalCard } from "./AgentSelectionCard";

export function toExternalCard(agent: A2AExternalAgent): AgentCardItem {
  return {
    id: String(agent.id),
    agentId: agent.id,
    name: agent.name,
    description: agent.description ?? "",
    updatedAt: agent.create_time ? formatDate(agent.create_time) : undefined,
    version: agent.version,
    tags: [],
  };
}

export interface AgentDrawerCategory {
  key: string;
  label: string;
  items: AgentCardItem[];
  loading?: boolean;
  error?: string;
  icon?: ReactNode;
  supportsTagFilter?: boolean;
}

export interface AgentDrawerProps {
  open: boolean;
  onClose: () => void;
  categories: AgentDrawerCategory[];
  selected: SelectedItem[];
  onConfirm: (selected: SelectedItem[]) => Promise<void> | void;
  onRefresh?: () => void;
  title?: string;
}

/** Categories and stable resource IDs are owned by the caller. */
export function AgentDrawer({
  open,
  onClose,
  categories,
  selected,
  onConfirm,
  onRefresh,
  title,
}: AgentDrawerProps) {
  const { t } = useTranslation("common");
  const authorization = useContext(AuthorizationContext);
  const [activeKey, setActiveKey] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [draft, setDraft] = useState<SelectedItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const sessionOpen = useRef(false);
  const confirming = useRef(false);
  useEffect(() => {
    if (open && !sessionOpen.current) {
      setDraft(selected);
      setActiveKey(categories[0]?.key ?? "");
      setSearch("");
      setPage(1);
      setError(undefined);
    }
    sessionOpen.current = open;
  }, [open, selected, categories]);
  const category =
    categories.find((entry) => entry.key === activeKey) ?? categories[0];
  const items = category?.items ?? [];
  const resourceTags = useResourceTagFilter(
    open && category?.supportsTagFilter !== false,
    "agent",
    items.map((item) => item.tagResourceId ?? String(item.agentId ?? item.id))
  );
  const filtered = items.filter((item) => {
    const keyword = search.trim().toLowerCase();
    return (
      (!keyword ||
        [item.name, item.description, ...(item.tags ?? [])].some((text) =>
          text.toLowerCase().includes(keyword)
        )) &&
      (!resourceTags.matchedIds ||
        category?.supportsTagFilter === false ||
        resourceTags.matchedIds.has(
          item.tagResourceId ?? String(item.agentId ?? item.id)
        ))
    );
  });
  const currentPage = Math.min(
    page,
    Math.max(1, Math.ceil(filtered.length / pageSize))
  );
  const paged = filtered.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize
  );
  const selectedIds = new Set(draft.map((item) => item.id));
  const tagIds = [
    ...new Set(
      paged.flatMap((item) => (item.tagResourceId ? [item.tagResourceId] : []))
    ),
  ];
  const assignments = useResourceTagAssignments(
    "agent",
    open && !category?.loading && !category?.error,
    tagIds,
    resourceTags.revision,
    authorization?.user?.tenantId ?? null
  );
  const allSelected =
    paged.length > 0 && paged.every((item) => selectedIds.has(item.id));
  const partiallySelected =
    !allSelected && paged.some((item) => selectedIds.has(item.id));
  const toggle = (item: AgentCardItem) =>
    setDraft((current) =>
      selectedIds.has(item.id)
        ? current.filter((entry) => entry.id !== item.id)
        : [...current, { id: item.id, label: item.name }]
    );
  const confirm = async () => {
    if (confirming.current) return;
    confirming.current = true;
    setSaving(true);
    setError(undefined);
    try {
      await onConfirm(draft);
      onClose();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : t("resourcePicker.selectionFailed", "选择失败，请重试")
      );
    } finally {
      confirming.current = false;
      setSaving(false);
    }
  };
  return (
    <ResourceDrawer
      width="min(768px, 100vw)"
      bodyClassName={cn(styles.drawer, styles.agent)}
      open={open}
      title={title ?? t("resourcePicker.addAgent", "添加协作智能体")}
      searchPlaceholder={t("agent.collaborative.selector.searchPlaceholder")}
      keyword={search}
      tagFilter={
        category?.supportsTagFilter === false ? null : (
          <ResourceTagFilterControl
            filter={resourceTags}
            onChange={() => setPage(1)}
          />
        )
      }
      selected={draft}
      listTitle={t("resourcePicker.list.agent")}
      tabs={categories.map(({ key, label }) => ({ key, label }))}
      activeTab={category?.key}
      total={filtered.length}
      page={currentPage}
      onPageChange={setPage}
      pageSize={pageSize}
      onPageSizeChange={(size) => {
        setPageSize(size);
        setPage(1);
      }}
      onClose={onClose}
      onConfirm={() => void confirm()}
      confirmLoading={saving}
      confirmDisabled={
        category?.loading ||
        Boolean(category?.error) ||
        resourceTags.filtering ||
        !!(resourceTags.predicates.length && resourceTags.error)
      }
      controlsContent={error ? <Alert type="error" title={error} /> : undefined}
      onRemoveSelected={(id) =>
        setDraft((current) => current.filter((item) => item.id !== id))
      }
      onSearch={(value) => {
        setSearch(value);
        setPage(1);
      }}
      onTabChange={(key) => {
        setActiveKey(key);
        resourceTags.setPredicates([]);
        setPage(1);
      }}
      onSelectAll={(checked) =>
        setDraft((current) =>
          checked
            ? [
                ...current,
                ...paged
                  .filter((item) => !selectedIds.has(item.id))
                  .map((item) => ({ id: item.id, label: item.name })),
              ]
            : current.filter(
                (item) => !paged.some((visible) => visible.id === item.id)
              )
        )
      }
      allSelected={allSelected}
      partiallySelected={partiallySelected}
      onRefresh={
        onRefresh
          ? () => {
              onRefresh();
              if (open && tagIds.length > 0) void assignments.refetch();
            }
          : undefined
      }
    >
      {category?.error ? (
        <Alert type="error" title={category.error} />
      ) : category?.loading ? (
        <div className="flex justify-center py-12">
          <Spin />
        </div>
      ) : filtered.length === 0 ? (
        <Empty description={t("agent.collaborative.selector.empty")} />
      ) : (
        <AgentSelectionGrid>
          {paged.map((item) => (
            <AgentSelectionCard
              key={item.id}
              item={item}
              disabled={saving}
              refreshKey={resourceTags.revision}
              assignments={assignments.data?.[item.tagResourceId ?? ""] ?? []}
              selected={selectedIds.has(item.id)}
              onToggle={() => toggle(item)}
              icon={category?.icon ?? <Bot size={20} />}
            />
          ))}
        </AgentSelectionGrid>
      )}
    </ResourceDrawer>
  );
}
