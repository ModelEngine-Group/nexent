"use client";

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Tooltip } from "antd";
import { ChevronRight, Info, Settings, X } from "lucide-react";

import { useSkillList } from "@/hooks/agent/useSkillList";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import type { Skill, SkillParam } from "@/types/agentConfig";
import SkillDetailModal from "./SkillDetailModal";
import SkillConfigModal from "./skill/SkillConfigModal";

type SkillSourceKey = "official" | "custom";

const OFFICIAL_SKILL_SOURCES = new Set(["official", "官方"]);

const SOURCE_META: Record<
  SkillSourceKey,
  { label: string; dot: string; accentClass: string }
> = {
  official: {
    label: "skillPool.group.official",
    dot: "bg-emerald-500",
    accentClass: "bg-emerald-500/10 text-emerald-600",
  },
  custom: {
    label: "skillPool.group.custom",
    dot: "bg-violet-500",
    accentClass: "bg-violet-500/10 text-violet-600",
  },
};

interface SelectedSkillGroup {
  key: SkillSourceKey;
  skills: Skill[];
}

type PersistedSkill = Skill & {
  skill_name?: string;
  skill_description?: string;
  skill_content?: string;
};

function toSourceKey(source?: string): SkillSourceKey {
  return OFFICIAL_SKILL_SOURCES.has((source || "").trim())
    ? "official"
    : "custom";
}

interface SelectedSkillManagementProps {
  isCreatingMode?: boolean;
  currentAgentId?: number;
  isReadOnly?: boolean;
}

