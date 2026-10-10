"use client";

import type { FC } from "react";
import { useMemo } from "react";
import { Dropdown } from "antd";
import type { MenuProps } from "antd";
import { ChevronDown } from "lucide-react";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { useConversationAgentHistory } from "@/hooks/chat/useConversationAgentHistory";
import { useThreadAgentRegistryVersion } from "../adapter/thread-agent-registry";
import { getAgentIcon } from "@/lib/chat/agentIconUtils";
import type { Agent, PublishedAgent } from "@/types/agentConfig";

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
  const { data: conversations } = useConversationAgentHistory();
  // Re-read the session recency list whenever a new selection is registered so
  // the "most recently used" agent updates immediately after picking a card.
  const registryVersion = useThreadAgentRegistryVersion();

  const usedAgentIds = useMemo(() => {
    const seen = new Set<number>();
    const ordered: number[] = [];
    for (const conversation of conversations ?? []) {
      const id = conversation.agent_id;
      if (typeof id === "number" && !seen.has(id)) {
        seen.add(id);
        ordered.push(id);
      }
    }
    try {
      const recent = JSON.parse(
        window.sessionStorage.getItem("nexent_recent_agent_ids") || "[]"
      );
      if (Array.isArray(recent)) {
        for (const id of recent) {
          if (typeof id === "number" && !seen.has(id)) {
            seen.add(id);
            ordered.unshift(id);
          }
        }
      }
    } catch {
      // ignore malformed session storage
    }
    void registryVersion;
    return ordered;
  }, [conversations, registryVersion]);

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

  return (
    <Dropdown
      menu={{ items: menuItems, onClick: handleMenuClick }}
      trigger={["click"]}
    >
      <button
        type="button"
        className="flex w-full cursor-pointer items-center gap-1.5 rounded-[4px] px-2 py-1 text-[16px] leading-[24px] text-[#191919] hover:bg-white"
      >
        <span className="min-w-0 flex-1 truncate text-left">
          {selectedAgent?.display_name ||
            selectedAgent?.name ||
            lastUsedAgent.display_name ||
            lastUsedAgent.name}
        </span>
        <ChevronDown className="size-4 shrink-0 text-[#808080]" aria-hidden />
      </button>
    </Dropdown>
  );
};
