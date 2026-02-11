"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Tag, App, Card, Flex, Dropdown, Space, Col } from "antd";
import { Plus, X } from "lucide-react";
import { Agent } from "@/types/agentConfig";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useAgentList } from "@/hooks/agent/useAgentList";
import { useAgentInfo } from "@/hooks/agent/useAgentInfo";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";

interface CollaborativeAgentProps {}

export default function CollaborativeAgent({}: CollaborativeAgentProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { user } = useAuthorizationContext();

  const currentAgentId = useAgentConfigStore((state) => state.currentAgentId);
  const isCreatingMode = useAgentConfigStore((state) => state.isCreatingMode);
  const currentAgentPermission = useAgentConfigStore(
    (state) => state.currentAgentPermission
  );
  const editedAgent = useAgentConfigStore((state) => state.editedAgent);
  const updateSubAgentIds = useAgentConfigStore(
    (state) => state.updateSubAgentIds
  );

  const { availableAgents } = useAgentList(user?.tenantId ?? null);

  const editable =
    !!isCreatingMode ||
    ((currentAgentId != null && currentAgentId != undefined) &&
      currentAgentPermission !== "READ_ONLY");

  // Get related agents - use edited agent state (which includes current agent data when editing)
  const relatedAgentIds = Array.isArray(editedAgent?.sub_agent_id_list)
    ? editedAgent.sub_agent_id_list
    : [];

  const relatedAgents = (
    Array.isArray(availableAgents) ? availableAgents : []
  ).filter((agent: Agent) => relatedAgentIds.includes(Number(agent.id)));

  // Filter available agents (exclude already related ones and current agent)
  const availableAgentsForMenu = (
    Array.isArray(availableAgents) ? availableAgents : []
  ).filter(
    (agent: Agent) =>
      !relatedAgentIds.includes(Number(agent.id)) &&
      Number(agent.id) !== currentAgentId
  );

  const handleAddAgent = (agentId: number) => {
    const newRelatedAgentIds = [
      ...(Array.isArray(relatedAgentIds) ? relatedAgentIds : []),
      agentId,
    ];
    updateSubAgentIds(newRelatedAgentIds);
  };

  const handleRemoveAgent = (agentId: number) => {
    const newRelatedAgentIds = (
      Array.isArray(relatedAgentIds) ? relatedAgentIds : []
    ).filter((id: number) => id !== agentId);
    updateSubAgentIds(newRelatedAgentIds);
  };

  const addRelatedAgent = (event: React.MouseEvent) => {};

  const menuItems = Array.isArray(availableAgentsForMenu)
    ? availableAgentsForMenu.map((agent: Agent) => ({
        key: String(agent.id),
        label: (
          <>
            <span>{agent.display_name || agent.name}</span>
            {agent.display_name && (
              <span className="ml-2 text-xs text-gray-400">({agent.name})</span>
            )}
          </>
        ),
        onClick: () => handleAddAgent(Number(agent.id)),
      }))
    : [];

  return (
    <>
      <Col xs={24}>
        <h4 className="text-md font-medium text-gray-700">
          {t("collaborativeAgent.title")}
        </h4>
      </Col>
      <Col xs={24}>
        <Flex className="w-full">
          <Card
            className="w-full bg-gray-50 rounded-md border-2 border-gray-200 h-24"
            styles={{ body: { padding: "16px" } }}
          >
            <Flex justify="flex-start" align="center" className="h-full">
              <Dropdown
                menu={{
                  items: menuItems,
                }}
                disabled={!editable}
              >
                <button
                  type="button"
                  onClick={addRelatedAgent}
                  disabled={!editable}
                  className={`flex-shrink-0 box-border flex items-center justify-center w-8 h-8 border-2 border-dashed transition-colors duration-200 ${
                    editable
                      ? "border-blue-400 text-blue-500 hover:border-blue-500 hover:text-blue-600 hover:bg-blue-50"
                      : "border-gray-300 text-gray-400 cursor-not-allowed"
                  }`}
                  title={editable ? t("collaborativeAgent.button.add") : ""}
                >
                  <Plus size={16} />
                </button>
              </Dropdown>
              <div className="h-full overflow-y-auto ml-4">
                <Flex className="flex flex-wrap items-center h-full gap-2">
                  {relatedAgents.map((agent: Agent) => (
                    <Tag
                      key={agent.id}
                      closable={!!editable}
                      onClose={() => handleRemoveAgent(Number(agent.id))}
                      className="bg-blue-50 text-blue-700 border-blue-200 truncate"
                      style={{
                        maxWidth: "200px",
                      }}
                    >
                      {agent.display_name || agent.name}
                    </Tag>
                  ))}
                </Flex>
              </div>
            </Flex>
          </Card>
        </Flex>
      </Col>
    </>
  );
}
