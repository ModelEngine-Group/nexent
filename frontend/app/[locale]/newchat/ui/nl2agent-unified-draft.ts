// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { Nl2aUnifiedResourcesPayload } from "../adapter/remote-chat-model-adapter";
import type { BindingItemState } from "./installed-resource-binding-card";

export interface UnifiedResourceDraft {
  queries: Record<string, string>;
  selections: Record<string, string[]>;
  items: BindingItemState[];
}

/** Migrate only unchanged requirement edges and resources with identical schemas. */
export function restoreUnifiedDraft(
  payload: Nl2aUnifiedResourcesPayload,
  initialized: BindingItemState[],
  previous?: UnifiedResourceDraft
): UnifiedResourceDraft {
  const selections: Record<string, string[]> = {};
  for (const row of payload.requirements) {
    const refs = row.covered_resources
      .map((resource) => resource.candidate_ref)
      .filter((ref) =>
        initialized.some(
          (item) =>
            item.resource.candidate.candidate_ref === ref &&
            item.resource.readiness !== "not_ready"
        )
      );
    const unchanged = previous?.queries[row.requirement_id] === row.query;
    const ready = initialized
      .filter(
        (item) =>
          item.bindingStatus === "bound" &&
          refs.includes(item.resource.candidate.candidate_ref)
      )
      .map((item) => item.resource.candidate.candidate_ref);
    selections[row.requirement_id] = unchanged
      ? (previous.selections[row.requirement_id] ?? []).filter((ref) =>
          refs.includes(ref)
        )
      : ready.length
        ? ready
        : refs.slice(0, 1);
  }
  const chosen = new Set(Object.values(selections).flat());
  const items = initialized.map((item) => {
    const ref = item.resource.candidate.candidate_ref;
    const old = previous?.items.find(
      (entry) => entry.resource.candidate.candidate_ref === ref
    );
    const retainsUnchangedEdge = payload.requirements.some(
      (row) =>
        previous?.queries[row.requirement_id] === row.query &&
        row.covered_resources.some((resource) => resource.candidate_ref === ref)
    );
    const sameSchema =
      item.resource.configuration_revision &&
      old?.resource.configuration_revision ===
        item.resource.configuration_revision;
    return {
      ...item,
      ...(old &&
      sameSchema &&
      retainsUnchangedEdge &&
      item.bindingStatus !== "bound"
        ? {
            draftParams: old.draftParams,
            configStatus: old.configStatus,
            knowledgeEdited: old.knowledgeEdited,
          }
        : {}),
      selected:
        (item.bindingStatus === "bound" &&
          item.resource.readiness !== "not_ready") ||
        chosen.has(ref),
    };
  });
  return {
    queries: Object.fromEntries(
      payload.requirements.map((row) => [row.requirement_id, row.query])
    ),
    selections,
    items,
  };
}
