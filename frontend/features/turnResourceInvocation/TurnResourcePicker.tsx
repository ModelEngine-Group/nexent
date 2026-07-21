import { CalendarClock, Hammer, Loader2, SearchX, Slash } from "lucide-react";
import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { TURN_RESOURCE_COMMANDS } from "./registry";
import { createCommandSelection, createSkillSelection } from "./selection";
import type { TurnResourceSelection } from "./types";
import { useAvailableTurnResourceSkills } from "./useAvailableTurnResourceSkills";

interface TurnResourcePickerProps {
  input: string;
  selections: TurnResourceSelection[];
  onSelect: (selection: TurnResourceSelection) => void;
}

export function getTurnResourceSearchQuery(input: string): string | null {
  const normalized = input.trimStart();
  if (!normalized.startsWith("/") || normalized.includes("\n")) return null;

  const commandWithArgument = TURN_RESOURCE_COMMANDS.some((definition) =>
    normalized.toLowerCase().startsWith(`${definition.command.toLowerCase()} `)
  );
  return commandWithArgument ? null : normalized.slice(1).trim().toLowerCase();
}

export function TurnResourcePicker({
  input,
  selections,
  onSelect,
}: TurnResourcePickerProps) {
  const { t } = useTranslation("common");
  const query = getTurnResourceSearchQuery(input);
  const skillsQuery = useAvailableTurnResourceSkills();
  const selectedKeys = useMemo(
    () => new Set(selections.map((selection) => selection.key)),
    [selections]
  );

  const skills = useMemo(() => {
    if (query === null) return [];
    return (skillsQuery.data || []).filter((skill) => {
      if (selectedKeys.has(`skill:${skill.skill_id}`)) return false;
      if (!query) return true;
      return `${skill.name} ${skill.description}`.toLowerCase().includes(query);
    });
  }, [query, selectedKeys, skillsQuery.data]);

  const commands = useMemo(() => {
    if (query === null) return [];
    return TURN_RESOURCE_COMMANDS.filter((definition) => {
      const searchable = `${definition.command.slice(1)} ${t(
        definition.titleKey
      )} ${t(definition.descriptionKey)}`.toLowerCase();
      return !query || searchable.includes(query);
    });
  }, [query, t]);

  if (query === null) return null;

  const hasResults = skills.length > 0 || commands.length > 0;
  return (
    <div className="absolute bottom-full left-0 right-0 z-50 mb-2 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl shadow-slate-200/70">
      <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2.5 text-xs font-medium text-slate-500">
        <Slash className="h-3.5 w-3.5" />
        <span>{t("turnResourceInvocation.menuTitle")}</span>
        <span className="ml-auto text-[11px] text-slate-400">
          {t("turnResourceInvocation.menuHint")}
        </span>
      </div>

      <div className="max-h-[320px] overflow-y-auto p-2">
        {skillsQuery.isLoading && (
          <div className="flex items-center justify-center gap-2 py-8 text-sm text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("turnResourceInvocation.loadingSkills")}
          </div>
        )}

        {!skillsQuery.isLoading && skills.length > 0 && (
          <ResourceSection
            title={t("turnResourceInvocation.skills")}
            count={skills.length}
          >
            {skills.map((skill) => (
              <ResourceOption
                key={skill.skill_id}
                icon={<Hammer className="h-4 w-4" />}
                label={skill.name}
                description={skill.description}
                onClick={() => onSelect(createSkillSelection(skill))}
              />
            ))}
          </ResourceSection>
        )}

        {commands.length > 0 && (
          <ResourceSection
            title={t("turnResourceInvocation.commands")}
            count={commands.length}
          >
            {commands.map((definition) => (
              <ResourceOption
                key={definition.id}
                icon={<CalendarClock className="h-4 w-4" />}
                label={definition.command}
                description={t(definition.descriptionKey)}
                onClick={() =>
                  onSelect(
                    createCommandSelection(
                      definition,
                      t(definition.titleKey),
                      t(definition.descriptionKey)
                    )
                  )
                }
              />
            ))}
          </ResourceSection>
        )}

        {!skillsQuery.isLoading && !hasResults && (
          <div className="flex flex-col items-center justify-center gap-2 py-8 text-sm text-slate-400">
            <SearchX className="h-5 w-5" />
            {t("turnResourceInvocation.noResults")}
          </div>
        )}
      </div>
    </div>
  );
}

function ResourceSection({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <section className="mb-2 last:mb-0">
      <div className="px-2 py-1.5 text-xs font-semibold text-slate-400">
        {title} ({count})
      </div>
      <div>{children}</div>
    </section>
  );
}

function ResourceOption({
  icon,
  label,
  description,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="group flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-slate-100 focus-visible:bg-slate-100 focus-visible:outline-none"
      onMouseDown={(event) => event.preventDefault()}
      onClick={onClick}
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-50 text-slate-600 transition-colors group-hover:bg-white group-hover:text-blue-600">
        {icon}
      </span>
      <span className="min-w-0 flex-1 whitespace-nowrap">
        <span className="font-medium text-slate-800">{label}</span>
        {description && (
          <span className="ml-2 text-sm text-slate-400">{description}</span>
        )}
      </span>
    </button>
  );
}
