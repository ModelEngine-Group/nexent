"use client";

import { useEffect, useMemo, useState } from "react";
import { Bot, Clock } from "lucide-react";
import { Empty, Spin } from "antd";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { useExternalAgents } from "@/hooks/agent/useExternalAgents";
import { formatDate } from "@/lib/date";
import type { Agent } from "@/types/agentConfig";
import type { A2AExternalAgent } from "@/services/a2aService";
import { AddResourceDrawer, CheckMark } from "./AddResourceDrawer";
import type { AgentCardItem, SelectedItem } from "./types";

const PAGE_SIZE = 10;

const ICON_BG_PALETTE = [
  "#8B7BF6",
  "#5B8DEF",
  "#7B5BF2",
  "#3B82F6",
  "#2E5BFF",
  "#4D6BFE",
];

function iconColorFor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  }
  return ICON_BG_PALETTE[hash % ICON_BG_PALETTE.length];
}

function toLocalCard(agent: Agent): AgentCardItem {
  return {
    id: String(agent.id),
    name: agent.display_name || agent.name,
    description: agent.description ?? "",
    iconBg: iconColorFor(String(agent.id)),
    updatedAt: formatDate(agent.update_time ?? agent.create_time),
    online: agent.is_available !== false,
    tags: agent.tags ?? [],
  };
}

function toExternalCard(agent: A2AExternalAgent): AgentCardItem {
  return {
    id: String(agent.id),
    name: agent.name,
    description: agent.description ?? "",
    iconBg: iconColorFor(String(agent.id)),
    updatedAt: formatDate(agent.create_time),
    online: agent.is_available !== false,
    tags: [],
  };
}

function AgentCard({
  item,
  selected,
  onToggle,
}: {
  item: AgentCardItem;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className={cn(
        "relative flex h-[149px] flex-col gap-1.5 rounded-[8px] border p-3",
        selected ? "border-[#7EB6F0] bg-[#E6F2FD]" : "border-[#D9D9D9] bg-white"
      )}
    >
      <div className="absolute right-3 top-3">
        <CheckMark checked={selected} onToggle={onToggle} />
      </div>
      <div className="flex items-center gap-2.5">
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[8px] text-white"
          style={{ background: item.iconBg }}
        >
          <Bot size={20} />
        </div>
        <span className="text-[14px] font-medium leading-[22px] text-[#191919]">
          {item.name}
        </span>
      </div>
      <p className="line-clamp-2 text-[14px] leading-[20px] text-[#737373]">
        {item.description}
      </p>
      <div className="mt-auto flex items-center gap-3.5 text-[12px] leading-[18px] text-[#999]">
        {item.updatedAt && (
          <span className="flex items-center gap-1">
            <Clock size={14} />
            更新于 {item.updatedAt}
          </span>
        )}
        <span className="flex items-center gap-1">
          <span
            className={cn(
              "size-1.5 rounded-full",
              item.online ? "bg-[#52C41A]" : "bg-[#D9D9D9]"
            )}
          />
          {item.online ? "已上线" : "未上线"}
        </span>
      </div>
    </div>
  );
}

export interface AddAgentDrawerProps {
  open: boolean;
  onClose: () => void;
  onConfirm?: (selected: AgentCardItem[]) => void;
}

export function AddAgentDrawer({ open, onClose, onConfirm }: AddAgentDrawerProps) {
  const { t } = useTranslation("common");
  const {
    availableAgents: localAgents,
    isLoading: isLocalLoading,
    refetch: refetchLocal,
  } = usePublishedAgentList();
  const {
    availableAgents: externalAgents,
    isLoading: isExternalLoading,
    refetch: refetchExternal,
  } = useExternalAgents();

  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [tab, setTab] = useState("local");
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [tagFilter, setTagFilter] = useState("");

  const localCards = useMemo(() => localAgents.map(toLocalCard), [localAgents]);
  const externalCards = useMemo(() => externalAgents.map(toExternalCard), [externalAgents]);

  const allCards = useMemo(() => [...localCards, ...externalCards], [
    localCards,
    externalCards,
  ]);

  const tagOptions = useMemo(() => {
    const tags = new Set<string>();
    localAgents.forEach((agent) =>
      (agent.tags ?? []).forEach((tag) => tags.add(tag))
    );
    return Array.from(tags)
      .sort()
      .map((value) => ({ value, label: value }));
  }, [localAgents]);

  const filterCards = (cards: AgentCardItem[]): AgentCardItem[] => {
    let filtered = cards;
    const kw = keyword.trim().toLowerCase();
    if (kw) {
      filtered = filtered.filter(
        (item) =>
          item.name.toLowerCase().includes(kw) ||
          item.description.toLowerCase().includes(kw)
      );
    }
    if (tagFilter) {
      filtered = filtered.filter((item) => (item.tags ?? []).includes(tagFilter));
    }
    return filtered;
  };

  // Reset to the first page whenever the search, tag or tab changes.
  useEffect(() => {
    setPage(1);
  }, [keyword, tagFilter, tab]);

  const filteredAgents = filterCards(tab === "local" ? localCards : externalCards);
  const agents = filteredAgents.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const isLoading = tab === "local" ? isLocalLoading : isExternalLoading;

  const selected: SelectedItem[] = useMemo(
    () =>
      allCards
        .filter((item) => selectedIds.has(item.id))
        .map((item) => ({ id: item.id, label: item.name })),
    [allCards, selectedIds]
  );

  const allSelected =
    filteredAgents.length > 0 && filteredAgents.every((a) => selectedIds.has(a.id));

  const toggle = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleRefresh = () => {
    void refetchLocal();
    void refetchExternal();
  };

  return (
    <AddResourceDrawer
      open={open}
      title={t("resourcePicker.addAgent", "添加子智能体")}
      searchPlaceholder={t("resourcePicker.search.agent", "按名称、描述检索")}
      selected={selected}
      tagOptions={tab === "local" ? tagOptions : undefined}
      listTitle={t("resourcePicker.list.agent", "智能体列表")}
      tabs={[
        { key: "local", label: t("resourcePicker.tab.localAgent", "本地智能体") },
        { key: "external", label: t("resourcePicker.tab.externalAgent", "外部智能体") },
      ]}
      activeTab={tab}
      total={filteredAgents.length}
      page={page}
      onPageChange={setPage}
      showConfirm
      onClose={onClose}
      onConfirm={() => onConfirm?.(allCards.filter((a) => selectedIds.has(a.id)))}
      onRemoveSelected={(id) => toggle(id)}
      onSearch={setKeyword}
      onTagChange={(value) => setTagFilter(value ?? "")}
      onTabChange={setTab}
      onSelectAll={(checked) =>
        setSelectedIds(new Set(checked ? filteredAgents.map((a) => a.id) : []))
      }
      allSelected={allSelected}
      onRefresh={handleRefresh}
    >
      {isLoading ? (
        <div className="flex justify-center py-12">
          <Spin />
        </div>
      ) : agents.length === 0 ? (
        <Empty description={t("resourcePicker.empty", "暂无数据")} />
      ) : (
        <div className="grid grid-cols-2 content-start gap-2">
          {agents.map((item) => (
            <AgentCard
              key={item.id}
              item={item}
              selected={selectedIds.has(item.id)}
              onToggle={() => toggle(item.id)}
            />
          ))}
        </div>
      )}
    </AddResourceDrawer>
  );
}