"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { App, Empty, Spin } from "antd";
import { Bot, Clock, Globe } from "lucide-react";

import { cn } from "@/lib/utils";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { useExternalAgents } from "@/hooks/agent/useExternalAgents";
import { useAgentStore } from "@/stores/agentStore";
import { formatDate } from "@/lib/date";
import type { Agent } from "@/types/agentConfig";
import { a2aClientService, type A2AExternalAgent } from "@/services/a2aService";
import { AddResourceDrawer, CheckMark } from "./AddResourceDrawer";
import type { AgentCardItem, SelectedItem } from "./types";

const PAGE_SIZE = 10;

// Stable fallback so the zustand selectors return a referentially-stable value
// when `editedAgent` is undefined (avoids a getSnapshot infinite loop).
const EMPTY_IDS: number[] = [];

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
  const updatedAt =
    agent.update_time || agent.create_time
      ? formatDate(agent.update_time ?? agent.create_time)
      : undefined;
  return {
    id: String(agent.id),
    name: agent.display_name || agent.name,
    description: agent.description ?? "",
    iconBg: iconColorFor(String(agent.id)),
    updatedAt,
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
    updatedAt: agent.create_time ? formatDate(agent.create_time) : undefined,
    online: agent.is_available !== false,
    tags: [],
  };
}

function AgentCard({
  item,
  selected,
  onToggle,
  icon,
}: {
  item: AgentCardItem;
  selected: boolean;
  onToggle: () => void;
  icon: ReactNode;
}) {
  const { t } = useTranslation("common");
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
          {icon}
        </div>
        <span className="truncate text-[14px] font-medium leading-[22px] text-[#191919]">
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
            {t("agentConfig.list.updatedAt", { date: item.updatedAt })}
          </span>
        )}
        <span className="flex items-center gap-1">
          <span
            className={cn(
              "size-1.5 rounded-full",
              item.online ? "bg-[#52C41A]" : "bg-[#D9D9D9]"
            )}
          />
          {item.online
            ? t("agentConfig.list.online")
            : t("agentConfig.list.offline")}
        </span>
      </div>
    </div>
  );
}

export interface AddAgentDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function AddAgentDrawer({ open, onClose }: AddAgentDrawerProps) {
  const { t } = useTranslation("common");
  const { message: messageApi } = App.useApp();
  const currentAgentId = useAgentStore((state) => state.agentId);
  const editedAgent = useAgentStore((state) => state.editedAgent);
  const selectedInternalIds = useAgentStore(
    (state) => state.editedAgent?.sub_agent_id_list ?? EMPTY_IDS
  );
  const selectedExternalIds = useAgentStore(
    (state) => state.editedAgent?.external_sub_agent_id_list ?? EMPTY_IDS
  );
  const updateSubAgentIds = useAgentStore((state) => state.updateSubAgentIds);
  const updateSubAgentRelations = useAgentStore(
    (state) => state.updateSubAgentRelations
  );
  const updateExternalSubAgentIds = useAgentStore(
    (state) => state.updateExternalSubAgentIds
  );
  const {
    availableAgents: internalAgents,
    isLoading: isInternalLoading,
    invalidate: invalidateInternal,
  } = usePublishedAgentList();
  const {
    availableAgents: externalAgents,
    isLoading: isExternalLoading,
    invalidate: invalidateExternal,
  } = useExternalAgents();

  const [activeSource, setActiveSource] = useState<"internal" | "external">(
    "internal"
  );
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [tagFilter, setTagFilter] = useState("");

  useEffect(() => {
    if (!open) return;
    setActiveSource("internal");
    setSearch("");
    setPage(1);
    setTagFilter("");
  }, [open]);

  const selectableInternalAgents = useMemo(
    () =>
      internalAgents.filter(
        (agent: Agent) => Number(agent.id) !== currentAgentId
      ),
    [currentAgentId, internalAgents]
  );

  const localCards = useMemo(
    () => selectableInternalAgents.map(toLocalCard),
    [selectableInternalAgents]
  );
  const externalCards = useMemo(
    () => externalAgents.map(toExternalCard),
    [externalAgents]
  );

  const tagOptions = useMemo(() => {
    const tags = new Set<string>();
    selectableInternalAgents.forEach((agent) =>
      (agent.tags ?? []).forEach((tag) => tags.add(tag))
    );
    return Array.from(tags)
      .sort()
      .map((value) => ({ value, label: value }));
  }, [selectableInternalAgents]);

  const filteredAgents = useMemo(() => {
    const cards = activeSource === "internal" ? localCards : externalCards;
    const kw = search.trim().toLowerCase();
    let filtered = cards;
    if (kw) {
      filtered = filtered.filter(
        (item) =>
          item.name.toLowerCase().includes(kw) ||
          item.description.toLowerCase().includes(kw)
      );
    }
    if (activeSource === "internal" && tagFilter) {
      filtered = filtered.filter((item) =>
        (item.tags ?? []).includes(tagFilter)
      );
    }
    return filtered;
  }, [activeSource, externalCards, localCards, search, tagFilter]);

  const pagedAgents = filteredAgents.slice(
    (page - 1) * PAGE_SIZE,
    page * PAGE_SIZE
  );
  const isLoading =
    activeSource === "internal" ? isInternalLoading : isExternalLoading;

  const currentSelectedIds =
    activeSource === "internal" ? selectedInternalIds : selectedExternalIds;

