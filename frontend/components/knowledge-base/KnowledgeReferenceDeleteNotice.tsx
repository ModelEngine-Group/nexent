// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";

import type { KnowledgeReferencePreview } from "@/types/knowledgeResource";

/**
 * Extra content for the knowledge-base delete confirmation dialog.
 *
 * Deletion cascades on the backend: agent bindings (draft and published
 * versions alike) and conversation scopes are removed together with the
 * knowledge base. Agents are listed by name, one row per agent; conversations
 * are covered by a fixed notice instead of being enumerated.
 */
export default function KnowledgeReferenceDeleteNotice({
  preview,
}: {
  preview: KnowledgeReferencePreview | null;
}) {
  const { t } = useTranslation("common");
  if (!preview) return null;

  const agents = preview.agents ?? [];
  const hiddenCount = preview.hidden_agent_count ?? 0;
  if (agents.length === 0 && hiddenCount === 0) {
    return (
      <div className="mt-2 text-sm text-gray-600">
        {t("knowledgeResource.deleteNotice.conversationsNotice")}
      </div>
    );
  }

  return (
    <div className="mt-2 space-y-1 text-sm text-gray-600">
      {agents.length > 0 && (
        <>
          <div>{t("knowledgeResource.deleteNotice.agentsIntro")}</div>
          <ul
            className="max-h-40 list-inside list-disc overflow-y-auto"
            data-testid="knowledge-reference-delete-agents"
          >
            {agents.map((agent) => (
              <li key={agent.agent_id} className="truncate">
                {agent.display_name}
              </li>
            ))}
          </ul>
        </>
      )}
      {hiddenCount > 0 && (
        <div>
          {t("knowledgeResource.deleteNotice.hiddenAgents", {
            count: hiddenCount,
          })}
        </div>
      )}
      <div>{t("knowledgeResource.deleteNotice.conversationsNotice")}</div>
    </div>
  );
}
