"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Input, InputNumber, message, Tag, Skeleton } from "antd";
import { CloseOutlined } from "@ant-design/icons";

import { Skill, SkillParam } from "@/types/agentConfig";
import { KnowledgeBase } from "@/types/knowledgeBase";
import KnowledgeBaseSelectorModal from "@/components/tool-config/KnowledgeBaseSelectorModal";
import {
  getToolTypeForSkill,
  skillRequiresKbSelection as checkSkillRequiresKb,
  getKbParamNameForSkill,
  ToolKbType,
} from "@/components/tool-config";
import {
  useKnowledgeBasesForToolConfig,
  useSyncKnowledgeBases,
} from "@/hooks/useKnowledgeBaseSelector";
import {
  ParamDialog,
  ParamField,
  ParamInput,
  ParamSwitch,
} from "@/components/resource-picker/ParamDialog";
import log from "@/lib/logger";
import {
  isZhLocale,
  getKbDisplayName,
  mapKbIdsToDisplayNames,
  parseKbIds,
} from "@/lib/utils";

export interface SkillConfigModalProps {
  isOpen: boolean;
  onCancel: () => void;
  onSave?: (params: SkillParam[]) => void;
  skill: Skill;
  initialParams: SkillParam[];
  currentAgentId?: number;
  zIndex?: number;
  maskClosable?: boolean;
}

function extractDefaultValue(value: any, type: string): any {
  if (value !== undefined && value !== null) return value;
  switch (type) {
    case "string":
    case "Optional":
      return "";
    case "number":
      return undefined;
    case "boolean":
      return false;
    case "array":
      return [];
    case "object":
      return {};
    default:
      return undefined;
  }
}

