"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Col, Flex, Tag } from "antd";
import { Globe, Plus } from "lucide-react";

import CollaborativeAgentSelectorModal from "./collaborative-agent-selector-modal";
import { useExternalAgents } from "@/hooks/agent/useExternalAgents";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { a2aClientService, A2AExternalAgent } from "@/services/a2aService";
import { useAgentStore } from "@/stores/agentStore";
import { Agent } from "@/types/agentConfig";

export function CollaborativeAgentActions() {
  const { t } = useTranslation("common");
  const { message: messageApi } = App.useApp();
  const [selectorOpen, setSelectorOpen] = useState(false);
  const currentAgentId = useAgentStore((state) => state.agentId);
  const editedAgent = useAgentStore((state) => state.editedAgent);
  const updateSubAgentIds = useAgentStore((state) => state.updateSubAgentIds);
  const updateSubAgentRelations = useAgentStore(
    (state) => state.updateSubAgentRelations
  );
  const updateExternalSubAgentIds = useAgentStore(
    (state) => state.updateExternalSubAgentIds
  );
  const isReadOnly = useAgentStore((state) => state.isReadOnly);
  const relatedAgentIds = Array.isArray(editedAgent?.sub_agent_id_list)
    ? editedAgent.sub_agent_id_list
    : [];
  const externalSubAgentIdList = editedAgent?.external_sub_agent_id_list || [];
  const handleConfirmSelection = async (
    internalAgentIds: number[],
    externalAgentIds: number[],
    internalAgents: Agent[]
  ) => {
    const addedInternalIds = internalAgentIds.filter(
      (agentId) => !relatedAgentIds.includes(agentId)
    );
    const nextRelations = [
      ...(editedAgent?.sub_agent_relations || []).filter((relation) =>
        internalAgentIds.includes(relation.agent_id)
      ),
      ...addedInternalIds.map((agentId) => {
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

    updateSubAgentIds(internalAgentIds);
    updateSubAgentRelations(nextRelations);

    const addedExternalIds = externalAgentIds.filter(
      (agentId) => !externalSubAgentIdList.includes(agentId)
    );
    const removedExternalIds = externalSubAgentIdList.filter(
      (agentId) => !externalAgentIds.includes(agentId)
    );

    if (currentAgentId) {
      const results = await Promise.all([
        ...addedExternalIds.map((agentId) =>
          a2aClientService.addRelation(Number(currentAgentId), agentId)
        ),
        ...removedExternalIds.map((agentId) =>
          a2aClientService.removeRelation(Number(currentAgentId), agentId)
        ),
      ]);
      if (results.some((result) => !result.success)) {
        messageApi.error(t("a2a.service.addRelationFailed"));
        return;
      }
    }

    updateExternalSubAgentIds(externalAgentIds);
    setSelectorOpen(false);
  };

  return (
    <>
      <Button
        size="middle"
        icon={<Plus size={14} />}
        disabled={isReadOnly}
        onClick={() => setSelectorOpen(true)}
      >
        选择智能体
      </Button>
      <CollaborativeAgentSelectorModal
        open={selectorOpen}
        onCancel={() => setSelectorOpen(false)}
        onConfirm={handleConfirmSelection}
      />
    </>
  );
}

export default function CollaborativeAgent() {
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
  const isReadOnly = useAgentStore((state) => state.isReadOnly);

  const { availableAgents: internalAgents } = usePublishedAgentList({
    enabled: true,
  });
  const { availableAgents: externalAgents } = useExternalAgents({
    enabled: true,
  });

  // Local state for edit mode (when currentAgentId exists)
  const [externalRelatedAgents, setExternalRelatedAgents] = useState<
    A2AExternalAgent[]
  >([]);

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

  const relatedInternalAgents = relatedAgentIds.map((agentId: number) => {
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
          : (publishedAgent as any).current_version_no) ?? undefined;
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
    } as Agent;
  });

  // Include the latest store selection so changes from the selector render immediately.
  const displayExternalAgents = currentAgentId
    ? [
        ...externalRelatedAgents,
        ...externalRelatedAgentsFromStore.filter(
          (agent) => !externalRelatedAgents.some(({ id }) => id === agent.id)
        ),
      ]
    : externalRelatedAgentsFromStore;

  // Load external related agents
  useEffect(() => {
    if (currentAgentId) {
      loadExternalRelatedAgents();
    }
  }, [currentAgentId]);

  const loadExternalRelatedAgents = async () => {
    if (!currentAgentId) return;
    const result = await a2aClientService.getSubAgents(Number(currentAgentId));
    if (result.success && result.data) {
      setExternalRelatedAgents(result.data);
    }
  };

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

  return (
    <>
      <Col xs={24}>
        <div className="min-h-20 rounded-md border border-dashed border-gray-300 bg-white px-4 py-3">
          {hasCollaborativeAgents ? (
            <div className="flex items-center gap-4">
              <div className="min-w-0 flex-1">
                <div
                  className={
                    relatedInternalAgents.length > 0 &&
                    displayExternalAgents.length > 0
                      ? "mb-3"
                      : ""
                  }
                >
                  <Flex className="flex flex-wrap items-center gap-2">
                    {relatedInternalAgents.map((agent: Agent) => (
                      <Tag
                        key={`internal-${agent.id}`}
                        closable={!isReadOnly}
                        onClose={
                          !isReadOnly
                            ? () => handleRemoveInternalAgent(Number(agent.id))
                            : undefined
                        }
                        className="!inline-flex !items-center !whitespace-nowrap !py-1.5 !px-3 !text-sm !bg-blue-50 !text-blue-700 !border !border-blue-200 !rounded-lg !shadow-sm hover:!shadow-md hover:!border-blue-400 transition-all"
                      >
                        <span className="inline-flex items-center gap-1.5">
                          <span className="text-sm">
                            {agent.display_name || agent.name}
                          </span>
                          {agent.version_name && (
                            <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs text-blue-500">
                              {agent.version_name}
                            </span>
                          )}
                        </span>
                      </Tag>
                    ))}
                  </Flex>
                </div>
                <Flex className="flex flex-wrap items-center gap-2">
                  {displayExternalAgents.map((agent) => (
                    <Tag
                      key={`external-${agent.id}`}
                      closable={!isReadOnly}
                      onClose={
                        !isReadOnly
                          ? () => handleRemoveExternalAgent(agent.id)
                          : undefined
                      }
                      className="!inline-flex !items-center !whitespace-nowrap !py-1.5 !px-3 !text-sm !bg-green-50 !text-green-700 !border !border-green-200 !rounded-lg !shadow-sm hover:!shadow-md hover:!border-green-400 transition-all"
                    >
                      <span className="inline-flex items-center gap-1.5">
                        <Globe size={14} />
                        <span className="font-medium">{agent.name}</span>
                      </span>
                    </Tag>
                  ))}
                </Flex>
              </div>
            </div>
          ) : (
            <div className="flex min-h-20 items-center justify-center gap-4 rounded-md border border-dashed border-gray-300 bg-white px-4 py-3">
            <div className="flex items-center gap-3">
              <div>
                <p className="text-sm font-medium text-gray-700"></p>
                <p className="mt-0.5 text-xs text-gray-400">
                暂未选择协作智能体，点击「选择智能体」添加
                </p>
              </div>
            </div>
          </div>
          )}
        </div>
      </Col>
    </>
  );
}
