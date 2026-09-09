"use client";

import { useAui, useAuiState } from "@assistant-ui/react";
import { useTranslation } from "react-i18next";
import {
  ChevronLeft,
  FileText,
  ClipboardCheck,
  NotebookPen,
  BookOpen,
  Headphones,
  ChartColumn,
} from "lucide-react";
import { CREATION_PROMPTS } from "../state";

const examples = {
  skill_create: [
    { key: "invoiceExtraction", title: "发票信息提取", icon: FileText },
    { key: "contractReview", title: "合同关键信息审查", icon: ClipboardCheck },
    { key: "meetingNotes", title: "会议纪要整理", icon: NotebookPen },
  ],
  agent_create: [
    { key: "knowledgeAssistant", title: "企业知识问答助手", icon: BookOpen },
    { key: "customerService", title: "智能客服", icon: Headphones },
    { key: "businessAnalysis", title: "经营数据分析助手", icon: ChartColumn },
  ],
};

export function CreationExamples({
  mode,
  onBack,
}: {
  mode: "skill_create" | "agent_create";
  onBack: () => void;
}) {
  const aui = useAui();
  const { t } = useTranslation("common");
  const visible = useAuiState(
    (state) =>
      state.thread.messages.length === 0 && state.composer.text.length === 0
  );
  if (!visible) return null;
  return (
    <section
      aria-label={mode === "skill_create" ? "Skill 创建示例" : "应用创建示例"}
      className="mb-3 max-h-[40vh] overflow-y-auto rounded-2xl border border-border bg-card p-3 shadow-sm sm:max-h-none"
    >
      <div className="mb-3 flex items-center gap-2">
        <button
          type="button"
          aria-label="返回普通对话"
          onClick={onBack}
          className="rounded-lg p-2 hover:bg-muted focus-visible:ring-2"
        >
          <ChevronLeft className="size-4" />
        </button>
        <h2 className="text-sm font-semibold">
          {mode === "skill_create" ? "Skill 创建示例" : "应用创建示例"}
        </h2>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        {examples[mode].map(({ key, title, icon: Icon }, index) => {
          const prompt = t(
            `workbench.creationExamples.${mode === "skill_create" ? "skill" : "agent"}.${key}`,
            CREATION_PROMPTS[mode][index]
          );
          return (
            <button
              type="button"
              key={key}
              onClick={() => {
                aui.composer().setText(prompt);
                requestAnimationFrame(() =>
                  document
                    .querySelector<HTMLTextAreaElement>(
                      "[data-workbench-composer]"
                    )
                    ?.focus()
                );
              }}
              className="min-w-0 rounded-xl border border-border bg-background p-4 text-left transition-colors hover:border-primary/40 hover:bg-accent/30 focus-visible:ring-2"
            >
              <span className="mb-3 flex items-center gap-2">
                <span className="rounded-xl bg-primary/10 p-2 text-primary">
                  <Icon className="size-5" />
                </span>
                <span className="text-sm font-semibold">{title}</span>
              </span>
              <span className="line-clamp-3 text-xs leading-6 text-muted-foreground">
                {prompt}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
