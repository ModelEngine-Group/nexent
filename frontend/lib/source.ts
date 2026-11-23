// Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import type {
  JsonObject,
  SourceAttributes,
} from "@/types/source";

const knowledgeProviders: Record<string, string> = {
  knowledge_base_search: "Nexent",
  aidp_search: "AIDP",
  dify_search: "Dify",
  datamate_search: "DataMate",
  ragflow_search: "RAGFlow",
  idata_search: "iData",
  haotian_search: "Haotian",
  ind_aidp_search: "AIDP",
};

export function getSourceProvider(
  searchType?: string,
  toolSign?: string
): string | undefined {
  if (!searchType && ["j", "l"].includes(toolSign?.toLowerCase() ?? ""))
    return "AIDP";
  return searchType && Object.hasOwn(knowledgeProviders, searchType)
    ? knowledgeProviders[searchType]
    : undefined;
}

export function getSourceLabel(
  source: SourceAttributes & { sourceType?: string; url?: string },
  labels: {
    knowledgeBase: string;
    web: string;
    document: string;
    source: string;
  }
): string {
  const provider = getSourceProvider(source.searchType, source.toolSign);
  if (provider) return `${labels.knowledgeBase} · ${provider}`;
  if (source.sourceType === "document" || source.sourceType === "file")
    return labels.document;
  if (source.url) {
    try {
      return `${labels.web} · ${new URL(source.url).hostname.replace(/^www\./, "")}`;
    } catch {
      return labels.source;
    }
  }
  return labels.source;
}

export function getSourceAttributes(
  searchType: unknown,
  scoreDetails: unknown
): SourceAttributes {
  const details =
    scoreDetails && typeof scoreDetails === "object"
      ? (scoreDetails as Record<string, unknown>)
      : {};
  const { metadata, ...sourceReference } = details;
  return {
    searchType: typeof searchType === "string" ? searchType : undefined,
    sourceMetadata:
      metadata && typeof metadata === "object" && !Array.isArray(metadata)
        ? (metadata as JsonObject)
        : undefined,
    sourceReference,
  };
}

export function isAidpSource(source: SourceAttributes): boolean {
  return getSourceProvider(source.searchType, source.toolSign) === "AIDP";
}
