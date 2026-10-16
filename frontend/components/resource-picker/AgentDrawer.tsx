// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  createElement,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { Alert, Avatar, Empty, Spin } from "antd";
import { Bot, Clock } from "lucide-react";

import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/date";
import {
  getAgentIcon,
  getAgentUploadedIconRevision,
} from "@/lib/chat/agentIconUtils";
import { API_ENDPOINTS } from "@/services/api";
import type { Agent } from "@/types/agentConfig";
import type { A2AExternalAgent } from "@/services/a2aService";
import { ResourceDrawer, CheckMark } from "./ResourceDrawer";
import type { AgentCardItem, SelectedItem } from "./types";
import { useResourceTagFilter } from "@/hooks/useResourceTagFilter";
import { ResourceTagFilterControl } from "./ResourceTagFilterControl";
import { ResourceAssignedTags } from "./ResourceAssignedTags";

import styles from "./ResourcePickerDrawer.module.css";

export function toLocalCard(agent: Agent): AgentCardItem {
  const updatedAt =
    agent.update_time || agent.create_time
      ? formatDate(agent.update_time ?? agent.create_time)
      : undefined;
  return {
    id: String(agent.id),
    agentId: Number(agent.id),
    tagResourceId: String(agent.id),
    iconUrl:
      agent.icon_url?.trim() && Number(agent.id) > 0
        ? API_ENDPOINTS.agent.icon(
            Number(agent.id),
            getAgentUploadedIconRevision(agent.icon_url)
          )
        : undefined,
    name: agent.display_name || agent.name,
    description: agent.description ?? "",
    updatedAt,
    version:
      agent.version_name?.trim() ||
      agent.version_label?.trim() ||
      (agent.current_version_no != null
        ? String(agent.current_version_no)
        : undefined),
    tags: agent.tags ?? [],
  };
}

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

function AgentCard({
  item,
  selected,
  onToggle,
  icon,
  disabled = false,
  refreshKey,
}: {
  item: AgentCardItem;
  selected: boolean;
  onToggle: () => void;
  icon: ReactNode;
  disabled?: boolean;
  refreshKey?: number;
}) {
  const { t } = useTranslation("common");
  const [failedIconSource, setFailedIconSource] = useState<string>();
  const iconSource =
    failedIconSource === item.iconUrl ? undefined : item.iconUrl;
  const agentId = item.agentId ?? Number(item.id);
  const fallbackIcon =
    Number.isInteger(agentId) && agentId >= 0
      ? createElement(getAgentIcon({ agent_id: agentId }), {
          size: 20,
          "aria-hidden": true,
        })
      : icon;
  return (
    <div
      role="option"
      aria-label={item.name}
      aria-selected={selected}
      aria-disabled={disabled}
      tabIndex={disabled ? -1 : 0}
      onClick={() => {
        if (!disabled) onToggle();
      }}
      onKeyDown={(event) => {
        if (
          !disabled &&
          event.target === event.currentTarget &&
          (event.key === "Enter" || event.key === " ")
        ) {
          event.preventDefault();
          onToggle();
        }
      }}
      className={cn(
        styles.agentCard,
        !disabled &&
          "cursor-pointer hover:!shadow-[inset_0_0_0_1px_#0067d1] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
        selected ? styles.agentCardSelected : "bg-white"
      )}
    >
      <div
        className="absolute right-6 top-7"
        onClick={(event) => event.stopPropagation()}
      >
        <CheckMark
          checked={selected}
          disabled={disabled}
          onToggle={onToggle}
          ariaLabel={item.name}
        />
      </div>
      <div className="flex min-h-10 shrink-0 items-start gap-3 pr-6">
        <Avatar
          shape="square"
          size={40}
          src={iconSource}
          onError={() => {
            setFailedIconSource(item.iconUrl);
            return false;
          }}
          icon={fallbackIcon}
          className={cn(
            "shrink-0 !rounded-[8px]",
            iconSource ? "!bg-white" : "!bg-primary/10 !text-primary"
          )}
        />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="min-w-0 truncate text-[16px] font-medium leading-[24px] text-[#191919]">
            {item.name}
          </span>
          {item.version && (
            <span
              className={styles.agentVersion}
              title={`${t("agent.version")}: ${item.version}`}
            >
              {t("agent.version")}: {item.version}
            </span>
          )}
        </div>
      </div>
      <p className="line-clamp-2 h-[42px] shrink-0 text-[12px] font-normal leading-[20px] text-[#777777]">
        {item.description}
      </p>
      {item.tagResourceId && (
        <ResourceAssignedTags
          resourceType="agent"
          resourceId={item.tagResourceId}
          tags={item.tags}
          refreshKey={refreshKey}
        />
      )}
      <div className={styles.agentMetadata}>
        {item.updatedAt && (
          <span className={styles.agentUpdatedAt}>
            <Clock size={14} className="shrink-0" />
            {t("agentConfig.list.updatedAt", { date: item.updatedAt })}
          </span>
        )}
      </div>
    </div>
  );
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
      onRefresh={onRefresh}
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
        <div
          role="listbox"
          aria-multiselectable="true"
          className={styles.agentGrid}
        >
          {paged.map((item) => (
            <AgentCard
              key={item.id}
              item={item}
              disabled={saving}
              refreshKey={resourceTags.revision}
              selected={selectedIds.has(item.id)}
              onToggle={() => toggle(item)}
              icon={category?.icon ?? <Bot size={20} />}
            />
          ))}
        </div>
      )}
    </ResourceDrawer>
  );
}
