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
import styles from "./ResourcePickerDrawer.module.css";

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
        styles.agentCard,
        selected ? styles.agentCardSelected : "bg-white"
      )}
    >
      <div className="absolute right-6 top-7">
        <CheckMark checked={selected} onToggle={onToggle} />
      </div>
      <div className="flex h-10 shrink-0 items-center gap-3 pr-6">
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[8px] text-white"
          style={{ background: item.iconBg }}
        >
          {icon}
        </div>
        <span className="min-w-0 truncate text-[16px] font-medium leading-[24px] text-[#191919]">
          {item.name}
        </span>
      </div>
      <p className="line-clamp-2 h-[42px] shrink-0 text-[12px] font-normal leading-[20px] text-[#777777]">
        {item.description}
      </p>
      <div className={styles.agentMetadata}>
        {item.updatedAt && (
          <span className={styles.agentUpdatedAt}>
            <Clock size={14} className="shrink-0" />
            {t("agentConfig.list.updatedAt", { date: item.updatedAt })}
          </span>
        )}
        <span className={styles.agentStatus}>
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

  // Local drafts of the selected sub-agent ids. Changes are only committed to
  // the agent store (and external A2A relations) when confirm is clicked.
  const [draftInternalIds, setDraftInternalIds] = useState<number[]>([]);
  const [draftExternalIds, setDraftExternalIds] = useState<number[]>([]);

  useEffect(() => {
    if (!open) return;
    setActiveSource("internal");
    setSearch("");
    setPage(1);
    setTagFilter("");
    setDraftInternalIds(selectedInternalIds);
    setDraftExternalIds(selectedExternalIds);
  }, [open, selectedInternalIds, selectedExternalIds]);

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
      .sort((left, right) => (left < right ? -1 : Number(left > right)))
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
    activeSource === "internal" ? draftInternalIds : draftExternalIds;

  const selectedChips = useMemo<SelectedItem[]>(() => {
    const internalChips = draftInternalIds.map((id) => {
      const agent = internalAgents.find(
        (item: Agent) => Number(item.id) === id
      );
      return {
        id: `internal-${id}`,
        label: agent?.display_name || agent?.name || String(id),
      };
    });
    const externalChips = draftExternalIds.map((id) => {
      const agent = externalAgents.find(
        (item: A2AExternalAgent) => Number(item.id) === id
      );
      return { id: `external-${id}`, label: agent?.name || String(id) };
    });
    return [...internalChips, ...externalChips];
  }, [draftExternalIds, draftInternalIds, externalAgents, internalAgents]);

  const allSelected =
    filteredAgents.length > 0 &&
    filteredAgents.every((item) =>
      currentSelectedIds.includes(Number(item.id))
    );

  const computeInternalRelations = (nextIds: number[]) => {
    const existing = editedAgent?.sub_agent_relations || [];
    const addedIds = nextIds.filter(
      (id) => !existing.some((rel) => rel.agent_id === id)
    );
    return [
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
  };

  const toggle = (id: string) => {
    const num = Number(id);
    if (activeSource === "internal") {
      const isSelected = draftInternalIds.includes(num);
      setDraftInternalIds(
        isSelected
          ? draftInternalIds.filter((item) => item !== num)
          : [...draftInternalIds, num]
      );
    } else {
      const isSelected = draftExternalIds.includes(num);
      setDraftExternalIds(
        isSelected
          ? draftExternalIds.filter((item) => item !== num)
          : [...draftExternalIds, num]
      );
    }
  };

  const removeSelected = (id: string) => {
    if (id.startsWith("internal-")) {
      const num = Number(id.slice("internal-".length));
      setDraftInternalIds(draftInternalIds.filter((item) => item !== num));
      return;
    }
    if (id.startsWith("external-")) {
      const num = Number(id.slice("external-".length));
      setDraftExternalIds(draftExternalIds.filter((item) => item !== num));
    }
  };

  const handleSelectAll = (checked: boolean) => {
    const ids = filteredAgents.map((item) => Number(item.id));
    if (activeSource === "internal") {
      setDraftInternalIds(checked ? ids : []);
    } else {
      setDraftExternalIds(checked ? ids : []);
    }
  };

  const handleConfirm = async () => {
    // Commit internal sub-agent ids and their version relations.
    updateSubAgentIds(draftInternalIds);
    updateSubAgentRelations(computeInternalRelations(draftInternalIds));

    // Commit external sub-agent ids and their A2A relations.
    const added = draftExternalIds.filter(
      (id) => !selectedExternalIds.includes(id)
    );
    const removed = selectedExternalIds.filter(
      (id) => !draftExternalIds.includes(id)
    );
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
    updateExternalSubAgentIds(draftExternalIds);

    onClose();
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
      width={768}
      bodyClassName={cn(styles.drawer, styles.agent)}
      open={open}
      title={t("resourcePicker.addAgent", "添加子智能体")}
      searchPlaceholder={t("agent.collaborative.selector.searchPlaceholder")}
      selected={selectedChips}
      tagOptions={activeSource === "internal" ? tagOptions : undefined}
      listTitle={t("resourcePicker.list.agent")}
      tabs={[
        {
          key: "internal",
          label: t("resourcePicker.tab.localAgent", "本地智能体"),
        },
        {
          key: "external",
          label: t("resourcePicker.tab.externalAgent", "外部智能体"),
        },
      ]}
      activeTab={activeSource}
      total={filteredAgents.length}
      page={page}
      onPageChange={setPage}
      onClose={onClose}
      onConfirm={handleConfirm}
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
        <div className={styles.agentGrid}>
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
