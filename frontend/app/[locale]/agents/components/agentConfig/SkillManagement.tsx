"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { SkillGroup, Skill, SkillParam } from "@/types/agentConfig";
import { Badge, message, Tabs, Tooltip } from "antd";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useSkillList } from "@/hooks/agent/useSkillList";
import { Info, Trash2, Settings } from "lucide-react";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import {
  deleteSkill,
  fetchSkillInstances,
} from "@/services/agentConfigService";
import log from "@/lib/logger";
import SkillDetailModal from "./SkillDetailModal";
import SkillConfigModal from "./skill/SkillConfigModal";
import SkillRowContent from "./skill/SkillRowContent";

interface SkillManagementProps {
  skillGroups: SkillGroup[];
  isCreatingMode?: boolean;
  currentAgentId?: number | undefined;
  isReadOnly?: boolean;
  onEditSkill?: (skill: Skill) => void;
  displayMode?: "tabs" | "list";
  dialogZIndex?: number;
}

export default function SkillManagement({
  skillGroups,
  isCreatingMode,
  currentAgentId,
  isReadOnly: isReadOnlyProp,
  onEditSkill,
  displayMode = "tabs",
  dialogZIndex = 1000,
}: SkillManagementProps) {
  const { t } = useTranslation("common");
  const { confirm } = useConfirmModal();

  // Use prop if provided, otherwise fall back to store
  const storeIsReadOnly = useAgentConfigStore((state) => state.isReadOnly());
  const isReadOnly = isReadOnlyProp ?? storeIsReadOnly;

  const originalSelectedSkills = useAgentConfigStore(
    (state) => state.editedAgent.skills
  );
  const originalSelectedSkillIdsSet = new Set(
    originalSelectedSkills.map((skill) => Number(skill.skill_id))
  );

  const updateSkills = useAgentConfigStore((state) => state.updateSkills);

  const { groupedSkills, invalidate } = useSkillList();

  const [activeTabKey, setActiveTabKey] = useState<string>("");
  const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState<boolean>(false);
  const [configModalSkill, setConfigModalSkill] = useState<Skill | null>(null);
  const [configModalOpen, setConfigModalOpen] = useState<boolean>(false);
  const [skillInstanceMap, setSkillInstanceMap] = useState<
    Record<string, Record<string, any>>
  >({});

  useEffect(() => {
    if (groupedSkills.length > 0 && !activeTabKey) {
      setActiveTabKey(groupedSkills[0].key);
    }
  }, [groupedSkills, activeTabKey]);

  // Fetch per-agent skill instances to get saved config_values
  useEffect(() => {
    if (!currentAgentId || isCreatingMode) {
      setSkillInstanceMap({});
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const result = await fetchSkillInstances(Number(currentAgentId), 0);
        if (result.success && result.data) {
          const map: Record<string, Record<string, any>> = {};
          for (const instance of result.data) {
            if (
              instance.config_values &&
              typeof instance.config_values === "object"
            ) {
              map[instance.skill_id] = instance.config_values;
            }
          }
          if (!cancelled) {
            setSkillInstanceMap(map);
          }
        }
      } catch (err) {
        log.error("Failed to fetch skill instances:", err);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [currentAgentId, isCreatingMode]);

  const handleSkillClick = (skill: Skill) => {
    if (isReadOnly) return;

    const currentSkills = useAgentConfigStore.getState().editedAgent.skills;
    const isCurrentlySelected = currentSkills.some(
      (s) => Number(s.skill_id) === Number(skill.skill_id)
    );

    if (isCurrentlySelected) {
      const newSelectedSkills = currentSkills.filter(
        (s) => Number(s.skill_id) !== Number(skill.skill_id)
      );
      updateSkills(newSelectedSkills);
    } else {
      // In uninstantiated mode, skillInstanceMap is empty — preserve skill.config_values (template defaults)
      const savedConfigValues = skillInstanceMap[skill.skill_id] || null;
      const skillWithValues: Skill = {
        ...skill,
        config_values:
          savedConfigValues !== null
            ? savedConfigValues
            : skill.config_values || {},
      };
      const effectiveConfigValues =
        savedConfigValues !== null
          ? savedConfigValues
          : skill.config_values || {};
      const hasRequiredParams = (skill.config_schemas || []).some(
        (schema: SkillParam) =>
          schema.required &&
          (effectiveConfigValues[schema.name] === undefined ||
            effectiveConfigValues[schema.name] === null ||
            effectiveConfigValues[schema.name] === "")
      );
      const isKnowledgeBaseSkill = skill.name === "search-knowledge-base";

      if (hasRequiredParams || isKnowledgeBaseSkill) {
        setConfigModalSkill(skillWithValues);
        setConfigModalOpen(true);
      } else {
        updateSkills([...currentSkills, skillWithValues]);
      }
    }
  };

  const handleInfoClick = (skill: Skill, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!isReadOnly && skill.permission === "EDIT" && onEditSkill) {
      onEditSkill(skill);
      return;
    }
    setSelectedSkill(skill);
    setIsDetailModalOpen(true);
  };

  const handleDeleteClick = async (skill: Skill, e: React.MouseEvent) => {
    e.stopPropagation();
    confirm({
      title: t("skillManagement.delete.confirmTitle"),
      content: t("skillManagement.delete.confirmContent", {
        skillName: skill.name,
      }),
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
      onOk: async () => {
        const result = await deleteSkill(skill.name);
        if (result.success) {
          message.success(t("skillManagement.delete.success"));
          const currentSkills =
            useAgentConfigStore.getState().editedAgent.skills;
          const updatedSkills = currentSkills.filter(
            (s) => Number(s.skill_id) !== Number(skill.skill_id)
          );
          updateSkills(updatedSkills);
          invalidate();
        } else {
          message.error(result.message || t("skillManagement.delete.failed"));
        }
      },
    });
  };

  const handleConfigClick = (skill: Skill, e: React.MouseEvent) => {
    e.stopPropagation();
    const savedConfigValues = skillInstanceMap[skill.skill_id] || null;
    // In uninstantiated mode, skillInstanceMap is empty — preserve skill.config_values (template defaults)
    setConfigModalSkill({
      ...skill,
      config_values:
        savedConfigValues !== null
          ? savedConfigValues
          : skill.config_values || {},
    });
    setConfigModalOpen(true);
  };

  const handleSkillConfigSave = (skill: Skill, savedParams: SkillParam[]) => {
    // Build the config_values dict from saved params
    const configValues: Record<string, any> = {};
    for (const p of savedParams) {
      configValues[p.name] = p.value;
    }

    // Update skillInstanceMap so the map stays in sync with saved data
    setSkillInstanceMap((prev) => ({
      ...prev,
      [skill.skill_id]: configValues,
    }));

    // Update the skill in the edited agent's skills list with the new params
    const currentSkills = useAgentConfigStore.getState().editedAgent.skills;
    const existingIndex = currentSkills.findIndex(
      (s) => Number(s.skill_id) === Number(skill.skill_id)
    );

    const updatedSkill: Skill = {
      ...skill,
      config_values: configValues,
    };

    let updatedSkills: Skill[];
    if (existingIndex >= 0) {
      // Replace existing entry with updated config
      updatedSkills = [...currentSkills];
      updatedSkills[existingIndex] = updatedSkill;
    } else {
      // Skill not yet in list — add it (came from forced modal open)
      updatedSkills = [...currentSkills, updatedSkill];
    }
    updateSkills(updatedSkills);
  };

  const renderSkillRows = (skills: Skill[]) => (
    <ul
      className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pr-1"
      style={{ padding: "4px 0" }}
    >
      {skills.map((skill) => {
        const isSelected = originalSelectedSkillIdsSet.has(
          Number(skill.skill_id)
        );
        const hasConfigurableParams =
          Array.isArray(skill.config_schemas) &&
          skill.config_schemas.length > 0;

        return (
          <li key={skill.skill_id}>
            <div
              role="button"
              tabIndex={isReadOnly ? -1 : 0}
              className={`group flex items-center gap-2 rounded-md px-2 py-1.5 transition-colors ${
                isReadOnly
                  ? "cursor-not-allowed opacity-60"
                  : "cursor-pointer hover:bg-gray-50"
              }`}
              onClick={isReadOnly ? undefined : () => handleSkillClick(skill)}
              onKeyDown={(event) => {
                if (
                  !isReadOnly &&
                  (event.key === "Enter" || event.key === " ")
                ) {
                  event.preventDefault();
                  handleSkillClick(skill);
                }
              }}
            >
              <SkillRowContent
                skill={skill}
                selected={isSelected}
                isReadOnly={isReadOnly}
              />
              <div
                className="ml-2 flex shrink-0 items-center justify-end gap-1"
                data-testid={`skill-row-actions-${skill.skill_id}`}
              >
                <button
                  type="button"
                  onClick={(event) => handleInfoClick(skill, event)}
                  aria-label={t("skillPool.viewDetails")}
                  title={t("skillPool.viewDetails")}
                  className="flex size-7 shrink-0 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
                >
                  <Info className="size-4" />
                </button>
                <button
                  type="button"
                  disabled={isReadOnly || !hasConfigurableParams}
                  onClick={(event) => handleConfigClick(skill, event)}
                  aria-label={t("skillPool.configure")}
                  title={t("skillPool.configure")}
                  className="flex size-7 shrink-0 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Settings className="size-4" />
                </button>
                {displayMode !== "list" ? (
                  <button
                    type="button"
                    disabled={isReadOnly}
                    onClick={(event) => handleDeleteClick(skill, event)}
                    aria-label={t("skillPool.remove")}
                    title={t("skillPool.remove")}
                    className="flex size-7 shrink-0 items-center justify-center rounded-md text-gray-400 opacity-0 transition-opacity hover:bg-red-50 hover:text-red-500 group-hover:opacity-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Trash2 className="size-4" />
                  </button>
                ) : null}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );

  const tabItems = skillGroups.map((group) => {
    const selectedCount = group.skills.filter((skill) =>
      originalSelectedSkillIdsSet.has(Number(skill.skill_id))
    ).length;

    return {
      key: group.key,
      label: (
        <Tooltip title={group.label} placement="right">
          <span className="inline-flex items-center gap-1">
            <span
              style={{
                maxWidth: "100px",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                textAlign: "left",
              }}
            >
              {group.label}
            </span>
            {selectedCount > 0 && (
              <Badge count={selectedCount} size="small" color="blue" />
            )}
          </span>
        </Tooltip>
      ),
      children: renderSkillRows(group.skills),
    };
  });

  return (
    <div
      className={`h-full min-h-0 flex flex-col ${
        displayMode === "list" ? "flex-1" : ""
      }`}
    >
      {skillGroups.length === 0 ? (
        <div className="flex items-center justify-center flex-1">
          <span className="text-gray-500">{t("skillPool.noSkills")}</span>
        </div>
      ) : displayMode === "list" ? (
        renderSkillRows(skillGroups[0].skills)
      ) : (
        <Tabs
          tabPlacement="start"
          activeKey={activeTabKey}
          onChange={setActiveTabKey}
          items={tabItems}
          className="h-full skill-pool-tabs"
          style={{
            height: "100%",
          }}
          tabBarStyle={{
            minWidth: "120px",
            maxWidth: "120px",
            padding: "4px 0",
            margin: 0,
          }}
        />
      )}

      <SkillDetailModal
        skill={selectedSkill}
        open={isDetailModalOpen}
        zIndex={dialogZIndex}
        maskClosable
        onClose={() => {
          setIsDetailModalOpen(false);
          setSelectedSkill(null);
        }}
      />

      {configModalSkill && (
        <SkillConfigModal
          isOpen={configModalOpen}
          onCancel={() => {
            setConfigModalOpen(false);
            setConfigModalSkill(null);
          }}
          onSave={(params) => {
            if (configModalSkill) {
              handleSkillConfigSave(configModalSkill, params);
            }
          }}
          skill={configModalSkill}
          initialParams={configModalSkill.config_schemas || []}
          currentAgentId={currentAgentId}
          isCreatingMode={isCreatingMode}
          zIndex={dialogZIndex}
          maskClosable
        />
      )}
    </div>
  );
}
