// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";

import type { KnowledgeBaseDeletionPreview } from "@/types/knowledgeBase";

/**
 * Show bound agent names and the conversation notice
 * in the knowledge-base delete confirmation dialog.
 */
export default function KnowledgeBaseDeleteNotice({
  preview,
}: {
  preview: KnowledgeBaseDeletionPreview | null;
}) {
  const { t } = useTranslation("common");
  const agents = preview?.agents ?? [];

  return (
    <div className="mt-2 space-y-1 text-sm text-gray-600">
      {preview === null && (
        <div>{t("knowledgeBase.deleteNotice.agentsNotice")}</div>
      )}
      {agents.length > 0 && (
        <>
          <div>{t("knowledgeBase.deleteNotice.agentsIntro")}</div>
          <ul
            className="max-h-40 list-inside list-disc overflow-y-auto overscroll-contain"
            data-testid="knowledge-reference-delete-agents"
            tabIndex={0}
            aria-label={t("knowledgeBase.deleteNotice.agentsIntro")}
          >
            {agents.map((agent) => (
              <li
                key={agent.agent_id}
                className="truncate"
                title={agent.display_name}
              >
                {agent.display_name}
              </li>
            ))}
          </ul>
        </>
      )}
      <div>{t("knowledgeBase.deleteNotice.conversationsNotice")}</div>
    </div>
  );
}