export default function SkillConfigModal({
  isOpen,
  onCancel,
  onSave,
  skill,
  initialParams,
  currentAgentId,
  zIndex,
  maskClosable = true,
}: SkillConfigModalProps) {
  const [currentParams, setCurrentParams] = useState<SkillParam[]>([]);
  const { t } = useTranslation("common");
  const isZh = isZhLocale();

  // Check if this skill requires knowledge base selection (has index_names or dataset_ids param)
  const skillRequiresKbSelection = useMemo(() => {
    return checkSkillRequiresKb(initialParams || []);
  }, [initialParams]);

  // Derive the correct toolType based on skill name
  const skillToolType = useMemo<ToolKbType>(() => {
    return getToolTypeForSkill(skill?.name || "");
  }, [skill?.name]);

  // Get the KB param name for the current skill (index_names or dataset_ids)
  const kbParamName = useMemo(() => {
    return getKbParamNameForSkill(skill?.name || "");
  }, [skill?.name]);

  // Compute the set of param indices that should be visible, based on depends_on.
  // A param is hidden when its dependency's current value is falsy.
  const visibleIndices = useMemo<Set<number>>(() => {
    const hidden = new Set<number>();
    currentParams.forEach((param, idx) => {
      if (param.depends_on) {
        const depIdx = currentParams.findIndex(
          (p) => p.name === param.depends_on
        );
        if (depIdx !== -1) {
          const depVal = currentParams[depIdx].value;
          if (!depVal) {
            hidden.add(idx);
          }
        }
      }
    });
    return new Set(
      currentParams.map((_, i) => i).filter((i) => !hidden.has(i))
    );
  }, [currentParams]);

  // Knowledge base selector state
  const [kbSelectorVisible, setKbSelectorVisible] = useState(false);
  const [currentKbParamIndex, setCurrentKbParamIndex] = useState<number | null>(
    null
  );
  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  const [selectedKbDisplayNames, setSelectedKbDisplayNames] = useState<
    string[]
  >([]);
  const [hasSubmitted, setHasSubmitted] = useState(false);

  // Fetch knowledge bases based on skill tool type
  const {
    data: knowledgeBases = [],
    isLoading: kbLoading,
  } = useKnowledgeBasesForToolConfig(skillToolType);

  // Sync knowledge bases based on skill tool type
  const { syncKnowledgeBases, isSyncing } = useSyncKnowledgeBases();

  // Sync selectedKbDisplayNames when knowledgeBases or selectedKbIds changes
  useEffect(() => {
    if (selectedKbIds.length > 0 && knowledgeBases.length > 0) {
      setSelectedKbDisplayNames(
        mapKbIdsToDisplayNames(selectedKbIds, knowledgeBases)
      );
    }
  }, [knowledgeBases, selectedKbIds]);

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setSelectedKbIds([]);
      setSelectedKbDisplayNames([]);
      setHasSubmitted(false);
      setKbSelectorVisible(false);
      setCurrentKbParamIndex(null);
    }
  }, [isOpen]);

  useEffect(() => {
    if (selectedKbIds.length > 0 && knowledgeBases.length > 0) {
      const validKbIds = selectedKbIds.filter((id) =>
        knowledgeBases.some((kb) => String(kb.id).trim() === String(id).trim())
      );
      if (validKbIds.length !== selectedKbIds.length) {
        setSelectedKbIds(validKbIds);
        setSelectedKbDisplayNames(
          mapKbIdsToDisplayNames(validKbIds, knowledgeBases)
        );
      }
    }
  }, [knowledgeBases, selectedKbIds]);

  // Build currentParams: merge saved config_values with schema defaults.
  // config_values from the database (skill.config_values) takes precedence over schema defaults.
  useEffect(() => {
    if (!isOpen) return;

    const schema =
      initialParams && Array.isArray(initialParams) ? initialParams : [];

    // Saved config_values from database (per-agent instance values)
    const savedConfigValues =
      skill.config_values && typeof skill.config_values === "object"
        ? skill.config_values
        : {};

    const merged: SkillParam[] = schema.map((param) => {
      if (savedConfigValues[param.name] !== undefined) {
        return { ...param, value: savedConfigValues[param.name] };
      }
      return { ...param, value: extractDefaultValue(param.value, param.type) };
    });

    setCurrentParams(merged);

    // Parse initial knowledge base IDs from the relevant param (index_names or dataset_ids)
    if (skillRequiresKbSelection && kbParamName) {
      const kbParam = merged.find((p) => p.name === kbParamName);
      if (kbParam?.value) {
        const ids = parseKbIds(kbParam.value);
        if (ids.length > 0) {
          setSelectedKbIds(ids);
        }
      }
    }
  }, [isOpen, initialParams, skill.config_values, skillRequiresKbSelection, kbParamName]);

  const updateParamValue = useCallback((index: number, value: unknown) => {
    setCurrentParams((prev) => {
      const next = [...prev];
      if (next[index]) next[index] = { ...next[index], value };
      return next;
    });
  }, []);

  const getLocalizedDescription = useCallback(
    (param: SkillParam) => {
      return isZh
        ? param.description_zh || param.description_en
        : param.description_en;
    },
    [isZh]
  );

  // Open knowledge base selector for index_names parameter
  const openKbSelector = (paramIndex: number) => {
    setCurrentKbParamIndex(paramIndex);
    setKbSelectorVisible(true);
  };

  // Handle knowledge base selection confirm
  const handleKbConfirm = (selectedKnowledgeBases: KnowledgeBase[]) => {
    const ids = selectedKnowledgeBases.map((kb) => kb.id);
    const displayNames = selectedKnowledgeBases.map((kb) =>
      getKbDisplayName(kb)
    );

    setSelectedKbIds(ids);
    setSelectedKbDisplayNames(displayNames);
    setHasSubmitted(false);

    if (currentKbParamIndex !== null) {
      updateParamValue(currentKbParamIndex, ids);
    }

    setKbSelectorVisible(false);
    setCurrentKbParamIndex(null);
  };

  // Remove a single knowledge base from selection
  const removeKbFromSelection = (indexToRemove: number, paramIndex: number) => {
    const newIds = selectedKbIds.filter((_, i) => i !== indexToRemove);
    const newDisplayNames = selectedKbDisplayNames.filter(
      (_, i) => i !== indexToRemove
    );

    setSelectedKbIds(newIds);
    setSelectedKbDisplayNames(newDisplayNames);
    setHasSubmitted(false);

    updateParamValue(paramIndex, newIds);
  };

  // Render knowledge base selector input (clickable input that opens selector modal)
  const renderKbSelectorInput = useCallback(
    (param: SkillParam, index: number) => {
      let displayNames = selectedKbDisplayNames;
      let ids = selectedKbIds;
      if (displayNames.length === 0 && ids.length > 0 && knowledgeBases.length > 0) {
        displayNames = mapKbIdsToDisplayNames(ids, knowledgeBases);
      }

      const placeholder = t(
        "toolConfig.input.knowledgeBaseSelector.placeholder",
        {
          name: getLocalizedDescription(param) || param.name,
        }
      );

      const hasError =
        hasSubmitted && param.required && selectedKbIds.length === 0;

      return (
        <div>
          <div
            className={`flex min-h-7 w-full cursor-pointer flex-wrap items-center gap-1 rounded-[2px] border bg-white px-3 transition-colors ${
              hasError
                ? "border-red-500 hover:border-red-500"
                : "border-[#D9D9D9] hover:border-[#2673E5]"
            }`}
            onClick={() => openKbSelector(index)}
            title={displayNames.join(", ")}
          >
            {kbLoading && knowledgeBases.length === 0 ? (
              <div className="flex w-full items-center gap-2">
                <Skeleton.Input active size="small" style={{ width: "60%" }} />
              </div>
            ) : displayNames.length > 0 ? (
              displayNames.map((name, i) => (
                <Tag
                  key={ids[i]}
                  closable
                  closeIcon={
                    <span className="ant-tag-close-icon">
                      <CloseOutlined style={{ fontSize: "10px" }} />
                    </span>
                  }
                  onClose={(e) => {
                    e.stopPropagation();
                    removeKbFromSelection(i, index);
                  }}
                  style={{ marginRight: 0 }}
                >
                  <span
                    style={{
                      maxWidth: "150px",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={name}
                  >
                    {name}
                  </span>
                </Tag>
              ))
            ) : (
              <span style={{ color: "#999", fontSize: "14px" }}>
                {placeholder}
              </span>
            )}
          </div>
          {hasError && (
            <div
              style={{ color: "#ff4d4f", fontSize: "12px", marginTop: "4px" }}
            >
              {t("toolConfig.validation.selectKb")}
            </div>
          )}
        </div>
      );
    },
    [
      selectedKbIds,
      selectedKbDisplayNames,
      hasSubmitted,
      kbLoading,
      knowledgeBases,
      openKbSelector,
      removeKbFromSelection,
      getLocalizedDescription,
      t,
    ]
  );

  const renderParamInput = (param: SkillParam, index: number) => {
    // For knowledge base selector, use custom input
    if (skillRequiresKbSelection && param.name === kbParamName) {
      return renderKbSelectorInput(param, index);
    }

    const placeholder = getLocalizedDescription(param) || param.name;

    switch (param.type) {
      case "number":
        return (
          <InputNumber
            className="!w-full !rounded-[2px] !border-[#D9D9D9]"
            controls={false}
            value={param.value}
            onChange={(value) => updateParamValue(index, value)}
            placeholder={placeholder}
          />
        );

      case "array":
      case "object":
        return (
          <Input.TextArea
            className="!rounded-[2px] !border-[#D9D9D9] !text-[14px]"
            value={param.value != null ? String(param.value) : ""}
            onChange={(e) => updateParamValue(index, e.target.value)}
            placeholder={placeholder}
            autoSize={{ minRows: 1, maxRows: 6 }}
          />
        );

      case "string":
      case "Optional":
      default:
        return (
          <ParamInput
            value={param.value != null ? String(param.value) : ""}
            onChange={(e) => updateParamValue(index, e.target.value)}
            placeholder={placeholder}
          />
        );
    }
  };

  const handleSave = () => {
    if (!currentAgentId) {
      message.error(t("agentConfig.skill.noAgentSelected"));
      return;
    }

    setHasSubmitted(true);

    // Validate required params manually (replacing antd Form.validateFields)
    for (const param of currentParams) {
      if (skillRequiresKbSelection && param.name === kbParamName) {
        if (param.required && selectedKbIds.length === 0) {
          message.error(t("toolConfig.validation.selectKb"));
          return;
        }
        continue;
      }
      if (param.required) {
        const value = param.value;
        const empty =
          value === undefined ||
          value === null ||
          value === "" ||
          (Array.isArray(value) && value.length === 0);
        if (empty) {
          message.error(t("toolConfig.validation.required"));
          return;
        }
      }
    }

    const paramsToSave = currentParams.map((param) => {
      if (skillRequiresKbSelection && param.name === kbParamName) {
        return { ...param, value: selectedKbIds };
      }
      return { ...param };
    });

    if (onSave) {
      onSave(paramsToSave);
    }
    message.success(t("toolConfig.message.saveSuccess"));
    onCancel();
  };

  return (
    <ParamDialog
      open={isOpen}
      title={skill.name}
      onClose={onCancel}
      onConfirm={handleSave}
      confirmText={t("common.save")}
      cancelText={t("common.cancel")}
      zIndex={zIndex}
      maskClosable={maskClosable}
    >
      {currentParams.length > 0 ? (
        currentParams.map((param, index) => {
          if (!visibleIndices.has(index)) return null;
          const description = getLocalizedDescription(param);
          const isKbParam =
            skillRequiresKbSelection && param.name === kbParamName;

          if (param.type === "boolean" && !isKbParam) {
            return (
              <ParamField
                key={param.name}
                label={param.name}
                required={param.required}
                info={!!description}
                infoText={description}
              >
                <ParamSwitch
                  checked={!!param.value}
                  onChange={(value) => updateParamValue(index, value)}
                />
              </ParamField>
            );
          }

          return (
            <ParamField
              key={param.name}
              label={param.name}
              required={param.required}
              info={!!description}
              infoText={description}
            >
              {renderParamInput(param, index)}
            </ParamField>
          );
        })
      ) : (
        <div style={{ textAlign: "center", padding: "24px 0", color: "#999" }}>
          {t("agentConfig.skill.noParams")}
        </div>
      )}

      {/* Knowledge Base Selector Modal */}
      <KnowledgeBaseSelectorModal
        isOpen={kbSelectorVisible}
        onClose={() => setKbSelectorVisible(false)}
        onConfirm={handleKbConfirm}
        selectedIds={selectedKbIds}
        toolType={skillToolType}
        knowledgeBases={knowledgeBases}
        isLoading={kbLoading}
        showCheckbox={true}
        onSync={async () => {
          try {
            await syncKnowledgeBases(skillToolType);
            message.success(t("knowledgeBase.message.syncSuccess"));
          } catch (error) {
            log.error("Failed to sync knowledge bases:", error);
            message.error(t("knowledgeBase.message.syncError"));
          }
        }}
        syncLoading={!!kbLoading || !!isSyncing}
      />
    </ParamDialog>
  );
}