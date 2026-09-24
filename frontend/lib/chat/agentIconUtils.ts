import type { LucideIcon } from "lucide-react";
import {
  SparklesIcon,
  BotIcon,
  WandIcon,
  LightbulbIcon,
  ZapIcon,
  CodeIcon,
  SearchIcon,
  FileTextIcon,
} from "lucide-react";
import type { Agent, PublishedAgent } from "@/types/agentConfig";

type AgentIconType = "sparkles" | "code" | "search" | "file";

const agentIconMap: Record<AgentIconType, LucideIcon> = {
  sparkles: SparklesIcon,
  code: CodeIcon,
  search: SearchIcon,
  file: FileTextIcon,
};

const agentIcons = [SparklesIcon, BotIcon, WandIcon, LightbulbIcon, ZapIcon];

/**
 * Get icon for an agent, with fallback logic:
 * 1. Try icon property from agent
 * 2. Fall back to the agent ID based icon
 * 3. Default to SparklesIcon
 */
export function getAgentIcon(
  agent: Agent | PublishedAgent | { agent_id: number }
): LucideIcon {
  const typedAgent = agent as PublishedAgent;
  // Try icon property first
  const iconType = (typedAgent as PublishedAgent & { icon?: AgentIconType })
    .icon;
  if (iconType && agentIconMap[iconType]) {
    return agentIconMap[iconType];
  }

  // Agent list items expose id; published agents also expose agent_id.
  const agentId = Number("agent_id" in agent ? agent.agent_id : agent.id);
  if (Number.isInteger(agentId) && agentId >= 0) {
    return agentIcons[agentId % agentIcons.length];
  }

  return SparklesIcon;
}

export function getAgentUploadedIconId(agent: {
  agent_id: number;
  icon_url?: string | null;
}): number | null {
  return agent.icon_url?.trim() &&
    Number.isInteger(agent.agent_id) &&
    agent.agent_id > 0
    ? agent.agent_id
    : null;
}

export function getAgentUploadedIconRevision(iconUrl?: string | null): string | null {
  const query = iconUrl?.split("?", 2)[1];
  return query ? new URLSearchParams(query).get("v") : null;
}
