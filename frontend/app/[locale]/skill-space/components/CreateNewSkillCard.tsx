"use client";

import { Plus } from "lucide-react";

interface CreateNewSkillCardProps {
  onClick: () => void;
}

export function CreateNewSkillCard({ onClick }: CreateNewSkillCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex h-full min-h-52 w-full flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-slate-200 text-slate-500 transition-colors hover:border-primary/50 hover:text-primary dark:border-slate-700 dark:text-slate-400 dark:hover:border-primary/50 dark:hover:text-primary"
      aria-label="添加Skill服务"
    >
      <div className="flex size-12 items-center justify-center rounded-full border-2 border-current">
        <Plus className="size-6" aria-hidden />
      </div>
      <span className="text-sm font-medium">添加Skill服务</span>
    </button>
  );
}
