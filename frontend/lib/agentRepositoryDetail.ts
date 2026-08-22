import type { AgentVersionDetail } from "@/services/agentVersionService";
import type {
  AgentRepositoryListingDetail,
  AgentRepositoryListingStatus,
} from "@/types/agentRepository";

export interface AgentDetailModalData {
  name: string;
  display_name?: string | null;
  description?: string | null;
  author?: string | null;
  icon?: string | null;
  status?: AgentRepositoryListingStatus;
  version_label?: string | null;
  downloads?: number;
  created_at?: string | null;
  model_name?: string | null;
  duty_prompt?: string | null;
  tools?: string[];
}

function extractToolNames(
  tools: Array<{ origin_name?: string; name?: string }> | undefined
): string[] {
  if (!tools?.length) {
    return [];
  }
  const names: string[] = [];
  for (const tool of tools) {
    const name = tool.origin_name?.trim() || tool.name?.trim();
    if (name) {
      names.push(name);
    }
  }
  return names;
}

export function mapRepositoryListingDetail(
  detail: AgentRepositoryListingDetail
): AgentDetailModalData {
  return {
    name: detail.name,
    display_name: detail.display_name,
    description: detail.description,
    author: detail.author,
    icon: detail.icon,
    status: detail.status,
    version_label: detail.version_label,
    downloads: detail.downloads,
    created_at: detail.created_at,
    model_name: detail.model_name,
    duty_prompt: detail.duty_prompt,
    tools: detail.tools,
  };
}

export function mapAgentVersionDetail(
  detail: AgentVersionDetail
): AgentDetailModalData {
  const versionMeta = detail.version as
    | { version_name?: string; create_time?: string }
    | undefined;

  return {
    name: detail.name,
    display_name: detail.display_name,
    description: detail.description,
    author: detail.author,
    model_name: detail.model_name,
    duty_prompt: detail.duty_prompt,
    version_label: versionMeta?.version_name ?? null,
    created_at: versionMeta?.create_time ?? null,
    tools: extractToolNames(
      detail.tools as Array<{ origin_name?: string; name?: string }>
    ),
  };
}
