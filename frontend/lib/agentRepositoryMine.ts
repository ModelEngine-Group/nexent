// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { AgentRepositoryListingItem } from "@/types/agentRepository";
import type { TagAssignmentValue, TagDefinition } from "@/types/tagManagement";

export function pickApplyListingPrefillSource(
  items: AgentRepositoryListingItem[],
  currentVersionLabel?: string | null
): AgentRepositoryListingItem | null {
  const normalizedVersion = currentVersionLabel?.trim();
  if (normalizedVersion) {
    const byVersion = items.find(
      (item) => item.version_label?.trim() === normalizedVersion
    );
    if (byVersion) {
      return byVersion;
    }
  }

  const shared = items.find((item) => item.status === "shared");
  return shared ?? null;
}

export interface ApplyListingFormPrefill {
  icon_url: string | null;
  tags: string[];
}

export function getListingTagsFromAssignments(
  assignments: Pick<
    TagAssignmentValue,
    "definition_id" | "value_id" | "display_value"
  >[],
  agentCategory: Pick<TagDefinition, "definition_id" | "values"> | null
): string[] {
  const tags: string[] = [];
  const seen = new Set<string>();
  for (const assignment of assignments) {
    const categoryValue =
      assignment.definition_id === agentCategory?.definition_id
        ? agentCategory.values?.find(
            (value) => value.value_id === assignment.value_id
          )
        : null;
    const tag = (
      categoryValue?.normalized_value || assignment.display_value
    ).trim();
    const key = tag.toLocaleLowerCase();
    if (key && !seen.has(key)) {
      seen.add(key);
      tags.push(tag);
    }
  }
  return tags;
}

function normalizeApplyListingTags(tags: string[], maxTags: number): string[] {
  const normalized: string[] = [];
  const seen = new Set<string>();
  for (const rawTag of tags) {
    const tag = rawTag.trim();
    if (!tag || seen.has(tag)) {
      continue;
    }
    seen.add(tag);
    normalized.push(tag);
    if (normalized.length >= maxTags) {
      break;
    }
  }
  return normalized;
}

export function buildApplyListingFormPrefill(
  item: AgentRepositoryListingItem | null,
  options: {
    maxTags?: number;
  } = {}
): ApplyListingFormPrefill | null {
  if (!item) {
    return null;
  }

  const maxTags = options.maxTags ?? 5;
  const tags = normalizeApplyListingTags(item.tags ?? [], maxTags);

  return {
    icon_url: item.icon_url?.trim() || null,
    tags,
  };
}
