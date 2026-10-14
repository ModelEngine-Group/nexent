import type { WorkbenchMode } from "../types";
import { Lightbulb, Bot } from "lucide-react";
import { useTranslation } from "react-i18next";

export function CreationActions({
  canCreateAgent,
  canCreateSkill,
  disabled,
  onSelect,
  mode,
  onExit,
}: {
  canCreateAgent: boolean;
  canCreateSkill: boolean;
  disabled: boolean;
  mode?: WorkbenchMode;
  onExit?: () => void;
  onSelect: (
    mode: Extract<WorkbenchMode, "agent_create" | "skill_create">
  ) => void;
}) {
  const { t } = useTranslation();
  if (!canCreateAgent && !canCreateSkill) return null;
  return (
    <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
      {canCreateAgent && (
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-background px-3 py-1.5 hover:bg-muted aria-pressed:border-primary aria-pressed:bg-primary/10 aria-pressed:text-primary disabled:opacity-50"
          disabled={disabled}
          aria-pressed={mode === "agent_create"}
          onClick={() => onSelect("agent_create")}
        >
          <Bot className="size-3.5" />
          {t("workbench.controls.agentCreate", "智能体创建")}
        </button>
      )}
      {canCreateSkill && (
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-background px-3 py-1.5 hover:bg-muted aria-pressed:border-primary aria-pressed:bg-primary/10 aria-pressed:text-primary disabled:opacity-50"
          disabled={disabled}
          aria-pressed={mode === "skill_create"}
          onClick={() => onSelect("skill_create")}
        >
          <Lightbulb className="size-3.5" />
          {t("workbench.controls.skillCreate", "技能创建")}
        </button>
      )}
      {(mode === "skill_create" || mode === "agent_create") && onExit && (
        <button
          type="button"
          onClick={onExit}
          disabled={disabled}
          className="ml-auto inline-flex items-center justify-center rounded-xl border border-border bg-background px-3 py-1.5 text-primary hover:bg-muted disabled:opacity-50"
        >
          {t("workbench.controls.exit", "返回普通对话")}
        </button>
      )}
    </div>
  );
}
