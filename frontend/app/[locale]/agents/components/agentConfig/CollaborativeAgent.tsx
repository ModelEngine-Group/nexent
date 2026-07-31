"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Tag, App, Flex, Dropdown, Col, Button } from "antd";
import { Plus, Globe } from "lucide-react";
import { Agent } from "@/types/agentConfig";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { useExternalAgents } from "@/hooks/agent/useExternalAgents";
import { a2aClientService, A2AExternalAgent } from "@/services/a2aService";

export default function CollaborativeAgent() {
  const { t } = useTranslation("common");
  const { message: messageApi } = App.useApp();

  const currentAgentId = useAgentConfigStore((state) => state.currentAgentId);
  const isCreatingMode = useAgentConfigStore((state) => state.isCreatingMode);
  const editedAgent = useAgentConfigStore((state) => state.editedAgent);
  const updateSubAgentIds = useAgentConfigStore((state) => state.updateSubAgentIds);
  const updateSubAgentRelations = useAgentConfigStore((state) => state.updateSubAgentRelations);
  const updateExternalSubAgentIds = useAgentConfigStore((state) => state.updateExternalSubAgentIds);

  const { availableAgents: internalAgents } = usePublishedAgentList();
  const { availableAgents: externalAgents } = useExternalAgents();

  // Local state for edit mode (when currentAgentId exists)
  const [externalRelatedAgents, setExternalRelatedAgents] = useState<A2AExternalAgent[]>([]);

  // External agent IDs from store (for creation mode)
  const externalSubAgentIdList = editedAgent?.external_sub_agent_id_list || [];

  // Store-based external agents for creation mode
  const externalRelatedAgentsFromStore = (Array.isArray(externalAgents) ? externalAgents : []).filter(
    (agent: A2AExternalAgent) => externalSubAgentIdList.includes(agent.id)
  );

  // isReadOnly from store: isCreatingMode → false, READ_ONLY permission → true
  const isReadOnly = useAgentConfigStore((state) => state.isReadOnly());

  // Related internal agent IDs
  const relatedAgentIds = Array.isArray(editedAgent?.sub_agent_id_list) ? editedAgent.sub_agent_id_list : [];

  // Map of agent_id -> saved version info (from snapshot)
  const savedVersionMap = (() => {
    const map: Record<number, { version_no: number; version_name?: string }> = {};
    (editedAgent?.sub_agent_relations || []).forEach((rel) => {
      if (rel.version_no !== null && rel.version_no !== undefined) {
        map[rel.agent_id] = {
          version_no: rel.version_no,
          version_name: rel.version_name,
        };
      }
    });
    return map;
  })();

  // Related internal agents (from published list) with saved version info
  const relatedInternalAgents = (Array.isArray(internalAgents) ? internalAgents : []).filter(
    (agent: Agent) => relatedAgentIds.includes(Number(agent.id))
  ).map((agent: Agent) => {
    const savedVersion = savedVersionMap[Number(agent.id)];
    return {
      ...agent,
      // Override version_name with saved version from sub_agent_relations
      version_name: savedVersion?.version_name || agent.version_name || null,
    };
  });

  // Available internal agents (exclude already related ones and current agent)
  const availableInternalAgents = (Array.isArray(internalAgents) ? internalAgents : []).filter(
    (agent: Agent) => !relatedAgentIds.includes(Number(agent.id)) && Number(agent.id) !== currentAgentId
  );

  // Related external agent IDs (combine local state for edit mode + store for creation mode)
  const relatedExternalAgentIds: number[] = isCreatingMode
    ? externalSubAgentIdList
    : externalRelatedAgents.map((agent) => agent.id);

  // Available external agents (exclude already related ones)
  const availableExternalForSelection = (Array.isArray(externalAgents) ? externalAgents : []).filter(
    (agent: A2AExternalAgent) => !relatedExternalAgentIds.includes(agent.id)
  );

  // External agents to display (from store for creation mode, from API for edit mode)
  const displayExternalAgents = isCreatingMode ? externalRelatedAgentsFromStore : externalRelatedAgents;

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

  // Add internal agent
  const handleSelectInternalAgent = (agentId: number) => {
    const newRelatedAgentIds = [...(Array.isArray(relatedAgentIds) ? relatedAgentIds : []), agentId];
    updateSubAgentIds(newRelatedAgentIds);

    // Sync sub_agent_relations: add new agent with its current published version_no
    const selectedAgent = (Array.isArray(internalAgents) ? internalAgents : []).find(
      (a: Agent) => Number(a.id) === agentId
    );
    const currentVersionNo = selectedAgent?.current_version_no ?? null;
    const existingRelations = editedAgent?.sub_agent_relations || [];
    const newRelations = [
      ...existingRelations,
      { agent_id: agentId, version_no: currentVersionNo, version_name: selectedAgent?.version_name },
    ];
    updateSubAgentRelations(newRelations);
  };

  // Add external agent
  const handleSelectExternalAgent = async (externalAgentId: number) => {
    if (isCreatingMode) {
      const newRelatedAgentIds = [...externalSubAgentIdList, externalAgentId];
      updateExternalSubAgentIds(newRelatedAgentIds);
    } else if (currentAgentId) {
      const result = await a2aClientService.addRelation(Number(currentAgentId), externalAgentId);
      if (result.success) {
        messageApi.success(t("a2a.service.addRelationSuccess"));
        // Sync the store so save() sends the updated external_sub_agent_id_list
        updateExternalSubAgentIds([...externalSubAgentIdList, externalAgentId]);
        loadExternalRelatedAgents();
      } else {
        messageApi.error(result.message || t("a2a.service.addRelationFailed"));
      }
    }
  };

  // Remove internal agent
  const handleRemoveInternalAgent = (agentId: number) => {
    const newRelatedAgentIds = (Array.isArray(relatedAgentIds) ? relatedAgentIds : []).filter(
      (id: number) => id !== agentId
    );
    updateSubAgentIds(newRelatedAgentIds);

    // Sync sub_agent_relations: remove the agent
    const existingRelations = editedAgent?.sub_agent_relations || [];
    const newRelations = existingRelations.filter(
      (rel: { agent_id: number; version_no: number | null; version_name?: string }) => rel.agent_id !== agentId
    );
    updateSubAgentRelations(newRelations);
  };

  // Remove external agent
  const handleRemoveExternalAgent = async (agentId: number) => {
    if (isCreatingMode) {
      const newRelatedAgentIds = externalSubAgentIdList.filter((id) => id !== agentId);
      updateExternalSubAgentIds(newRelatedAgentIds);
    } else if (currentAgentId) {
      const result = await a2aClientService.removeRelation(Number(currentAgentId), agentId);
      if (result.success) {
        messageApi.success(t("a2a.service.removeRelationSuccess"));
        // Sync the store so save() sends the updated external_sub_agent_id_list
        updateExternalSubAgentIds(externalSubAgentIdList.filter((id) => id !== agentId));
        loadExternalRelatedAgents();
      } else {
        messageApi.error(result.message || t("a2a.service.removeRelationFailed"));
      }
    }
  };

  // Unified dropdown menu items
  const dropdownMenuItems = [
    // Internal agents group
    {
      key: "internal",
      type: "group" as const,
      label: t("collaborativeAgent.internalAgents"),
      children: availableInternalAgents.map((agent: Agent) => ({
        key: `internal-${agent.id}`,
        label: (
          <div className="flex items-center justify-between w-full">
            <span>{agent.display_name || agent.name}</span>
            {agent.version_name && (
              <span className="text-xs text-gray-400 ml-2">{agent.version_name}</span>
            )}
          </div>
        ),
        onClick: () => handleSelectInternalAgent(Number(agent.id)),
      })),
    },
    // External A2A agents group
    {
      key: "external",
      type: "group" as const,
      label: t("collaborativeAgent.externalAgents"),
      children: availableExternalForSelection.map((agent: A2AExternalAgent) => ({
        key: `external-${agent.id}`,
        label: (
          <div className="flex items-center justify-between w-full">
            <span className="flex items-center gap-2">
              <Globe size={12} />
              {agent.name}
            </span>
            {agent.version && (
              <span className="text-xs text-gray-400 ml-2">v{agent.version}</span>
            )}
          </div>
        ),
        onClick: () => handleSelectExternalAgent(agent.id),
      })),
    },
  ];

  return (
    <>
      {/* Agent Selection & Lists */}
      <Col xs={24} className="border-2 p-4 rounded-md min-h-[100px] flex items-center bg-gray-50">
        {/* Add Button with Dropdown */}
        <Flex justify="flex-start" align="center" className="w-full">
          <Dropdown
            menu={{ items: dropdownMenuItems }}
            disabled={isReadOnly}
            trigger={["click"]}
          >
            <div className="flex items-center shrink-0">
              <Button
                icon={<Plus size={14} />}
                disabled={isReadOnly}
                className={`${isReadOnly ? "!bg-gray-50" : "hover:!border-2 hover:!border-dashed hover:!border-blue-500 hover:!text-blue-500 hover:!bg-blue-50 transition-colors"}`}
                style={{ border: '2px dashed #9ca3af' }}
              >
              </Button>
            </div>
          </Dropdown>
          <div className="ml-4">
            {/* Internal Agents List */}
            <div className={relatedInternalAgents.length > 0 && displayExternalAgents.length > 0 ? "mb-3" : ""}>
              <Flex className="flex flex-wrap items-center gap-2">
              {relatedInternalAgents.map((agent: Agent) => (
                <Tag
                  key={`internal-${agent.id}`}
                  closable={!isReadOnly}
                  onClose={!isReadOnly ? () => handleRemoveInternalAgent(Number(agent.id)) : undefined}
                  className="bg-blue-50 text-blue-700 border-blue-200"
                >
                  <span className="flex items-center gap-1">
                    {agent.display_name || agent.name}
                    {agent.version_name && (
                      <span className="text-xs text-blue-400">{agent.version_name}</span>
                    )}
                  </span>
                </Tag>
              ))}
              </Flex>
            </div>
            
            {/* External Agents List */}
            <div >
              <Flex className="flex flex-wrap items-center gap-2">  
              {displayExternalAgents.map((agent) => (
                <Tag
                  key={`external-${agent.id}`}
                  closable={!isReadOnly}
                  onClose={!isReadOnly ? () => handleRemoveExternalAgent(agent.id) : undefined}
                  className="bg-green-50 text-green-700 border-green-200"
                >
                  <span className="inline-flex items-center gap-1">
                    <Globe size={12} />
                    {agent.name}
                    {agent.version && (
                      <span className="text-xs text-green-400">v{agent.version}</span>
                    )}
                  </span>
                </Tag>
              ))}
              </Flex>
            </div>
          </div>
        </Flex>
      </Col>
    </>
  );
}
