"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Tag, App, Flex, Dropdown, Col, Button, Card } from "antd";
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
  const currentAgentPermission = useAgentConfigStore((state) => state.currentAgentPermission);
  const editedAgent = useAgentConfigStore((state) => state.editedAgent);
  const updateSubAgentIds = useAgentConfigStore((state) => state.updateSubAgentIds);
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

  const editable = !!isCreatingMode || (currentAgentId != null && currentAgentPermission !== "READ_ONLY");

  // Related internal agent IDs
  const relatedAgentIds = Array.isArray(editedAgent?.sub_agent_id_list) ? editedAgent.sub_agent_id_list : [];

  // Related internal agents (from published list)
  const relatedInternalAgents = (Array.isArray(internalAgents) ? internalAgents : []).filter(
    (agent: Agent) => relatedAgentIds.includes(Number(agent.id))
  );

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
        label: agent.display_name || agent.name,
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
          <span className="flex items-center gap-2">
            <Globe size={12} />
            {agent.name}
          </span>
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
            disabled={!editable}
            trigger={["click"]}
          >
            <div className="flex items-center shrink-0">
              <Button
                icon={<Plus size={14} />}
                disabled={!editable}
                className={`${editable ? "hover:!border-2 hover:!border-dashed hover:!border-blue-500 hover:!text-blue-500 hover:!bg-blue-50 transition-colors" : "!bg-gray-50"}`}
                style={{ border: '2px dashed #9ca3af' }}
              >
              </Button>
            </div>
          </Dropdown>
          <div className="ml-4">
            {editable && (
              <>
                {/* Internal Agents List */}
                <div className={relatedInternalAgents.length > 0 && displayExternalAgents.length > 0 ? "mb-3" : ""}>
                  <Flex className="flex flex-wrap items-center gap-2">
                  {relatedInternalAgents.map((agent: Agent) => (
                    <Tag
                      key={`internal-${agent.id}`}
                      closable
                      onClose={() => handleRemoveInternalAgent(Number(agent.id))}
                      className="bg-blue-50 text-blue-700 border-blue-200"
                    >
                      {agent.display_name || agent.name}
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
                      closable
                      onClose={() => handleRemoveExternalAgent(agent.id)}
                      className="bg-green-50 text-green-700 border-green-200"
                    >
                      <span className="inline-flex items-center gap-1">
                        <Globe size={12} />
                        {agent.name}
                      </span>
                    </Tag>
                  ))}
                  </Flex>
                </div>
              </>
            )}
          </div>
        </Flex>
      </Col>
    </>
  );
}