export default function SelectedSkillManagement({
  isCreatingMode,
  currentAgentId,
  isReadOnly = false,
}: SelectedSkillManagementProps) {
  const { t } = useTranslation("common");
  const selectedSkills = useAgentConfigStore(
    (state) => state.editedAgent.skills
  );
  const updateSkills = useAgentConfigStore((state) => state.updateSkills);
  const { skills: catalogSkillData } = useSkillList({ enabled: true });
  const catalogSkills = catalogSkillData as Skill[];
  const [detailSkill, setDetailSkill] = useState<Skill | null>(null);
  const [configSkill, setConfigSkill] = useState<Skill | null>(null);
  const [collapsedGroups, setCollapsedGroups] = useState<
    Record<SkillSourceKey, boolean>
  >({ official: false, custom: false });

  // Agent detail responses contain persisted skill-instance values, while the
  // skill catalog owns display metadata such as name, tags, and source. Merge
  // them by ID so an agent reloaded after saving keeps both its selection and
  // the canonical card content.
  const groupedSkills = useMemo<SelectedSkillGroup[]>(() => {
    const catalogById = new Map(
      catalogSkills.map((skill: Skill) => [Number(skill.skill_id), skill])
    );
    const grouped = new Map<SkillSourceKey, Skill[]>([
      ["official", []],
      ["custom", []],
    ]);

    selectedSkills.forEach((selectedSkill) => {
      const persistedSkill = selectedSkill as PersistedSkill;
      const canonicalSkill = catalogById.get(Number(selectedSkill.skill_id));
      const hydratedSkill: Skill = {
        ...canonicalSkill,
        ...selectedSkill,
        skill_id: Number(selectedSkill.skill_id),
        name:
          selectedSkill.name ||
          persistedSkill.skill_name ||
          canonicalSkill?.name ||
          "",
        description:
          selectedSkill.description ||
          persistedSkill.skill_description ||
          canonicalSkill?.description ||
          "",
        source: selectedSkill.source || canonicalSkill?.source || "custom",
        tags: selectedSkill.tags || canonicalSkill?.tags || [],
        content:
          selectedSkill.content ||
          persistedSkill.skill_content ||
          canonicalSkill?.content ||
          "",
        config_schemas:
          selectedSkill.config_schemas ??
          canonicalSkill?.config_schemas ??
          null,
        config_values:
          selectedSkill.config_values ?? canonicalSkill?.config_values ?? null,
      };
      grouped.get(toSourceKey(hydratedSkill.source))!.push(hydratedSkill);
    });

    return (["official", "custom"] as SkillSourceKey[])
      .map((key) => ({ key, skills: grouped.get(key)! }))
      .filter((group) => group.skills.length > 0);
  }, [catalogSkills, selectedSkills]);

  const removeSkill = (skillId: number) => {
    updateSkills(
      selectedSkills.filter((skill) => Number(skill.skill_id) !== skillId)
    );
  };

  const saveConfig = (skill: Skill, params: SkillParam[]) => {
    const configValues: Record<string, unknown> = {};
    params.forEach((param) => {
      configValues[param.name] = param.value;
    });
    updateSkills(
      selectedSkills.map((selectedSkill) =>
        Number(selectedSkill.skill_id) === Number(skill.skill_id)
          ? { ...selectedSkill, config_values: configValues }
          : selectedSkill
      )
    );
    setConfigSkill(null);
  };

  if (selectedSkills.length === 0) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-gray-200 py-10 text-sm text-gray-400">
        {t("skillPool.noSkillsSelected")}
      </div>
    );
  }

  return (
    <>
      <div className="h-full overflow-y-auto pr-1">
        <div className="mb-3 text-sm font-medium text-gray-700">
          {t("skillPool.selectedSkillsLabel")}{" "}
          <span className="text-xs text-gray-400">
            ({selectedSkills.length})
          </span>
        </div>
        <div className="space-y-4">
          {groupedSkills.map((group) => {
            const isCollapsed = collapsedGroups[group.key];
            const sourceMeta = SOURCE_META[group.key];

            return (
              <div
                key={group.key}
                className="overflow-hidden rounded-lg border border-gray-200 bg-white"
              >
                <button
                  type="button"
                  onClick={() =>
                    setCollapsedGroups((current) => ({
                      ...current,
                      [group.key]: !current[group.key],
                    }))
                  }
                  className={`flex w-full items-center gap-1.5 px-3 py-2 text-left transition-colors hover:bg-gray-50 ${
                    !isCollapsed ? "border-b border-gray-100" : ""
                  }`}
                >
                  <ChevronRight
                    className={`size-3.5 shrink-0 text-gray-400 transition-transform ${
                      !isCollapsed ? "rotate-90" : ""
                    }`}
                  />
                  <span
                    className={`size-1.5 shrink-0 rounded-full ${sourceMeta.dot}`}
                  />
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${sourceMeta.accentClass}`}
                  >
                    {t(sourceMeta.label)}
                  </span>
                  <span className="text-[10px] text-gray-400">
                    {group.skills.length}
                  </span>
                </button>

                {!isCollapsed ? (
                  <div className="divide-y divide-gray-100">
                    {group.skills.map((skill) => (
                      <div
                        key={skill.skill_id}
                        className="group flex items-center gap-3 px-3 py-2"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="truncate text-sm font-medium text-gray-800">
                              {skill.name}
                            </span>
                            {(skill.tags || []).slice(0, 2).map((tag) => (
                              <span
                                key={tag}
                                className="shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-600"
                              >
                                {tag}
                              </span>
                            ))}
                          </div>
                          {skill.description ? (
                            <p className="truncate text-xs text-gray-400">
                              {skill.description}
                            </p>
                          ) : null}
                        </div>
                        <Tooltip title={t("skillPool.viewDetails")}>
                          <button
                            type="button"
                            className="flex size-7 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
                            onClick={() => setDetailSkill(skill)}
                          >
                            <Info className="size-4" />
                          </button>
                        </Tooltip>
                        {(skill.config_schemas || []).length > 0 ? (
                          <Tooltip title={t("skillPool.configure")}>
                            <button
                              type="button"
                              disabled={isReadOnly}
                              className="flex size-7 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 disabled:cursor-not-allowed disabled:opacity-50"
                              onClick={() => setConfigSkill(skill)}
                            >
                              <Settings className="size-4" />
                            </button>
                          </Tooltip>
                        ) : null}
                        <button
                          type="button"
                          disabled={isReadOnly}
                          className="flex size-7 shrink-0 items-center justify-center rounded-md text-transparent transition-colors hover:bg-red-50 hover:text-red-500 group-hover:text-gray-400 group-focus-within:text-gray-400 disabled:cursor-not-allowed disabled:opacity-50"
                          onClick={() => removeSkill(skill.skill_id)}
                          title={t("skillPool.remove")}
                        >
                          <X className="size-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>

      <SkillDetailModal
        skill={detailSkill}
        open={Boolean(detailSkill)}
        onClose={() => setDetailSkill(null)}
      />
      {configSkill ? (
        <SkillConfigModal
          isOpen
          onCancel={() => setConfigSkill(null)}
          onSave={(params) => saveConfig(configSkill, params)}
          skill={configSkill}
          initialParams={configSkill.config_schemas || []}
          currentAgentId={currentAgentId}
          isCreatingMode={isCreatingMode}
        />
      ) : null}
    </>
  );
}
