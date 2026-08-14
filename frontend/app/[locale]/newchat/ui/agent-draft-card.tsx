"use client";

import { useState, type FC } from "react";
import { CheckCircle2Icon, FileCheck2Icon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import type { Nl2aAgentDraftPayload } from "../adapter/remote-chat-model-adapter";

export const AgentDraftCard: FC<{ draft: Nl2aAgentDraftPayload }> = ({
  draft,
}) => {
  const { t } = useTranslation("common");
  const updateAgentConfig = useAgentConfigStore(
    (state) => state.updateAgentConfig
  );
  const [isApplied, setIsApplied] = useState(false);

  const applyDraft = () => {
    if (isApplied) return;

    updateAgentConfig({
      name: draft.name,
      display_name: draft.display_name,
      description: draft.description,
      duty_prompt: draft.duty_prompt,
      constraint_prompt: draft.constraint_prompt,
      few_shots_prompt: draft.few_shots_prompt ?? "",
      greeting_message: draft.greeting_message,
      example_questions: draft.example_questions,
    });
    setIsApplied(true);
  };

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

      <div className="flex items-center justify-end border-t bg-muted/20 px-4 py-3">
        <Button
          type="button"
          size="sm"
          disabled={isApplied}
          onClick={applyDraft}
        >
          <CheckCircle2Icon />
          {isApplied
            ? t("nl2agent.agentDraft.applied")
            : t("nl2agent.agentDraft.apply")}
        </Button>
      </div>
    </section>
  );
};
