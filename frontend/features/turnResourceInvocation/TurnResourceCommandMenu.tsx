import { CalendarClock, Slash } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getTurnResourceCommandSuggestions } from "./parser";

interface TurnResourceCommandMenuProps {
  input: string;
  onSelect: (command: string) => void;
}

export function TurnResourceCommandMenu({
  input,
  onSelect,
}: TurnResourceCommandMenuProps) {
  const { t } = useTranslation("common");
  const suggestions = getTurnResourceCommandSuggestions(input);
  if (suggestions.length === 0) return null;

  return (
    <div className="mx-3 mt-3 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2 text-xs font-medium text-slate-500">
        <Slash className="h-3.5 w-3.5" />
        <span>{t("turnResourceInvocation.menuTitle")}</span>
      </div>
      <div className="p-1.5">
        {suggestions.map((definition) => (
          <button
            key={definition.id}
            type="button"
            className="group flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-blue-50 focus-visible:bg-blue-50 focus-visible:outline-none"
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onSelect(definition.command)}
          >
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600 transition-colors group-hover:bg-blue-100">
              <CalendarClock className="h-4 w-4" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <code className="text-sm font-semibold text-slate-900">
                  {definition.command}
                </code>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">
                  {t(definition.titleKey)}
                </span>
              </span>
              <span className="mt-0.5 block text-xs leading-5 text-slate-500">
                {t(definition.descriptionKey)}
              </span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
