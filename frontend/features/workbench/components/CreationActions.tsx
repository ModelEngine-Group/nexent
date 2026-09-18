import type { WorkbenchMode } from "../types";
import { Lightbulb, Bot } from "lucide-react";

export function CreationActions({
  canCreateAgent,
  canCreateSkill,
  disabled,
  onSelect,
}: {
  canCreateAgent: boolean;
  canCreateSkill: boolean;
  disabled: boolean;
  onSelect: (
    mode: Extract<WorkbenchMode, "agent_create" | "skill_create">
  ) => void;
}) {
  if (!canCreateAgent && !canCreateSkill) return null;
  return (
    <div className="mb-2 flex items-center gap-2 text-xs">
      {canCreateSkill && (
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-background px-3 py-1.5 hover:bg-muted disabled:opacity-50"
          disabled={disabled}
          onClick={() => onSelect("skill_create")}
        >
          <Lightbulb className="size-3.5" />
          Skill 创建
        </button>
      )}
      {canCreateAgent && (
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-background px-3 py-1.5 hover:bg-muted disabled:opacity-50"
          disabled={disabled}
          onClick={() => onSelect("agent_create")}
        >
          <Bot className="size-3.5" />
          Agent创建
        </button>
      )}
    </div>
  );
}
