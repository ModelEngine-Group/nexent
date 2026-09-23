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
      aria-label={mode === "skill_create" ? "Skill 创建示例" : "Agent创建示例"}
      className="mt-12 max-h-[min(40vh,320px)] overflow-y-auto px-1"
    >
      <div className="mb-3 flex items-center gap-2">
        <button
          type="button"
          aria-label="返回普通对话"
          onClick={onBack}
          className="rounded-lg p-1.5 hover:bg-muted focus-visible:ring-2"
        >
          <ChevronLeft className="size-4" />
        </button>
        <h2 className="text-sm font-semibold">
          {t("workbench.recommendedPrompts", "推荐提示词")}
        </h2>
      </div>
      <div className="flex flex-col gap-2">
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
              className="flex w-full min-w-0 items-start gap-3 rounded-xl px-3 py-3 text-left transition-colors hover:bg-accent/50 focus-visible:ring-2"
            >
              <span className="mt-0.5 shrink-0 text-muted-foreground">
                <Icon className="size-4" />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium text-foreground">
                  {title}
                </span>
                <span className="mt-1 block line-clamp-2 text-xs leading-5 text-muted-foreground">
                  {prompt}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
