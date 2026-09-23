"use client";

import { Avatar } from "antd";
import { createElement } from "react";
import {
  getAgentIcon,
  getAgentUploadedIconId,
} from "@/lib/chat/agentIconUtils";
import { API_ENDPOINTS } from "@/services/api";
import type { MyEditableAgentItem } from "@/types/agentRepository";

interface MyAgentIconProps {
  agent: Pick<MyEditableAgentItem, "agent_id" | "icon_url">;
  size: number;
  iconSize: number;
}

export function MyAgentIcon({ agent, size, iconSize }: MyAgentIconProps) {
  const fallbackIcon = createElement(
    getAgentIcon({ agent_id: agent.agent_id }),
    {
      size: iconSize,
      "aria-hidden": true,
    }
  );
  const uploadedIconId = getAgentUploadedIconId(agent);

  return (
    <Avatar
      shape="square"
      size={size}
      src={
        uploadedIconId === null
          ? undefined
          : API_ENDPOINTS.agent.icon(uploadedIconId)
      }
      icon={fallbackIcon}
      className="!shrink-0 !rounded-xl !bg-primary/10 !text-primary"
    />
  );
}
