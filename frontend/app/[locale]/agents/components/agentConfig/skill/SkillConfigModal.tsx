"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { useTranslation } from "react-i18next";
import {
  Modal,
  Form,
  Input,
  Switch,
  InputNumber,
  Button,
  message,
  Tag,
  Skeleton,
} from "antd";
import { Settings } from "lucide-react";
import { CloseOutlined } from "@ant-design/icons";

import { Skill, SkillParam } from "@/types/agentConfig";
import { KnowledgeBase } from "@/types/knowledgeBase";
import { Tooltip } from "@/components/ui/tooltip";
import { saveSkillInstance } from "@/services/agentConfigService";
import KnowledgeBaseSelectorModal from "@/components/tool-config/KnowledgeBaseSelectorModal";
import {
  getToolTypeForSkill,
  skillRequiresKbSelection as checkSkillRequiresKb,
  getKbParamNameForSkill,
  ToolKbType,
} from "@/components/tool-config";
import { useKnowledgeBasesForToolConfig, useSyncKnowledgeBases } from "@/hooks/useKnowledgeBaseSelector";
import log from "@/lib/logger";
import { isZhLocale, getKbDisplayName, mapKbIdsToDisplayNames, parseKbIds } from "@/lib/utils";

export interface SkillConfigModalProps {
  isOpen: boolean;
  onCancel: () => void;
  onSave?: (params: SkillParam[]) => void;
  skill: Skill;
  initialParams: SkillParam[];
  currentAgentId?: number;
  isCreatingMode?: boolean;
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
  isCreatingMode,
}: SkillConfigModalProps) {
  const [form] = Form.useForm();
  const [isLoading, setIsLoading] = useState(false);
  const [currentParams, setCurrentParams] = useState<SkillParam[]>([]);
  const { t } = useTranslation("common");
  const isZh = isZhLocale();

  // Check if this skill requires knowledge base selection (has index_names or dataset_ids param)
  const skillRequiresKbSelection = useMemo(() => {
    return checkSkillRequiresKb(initialParams || []);
  }, [initialParams]);

  // Derive the correct toolType based on skill name
  const skillToolType = useMemo((): ToolKbType => {
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
        const depIdx = currentParams.findIndex((p) => p.name === param.depends_on);
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
  const [currentKbParamIndex, setCurrentKbParamIndex] = useState<number | null>(null);
  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  const [selectedKbDisplayNames, setSelectedKbDisplayNames] = useState<string[]>([]);
  const [hasSubmitted, setHasSubmitted] = useState(false);

  // Fetch knowledge bases based on skill tool type
  const {
    data: knowledgeBases = [],
    isLoading: kbLoading,
    refetch: refetchKnowledgeBases,
  } = useKnowledgeBasesForToolConfig(skillToolType);

  // Sync knowledge bases based on skill tool type
  const { syncKnowledgeBases, isSyncing } = useSyncKnowledgeBases();

  // Sync selectedKbDisplayNames when knowledgeBases or selectedKbIds changes
  useEffect(() => {
    if (selectedKbIds.length > 0 && knowledgeBases.length > 0) {
      setSelectedKbDisplayNames(mapKbIdsToDisplayNames(selectedKbIds, knowledgeBases));
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
        setSelectedKbDisplayNames(mapKbIdsToDisplayNames(validKbIds, knowledgeBases));
      }
    }
  }, [knowledgeBases, selectedKbIds]);

  // Build currentParams: merge saved config_values with schema defaults.
  // config_values from the database (skill.config_values) takes precedence over schema defaults.
  useEffect(() => {
    if (!isOpen) return;

    const schema = initialParams && Array.isArray(initialParams) ? initialParams : [];

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

    // Initialize form with indexed field names
    const formValues: Record<string, any> = {};
    merged.forEach((param, index) => {
      formValues[`param_${index}`] = param.value;
    });
    form.setFieldsValue(formValues);

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
  }, [isOpen, initialParams, skill.config_values, form, skillRequiresKbSelection, kbParamName]);

  // Watch all form values and sync to currentParams
  const formValues = Form.useWatch([], form);
  useEffect(() => {
    if (!formValues) return;
    const newParams = [...currentParams];
    Object.entries(formValues).forEach(([fieldName, value]) => {
      const index = parseInt(fieldName.replace("param_", ""));
      if (!isNaN(index) && newParams[index]) {
        // Skip knowledge base selector field (controlled by selectedKbIds)
        if (newParams[index].name === kbParamName) {
          return;
        }
        newParams[index] = { ...newParams[index], value };
      }
    });
    setCurrentParams(newParams);
  }, [formValues]);

  const handleSave = async () => {
    if (!currentAgentId && !isCreatingMode) {
      message.error(t("agentConfig.skill.noAgentSelected"));
      return;
    }

    setIsLoading(true);
    setHasSubmitted(true);
    try {
      // Force sync form values before validation
      const latestFormValues = form.getFieldsValue();
      if (latestFormValues) {
        const newParams = [...currentParams];
        Object.entries(latestFormValues).forEach(([fieldName, value]) => {
          const index = parseInt(fieldName.replace("param_", ""));
          if (!isNaN(index) && newParams[index]) {
            newParams[index] = { ...newParams[index], value };
          }
        });
        setCurrentParams(newParams);
      }

      // Check if knowledge base selector has valid selection
      if (skillRequiresKbSelection && selectedKbIds.length === 0) {
        const kbParam = currentParams.find(
          (p) => p.required && p.name === kbParamName
        );
        if (kbParam) {
          message.error(t("toolConfig.validation.selectKb"));
          setIsLoading(false);
          return;
        }
      }

      await form.validateFields();

      const paramsToSave = currentParams.map((param) => ({
        ...param,
        value: param.value,
      }));

      const configValues = paramsToSave.reduce<Record<string, any>>((acc, p) => {
        acc[p.name] = p.value;
        return acc;
      }, {});

      if (!isCreatingMode && currentAgentId) {
        const result = await saveSkillInstance(
          Number(skill.skill_id),
          Number(currentAgentId),
          true,
          0,
          configValues
        );

        if (!result.success) {
          message.error(result.message || t("agentConfig.skill.saveFailed"));
          setIsLoading(false);
          return;
        }
      }

      if (onSave) {
        onSave(paramsToSave);
      }
      message.success(t("toolConfig.message.saveSuccess"));
      onCancel();
    } catch {
      // Validation failed - error shown by antd Form
    } finally {
      setIsLoading(false);
    }
  };

  const getLocalizedDescription = useCallback(
    (param: SkillParam) => {
      return isZh ? param.description_zh || param.description_en : param.description_en;
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
    const displayNames = selectedKnowledgeBases.map((kb) => getKbDisplayName(kb));

    setSelectedKbIds(ids);
    setSelectedKbDisplayNames(displayNames);
    setHasSubmitted(false);

    // Update form value
    if (currentKbParamIndex !== null) {
      const param = currentParams[currentKbParamIndex];
      if (param) {
        const formFieldName = `param_${currentKbParamIndex}`;
        form.setFieldValue(formFieldName, ids);

        // Also update currentParams directly since Form.Item has no name for KB param
        const updatedParams = [...currentParams];
        updatedParams[currentKbParamIndex] = {
          ...updatedParams[currentKbParamIndex],
          name: param.name,
          value: ids,
        };
        setCurrentParams(updatedParams);
      }
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

    // Update form value
    const formFieldName = `param_${paramIndex}`;
    form.setFieldValue(formFieldName, newIds);

    // Also update currentParams directly
    const updatedParams = [...currentParams];
    if (updatedParams[paramIndex]) {
      updatedParams[paramIndex] = {
        ...updatedParams[paramIndex],
        value: newIds,
      };
      setCurrentParams(updatedParams);
    }
  };

  // Render knowledge base selector input (clickable input that opens selector modal)
  const renderKbSelectorInput = useCallback(
    (param: SkillParam, index: number) => {
      const fieldName = `param_${index}`;
      const formValue = form.getFieldValue(fieldName);

      // Get display names based on current form value and knowledgeBases
      let displayNames: string[] = [];
      let ids: string[] = [];
      if (formValue) {
        ids = parseKbIds(formValue);

        if (ids.length > 0 && knowledgeBases.length > 0) {
          displayNames = mapKbIdsToDisplayNames(ids, knowledgeBases);
        }
      }

      // Fallback to selectedKbDisplayNames if displayNames is empty
      if (displayNames.length === 0 && selectedKbDisplayNames.length > 0) {
        displayNames = selectedKbDisplayNames;
        ids = selectedKbIds;
      }

      const placeholder = t(
        "toolConfig.input.knowledgeBaseSelector.placeholder",
        {
          name: getLocalizedDescription(param) || param.name,
        }
      );

      // Check if this field has validation error
      const hasError =
        hasSubmitted && param.required && selectedKbIds.length === 0;

      return (
        <div>
          <div
            className={`cursor-pointer bg-white border rounded px-3 py-2 transition-colors ${
              hasError
                ? "border-red-500 hover:border-red-500"
                : "border-gray-300 hover:border-blue-400"
            }`}
            onClick={() => openKbSelector(index)}
            style={{
              width: "100%",
              minHeight: "32px",
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              gap: "4px",
            }}
            title={displayNames.join(", ")}
          >
            {kbLoading && knowledgeBases.length === 0 ? (
              <div className="flex items-center gap-2 w-full">
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
            <div style={{ color: "#ff4d4f", fontSize: "12px", marginTop: "4px" }}>
              {t("toolConfig.validation.selectKb")}
            </div>
          )}
        </div>
      );
    },
    [
      form,
      knowledgeBases,
      selectedKbIds,
      selectedKbDisplayNames,
      hasSubmitted,
      kbLoading,
      openKbSelector,
      removeKbFromSelection,
      getLocalizedDescription,
      t,
      kbParamName,
    ]
  );

  const renderParamInput = (param: SkillParam, index: number) => {
    const inputStyle = { width: "100%" };

    // For knowledge base selector, use custom input
    if (skillRequiresKbSelection && param.name === kbParamName) {
      return renderKbSelectorInput(param, index);
    }

    switch (param.type) {
      case "number":
        return (
          <InputNumber
            style={inputStyle}
            value={param.value}
            placeholder={getLocalizedDescription(param) || param.name}
          />
        );

      case "boolean":
        return (
          <Switch
            value={param.value}
            onChange={(checked) => {
              const updatedParams = [...currentParams];
              updatedParams[index] = { ...updatedParams[index], value: checked };
              setCurrentParams(updatedParams);
              form.setFieldValue(`param_${index}`, checked);
            }}
          />
        );

      case "array":
      case "object":
        return (
          <Input.TextArea
            style={inputStyle}
            value={param.value != null ? String(param.value) : ""}
            placeholder={getLocalizedDescription(param) || param.name}
            autoSize={{ minRows: 1, maxRows: 6 }}
          />
        );

      case "string":
      case "Optional":
      default:
        return (
          <Input
            style={inputStyle}
            value={param.value != null ? String(param.value) : ""}
            placeholder={getLocalizedDescription(param) || param.name}
          />
        );
    }
  };

  return (
    <Modal
      title={
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Settings size={18} />
          <span>{skill.name}</span>
        </div>
      }
      open={isOpen}
      onCancel={onCancel}
      width={600}
      destroyOnClose
      footer={
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button onClick={onCancel}>{t("common.cancel")}</Button>
          <Button type="primary" onClick={handleSave} loading={isLoading}>
            {t("common.save")}
          </Button>
        </div>
      }
    >
      {currentParams.length > 0 ? (
        <>
          <div style={{ fontSize: 14, color: "#666", marginBottom: 4 }}>
            {t("agentConfig.skill.config.parameters") || "Parameters"}
          </div>
          <div style={{ maxHeight: 500, overflow: "auto" }}>
            <Form
              form={form}
              layout="horizontal"
              labelAlign="left"
              labelCol={{ span: 6 }}
              wrapperCol={{ span: 18 }}
            >
              {currentParams.map((param, index) => {
                const fieldName = `param_${index}`;
                const rules: any[] = [];

                if (param.required) {
                  rules.push({
                    required: true,
                    message: t("toolConfig.validation.required"),
                  });
                }

                // Add custom validator for knowledge base selector field (index_names/dataset_ids)
                // Since this field uses custom display without form control, we need custom validation
                if (
                  skillRequiresKbSelection &&
                  param.name === kbParamName
                ) {
                  rules.push({
                    validator: async () => {
                      if (selectedKbIds.length === 0) {
                        throw new Error(t("toolConfig.validation.selectKb"));
                      }
                    },
                  });
                }

                const isVisible = visibleIndices.has(index);

                return (
                  <Form.Item
                    key={param.name}
                    required={param.required}
                    label={
                      <Tooltip title={param.name} placement="topLeft">
                        <span className="truncate">{param.name}</span>
                      </Tooltip>
                    }
                    name={
                      skillRequiresKbSelection && param.name === kbParamName
                        ? undefined
                        : fieldName
                    }
                    rules={rules}
                    tooltip={{
                      title: getLocalizedDescription(param),
                      placement: "topLeft",
                      styles: { root: { maxWidth: 400 } },
                    }}
                    style={{ display: isVisible ? undefined : "none" }}
                  >
                    {renderParamInput(param, index)}
                  </Form.Item>
                );
              })}
            </Form>
          </div>
        </>
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
    </Modal>
  );
}
