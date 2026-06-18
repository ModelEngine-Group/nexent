"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { SkillGroup, Skill, SkillParam } from "@/types/agentConfig";
import { Tabs, message, Tooltip } from "antd";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useSkillList } from "@/hooks/agent/useSkillList";
import { Info, Trash2, Settings } from "lucide-react";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { deleteSkill, fetchSkillInstances } from "@/services/agentConfigService";
import log from "@/lib/logger";
import SkillDetailModal from "./SkillDetailModal";
import SkillConfigModal from "./skill/SkillConfigModal";

interface SkillManagementProps {
  skillGroups: SkillGroup[];
  isCreatingMode?: boolean;
  currentAgentId?: number | undefined;
  isReadOnly?: boolean;
}

export default function SkillManagement({
  skillGroups,
  isCreatingMode,
  currentAgentId,
  isReadOnly: isReadOnlyProp,
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
    originalSelectedSkills.map((skill) => skill.skill_id)
  );

  const updateSkills = useAgentConfigStore((state) => state.updateSkills);

  const { groupedSkills, invalidate } = useSkillList();

  const [activeTabKey, setActiveTabKey] = useState<string>("");
  const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState<boolean>(false);
  const [configModalSkill, setConfigModalSkill] = useState<Skill | null>(null);
  const [configModalOpen, setConfigModalOpen] = useState<boolean>(false);
  const [skillInstanceMap, setSkillInstanceMap] = useState<Record<string, Record<string, any>>>({});

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
            if (instance.config_values && typeof instance.config_values === "object") {
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

    return () => { cancelled = true; };
  }, [currentAgentId, isCreatingMode]);

  const handleSkillClick = (skill: Skill) => {
    if (isReadOnly) return;

    const currentSkills = useAgentConfigStore.getState().editedAgent.skills;
    const isCurrentlySelected = currentSkills.some(
      (s) => s.skill_id === skill.skill_id
    );

    if (isCurrentlySelected) {
      const newSelectedSkills = currentSkills.filter(
        (s) => s.skill_id !== skill.skill_id
      );
      updateSkills(newSelectedSkills);
    } else {
      // In uninstantiated mode, skillInstanceMap is empty — preserve skill.config_values (template defaults)
      const savedConfigValues = skillInstanceMap[skill.skill_id] || null;
      const skillWithValues: Skill = {
        ...skill,
        config_values: savedConfigValues !== null ? savedConfigValues : (skill.config_values || {}),
      };

      // Check if skill has required params (optional: false) without saved values.
      // In uninstantiated mode, fall back to skill.config_values (template defaults).
      const effectiveConfigValues = savedConfigValues !== null ? savedConfigValues : (skill.config_values || {});
      const hasRequiredParams = (skill.config_schemas || []).some(
        (schema: SkillParam) =>
          schema.required &&
          (effectiveConfigValues[schema.name] === undefined ||
            effectiveConfigValues[schema.name] === null ||
            effectiveConfigValues[schema.name] === "")
      );

      // Special case: search-knowledge-base always opens the config modal for mandatory KB selection.
      const isKnowledgeBaseSkill = skill.name === "search-knowledge-base";

      if (hasRequiredParams || isKnowledgeBaseSkill) {
        // Force open config modal
        setConfigModalSkill(skillWithValues);
        setConfigModalOpen(true);
      } else {
        // No required params missing — add directly to selected skills
        const newSelectedSkills = [...currentSkills, skillWithValues];
        updateSkills(newSelectedSkills);
      }
    }
  };

  const handleInfoClick = (skill: Skill, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedSkill(skill);
    setIsDetailModalOpen(true);
  };

  const handleDeleteClick = async (skill: Skill, e: React.MouseEvent) => {
    e.stopPropagation();
    confirm({
      title: t("skillManagement.delete.confirmTitle"),
      content: t("skillManagement.delete.confirmContent", { skillName: skill.name }),
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
      onOk: async () => {
        const result = await deleteSkill(skill.name);
        if (result.success) {
          message.success(t("skillManagement.delete.success"));
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
      config_values: savedConfigValues !== null ? savedConfigValues : (skill.config_values || {}),
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
      (s) => s.skill_id === skill.skill_id
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

  const tabItems = skillGroups.map((group) => {
    return {
      key: group.key,
      label: (
        <Tooltip title={group.label} placement="right">
          <span
            style={{
              display: "block",
              maxWidth: "100px",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              textAlign: "left",
            }}
          >
            {group.label}
          </span>
        </Tooltip>
      ),
      children: (
        <div
          className="flex flex-col gap-2 pr-2 flex-1"
          style={{
            overflowY: "auto",
            padding: "4px 0",
          }}
        >
          {group.skills.map((skill) => {
            const isSelected = originalSelectedSkillIdsSet.has(skill.skill_id);
            const hasConfigurableParams =
              Array.isArray(skill.config_schemas) && skill.config_schemas.length > 0;

            return (
              <div
                key={skill.skill_id}
                className={`border-2 rounded-md px-3 py-2 flex items-center justify-between transition-all duration-300 ease-in-out min-h-[44px] ${
                  isSelected
                    ? "bg-blue-100 border-blue-400 shadow-md"
                    : "border-gray-200 hover:border-blue-300 hover:shadow-md"
                } ${isReadOnly ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}
                onClick={() => handleSkillClick(skill)}
              >
                <span className="font-medium text-gray-800 truncate">
                  {skill.name}
                </span>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {isSelected && hasConfigurableParams && (
                    <Settings
                      size={16}
                      className={`cursor-pointer text-gray-400 hover:text-blue-600 transition-colors ${
                        isReadOnly ? "pointer-events-none opacity-50" : ""
                      }`}
                      onClick={isReadOnly ? undefined : (e) => handleConfigClick(skill, e)}
                    />
                  )}
                  <Info
                    size={16}
                    className={`cursor-pointer text-gray-400 hover:text-gray-600 transition-colors ${
                      isReadOnly ? "pointer-events-none opacity-50" : ""
                    }`}
                    onClick={isReadOnly ? undefined : (e) => handleInfoClick(skill, e)}
                  />
                  <Trash2
                    size={16}
                    className={`cursor-pointer text-gray-400 hover:text-red-500 transition-colors ${
                      isReadOnly ? "pointer-events-none opacity-50" : ""
                    }`}
                    onClick={isReadOnly ? undefined : (e) => handleDeleteClick(skill, e)}
                  />
                </div>
              </div>
            );
          })}
        </div>
      ),
    };
  });

  return (
    <div className="h-full flex flex-col">
      {skillGroups.length === 0 ? (
        <div className="flex items-center justify-center flex-1">
          <span className="text-gray-500">{t("skillPool.noSkills")}</span>
        </div>
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
        />
      )}
    </div>
  );
}
