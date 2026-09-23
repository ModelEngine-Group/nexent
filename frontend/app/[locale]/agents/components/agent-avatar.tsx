"use client";

import { createElement } from "react";
import { Avatar } from "antd";

import { getAgentIcon } from "@/lib/chat/agentIconUtils";
import { API_ENDPOINTS } from "@/services/api";
import type { Agent } from "@/types/agentConfig";

interface AgentAvatarProps {
  agent: Agent;
  size: number;
  iconSize: number;
}

export default function AgentAvatar({
  agent,
  size,
  iconSize,
}: AgentAvatarProps) {
  const defaultIcon = createElement(getAgentIcon(agent), {
    size: iconSize,
    "aria-hidden": true,
  });
  const agentId = Number(agent.id);
  const iconSource =
    agent.icon_url?.trim() && Number.isInteger(agentId) && agentId > 0
      ? API_ENDPOINTS.agent.icon(agentId)
      : undefined;

  return (
    <Avatar
      shape="square"
      size={size}
      src={iconSource}
      icon={defaultIcon}
      className="!rounded-xl !bg-primary/10 !text-primary"
    />
  );
}
