// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { AgentVersionDetail } from "@/services/agentVersionService";
import type {
  AgentRepositoryListingDetail,
  MyEditableAgentItem,
} from "@/types/agentRepository";
import type { Agent, Skill, Tool } from "@/types/agentConfig";
import type { ModelOption } from "@/types/modelConfig";
import type { KnowledgeBase } from "@/types/knowledgeBase";

export interface MyAgentDetailView {
  title: string;
  description: string;
  author: string | null;
  authorCasUsername?: string | null;
  modelName: string | null;
  versionLabel: string | null;
  tools: string[];
  skills: string[];
  knowledgeBases: string[];
  subAgents: string[];
  tags: string[];
  repositoryInfo?: {
    downloads: number;
    createdAt: string | null;
    publishedAt?: string | null;
    updatedAt?: string | null;
    modelNames?: string[];
    models?: ModelOption[];
    knowledgeDetails?: Map<string, KnowledgeBase>;
    skillTags?: Map<string, string[]>;
    toolTags?: Map<string, string[]>;
    subAgentTags?: Map<string, string[]>;
  };
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
    authorCasUsername: detail.author_cas_username,
    modelName: detail.model_name?.trim() || null,
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
    authorCasUsername: agent.author_cas_username,
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

export function mapRepositoryAgentDetail(
  versionDetail: AgentVersionDetail,
  listingDetail: AgentRepositoryListingDetail,
  tags: string[] = [],
  resources?: {
    tools?: Pick<Tool, "id" | "name" | "origin_name" | "labels">[];
    skills?: Pick<Skill, "skill_id" | "name" | "tags">[];
    models?: ModelOption[];
    knowledgeBases?: KnowledgeBase[];
    subAgents?: Array<{ name: string; tags: string[] }>;
  }
): MyAgentDetailView {
  const detail = mapMyAgentDetail(versionDetail, { tags }, resources);
  const knowledgeByIndex = new Map(
    resources?.knowledgeBases?.map((base) => [base.index_name || base.id, base])
  );
  const linkedKnowledge =
    versionDetail.tools?.flatMap(({ params }) => {
      return Array.isArray(params?.index_names)
        ? params.index_names.flatMap((index) => {
            const base = knowledgeByIndex.get(String(index));
            return base ? [base] : [];
          })
        : [];
    }) ?? [];
  const knowledgeDetails = new Map(
    linkedKnowledge.map((base) => [
      (base.display_name || base.name).trim(),
      base,
    ])
  );
  const skillById = new Map(
    resources?.skills?.map((skill) => [String(skill.skill_id), skill])
  );
  const toolById = new Map(
    resources?.tools?.map((tool) => [String(tool.id), tool])
  );
  return {
    ...detail,
    knowledgeBases: uniqueNames([
      ...detail.knowledgeBases,
      ...knowledgeDetails.keys(),
    ]),
    subAgents: uniqueNames([
      ...detail.subAgents,
      ...(resources?.subAgents?.map((agent) => agent.name) ?? []),
    ]),
    authorCasUsername:
      versionDetail.author_cas_username ??
      (versionDetail.author?.trim() === listingDetail.author?.trim()
        ? listingDetail.author_cas_username
        : undefined),
    repositoryInfo: {
      downloads: listingDetail.downloads ?? 0,
      createdAt: listingDetail.created_at ?? null,
      publishedAt: listingDetail.published_at ?? null,
      updatedAt: versionDetail.version?.update_time ?? null,
      modelNames: uniqueNames(versionDetail.model_names ?? []),
      knowledgeDetails,
      skillTags: new Map(
        versionDetail.skills?.flatMap((instance) => {
          const skill = skillById.get(String(instance.skill_id));
          const name = (instance.name || skill?.name)?.trim();
          return name && skill?.tags?.length
            ? [[name, uniqueNames(skill.tags)] as const]
            : [];
        })
      ),
      toolTags: new Map(
        versionDetail.tools?.flatMap((instance) => {
          const tool = toolById.get(String(instance.tool_id));
          const name = (
            instance.origin_name ||
            instance.name ||
            tool?.origin_name ||
            tool?.name
          )?.trim();
          return name && tool?.labels?.length
            ? [[name, uniqueNames(tool.labels)] as const]
            : [];
        })
      ),
      subAgentTags: new Map(
        resources?.subAgents?.map((agent) => [
          agent.name.trim(),
          uniqueNames(agent.tags),
        ])
      ),
      models: resources?.models?.filter((model) =>
        versionDetail.model_ids?.includes(model.id)
      ),
    },
  };
}

export function mapOfficialRepositoryDetail(
  detail: AgentRepositoryListingDetail,
  tags: string[] = []
): MyAgentDetailView {
  return {
    title: detail.display_name?.trim() || detail.name?.trim() || "",
    description: detail.description?.trim() || "",
    author: detail.author?.trim() || null,
    authorCasUsername: detail.author_cas_username,
    modelName: detail.model_name?.trim() || null,
    versionLabel: detail.version_label?.trim() || null,
    tools: uniqueNames(detail.tools ?? []),
    skills: [],
    knowledgeBases: [],
    subAgents: [],
    tags: uniqueNames(tags),
    repositoryInfo: {
      downloads: detail.downloads ?? 0,
      createdAt: detail.created_at ?? null,
    },
  };
}
