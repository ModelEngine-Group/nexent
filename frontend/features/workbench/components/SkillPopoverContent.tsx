"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2Icon, PuzzleIcon, SearchIcon } from "lucide-react";
import { message, Switch } from "antd";
import { useTranslation } from "react-i18next";
import { fetchSkillsList, type SkillListItem } from "@/services/skillService";
import { validateSkillConfig } from "@/features/workbench/skillConfig";

// Content of the "技能" toolbar Popover, replacing the former full-screen
// antd picker Modal: search + switch-to-mount list + manage-page link.
export interface SkillPopoverContentProps {
  mountedSkillIds: ReadonlySet<number>;
  onMount: (skill: SkillListItem) => void;
  onUnmount: (skillId: number) => void;
}

const SKILL_ICON_COLORS = [
  "#197BD5",
  "#E8A33D",
  "#7C5CFC",
  "#2FA36B",
  "#E36262",
];

const skillColor = (skillId: number) =>
  SKILL_ICON_COLORS[Math.abs(skillId) % SKILL_ICON_COLORS.length];

export function SkillPopoverContent({
  mountedSkillIds,
  onMount,
  onUnmount,
}: SkillPopoverContentProps) {
  const { t } = useTranslation();
  const router = useRouter();
  const [skills, setSkills] = useState<SkillListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void fetchSkillsList()
      .then((items) => {
        if (!cancelled) setSkills(items);
      })
      .catch((error) => {
        if (!cancelled)
          message.error(
            error instanceof Error ? error.message : "Skill 加载失败"
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const value = search.trim().toLowerCase();
    if (!value) return skills;
    return skills.filter((skill) =>
      [skill.name, skill.description]
        .filter(Boolean)
        .some((field) => String(field).toLowerCase().includes(value))
    );
  }, [search, skills]);

  const toggle = (skill: SkillListItem, next: boolean) => {
    const skillId = Number(skill.skill_id);
    if (
      next &&
      validateSkillConfig(skill.config_schemas || [], {
        ...skill.config_values,
      }).length > 0
    ) {
      message.warning(t("chat.skillsPopover.configRequired"));
      return;
    }
    if (next) onMount(skill);
    else onUnmount(skillId);
  };

  return (
    <div className="flex flex-col">
      <div className="px-3 pt-3 text-base leading-6 text-[#191919]">
        {t("chat.skillsPopover.all")}
      </div>
      <div className="px-3 pt-2 pb-1">
        <div className="flex h-9 items-center gap-2 rounded-lg border border-border px-2">
          <SearchIcon className="size-4 shrink-0 text-muted-foreground" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("chat.skillsPopover.searchPlaceholder")}
            aria-label={t("chat.skillsPopover.searchPlaceholder")}
            className="h-full min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
        </div>
      </div>
      <div className="max-h-64 overflow-y-auto px-1.5 pb-1">
        {loading ? (
          <div className="flex h-20 items-center justify-center">
            <Loader2Icon
              className="size-4 animate-spin text-muted-foreground"
              aria-hidden
            />
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex h-20 items-center justify-center text-sm text-muted-foreground">
            {t("chat.skillsPopover.empty")}
          </div>
        ) : (
          filtered.map((skill) => {
            const skillId = Number(skill.skill_id);
            const checked = mountedSkillIds.has(skillId);
            return (
              <div
                key={skillId}
                className="flex items-center gap-2 rounded-lg px-2 py-2 hover:bg-[rgba(25,25,25,0.03)]"
              >
                <span
                  className="flex size-8 shrink-0 items-center justify-center rounded-lg"
                  style={{
                    backgroundColor: `${skillColor(skillId)}1A`,
                    color: skillColor(skillId),
                  }}
                >
                  <PuzzleIcon className="size-4" aria-hidden />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-base leading-6 text-[#191919]">
                    {skill.name}
                  </div>
                  {skill.description ? (
                    <div className="truncate text-sm leading-[22px] text-[rgba(25,25,25,0.5)]">
                      {skill.description}
                    </div>
                  ) : null}
                </div>
                <Switch
                  size="small"
                  checked={checked}
                  onChange={(next) => toggle(skill, next)}
                />
              </div>
            );
          })
        )}
      </div>
      <div className="border-t px-3 py-2">
        <button
          type="button"
          className="text-sm leading-[22px] text-[#191919] hover:text-[#197BD5]"
          onClick={() => router.push("/skill-space?tab=mine")}
        >
          {t("chat.skillsPopover.manageSkills")}
        </button>
      </div>
    </div>
  );
}
