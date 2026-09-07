"use client";

import { type FC } from "react";
import { FileCheck2Icon } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Nl2aAgentDraftPayload } from "../adapter/remote-chat-model-adapter";

export const AgentDraftCard: FC<{
  draft: Nl2aAgentDraftPayload;
  disabled?: boolean;
}> = ({ draft }) => {
  const { t } = useTranslation("common");

  return (
    <section
      data-slot="aui-agent-draft"
      className="my-4 overflow-hidden rounded-lg border bg-card shadow-sm"
    >
      <div className="flex items-center gap-3 border-b bg-muted/30 px-4 py-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10">
          <FileCheck2Icon className="size-4 text-primary" />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-foreground">
            {t("nl2agent.agentDraft.title")}
          </h3>
          <p className="text-xs text-muted-foreground">
            {t("nl2agent.agentDraft.ready")}
          </p>
        </div>
      </div>

      <div className="px-4 py-4">
        <h4 className="text-sm font-semibold text-foreground">
          {draft.display_name}
        </h4>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          {draft.description}
        </p>
      </div>
    </section>
  );
};
