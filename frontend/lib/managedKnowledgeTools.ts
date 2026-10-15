// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { Tool } from "@/types/agentConfig";

export const MANAGED_KNOWLEDGE_TOOL_NAMES = [
  "knowledge_base_search",
  "aidp_search",
] as const;

export type ManagedKnowledgeToolName =
  (typeof MANAGED_KNOWLEDGE_TOOL_NAMES)[number];

export const AIDP_NON_PERSISTED_PARAM_NAMES = new Set([
  "display_names",
  "server_url",
  "api_key",
  "tenant_id",
  "kds_name_to_id_map",
  "observer",
]);

export const getSemanticToolName = (tool: Pick<Tool, "name" | "origin_name">) =>
  tool.origin_name || tool.name;

export const isManagedKnowledgeTool = (
  tool: Pick<Tool, "name" | "origin_name">
): boolean =>
  MANAGED_KNOWLEDGE_TOOL_NAMES.includes(
    getSemanticToolName(tool) as ManagedKnowledgeToolName
  );

export const isAidpManagedKnowledgeTool = (
  tool: Pick<Tool, "name" | "origin_name">
): boolean => getSemanticToolName(tool) === "aidp_search";

/** Knowledge range param name per managed retrieval tool. */
export const KNOWLEDGE_RANGE_PARAM_BY_TOOL_NAME: Record<string, string> = {
  knowledge_base_search: "index_names",
  aidp_search: "kds_list",
};

/** Return the persisted range param of a managed knowledge tool, or null. */
export const getKnowledgeRangeParam = (
  tool: Pick<Tool, "name" | "origin_name">
): string | null =>
  KNOWLEDGE_RANGE_PARAM_BY_TOOL_NAME[getSemanticToolName(tool)] ?? null;

/**
 * Normalize a persisted or submitted knowledge id collection into unique ids.
 *
 * Accepts arrays, JSON-encoded strings, and comma separated legacy strings so a
 * removal diff can never miss an id because of its storage form.
 */
export const parseKnowledgeIds = (value: unknown): string[] => {
  const normalize = (values: unknown[]): string[] =>
    Array.from(
      new Set(values.map((item) => String(item).trim()).filter(Boolean))
    );

  if (Array.isArray(value)) return normalize(value);
  if (typeof value !== "string" || !value.trim()) return [];
  try {
    const parsed = JSON.parse(value);
    if (Array.isArray(parsed)) return normalize(parsed);
    if (typeof parsed === "string") return normalize(parsed.split(","));
  } catch {
    return normalize(value.split(","));
  }
  return [];
};
