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
    const map: Record<number, { agent_name?: string | null; version_no: number | null; version_name?: string | null }> = {};
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
    (Array.isArray(internalAgents) ? internalAgents : []).map((a: Agent) => [Number(a.id), a])
  );

  const relatedInternalAgents = relatedAgentIds.map((agentId: number) => {
    const publishedAgent = publishedAgentMap.get(Number(agentId));
    const savedVersion = savedVersionMap[Number(agentId)];
    const hasSavedVersion = savedVersion?.version_no != null;

    if (publishedAgent) {
      const version_name = (hasSavedVersion
        ? (savedVersion?.version_name ?? publishedAgent.version_name)
        : publishedAgent.version_name) ?? undefined;
      const version_no = (hasSavedVersion
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
  const internalMenuItems = availableInternalAgents.map((agent: Agent) => ({
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
  }));

  const externalMenuItems = availableExternalForSelection.map((agent: A2AExternalAgent) => ({
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
  }));

  const hasInternal = internalMenuItems.length > 0;
  const hasExternal = externalMenuItems.length > 0;

  const dropdownMenuItems = (() => {
    if (!hasInternal && !hasExternal) {
      return [{
        key: "no-agents",
        disabled: true,
        label: (
          <span className="text-gray-400">{t("collaborativeAgent.noAgents")}</span>
        ),
      }];
    }
    const items: any[] = [];
    if (hasInternal) {
      items.push({
        key: "internal",
        type: "group" as const,
        label: t("collaborativeAgent.internalAgents"),
        children: internalMenuItems,
      });
    }
    if (hasExternal) {
      items.push({
        key: "external",
        type: "group" as const,
        label: t("collaborativeAgent.externalAgents"),
        children: externalMenuItems,
      });
    }
    return items;
  })();

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
            styles={{ root: { maxHeight: '400px', overflowY: 'auto' } }}
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
                  className="!inline-flex !items-center !whitespace-nowrap !py-1.5 !px-3 !text-sm !bg-blue-50 !text-blue-700 !border !border-blue-200 !rounded-lg !shadow-sm hover:!shadow-md hover:!border-blue-400 transition-all"
                >
                  <span className="inline-flex items-center gap-1.5">
                    <span className="font-medium">{agent.display_name || agent.name}</span>
                    {agent.version_name && (
                      <span className="text-xs text-blue-500 bg-blue-100 px-1.5 py-0.5 rounded">{agent.version_name}</span>
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
        </Flex>
      </Col>
    </>
  );
}
