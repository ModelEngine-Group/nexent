// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useAui, useAuiState } from "@assistant-ui/react";
import { useTranslation } from "react-i18next";
import { FileText, ClipboardCheck, NotebookPen } from "lucide-react";
import { CREATION_PROMPTS } from "../state";
import { AGENT_CREATION_EXAMPLES } from "@/const/agentCreationExamples";
import { CardSuggestion } from "@/components/agent/agent-suggestion";

const examples = {
  skill_create: [
    { key: "invoiceExtraction", title: "发票信息提取", icon: FileText },
    { key: "contractReview", title: "合同关键信息审查", icon: ClipboardCheck },
    { key: "meetingNotes", title: "会议纪要整理", icon: NotebookPen },
  ],
  agent_create: AGENT_CREATION_EXAMPLES,
};

export function CreationExamples({
  mode,
}: {
  mode: "skill_create" | "agent_create";
}) {
  const aui = useAui();
  const { t } = useTranslation("common");
  const visible = useAuiState(
    (state) =>
      state.thread.messages.length === 0 && state.composer.text.length === 0
  );
  if (!visible) return null;
  const suggestions = examples[mode].map((example, index) => {
    const { key, title, icon } = example;
    const translationKey = `workbench.creationExamples.${mode === "skill_create" ? "skill" : "agent"}.${key}`;
    const prompt = t(translationKey, CREATION_PROMPTS[mode][index]);
    return {
      id: key,
      title: t(`${translationKey}.title`, title),
      description:
        "description" in example
          ? t(`${translationKey}.description`, example.description)
          : prompt,
      prompt,
      icon,
    };
  });
  return (
    <section
      aria-label={t(
        mode === "skill_create"
          ? "workbench.creationExamples.skillSectionLabel"
          : "workbench.creationExamples.agentSectionLabel",
        mode === "skill_create" ? "Skill 创建示例" : "Agent 创建示例"
      )}
      className="px-1"
    >
      <CardSuggestion
        className="max-w-none"
        suggestions={suggestions}
        onSelect={(prompt) => {
          aui.composer().setText(prompt);
          requestAnimationFrame(() =>
            document
              .querySelector<HTMLTextAreaElement>("[data-workbench-composer]")
              ?.focus()
          );
        }}
      />
    </section>
  );
}
