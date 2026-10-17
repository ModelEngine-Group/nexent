// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { FC } from "react";
import { useMemo } from "react";
import { Dropdown, Tooltip } from "antd";
import type { MenuProps } from "antd";
import { ChevronDown } from "lucide-react";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { getAgentIcon } from "@/lib/chat/agentIconUtils";
import type { Agent, PublishedAgent } from "@/types/agentConfig";
import { useRecentAgentIds } from "./use-recent-agent-ids";

export interface AgentSelectorDropdownProps {
  selectedAgent?: Agent | null;
  onAgentSelected: (agent: Agent) => void;
}

/**
 * Top-bar agent selector for the conversation area: shows the most recently
 * used agent and expands to every agent that has had a conversation.
 * Renders nothing until there is conversation history.
 */
export const AgentSelectorDropdown: FC<AgentSelectorDropdownProps> = ({
  selectedAgent,
  onAgentSelected,
}) => {
  const { availableMainAgents, isLoading } = usePublishedAgentList();
  const usedAgentIds = useRecentAgentIds();

  const lastUsedAgent = useMemo(() => {
    for (const id of usedAgentIds) {
      const match = availableMainAgents.find(
        (agent) => (agent as unknown as PublishedAgent).agent_id === id
      );
      if (match) return match as unknown as PublishedAgent;
    }
    return null;
  }, [usedAgentIds, availableMainAgents]);

  const menuItems: MenuProps["items"] = useMemo(
    () =>
      usedAgentIds
        .map((id) => {
          const agent = availableMainAgents.find(
            (candidate) =>
              (candidate as unknown as PublishedAgent).agent_id === id
          ) as unknown as PublishedAgent | undefined;
          if (!agent) return null;
          const Icon = getAgentIcon(agent);
          return {
            key: String(agent.agent_id),
            icon: <Icon className="size-4 text-primary" aria-hidden />,
            label: agent.display_name || agent.name,
          };
        })
        .filter((item): item is NonNullable<typeof item> => item !== null),
    [usedAgentIds, availableMainAgents]
  );

  if (isLoading || !lastUsedAgent) {
    return null;
  }

  const handleMenuClick: MenuProps["onClick"] = ({ key }) => {
    const agent = availableMainAgents.find(
      (candidate) =>
        String((candidate as unknown as PublishedAgent).agent_id) === key
    ) as unknown as Agent | undefined;
    if (agent) {
      onAgentSelected(agent);
    }
  };

  const agentName =
    selectedAgent?.display_name ||
    selectedAgent?.name ||
    lastUsedAgent.display_name ||
    lastUsedAgent.name;

  return (
    <Dropdown
      menu={{ items: menuItems, onClick: handleMenuClick }}
      trigger={["click"]}
    >
      <button
        type="button"
        className="flex w-full cursor-pointer items-center gap-1.5 rounded-[4px] py-1 pl-0.5 pr-2 text-[16px] leading-[24px] text-[#191919] hover:bg-white"
      >
        <Tooltip title={agentName}>
          <span className="min-w-0 flex-1 truncate text-left">{agentName}</span>
        </Tooltip>
        <ChevronDown className="size-4 shrink-0 text-[#808080]" aria-hidden />
      </button>
    </Dropdown>
  );
};
