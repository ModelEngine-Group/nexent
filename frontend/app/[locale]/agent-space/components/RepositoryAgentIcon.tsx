"use client";

import { Avatar } from "antd";
import { createElement } from "react";
import { getAgentIcon } from "@/lib/chat/agentIconUtils";
import { withBasePath } from "@/lib/basePath";

interface RepositoryAgentIconProps {
  agentId?: number | null;
  iconUrl?: string | null;
  size: number;
  iconSize: number;
}

export function RepositoryAgentIcon({
  agentId,
  iconUrl,
  size,
  iconSize,
}: RepositoryAgentIconProps) {
  const DefaultIcon = getAgentIcon({ agent_id: agentId ?? 0 });
  return (
    <Avatar
      shape="square"
      size={size}
      src={iconUrl?.trim() ? withBasePath(iconUrl) : undefined}
      icon={createElement(DefaultIcon, { size: iconSize, "aria-hidden": true })}
      className="!shrink-0 !rounded-xl !bg-primary/10 !text-primary"
    />
  );
}
