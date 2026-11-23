// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { Tool } from "@/types/agentConfig";
import type { KnowledgeBase } from "@/types/knowledgeBase";
import {
  AIDP_NON_PERSISTED_PARAM_NAMES,
  getSemanticToolName,
  isManagedKnowledgeTool,
  type ManagedKnowledgeToolName,
} from "@/lib/managedKnowledgeTools";
import type { Nl2aResourceCandidate } from "../adapter/remote-chat-model-adapter";
import type { Nl2AgentResourceParam } from "./nl2agent-resource-config";

export function knowledgeToolName(
  candidate: Nl2aResourceCandidate,
  canonicalTool?: Tool
): ManagedKnowledgeToolName | null {
  if (candidate.resource_type !== "tool") return null;
  const identity = canonicalTool ?? { name: candidate.name };
  return isManagedKnowledgeTool(identity)
    ? (getSemanticToolName(identity) as ManagedKnowledgeToolName)
    : null;
}

export function knowledgeSelectionIds(
  params: Nl2AgentResourceParam[],
  toolName: ManagedKnowledgeToolName
): string[] {
  let value: unknown = params.find(
    (param) =>
      param.name === (toolName === "aidp_search" ? "kds_list" : "index_names")
  )?.value;
  if (typeof value === "string") {
    const text = value.trim();
    if (!text) return [];
    try {
      value = JSON.parse(text);
    } catch {
      value = text.startsWith("[") ? [] : text.split(",");
    }
  }
  if (!Array.isArray(value)) return [];
  return [
    ...new Set(
      value
        .filter((id) => typeof id === "string" || typeof id === "number")
        .map((id) => String(id).trim())
        .filter(Boolean)
    ),
  ];
}

export function withKnowledgeSelection(
  params: Nl2AgentResourceParam[],
  toolName: ManagedKnowledgeToolName,
  knowledgeBases: KnowledgeBase[]
): Nl2AgentResourceParam[] {
  const aidp = toolName === "aidp_search";
  const name = aidp ? "kds_list" : "index_names";
  const ids = [
    ...new Set(
      knowledgeBases.map((kb) =>
        aidp ? String(kb.id) : String(kb.index_name || kb.id)
      )
    ),
  ];
  const existing = params.find((param) => param.name === name);
  return [
    ...params.filter(
      (param) =>
        param.name !== name &&
        (!aidp || !AIDP_NON_PERSISTED_PARAM_NAMES.has(param.name))
    ),
    {
      ...existing,
      name,
      type: aidp ? "string" : "array",
      required: true,
      value: aidp ? JSON.stringify(ids) : ids,
    },
  ];
}

export function mergeKnowledgeConfig(
  params: Nl2AgentResourceParam[],
  toolName: ManagedKnowledgeToolName,
  values: Record<string, unknown>
): Nl2AgentResourceParam[] {
  const name = toolName === "aidp_search" ? "kds_list" : "index_names";
  // The selection can be a runtime input and absent from the tool config schema.
  const schema = params.some((param) => param.name === name)
    ? params
    : [
        ...params,
        {
          name,
          type:
            toolName === "aidp_search"
              ? ("string" as const)
              : ("array" as const),
          required: true,
        },
      ];
  return schema
    .filter(
      (param) =>
        toolName !== "aidp_search" ||
        !AIDP_NON_PERSISTED_PARAM_NAMES.has(param.name)
    )
    .map((param) =>
      Object.prototype.hasOwnProperty.call(values, param.name)
        ? { ...param, value: values[param.name] }
        : { ...param }
    );
}
