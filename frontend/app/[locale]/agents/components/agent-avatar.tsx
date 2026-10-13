"use client";

import { createElement } from "react";
import { Avatar } from "antd";

import {
  getAgentIcon,
  getAgentUploadedIconRevision,
} from "@/lib/chat/agentIconUtils";
import { API_ENDPOINTS } from "@/services/api";
import { cn } from "@/lib/utils";
import type { Agent } from "@/types/agentConfig";

interface AgentAvatarProps {
  agent: Agent;
  size: number;
  iconSize: number;
  className?: string;
}

export default function AgentAvatar({
  agent,
  size,
  iconSize,
  className,
}: AgentAvatarProps) {
  const defaultIcon = createElement(getAgentIcon(agent), {
    size: iconSize,
    "aria-hidden": true,
  });
  const agentId = Number(agent.id);
  const iconSource =
    agent.icon_url?.trim() && Number.isInteger(agentId) && agentId > 0
      ? API_ENDPOINTS.agent.icon(
          agentId,
          getAgentUploadedIconRevision(agent.icon_url)
        )
      : undefined;

  return (
    <Avatar
      shape="square"
      size={size}
      src={iconSource}
      icon={defaultIcon}
      className={cn("!rounded-xl !bg-primary/10 !text-primary", className)}
    />
  );
}
