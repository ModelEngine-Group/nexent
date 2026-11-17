// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import knowledgeBaseService from "@/services/knowledgeBaseService";
import type {
  ConversationKnowledgeScope,
  KnowledgeScopeEffectivePreview,
} from "@/types/knowledgeScope";

export async function restoreKnowledgeDisplay(
  scope: ConversationKnowledgeScope | null,
  lookupNames = true
): Promise<KnowledgeScopeEffectivePreview | null> {
  if (!scope) return null;
  const [local, aidp] = await Promise.all([
    lookupNames &&
    scope.local.mode === "override" &&
    scope.local.knowledge_ids.length
      ? knowledgeBaseService.getKnowledgeBasesInfo(true, false)
      : null,
    lookupNames && scope.aidp.mode === "override" && scope.aidp.kds_ids.length
      ? knowledgeBaseService.getAidpKnowledgeBasesAll()
      : null,
  ]);
  const localNames = new Map(
    (local?.knowledgeBases ?? []).map((kb) => [
      String(kb.knowledge_id),
      kb.display_name || kb.name,
    ])
  );
  const aidpNames = new Map(
    knowledgeBaseService
      .mapAidpKnowledgeBasesToKnowledgeBases(aidp?.value ?? [])
      .map((kb) => [String(kb.id), kb.display_name || kb.name])
  );
  return {
    local: {
      disabled: scope.local.mode === "disabled",
      knowledge_ids: scope.local.knowledge_ids,
      display_names: scope.local.knowledge_ids.map(
        (id) => localNames.get(id) || `#${id}`
      ),
    },
    aidp: {
      disabled: scope.aidp.mode === "disabled",
      kds_ids: scope.aidp.kds_ids,
      display_names: scope.aidp.kds_ids.map(
        (id) => aidpNames.get(id) || `#${id}`
      ),
    },
  };
}
