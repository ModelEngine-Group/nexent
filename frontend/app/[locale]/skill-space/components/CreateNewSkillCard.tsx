"use client";

import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

interface CreateNewSkillCardProps {
  onClick: () => void;
}

export function CreateNewSkillCard({ onClick }: CreateNewSkillCardProps) {
  const { t } = useTranslation("common");
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex h-full min-h-52 w-full flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-slate-200 text-slate-500 transition-colors hover:border-primary/50 hover:text-primary dark:border-slate-700 dark:text-slate-400 dark:hover:border-primary/50 dark:hover:text-primary"
      aria-label={t("skillRepository.mine.addSkillService")}
    >
      <div className="flex size-12 items-center justify-center rounded-full border-2 border-current">
        <Plus className="size-6" aria-hidden />
      </div>
      <span className="text-sm font-medium">
        {t("skillRepository.mine.addSkillService")}
      </span>
    </button>
  );
}
