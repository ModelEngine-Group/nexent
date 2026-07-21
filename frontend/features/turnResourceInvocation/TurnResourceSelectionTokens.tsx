import { CalendarClock, Hammer, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { TurnResourceSelection } from "./types";

interface TurnResourceSelectionTokensProps {
  selections: TurnResourceSelection[];
  onRemove: (key: string) => void;
}

export function TurnResourceSelectionTokens({
  selections,
  onRemove,
}: TurnResourceSelectionTokensProps) {
  const { t } = useTranslation("common");

  return selections.map((selection) => {
    const Icon = selection.resourceType === "skill" ? Hammer : CalendarClock;
    return (
      <span
        key={selection.key}
        title={selection.description}
        className="group inline-flex h-9 max-w-[260px] shrink-0 items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-2.5 text-sm font-medium text-slate-700 shadow-sm"
      >
        <Icon className="h-4 w-4 shrink-0 text-blue-600" />
        <span className="truncate">{selection.label}</span>
        <button
          type="button"
          aria-label={t("turnResourceInvocation.remove", {
            name: selection.label,
          })}
          className="ml-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
          onClick={() => onRemove(selection.key)}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </span>
    );
  });
}