  const selectedChips = useMemo<SelectedItem[]>(() => {
    const internalChips = selectedInternalIds.map((id) => {
      const agent = internalAgents.find(
        (item: Agent) => Number(item.id) === id
      );
      return {
        id: `internal-${id}`,
        label: agent?.display_name || agent?.name || String(id),
      };
    });
    const externalChips = selectedExternalIds.map((id) => {
      const agent = externalAgents.find(
        (item: A2AExternalAgent) => Number(item.id) === id
      );
      return { id: `external-${id}`, label: agent?.name || String(id) };
    });
    return [...internalChips, ...externalChips];
  }, [selectedExternalIds, selectedInternalIds, externalAgents, internalAgents]);

  const allSelected =
    filteredAgents.length > 0 &&
    filteredAgents.every((item) => currentSelectedIds.includes(Number(item.id)));

  const applyInternalSelection = (nextIds: number[]) => {
    updateSubAgentIds(nextIds);
    const existing = editedAgent?.sub_agent_relations || [];
    const addedIds = nextIds.filter(
      (id) => !existing.some((rel) => rel.agent_id === id)
    );
    const nextRelations = [
      ...existing.filter((rel) => nextIds.includes(rel.agent_id)),
      ...addedIds.map((agentId) => {
        const agent = internalAgents.find(
          (item: Agent) => Number(item.id) === agentId
        );
        return {
          agent_id: agentId,
          version_no: agent?.current_version_no ?? null,
          version_name: agent?.version_name,
        };
      }),
    ];
    updateSubAgentRelations(nextRelations);
  };

  const setExternalSelection = async (nextIds: number[]) => {
    const added = nextIds.filter((id) => !selectedExternalIds.includes(id));
    const removed = selectedExternalIds.filter((id) => !nextIds.includes(id));

    if (currentAgentId && (added.length || removed.length)) {
      const results = await Promise.all([
        ...added.map((id) =>
          a2aClientService.addRelation(Number(currentAgentId), id)
        ),
        ...removed.map((id) =>
          a2aClientService.removeRelation(Number(currentAgentId), id)
        ),
      ]);
      if (results.some((result) => !result.success)) {
        messageApi.error(t("a2a.service.addRelationFailed"));
        return;
      }
    }

    updateExternalSubAgentIds(nextIds);
  };

  const toggle = (id: string) => {
    const num = Number(id);
    if (activeSource === "internal") {
      const isSelected = selectedInternalIds.includes(num);
      applyInternalSelection(
        isSelected
          ? selectedInternalIds.filter((item) => item !== num)
          : [...selectedInternalIds, num]
      );
    } else {
      const isSelected = selectedExternalIds.includes(num);
      void setExternalSelection(
        isSelected
          ? selectedExternalIds.filter((item) => item !== num)
          : [...selectedExternalIds, num]
      );
    }
  };

  const removeSelected = (id: string) => {
    if (id.startsWith("internal-")) {
      const num = Number(id.slice("internal-".length));
      applyInternalSelection(selectedInternalIds.filter((item) => item !== num));
      return;
    }
    if (id.startsWith("external-")) {
      const num = Number(id.slice("external-".length));
      void setExternalSelection(
        selectedExternalIds.filter((item) => item !== num)
      );
    }
  };

  const handleSelectAll = (checked: boolean) => {
    const ids = filteredAgents.map((item) => Number(item.id));
    if (activeSource === "internal") {
      applyInternalSelection(checked ? ids : []);
    } else {
      void setExternalSelection(checked ? ids : []);
    }
  };

  useEffect(() => {
    setPage(1);
  }, [activeSource, search, tagFilter]);

  const handleRefresh = () => {
    void invalidateInternal();
    void invalidateExternal();
  };

  return (
    <AddResourceDrawer
      open={open}
      title={t("agent.collaborative.selector.title")}
      searchPlaceholder={t("agent.collaborative.selector.searchPlaceholder")}
      selected={selectedChips}
      tagOptions={activeSource === "internal" ? tagOptions : undefined}
      listTitle={t("resourcePicker.list.agent")}
      tabs={[
        {
          key: "internal",
          label: t("agent.collaborative.selector.tab.internal"),
        },
        {
          key: "external",
          label: t("agent.collaborative.selector.tab.external"),
        },
      ]}
      activeTab={activeSource}
      total={filteredAgents.length}
      page={page}
      onPageChange={setPage}
      showConfirm={false}
      onClose={onClose}
      onRemoveSelected={removeSelected}
      onSearch={setSearch}
      onTagChange={(value) => setTagFilter(value ?? "")}
      onTabChange={(key) => setActiveSource(key as "internal" | "external")}
      onSelectAll={handleSelectAll}
      allSelected={allSelected}
      onRefresh={handleRefresh}
    >
      {isLoading ? (
        <div className="flex justify-center py-12">
          <Spin />
        </div>
      ) : filteredAgents.length === 0 ? (
        <Empty description={t("agent.collaborative.selector.empty")} />
      ) : (
        <div className="grid grid-cols-2 content-start gap-2">
          {pagedAgents.map((item) => (
            <AgentCard
              key={`${activeSource}-${item.id}`}
              item={item}
              selected={currentSelectedIds.includes(Number(item.id))}
              onToggle={() => toggle(item.id)}
              icon={
                activeSource === "external" ? (
                  <Globe size={20} />
                ) : (
                  <Bot size={20} />
                )
              }
            />
          ))}
        </div>
      )}
    </AddResourceDrawer>
  );
}