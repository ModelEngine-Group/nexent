"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";

import { useTranslation } from "react-i18next";

import { useExternalAgents } from "@/hooks/agent/useExternalAgents";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import {
  Button,
  Empty,
  Input,
  Modal,
  Pagination,
  Spin,
  Tabs,
} from "antd";
import { Bot, Check, Globe, Search } from "lucide-react";

import type { A2AExternalAgent } from "@/services/a2aService";
import { useAgentStore } from "@/stores/agentStore";
import type { Agent } from "@/types/agentConfig";

const PAGE_SIZE = 10;

type AgentSource = "internal" | "external";

interface CollaborativeAgentSelectorModalProps {
  open: boolean;
  onCancel: () => void;
  onConfirm: (
    internalAgentIds: number[],
    externalAgentIds: number[],
    internalAgents: Agent[]
  ) => void;
}

function filterAgents<
  T extends { name: string; description?: string; display_name?: string },
>(agents: T[], search: string) {
  const keyword = search.trim().toLocaleLowerCase();
  if (!keyword) return agents;

  return agents.filter((agent) =>
    [agent.name, agent.display_name, agent.description].some((value) =>
      value?.toLocaleLowerCase().includes(keyword)
    )
  );
}

interface SelectCardProps {
  selected: boolean;
  onToggle: () => void;
  icon: ReactNode;
  name: string;
  description: string;
  version?: string;
}

function SelectCard({
  selected,
  onToggle,
  icon,
  name,
  description,
  version,
}: SelectCardProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={selected}
      title={description}
      className={`relative flex w-full min-w-0 items-center gap-2.5 overflow-hidden rounded-lg border p-2.5 text-left transition ${
        selected
          ? "border-primary bg-primary/5"
          : "border-gray-200 hover:border-primary/40 hover:bg-gray-50"
      }`}
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-1.5">
          <strong className="min-w-0 truncate text-sm text-gray-800">{name}</strong>
          {version && (
            <span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-gray-500">
              {version}
            </span>
          )}
        </span>
        <span className="mt-0.5 block min-w-0 truncate text-xs text-gray-500">
          {description}
        </span>
      </span>
      {selected && (
        <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-primary text-white">
          <Check size={11} />
        </span>
      )}
    </button>
  );
}

export default function CollaborativeAgentSelectorModal({
  open,
  onCancel,
  onConfirm,
}: CollaborativeAgentSelectorModalProps) {
  const { t } = useTranslation("common");
  const currentAgentId = useAgentStore((state) => state.agentId);
  const { availableAgents: internalAgents, isLoading: isInternalLoading } =
    usePublishedAgentList();
  const { availableAgents: externalAgents, isLoading: isExternalLoading } =
    useExternalAgents();
  const selectedInternalIds = useAgentStore(
    (state) => state.editedAgent?.sub_agent_id_list || []
  );
  const selectedExternalIds = useAgentStore(
    (state) => state.editedAgent?.external_sub_agent_id_list || []
  );
  const [activeSource, setActiveSource] = useState<AgentSource>("internal");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [draftInternalIds, setDraftInternalIds] = useState<number[]>([]);
  const [draftExternalIds, setDraftExternalIds] = useState<number[]>([]);
  useEffect(() => {
    if (!open) return;
    setActiveSource("internal");
    setSearch("");
    setPage(1);
    setDraftInternalIds(selectedInternalIds);
    setDraftExternalIds(selectedExternalIds);
  }, [open, selectedExternalIds, selectedInternalIds]);

  const selectableInternalAgents = useMemo(
    () =>
      internalAgents.filter(
        (agent: Agent) => Number(agent.id) !== currentAgentId
      ),
    [currentAgentId, internalAgents]
  );
  const filteredAgents = useMemo<Array<Agent | A2AExternalAgent>>(
    () =>
      activeSource === "internal"
        ? filterAgents<Agent>(selectableInternalAgents, search)
        : filterAgents<A2AExternalAgent>(externalAgents, search),
    [activeSource, externalAgents, search, selectableInternalAgents]
  );
  const pagedAgents = filteredAgents.slice(
    (page - 1) * PAGE_SIZE,
    page * PAGE_SIZE
  );
  const isLoading =
    activeSource === "internal" ? isInternalLoading : isExternalLoading;
  const selectedIds =
    activeSource === "internal" ? draftInternalIds : draftExternalIds;

  const changeSource = (source: string) => {
    setActiveSource(source as AgentSource);
    setSearch("");
    setPage(1);
  };

  const toggleSelection = (
    source: AgentSource,
    agentId: number,
    checked: boolean
  ) => {
    const update = (ids: number[]) =>
      checked
        ? [...new Set([...ids, agentId])]
        : ids.filter((id) => id !== agentId);

    if (source === "internal") {
      setDraftInternalIds(update);
      return;
    }
    setDraftExternalIds(update);
  };

  const renderAgent = (agent: Agent | A2AExternalAgent) => {
    const agentId = Number(agent.id);
    const isInternal = activeSource === "internal";
    const agentName = isInternal
      ? (agent as Agent).display_name || agent.name
      : agent.name;
    const version = isInternal
      ? (agent as Agent).version_name
      : (agent as A2AExternalAgent).version;
    const isSelected = selectedIds.includes(agentId);
    const AgentIcon = isInternal ? Bot : Globe;

    return (
      <SelectCard
        key={`${activeSource}-${agentId}`}
        selected={isSelected}
        onToggle={() => toggleSelection(activeSource, agentId, !isSelected)}
        icon={<AgentIcon size={16} />}
        name={agentName}
        description={agent.description || t("agent.collaborative.selector.noDescription")}
        version={version}
      />
    );
  };

  return (
    <Modal
      title={t("agent.collaborative.selector.title")}
      open={open}
      width={720}
      destroyOnHidden
      onCancel={onCancel}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          {t("common.cancel")}
        </Button>,
        <Button
          key="confirm"
          type="primary"
          onClick={() =>
            onConfirm(draftInternalIds, draftExternalIds, internalAgents)
          }
        >
          {t("common.confirm")}
        </Button>,
      ]}
    >
      <Tabs
        activeKey={activeSource}
        onChange={changeSource}
        items={[
          { key: "internal", label: t("agent.collaborative.selector.tab.internal") },
          { key: "external", label: t("agent.collaborative.selector.tab.external") },
        ]}
      />
      <Input
        allowClear
        value={search}
        prefix={<Search size={16} className="text-gray-400" />}
        placeholder={t("agent.collaborative.selector.searchPlaceholder")}
        onChange={(event) => {
          setSearch(event.target.value);
          setPage(1);
        }}
      />
      <div className="mt-4 min-h-72">
        {isLoading ? (
          <div className="flex min-h-72 items-center justify-center">
            <Spin />
          </div>
        ) : pagedAgents.length > 0 ? (
          <div className="grid gap-2">{pagedAgents.map(renderAgent)}</div>
        ) : (
          <div className="flex min-h-72 items-center justify-center">
            <Empty description={t("agent.collaborative.selector.empty")} />
          </div>
        )}
      </div>
      {filteredAgents.length > PAGE_SIZE && (
        <div className="mt-5 flex items-center justify-between border-t border-gray-100 pt-4">
          <span className="text-xs text-gray-400">
            {t("agent.collaborative.selector.totalAgents", { count: filteredAgents.length })}
          </span>
          <Pagination
            current={page}
            pageSize={PAGE_SIZE}
            total={filteredAgents.length}
            showSizeChanger={false}
            size="small"
            onChange={setPage}
          />
        </div>
      )}
    </Modal>
  );
}
