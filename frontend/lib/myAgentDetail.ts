import type { AgentVersionDetail } from "@/services/agentVersionService";
import type { MyEditableAgentItem } from "@/types/agentRepository";
import type { Agent, Skill, Tool } from "@/types/agentConfig";

export interface MyAgentDetailView {
  title: string;
  description: string;
  author: string | null;
  modelName: string | null;
  versionLabel: string | null;
  tools: string[];
  skills: string[];
  knowledgeBases: string[];
  subAgents: string[];
  tags: string[];
}

function uniqueNames(values: Array<string | null | undefined>): string[] {
  return Array.from(
    new Set(
      values
        .map((value) => value?.trim())
        .filter((value): value is string => Boolean(value))
    )
  );
}

export function mapMyAgentDetail(
  detail: AgentVersionDetail,
  agent: Pick<MyEditableAgentItem, "tags">,
  resources?: {
    tools?: Pick<Tool, "id" | "name" | "origin_name">[];
    skills?: Pick<Skill, "skill_id" | "name">[];
  }
): MyAgentDetailView {
  const toolNames = new Map(
    resources?.tools?.map((tool) => [
      String(tool.id),
      tool.origin_name || tool.name,
    ]) ?? []
  );
  const skillNames = new Map(
    resources?.skills?.map((skill) => [String(skill.skill_id), skill.name]) ??
      []
  );

  return {
    title: detail.display_name?.trim() || detail.name?.trim() || "",
    description: detail.description?.trim() || "",
    author: detail.author?.trim() || null,
    modelName:
      detail.model_names?.filter(Boolean).join(", ") ||
      detail.model_name?.trim() ||
      null,
    versionLabel: detail.version?.version_name?.trim() || null,
    tools: uniqueNames(
      detail.tools?.map(
        (tool) =>
          tool.origin_name ||
          tool.name ||
          toolNames.get(String(tool.tool_id)) ||
          `#${tool.tool_id}`
      ) ?? []
    ),
    skills: uniqueNames(
      detail.skills?.map(
        (skill) =>
          skill.name ||
          skillNames.get(String(skill.skill_id)) ||
          `#${skill.skill_id}`
      ) ?? []
    ),
    knowledgeBases: uniqueNames(
      detail.tools?.flatMap((tool) => tool.display_names ?? []) ?? []
    ),
    subAgents: uniqueNames(
      detail.sub_agent_relations?.map((relation) => relation.agent_name) ?? []
    ),
    tags: uniqueNames(agent.tags ?? []),
  };
}

export function mapAgentInfoDetail(agent: Agent): MyAgentDetailView {
  return {
    title: agent.display_name?.trim() || agent.name?.trim() || "",
    description: agent.description?.trim() || "",
    author: agent.author?.trim() || null,
    modelName: agent.model_names?.filter(Boolean).join(", ") || null,
    versionLabel:
      agent.version_name?.trim() ||
      (agent.current_version_no ? `V${agent.current_version_no}` : null),
    tools: uniqueNames(
      agent.tools?.map((tool) => tool.origin_name || tool.name) ?? []
    ),
    skills: uniqueNames(agent.skills?.map((skill) => skill.name) ?? []),
    knowledgeBases: uniqueNames(
      agent.tools?.flatMap((tool) => tool.display_names ?? []) ?? []
    ),
    subAgents: uniqueNames(
      agent.sub_agent_relations?.map((relation) => relation.agent_name) ?? []
    ),
    tags: uniqueNames(agent.tags ?? []),
  };
}
