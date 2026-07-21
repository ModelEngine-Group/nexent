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
import type { PublishedAgent } from "@/types/agentConfig";

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
 * 2. Fall back to agent_id based icon
 * 3. Default to SparklesIcon
 */
export function getAgentIcon(agent: Agent | PublishedAgent): LucideIcon {
  const typedAgent = agent as PublishedAgent;
  // Try icon property first
  const iconType = (typedAgent as PublishedAgent & { icon?: AgentIconType }).icon;
  if (iconType && agentIconMap[iconType]) {
    return agentIconMap[iconType];
  }

  // Fall back to agent_id based icon
  if (typedAgent.agent_id !== undefined) {
    return agentIcons[typedAgent.agent_id % agentIcons.length];
  }

  return SparklesIcon;
}
