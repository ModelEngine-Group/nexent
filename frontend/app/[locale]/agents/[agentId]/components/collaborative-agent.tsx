"use client";

import {
  createElement,
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { App, Avatar, Button, Col } from "antd";
import { ChevronRight, Plus, Search, Trash2, X } from "lucide-react";

import { AddAgentDrawer } from "@/components/resource-picker/AddAgentDrawer";
import A2AAgentDiscoveryModal from "./a2a/A2AAgentDiscoveryModal";
import { useExternalAgents } from "@/hooks/agent/useExternalAgents";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { a2aClientService, A2AExternalAgent } from "@/services/a2aService";
import { useAgentStore } from "@/stores/agentStore";
import { useAgentReadOnly } from "@/hooks/agent/useAgentReadOnly";
import { Agent } from "@/types/agentConfig";
import { ResourceAddButton } from "@/components/common/ResourceAddButton";
import {
  SelectedResourceRow,
  SelectedResourceTag,
} from "@/components/common/SelectedResourceRow";
import { getAgentIcon } from "@/lib/chat/agentIconUtils";
import AgentAvatar from "../../components/agent-avatar";
import type { ResourceSectionProps } from "./resource-section.types";

type CollaborativeAgentListItem = {
  id: number | string;
  name: string;
  versionNo?: number;
};

type RelatedInternalAgent = Agent & {
  version_no?: number;
};

interface CollaborativeAgentListProps {
  agents: CollaborativeAgentListItem[];
  label: string;
  tone: "primary" | "external";
  readOnly?: boolean;
  onRemove?: (agentId: number) => void;
}

export function CollaborativeAgentList({
  agents,
  label,
  tone,
  readOnly = false,
  onRemove,
}: CollaborativeAgentListProps) {
  const { t } = useTranslation("common");
  if (agents.length === 0) return null;

  const toneClasses =
    tone === "external"
      ? {
          badge: "bg-amber-100 text-amber-700",
          item: "border-amber-200 bg-amber-50 transition-colors hover:border-amber-300  hover:shadow-sm",
        }
      : {
          badge: "bg-primary/10 text-primary",
          item: "border-primary/20 bg-primary/5 transition-colors hover:border-primary/40  hover:shadow-sm",
        };

  return (
    <div className="flex flex-wrap items-center gap-2 p-3">
      <span
        className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ${toneClasses.badge}`}
      >
        {label} · {agents.length}
      </span>
      {agents.map((agent) => (
        <span
          key={`${tone}-${agent.id}`}
          className={`flex items-center gap-1 rounded-full border px-2.5 py-1 text-sm text-foreground ${toneClasses.item}`}
        >
          <span className="max-w-full truncate">{agent.name}</span>
          {agent.versionNo != null && (
            <span className="shrink-0 text-xs text-muted-foreground">
              V{agent.versionNo}
            </span>
          )}
          {!readOnly && onRemove && (
            <button
              type="button"
              aria-label={t("agent.collaborative.removeAria", {
                name: agent.name,
              })}
              onClick={() => onRemove(Number(agent.id))}
              className="shrink-0 text-muted-foreground hover:text-destructive"
            >
              <X size={12} />
            </button>
          )}
        </span>
      ))}
    </div>
  );
}

export function CollaborativeAgentActions({
  highFidelity = false,
  renderSection,
  children,
}: ResourceSectionProps & { children?: ReactNode } = {}) {
  const { t } = useTranslation("common");
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [discoveryOpen, setDiscoveryOpen] = useState(false);
  const currentAgentId = useAgentStore((state) => state.agentId);
  const editedAgent = useAgentStore((state) => state.editedAgent);
  const updateExternalSubAgentIds = useAgentStore(
    (state) => state.updateExternalSubAgentIds
  );
  const isReadOnly = useAgentReadOnly();
  const { invalidate: invalidateExternalAgents } = useExternalAgents();
  const externalSubAgentIdList = editedAgent?.external_sub_agent_id_list || [];

  const handleAgentDiscovered = (agent: A2AExternalAgent) => {
    const agentId = Number(agent.id);
    if (!externalSubAgentIdList.includes(agentId)) {
      updateExternalSubAgentIds([...externalSubAgentIdList, agentId]);
    }
    invalidateExternalAgents();
  };

  const content = (
    <div
      className="grid grid-cols-1 gap-2 sm:grid-cols-2"
      data-testid="agent-selected-child-grid"
    >
      {children}
      <ResourceAddButton
        disabled={isReadOnly}
        onClick={() => setSelectorOpen(true)}
      >
        {t("agentConfig.layout.addAgent")}
      </ResourceAddButton>
    </div>
  );
  const actions = (
    <Button
      type="link"
      disabled={isReadOnly}
      onClick={() => setDiscoveryOpen(true)}
      className="!h-[22px] !p-0 !text-sm !font-normal !leading-[22px] !tracking-[0px] !text-[#2673e5]"
    >
      <span className="inline-flex items-center gap-1">
        {t("agentConfig.layout.thirdPartyAgent")}
        <ChevronRight size={14} />
      </span>
    </Button>
  );

  return (
    <>
      {highFidelity ? (
        renderSection ? (
          renderSection(content, actions)
        ) : (
          <div className="flex flex-col gap-2">
            <div className="flex justify-end">{actions}</div>
            {content}
          </div>
        )
      ) : (
        <>
          <Button
            size="middle"
            icon={<Search size={14} />}
            disabled={isReadOnly}
            onClick={() => setDiscoveryOpen(true)}
          >
            {t("a2a.discovery.button")}
          </Button>
          <Button
            size="middle"
            icon={<Plus size={14} />}
            disabled={isReadOnly}
            onClick={() => setSelectorOpen(true)}
          >
            {t("agent.collaborative.button.selectAgent")}
          </Button>
        </>
      )}
      <A2AAgentDiscoveryModal
        open={discoveryOpen}
        onClose={() => setDiscoveryOpen(false)}
        onDiscoverSuccess={invalidateExternalAgents}
        onAgentDiscovered={handleAgentDiscovered}
        localAgentId={currentAgentId ? Number(currentAgentId) : undefined}
      />
      <AddAgentDrawer
        open={selectorOpen}
        onClose={() => setSelectorOpen(false)}
      />
    </>
  );
}

export default function CollaborativeAgent({
  highFidelity = false,
  renderSection,
}: ResourceSectionProps = {}) {
  const { t } = useTranslation("common");
  const { message: messageApi } = App.useApp();

  const currentAgentId = useAgentStore((state) => state.agentId);
  const editedAgent = useAgentStore((state) => state.editedAgent);
  const updateSubAgentIds = useAgentStore((state) => state.updateSubAgentIds);
  const updateSubAgentRelations = useAgentStore(
    (state) => state.updateSubAgentRelations
  );
  const updateExternalSubAgentIds = useAgentStore(
    (state) => state.updateExternalSubAgentIds
  );
  const isReadOnly = useAgentReadOnly();

  const { availableAgents: internalAgents } = usePublishedAgentList();
  const { availableAgents: externalAgents } = useExternalAgents();

  // Local state for edit mode (when currentAgentId exists)
  const [externalRelationSnapshot, setExternalRelationSnapshot] = useState<{
    agentId: number | null;
    agents: A2AExternalAgent[];
  }>({ agentId: currentAgentId, agents: [] });
  const externalRelatedAgents =
    externalRelationSnapshot.agentId === currentAgentId
      ? externalRelationSnapshot.agents
      : [];

  // External agent IDs from store (for creation mode)
  const externalSubAgentIdList = editedAgent?.external_sub_agent_id_list || [];

  // Store-based external agents for creation mode
  const externalRelatedAgentsFromStore = (
    Array.isArray(externalAgents) ? externalAgents : []
  ).filter((agent: A2AExternalAgent) =>
    externalSubAgentIdList.includes(agent.id)
  );

  // Related internal agent IDs
  const relatedAgentIds = Array.isArray(editedAgent?.sub_agent_id_list)
    ? editedAgent.sub_agent_id_list
    : [];

  // Map of agent_id -> saved version info (from snapshot)
  const savedVersionMap = (() => {
    const map: Record<
      number,
      {
        agent_name?: string | null;
        version_no: number | null;
        version_name?: string | null;
      }
    > = {};
    (editedAgent?.sub_agent_relations || []).forEach((rel) => {
      map[rel.agent_id] = {
        agent_name: rel.agent_name,
        version_no: rel.version_no,
        version_name: rel.version_name,
      };
    });
    return map;
  })();

  // Related internal agents - display all agents from sub_agent_id_list
  // For agents found in internalAgents, use full info (name, version)
  // For legacy agents not found, still display with fallback info
  const publishedAgentMap = new Map(
    (Array.isArray(internalAgents) ? internalAgents : []).map((a: Agent) => [
      Number(a.id),
      a,
    ])
  );

  const relatedInternalAgents: RelatedInternalAgent[] = relatedAgentIds.map(
    (agentId: number) => {
      const publishedAgent = publishedAgentMap.get(Number(agentId));
      const savedVersion = savedVersionMap[Number(agentId)];
      const hasSavedVersion = savedVersion?.version_no != null;

      if (publishedAgent) {
        const version_name =
          (hasSavedVersion
            ? (savedVersion?.version_name ?? publishedAgent.version_name)
            : publishedAgent.version_name) ?? undefined;
        const version_no =
          (hasSavedVersion
            ? savedVersion?.version_no
            : publishedAgent.current_version_no) ?? undefined;
        return {
          ...publishedAgent,
          version_name,
          version_no,
        };
      }

      // Legacy agent not found in published list - use name from sub_agent_relations
      return {
        id: String(agentId),
        name: savedVersion?.agent_name || `Agent #${agentId}`,
        display_name: savedVersion?.agent_name || `Agent #${agentId}`,
        description: "",
        model: "",
        max_step: 0,
        provide_run_summary: false,
        tools: [],
        skills: [],
        version_name: savedVersion?.version_name ?? undefined,
        version_no: savedVersion?.version_no ?? undefined,
      } as RelatedInternalAgent;
    }
  );

  // Include the latest store selection so changes from the selector render immediately.
  const displayExternalAgents = currentAgentId
    ? [
        ...externalRelatedAgents,
        ...externalRelatedAgentsFromStore.filter(
          (agent) => !externalRelatedAgents.some(({ id }) => id === agent.id)
        ),
      ]
    : externalRelatedAgentsFromStore;

  const externalAgentMap = new Map(
    displayExternalAgents.map((agent) => [agent.id, agent])
  );
  const selectedExternalAgents = highFidelity
    ? [
        ...externalSubAgentIdList.flatMap((agentId) => {
          const agent = externalAgentMap.get(agentId);
          return agent ? [agent] : [];
        }),
        ...displayExternalAgents.filter(
          (agent) => !externalSubAgentIdList.includes(agent.id)
        ),
      ]
    : displayExternalAgents;

  const loadExternalRelatedAgents = useCallback(async () => {
    if (!currentAgentId) return;
    const result = await a2aClientService.getSubAgents(Number(currentAgentId));
    if (useAgentStore.getState().agentId !== currentAgentId) return;
    if (result.success && result.data) {
      setExternalRelationSnapshot({
        agentId: currentAgentId,
        agents: result.data,
      });
    }
  }, [currentAgentId]);

  // Load external related agents.
  useEffect(() => {
    if (!currentAgentId) return;
    let active = true;
    void a2aClientService
      .getSubAgents(Number(currentAgentId))
      .then((result) => {
        if (active && result.success && result.data) {
          setExternalRelationSnapshot({
            agentId: currentAgentId,
            agents: result.data,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [currentAgentId]);

  // Remove internal agent
  const handleRemoveInternalAgent = (agentId: number) => {
    const newRelatedAgentIds = (
      Array.isArray(relatedAgentIds) ? relatedAgentIds : []
    ).filter((id: number) => id !== agentId);
    updateSubAgentIds(newRelatedAgentIds);

    // Sync sub_agent_relations: remove the agent
    const existingRelations = editedAgent?.sub_agent_relations || [];
    const newRelations = existingRelations.filter(
      (rel: {
        agent_id: number;
        version_no: number | null;
        version_name?: string;
      }) => rel.agent_id !== agentId
    );
    updateSubAgentRelations(newRelations);
  };

  const handleRemoveExternalAgent = async (agentId: number) => {
    if (!currentAgentId) {
      updateExternalSubAgentIds(
        externalSubAgentIdList.filter((id) => id !== agentId)
      );
      return;
    }

    const result = await a2aClientService.removeRelation(
      Number(currentAgentId),
      agentId
    );
    if (result.success) {
      messageApi.success(t("a2a.service.removeRelationSuccess"));
      updateExternalSubAgentIds(
        externalSubAgentIdList.filter((id) => id !== agentId)
      );
      loadExternalRelatedAgents();
    } else {
      messageApi.error(result.message || t("a2a.service.removeRelationFailed"));
    }
  };

  const hasCollaborativeAgents =
    relatedInternalAgents.length > 0 || displayExternalAgents.length > 0;

  const selectedRows = (
    <>
      {relatedInternalAgents.map((agent) => {
        const name = agent.display_name || agent.name;
        const tags = agent.tags ?? [];
        return (
          <SelectedResourceRow
            key={`internal-${agent.id}`}
            data-testid={`agent-selected-child-internal-${agent.id}`}
            icon={
              <AgentAvatar
                agent={agent}
                size={32}
                iconSize={20}
                className="!rounded-[4px]"
              />
            }
            name={name}
            nameTooltip={
              <span className="inline-flex flex-col">
                <span>{name}</span>
                {agent.version_no != null && <span>V{agent.version_no}</span>}
                {agent.version_name && (
                  <span>
                    {t("agent.collaborative.selector.versionName", {
                      name: agent.version_name,
                    })}
                  </span>
                )}
              </span>
            }
            metadata={
              tags.length ? (
                <>
                  {tags.slice(0, 2).map((tag, index) => (
                    <SelectedResourceTag key={`${tag}-${index}`} title={tag}>
                      {tag}
                    </SelectedResourceTag>
                  ))}
                  {tags.length > 2 && (
                    <SelectedResourceTag title={tags.slice(2).join(", ")}>
                      +{tags.length - 2}
                    </SelectedResourceTag>
                  )}
                </>
              ) : undefined
            }
            actions={
              <Button
                type="text"
                disabled={isReadOnly}
                aria-label={t("agent.collaborative.removeAria", { name })}
                icon={<Trash2 size={14} />}
                onClick={() => handleRemoveInternalAgent(Number(agent.id))}
                className="!h-6 !w-6 !min-w-6 !p-0 !text-[#777777]"
              />
            }
          />
        );
      })}
      {selectedExternalAgents.map((agent) => (
        <SelectedResourceRow
          key={`external-${agent.id}`}
          data-testid={`agent-selected-child-external-${agent.id}`}
          icon={
            <Avatar
              shape="square"
              size={32}
              icon={createElement(getAgentIcon({ agent_id: agent.id }), {
                size: 20,
                "aria-hidden": true,
              })}
              className="!rounded-[4px] !bg-primary/10 !text-primary"
            />
          }
          name={agent.name}
          actions={
            <Button
              type="text"
              disabled={isReadOnly}
              aria-label={t("agent.collaborative.removeAria", {
                name: agent.name,
              })}
              icon={<Trash2 size={14} />}
              onClick={() => handleRemoveExternalAgent(agent.id)}
              className="!h-6 !w-6 !min-w-6 !p-0 !text-[#777777]"
            />
          }
        />
      ))}
    </>
  );

  const content = hasCollaborativeAgents ? (
    <div className="min-w-0 flex-1 divide-y divide-border rounded-lg border border-border">
      <CollaborativeAgentList
        agents={relatedInternalAgents.map((agent) => ({
          id: agent.id,
          name: agent.display_name || agent.name,
          versionNo: agent.version_no,
        }))}
        label={t("agent.collaborative.label.internal")}
        tone="primary"
        readOnly={isReadOnly}
        onRemove={handleRemoveInternalAgent}
      />
      <CollaborativeAgentList
        agents={displayExternalAgents}
        label={t("agent.collaborative.label.external")}
        tone="external"
        readOnly={isReadOnly}
        onRemove={handleRemoveExternalAgent}
      />
    </div>
  ) : highFidelity ? null : (
    <div className="flex min-h-20 items-center justify-center gap-4 rounded-md border border-dashed border-gray-300 bg-white px-4 py-3">
      <div className="flex items-center gap-3">
        <div>
          <p className="text-sm font-medium text-gray-700"></p>
          <p className="mt-0.5 text-xs text-gray-400">
            {t("agent.collaborative.emptyHint")}
          </p>
        </div>
      </div>
    </div>
  );

  return highFidelity ? (
    <CollaborativeAgentActions highFidelity renderSection={renderSection}>
      {selectedRows}
    </CollaborativeAgentActions>
  ) : (
    <Col xs={24}>{content}</Col>
  );
}
