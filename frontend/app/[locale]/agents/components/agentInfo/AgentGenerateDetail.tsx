"use client";

import { useState, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  Tooltip,
  Tabs,
  Form,
  Input,
  Select,
  InputNumber,
  Row,
  Col,
  Flex,
  Card,
  App,
} from "antd";
import type { TabsProps } from "antd";
import { Zap, Maximize2 } from "lucide-react";

import log from "@/lib/logger";
import { EditableAgent } from "@/stores/agentConfigStore";
import { AgentProfileInfo, AgentBusinessInfo } from "@/types/agentConfig";
import { configService } from "@/services/configService";
import { ConfigStore } from "@/lib/config";
import {
  checkAgentName,
  checkAgentDisplayName,
} from "@/services/agentConfigService";
import {
  NAME_CHECK_STATUS,
  GENERATE_PROMPT_STREAM_TYPES,
} from "@/const/agentConfig";
import { generatePromptStream } from "@/services/promptService";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useModelList } from "@/hooks/model/useModelList";
import { useTenantList } from "@/hooks/tenant/useTenantList";
import { useGroupList } from "@/hooks/group/useGroupList";
import { USER_ROLES } from "@/const/auth";
import { Can } from "@/components/permission/Can";
import ExpandEditModal from "./ExpandEditModal";

const { TextArea } = Input;

export interface AgentGenerateDetailProps {
  editable: boolean;
  editedAgent: EditableAgent;
  currentAgentId?: number | null;
  onUpdateProfile: (updates: AgentProfileInfo) => void;
  onUpdateBusinessInfo: (updates: AgentBusinessInfo) => void;
  isGenerating: boolean;
  setIsGenerating: (value: boolean) => void;
}

export default function AgentGenerateDetail({
  editable = false,
  editedAgent,
  currentAgentId,
  onUpdateProfile,
  onUpdateBusinessInfo,
  isGenerating,
  setIsGenerating,
}: AgentGenerateDetailProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { user, groupIds: allowedGroupIds } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();
  const [form] = Form.useForm();

  // Model data from React Query
  const { availableLlmModels, defaultLlmModel, isLoading: loadingModels } = useModelList();

  // Tenant & group data for group selection
  const { data: tenantData } = useTenantList();
  const tenantId = user?.tenantId ?? tenantData?.[0]?.tenant_id ?? null;
  const { data: groupData } = useGroupList(tenantId, 1, 100);
  const groups = groupData?.groups || [];

  // State management
  const [activeTab, setActiveTab] = useState<string>("agent-info");

  // Modal states
  const [expandModalOpen, setExpandModalOpen] = useState(false);
  const [expandModalType, setExpandModalType] = useState<'duty' | 'constraint' | 'few-shots' | null>(null);

  // Only show "no edit permission" tooltip when the panel is active and agent is read-only.
  // Note: when no agent is selected, AgentInfoComp shows an overlay and we should not show
  // this tooltip in that state.
  const showNoEditPermissionTip =
    !editable && currentAgentId !== null && currentAgentId !== undefined;

  const noEditPermissionTitle = showNoEditPermissionTip
    ? t("agent.noEditPermission")
    : undefined;

  const wrapNoEditTooltipBlock = (node: React.ReactNode) => {
    return (
      <Tooltip title={noEditPermissionTitle}>
        <span style={{ display: "block" }}>{node}</span>
      </Tooltip>
    );
  };

  const wrapNoEditTooltipInline = (node: React.ReactNode) => {
    return (
      <Tooltip title={noEditPermissionTitle}>
        <span style={{ display: "inline-block" }}>{node}</span>
      </Tooltip>
    );
  };


  // Ensure tenant config is loaded for default model selection
  useEffect(() => {
    const loadConfigIfNeeded = async () => {
      try {
        // Check if config is already loaded
        const configStore = ConfigStore.getInstance();
        const modelConfig = configStore.getModelConfig();

        // If no LLM model is configured, try to load config from backend
        if (!modelConfig.llm?.modelName && !modelConfig.llm?.displayName) {
          await configService.loadConfigToFrontend();
        }
      } catch (error) {
        log.warn("Failed to load tenant config:", error);
      }
    };

    loadConfigIfNeeded();
  }, []);

  const stylesObject: TabsProps["styles"] = {
    root: {},
    header: {},
    item: {
      fontWeight: "500",
      color: "#000",
      padding: `6px 10px`,
      textAlign: "center",
      backgroundColor: "#fff",
    },
    indicator: { height: 4 },
    content: {
      backgroundColor: "#fff",
      borderWidth: 1,
      padding: "8px ",
      borderRadius: "0 0 8px 8px",
      height: "100%",
    },
  };

  // Local state for business info to avoid frequent updates
  const [businessInfo, setBusinessInfo] = useState({
    businessDescription: "",
    businessLogicModelName: "",
    businessLogicModelId: 0,
  });

  const normalizeNumberArray = (value: unknown): number[] => {
    const arr = Array.isArray(value) ? value : [];
    return Array.from(
      new Set(arr.map((id) => Number(id)).filter((id) => Number.isFinite(id)))
    ).sort((a, b) => a - b);
  };

  const groupSelectOptions = useMemo(() => {
    const selectedIds = normalizeNumberArray(editedAgent.group_ids || []);
    const allowedSet = new Set(normalizeNumberArray(allowedGroupIds || []));
    const canSelectAllGroups =
      user?.role === USER_ROLES.SU ||
      user?.role === USER_ROLES.ADMIN ||
      user?.role === USER_ROLES.SPEED;

    const baseGroups = canSelectAllGroups
      ? groups
      : groups.filter((g) => allowedSet.has(g.group_id));

    const baseSet = new Set(baseGroups.map((g) => g.group_id));
    const groupById = new Map(groups.map((g) => [g.group_id, g] as const));

    const options: Array<{ label: string; value: number; disabled?: boolean }> =
      baseGroups.map((g) => ({
        label: g.group_name,
        value: g.group_id,
      }));

    // Keep already-selected groups visible even if they are not selectable (disabled).
    for (const id of selectedIds) {
      if (baseSet.has(id)) continue;
      const g = groupById.get(id);
      options.push({
        label: g?.group_name ?? `Group ${id}`,
        value: id,
        disabled: true,
      });
    }

    return options;
  }, [allowedGroupIds, editedAgent.group_ids, groups, user?.role]);

  // Initialize form values when component mounts or currentAgentId changes
  useEffect(() => {
    const isCreateMode = editable && (currentAgentId === null || currentAgentId === undefined);

    // Note:
    // In create mode, do not set group_ids here. Otherwise, when switching from an existing
    // agent to create mode (currentAgentId changes to null), this initializer can overwrite
    // the default-group selection effect and leave group_ids empty.
    const initialAgentInfo: Record<string, any> = {
      agentName: editedAgent.name || "",
      agentDisplayName: editedAgent.display_name || "",
      agentAuthor: editedAgent.author || user?.email || (isSpeedMode ? "Default User" : ""),
      mainAgentModel:
        editedAgent.model || defaultLlmModel?.displayName || "",
      mainAgentMaxStep: editedAgent.max_step || 5,
      agentDescription: editedAgent.description || "",
      group_ids: normalizeNumberArray(editedAgent.group_ids || []),
      dutyPrompt: editedAgent.duty_prompt || "",
      constraintPrompt: editedAgent.constraint_prompt || "",
      fewShotsPrompt: editedAgent.few_shots_prompt || "",
    };

    if (isCreateMode) {
      delete initialAgentInfo.group_ids;
    }

    const initialBusinessInfo = {
      businessDescription: editedAgent.business_description || "",
      businessLogicModelName:
        editedAgent.business_logic_model_name ||
        defaultLlmModel?.displayName ||
        "",
      businessLogicModelId:
        editedAgent.business_logic_model_id || defaultLlmModel?.id || 0,
    };
    // Initialize local business description state
    setBusinessInfo(initialBusinessInfo);

    form.setFieldsValue(initialAgentInfo);
    // Sync model to store if not already set (e.g., in create mode with default model)
    if ((isCreateMode || !editedAgent.model) && defaultLlmModel) {
      onUpdateProfile({
        model: defaultLlmModel.displayName || "",
        model_id: defaultLlmModel.id || 0,
      });
    }
    // We intentionally initialize the form only when switching agent (or when default model becomes available),
    // otherwise it can create update loops with Form-controlled fields updating the store.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentAgentId, defaultLlmModel?.id]);

  // Default to selecting all groups when creating a new agent.
  // Only applies when groups are loaded and no group is selected yet.
  useEffect(() => {
    const isCreateMode = editable && (currentAgentId === null || currentAgentId === undefined);
    if (!isCreateMode) return;
    if (!groups || groups.length === 0) return;

    const currentGroupIds = normalizeNumberArray(editedAgent.group_ids || []);
    if (currentGroupIds.length > 0) return;

    const allowedSet = new Set(normalizeNumberArray(allowedGroupIds || []));
    const canSelectAllGroups =
      user?.role === USER_ROLES.SU ||
      user?.role === USER_ROLES.ADMIN ||
      user?.role === USER_ROLES.SPEED;
    const selectableGroups = canSelectAllGroups
      ? groups
      : groups.filter((g) => allowedSet.has(g.group_id));

    const allGroupIds = normalizeNumberArray(selectableGroups.map((g) => g.group_id));
    if (allGroupIds.length === 0) return;

    form.setFieldsValue({ group_ids: allGroupIds });
    onUpdateProfile({ group_ids: allGroupIds });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editable, currentAgentId, groups, allowedGroupIds, user?.role]);

  // Handle business description change
  const handleBusinessDescriptionChange = (value: string) => {
    onUpdateBusinessInfo({
      business_description: value,
      business_logic_model_id: businessInfo.businessLogicModelId,
      business_logic_model_name: businessInfo.businessLogicModelName,
    });
  };

  // Handle model selection for generation
  const handleModelChange = (modelName: string) => {
    const selectedModel = availableLlmModels.find(
      (m) => m.name === modelName || m.displayName === modelName
    );
    // Update local state so the Select component reflects the change
    setBusinessInfo((prev) => ({
      ...prev,
      businessLogicModelName: modelName,
      businessLogicModelId: selectedModel?.id || 0,
    }));
    onUpdateBusinessInfo({
      business_description: businessInfo.businessDescription || "",
      business_logic_model_id: selectedModel?.id || 0,
      business_logic_model_name: modelName,
    });
  };

  // Handle expand modal functions
  const handleOpenExpandModal = (type: 'duty' | 'constraint' | 'few-shots') => {
    if (!editable) return;
    setExpandModalType(type);
    setExpandModalOpen(true);
  };

  const renderExpandButton = (type: "duty" | "constraint" | "few-shots") => {
    return wrapNoEditTooltipInline(
      <Button
        onClick={() => handleOpenExpandModal(type)}
        title={t("systemPrompt.button.expand")}
        icon={<Maximize2 size={12} />}
        size="small"
        type="text"
        disabled={!editable}
      />
    );
  };

  const promptEditorStyle: React.CSSProperties = {
    width: "100%",
    height: "100%",
    resize: "none",
    border: "none",
    outline: "none",
    boxShadow: "none",
    display: "block",
    flex: 1,
    minHeight: 0,
  };

  const renderPromptEditor = (
    fieldName: "dutyPrompt" | "constraintPrompt" | "fewShotsPrompt",
    placeholder: string,
    onBlurUpdate: (value: string) => void
  ) => {
    const item = (
      <Form.Item name={fieldName} className="mb-0 h-full">
        <TextArea
          placeholder={placeholder}
          style={promptEditorStyle}
          disabled={!editable}
          onBlur={(e) => onBlurUpdate(e.target.value)}
        />
      </Form.Item>
    );

    return showNoEditPermissionTip ? (
      <Tooltip title={t("agent.noEditPermission")}>
        <div className="h-full">{item}</div>
      </Tooltip>
    ) : (
      item
    );
  };

  const handleCloseExpandModal = () => {
    setExpandModalOpen(false);
    setExpandModalType(null);
  };

  const handleSaveExpandModal = (content: string) => {
    switch (expandModalType) {
      case 'duty':
        form.setFieldsValue({ dutyPrompt: content });
        onUpdateProfile({ duty_prompt: content });
        break;
      case 'constraint':
        form.setFieldsValue({ constraintPrompt: content });
        onUpdateProfile({ constraint_prompt: content });
        break;
      case 'few-shots':
        form.setFieldsValue({ fewShotsPrompt: content });
        onUpdateProfile({ few_shots_prompt: content });
        break;
    }
    handleCloseExpandModal();
  };

  const getExpandModalTitle = () => {
    switch (expandModalType) {
      case 'duty':
        return t("systemPrompt.card.duty.title");
      case 'constraint':
        return t("systemPrompt.card.constraint.title");
      case 'few-shots':
        return t("systemPrompt.card.fewShots.title");
      default:
        return "";
    }
  };

  const getExpandModalContent = () => {
    switch (expandModalType) {
      case 'duty':
        return form.getFieldValue("dutyPrompt") || "";
      case 'constraint':
        return form.getFieldValue("constraintPrompt") || "";
      case 'few-shots':
        return form.getFieldValue("fewShotsPrompt") || "";
      default:
        return "";
    }
  };

  // Custom validator for agent name uniqueness
  const validateAgentNameUnique = async (_: any, value: string) => {
    if (!value) return Promise.resolve();

    try {
      const result = await checkAgentName(value, currentAgentId || undefined);
      if (result.status === NAME_CHECK_STATUS.EXISTS_IN_TENANT) {
        return Promise.reject(
          new Error(t("agent.error.nameExists", { name: value }))
        );
      }
      return Promise.resolve();
    } catch (error) {
      return Promise.reject(
        new Error(t("agent.error.displayNameExists", value))
      );
    }
  };

  // Custom validator for agent display name uniqueness
  const validateAgentDisplayNameUnique = async (_: any, value: string) => {
    if (!value) return Promise.resolve();

    try {
      const result = await checkAgentDisplayName(
        value,
        currentAgentId || undefined
      );
      if (result.status === NAME_CHECK_STATUS.EXISTS_IN_TENANT) {
        return Promise.reject(
          new Error(t("agent.error.displayNameExists", { displayName: value }))
        );
      }
      return Promise.resolve();
    } catch (error) {
      return Promise.reject(
        new Error(t("agent.error.displayNameExists", value))
      );
    }
  };

  const handleGenerateAgent = async () => {
    // Validate business description
    if (
      !businessInfo.businessDescription ||
      businessInfo.businessDescription.trim() === ""
    ) {
      message.error(
        t("businessLogic.config.error.businessDescriptionRequired")
      );
      return;
    }

    // Validate model selection
    if (!businessInfo.businessLogicModelId) {
      message.error("Please select a model first");
      return;
    }

    setIsGenerating(true);
    setActiveTab("few-shots");
    try {
      await generatePromptStream(
        {
          agent_id: currentAgentId || 0,
          task_description: businessInfo.businessDescription,
          model_id: businessInfo.businessLogicModelId.toString(),
          sub_agent_ids: editedAgent.sub_agent_id_list,
          tool_ids: Array.isArray(editedAgent.tools)
            ? editedAgent.tools.map((tool: any) =>
                typeof tool === "object" && tool.id !== undefined
                  ? tool.id
                  : tool
              )
            : [],
        },
        (data) => {
          // Process streaming response data

          switch (data.type) {
            case GENERATE_PROMPT_STREAM_TYPES.DUTY:
              form.setFieldsValue({ dutyPrompt: data.content });
              break;
            case GENERATE_PROMPT_STREAM_TYPES.CONSTRAINT:
              form.setFieldsValue({ constraintPrompt: data.content });
              break;
            case GENERATE_PROMPT_STREAM_TYPES.FEW_SHOTS:

              form.setFieldsValue({ fewShotsPrompt: data.content });
              break;
            case GENERATE_PROMPT_STREAM_TYPES.AGENT_VAR_NAME:
              if (!form.getFieldValue("agentName")?.trim()) {
                form.setFieldsValue({ agentName: data.content });
              }
              break;
            case GENERATE_PROMPT_STREAM_TYPES.AGENT_DESCRIPTION:
              form.setFieldsValue({ agentDescription: data.content });
              break;
            case GENERATE_PROMPT_STREAM_TYPES.AGENT_DISPLAY_NAME:
              // Only update if current agent display name is empty
              if (!form.getFieldValue("agentDisplayName")?.trim()) {
                form.setFieldsValue({ agentDisplayName: data.content });
              }
              break;
          }
        },
        (error) => {
          log.error("Generate prompt stream error:", error);
          message.error(t("businessLogic.config.message.generateError"));
          setIsGenerating(false);
        },
        () => {
          // After generation completes, get all form values and update parent component state
          const formValues = form.getFieldsValue();
          const profileUpdates: AgentProfileInfo = {
            name: formValues.agentName,
            display_name: formValues.agentDisplayName,
            author: formValues.agentAuthor,
            model: formValues.mainAgentModel,
            max_step: formValues.mainAgentMaxStep,
            description: formValues.agentDescription,
            duty_prompt: formValues.dutyPrompt,
            constraint_prompt: formValues.constraintPrompt,
            few_shots_prompt: formValues.fewShotsPrompt,
          };

          // Update parent component state
          onUpdateProfile(profileUpdates);

          message.success(t("businessLogic.config.message.generateSuccess"));
          setIsGenerating(false);
        }
      );
    } catch (error) {
      log.error("Generate agent error:", error);
      message.error(t("businessLogic.config.message.generateError"));
      setIsGenerating(false);
    }
  };

  // Select options for available models
  const modelSelectOptions = availableLlmModels.map((model) => ({
    value: model.displayName || model.name,
    label: model.displayName || model.name,
    disabled: model.connect_status !== "available",
  }));

  // Tab items configuration
  const tabItems = [
    {
      key: "agent-info",
      label: t("agent.info.title"),
      children: (
        <div className="overflow-y-auto overflow-x-hidden h-full px-3">
          <Row gutter={[16, 16]}>
            <Col span={24}>
              {wrapNoEditTooltipBlock(
                <Form form={form} layout="vertical" disabled={!editable}>
                <Form.Item
                  name="agentDisplayName"
                  label={t("agent.displayName")}
                  rules={[
                    {
                      required: true,
                      message: t("agent.info.name.error.empty"),
                    },
                    {
                      max: 50,
                      message: t("agent.info.name.error.length"),
                    },
                    { validator: validateAgentDisplayNameUnique },
                  ]}
                  validateTrigger={["onBlur"]}
                  className="mb-3"
                >
                  <Input
                    placeholder={t("agent.displayNamePlaceholder")}
                    onBlur={(e) =>
                      onUpdateProfile({ display_name: e.target.value })
                    }
                  />
                </Form.Item>

                <Form.Item
                  name="agentName"
                  label={t("agent.name")}
                  rules={[
                    {
                      required: true,
                      message: t("agent.info.name.error.empty"),
                    },
                    { max: 50, message: t("agent.info.name.error.length") },
                    {
                      pattern: /^[a-zA-Z_][a-zA-Z0-9_]*$/,
                      message: t("agent.info.name.error.format"),
                    },
                    { validator: validateAgentNameUnique },
                  ]}
                  className="mb-3"
                >
                  <Input
                    placeholder={t("agent.namePlaceholder")}
                    onChange={(e) => onUpdateProfile({ name: e.target.value })}
                  />
                </Form.Item>

                <Can permission="group:read">
                  <Form.Item
                    name="group_ids"
                    label={t("agent.userGroup")}
                    className="mb-3"
                  >
                    <Select
                      mode="multiple"
                      placeholder={t("agent.userGroup")}
                      options={groupSelectOptions}
                      allowClear
                      onChange={(value) => {
                        const nextGroupIds = normalizeNumberArray(value || []);
                        const currentGroupIds = normalizeNumberArray(
                          editedAgent.group_ids || []
                        );
                        if (
                          JSON.stringify(nextGroupIds) ===
                          JSON.stringify(currentGroupIds)
                        ) {
                          return;
                        }
                        onUpdateProfile({ group_ids: nextGroupIds });
                      }}
                    />
                  </Form.Item>
                </Can>

                <Form.Item
                  name="agentAuthor"
                  label={t("agent.author")}
                  rules={[
                    {
                      required: true,
                      message: t("agent.authorPlaceholder"),
                    },
                  ]}
                  className="mb-3"
                >
                  <Input
                    placeholder={t("agent.authorPlaceholder")}
                    onBlur={(e) => onUpdateProfile({ author: e.target.value })}
                  />
                </Form.Item>

                <Form.Item
                  name="mainAgentModel"
                  label={t("businessLogic.config.model")}
                  rules={[
                    {
                      required: true,
                      message: t("businessLogic.config.modelPlaceholder"),
                    },
                  ]}
                  help={
                    availableLlmModels.length === 0 &&
                    t("businessLogic.config.error.noAvailableModels")
                  }
                  className="mb-3"
                >
                  <Select
                    placeholder={t("businessLogic.config.modelPlaceholder")}
                    onChange={(value) => {
                      const selectedModel = availableLlmModels.find(
                        (m) => m.displayName === value
                      );
                      onUpdateProfile({
                        model: value,
                        model_id: selectedModel?.id || 0,
                      });
                    }}
                  >
                    {availableLlmModels.map((model) => (
                      <Select.Option
                        key={model.id}
                        value={model.displayName}
                        disabled={model.connect_status !== "available"}
                      >
                        {model.displayName}
                      </Select.Option>
                    ))}
                  </Select>
                </Form.Item>

                <Form.Item
                  name="mainAgentMaxStep"
                  label={t("businessLogic.config.maxSteps")}
                  rules={[
                    {
                      required: true,
                      message: t("businessLogic.config.maxSteps"),
                    },
                    {
                      type: "number",
                      min: 1,
                      max: 20,
                      message: t("businessLogic.config.maxSteps"),
                    },
                  ]}
                  className="mb-3"
                >
                  <InputNumber
                    min={1}
                    max={20}
                    style={{ width: "100%" }}
                    onBlur={() => {
                      const value = form.getFieldValue("mainAgentMaxStep");
                      onUpdateProfile({ max_step: value || 1 });
                    }}
                  />
                </Form.Item>

                <Form.Item
                  name="agentDescription"
                  label={t("agent.description")}
                  className="mb-3"
                >
                  <TextArea
                    placeholder={t("agent.descriptionPlaceholder")}
                    rows={6}
                    style={{ minHeight: "150px" }}
                    onBlur={(e) =>
                      onUpdateProfile({ description: e.target.value })
                    }
                  />
                </Form.Item>
              </Form>
              )}
            </Col>
          </Row>
        </div>
      ),
    },
    {
      key: "duty",
      label: t("systemPrompt.card.duty.title"),
      children: (
        <div className="overflow-y-auto overflow-x-hidden h-full relative">
          <div className="absolute top-2 right-2 z-10">
            {renderExpandButton("duty")}
          </div>
          <Form
            form={form}
            layout="vertical"
            className="h-full agent-config-form"
          >
            {renderPromptEditor(
              "dutyPrompt",
              t("systemPrompt.card.duty.title"),
              (value) => onUpdateProfile({ duty_prompt: value })
            )}
          </Form>
        </div>
      ),
    },
    {
      key: "constraint",
      label: t("systemPrompt.card.constraint.title"),
      children: (
        <div className="overflow-y-auto overflow-x-hidden h-full relative">
          <div className="absolute top-2 right-2 z-10">
            {renderExpandButton("constraint")}
          </div>
          <Form
            form={form}
            layout="vertical"
            className="h-full agent-config-form"
          >
            {renderPromptEditor(
              "constraintPrompt",
              t("systemPrompt.card.constraint.title"),
              (value) => onUpdateProfile({ constraint_prompt: value })
            )}
          </Form>
        </div>
      ),
    },
    {
      key: "few-shots",
      label: t("systemPrompt.card.fewShots.title"),
      children: (
        <div className="overflow-y-auto overflow-x-hidden h-full relative">
          <div className="absolute top-2 right-2 z-10">
            {renderExpandButton("few-shots")}
          </div>
          <Form
            form={form}
            layout="vertical"
            className="h-full agent-config-form"
          >
            {renderPromptEditor(
              "fewShotsPrompt",
              t("systemPrompt.card.fewShots.title"),
              (value) => onUpdateProfile({ few_shots_prompt: value })
            )}
          </Form>
        </div>
      ),
    },
  ];

  return (
    <Flex vertical className="h-full">
      {/* Business Logic Section */}
      <Row gutter={[12, 12]} className="mb-4">
        <Col xs={24}>
          <h4 className="text-md font-medium text-gray-700">
            {t("businessLogic.title")}
          </h4>
        </Col>
        <Col xs={24}>
          <Flex className="w-full">
            <Card
              className="w-full rounded-md"
              styles={{ body: { padding: "16px" } }}
            >
              {wrapNoEditTooltipBlock(
                <Input.TextArea
                  value={businessInfo.businessDescription}
                  onChange={(e) =>
                    setBusinessInfo((prev) => ({
                      ...prev,
                      businessDescription: e.target.value,
                    }))
                  }
                  onBlur={() =>
                    handleBusinessDescriptionChange(
                      businessInfo.businessDescription
                    )
                  }
                  placeholder={t("businessLogic.placeholder")}
                  className="w-full resize-none text-sm mb-2"
                  style={{
                    minHeight: "80px",
                    maxHeight: "160px",
                    border: "none",
                    boxShadow: "none",
                    padding: 0,
                    background: "transparent",
                    overflowX: "hidden",
                    overflowY: "auto",
                  }}
                  autoSize={false}
                  disabled={!editable}
                />
              )}

              {/* Control area */}
              <Flex style={{ width: "100%" }} align="center">
                <div style={{ flex: 1, display: "flex", alignItems: "center", minWidth: 0 }}>
                  <span className="text-xs text-gray-600 mr-3">
                    {t("model.type.llm")}:
                  </span>
                  <Select
                    value={businessInfo.businessLogicModelName}
                    onChange={handleModelChange}
                    loading={loadingModels}
                    placeholder={t("model.select.placeholder")}
                    options={modelSelectOptions}
                    size="middle"
                    disabled={!editable || isGenerating}
                    style={{
                      flex: 1,
                      minWidth: 0,
                      maxWidth: '300px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap'
                    }}
                  />
                </div>
                <div style={{ marginLeft: 12 }}>
                  {wrapNoEditTooltipInline(
                    <Button
                      type="primary"
                      size="middle"
                      onClick={handleGenerateAgent}
                      disabled={!editable || loadingModels || isGenerating}
                      icon={<Zap size={16} />}
                    >
                      <span className="button-text-full">
                        {isGenerating
                          ? t("businessLogic.config.button.generating")
                          : t("businessLogic.config.button.generatePrompt")}
                      </span>
                    </Button>
                  )}
                </div>
              </Flex>
            </Card>
          </Flex>
        </Col>
      </Row>

      {/* Agent Detail Section */}
      <Row gutter={[12, 12]} className="mb-3">
        <Col xs={24}>
          <h4 className="text-md font-medium text-gray-700">
            {t("agent.detailContent.title")}
          </h4>
        </Col>
      </Row>

      {/* Tabs Content */}
      <Row className="flex:1 min-h-0 h-full">
        <Col className="w-full h-full">
          <Tabs
            centered
            activeKey={activeTab}
            onChange={(key) => {
              setActiveTab(key);
            }}
            items={tabItems}
            size="middle"
            type="card"
            tabBarStyle={{}}
            tabBarGutter={0}
            styles={stylesObject}
            className="agent-config-tabs h-full"
          />
        </Col>
      </Row>

      {/* style={{ height: "100%" }}
      className="agent-config-tabs" */}

      {/* Fix tabs not adapting to height and make tabs evenly distributed (overriding Ant Design's default styles) */}
      <style jsx global>{`
        .agent-config-tabs .ant-tabs-nav-list {
          width: 100% !important;
          display: flex !important;
          transform: none !important;
          transition: none !important;
          justify-content: center !important;
        }

        /* Each tab is fixed to 1/4 of parent width */
        .agent-config-tabs .ant-tabs-tab {
          flex: 0 0 25% !important;
          max-width: 25% !important;
          box-sizing: border-box;
        }

        /* Ensure text in tab is horizontally centered and shows ellipsis when overflow */
        .agent-config-tabs .ant-tabs-tab-btn {
          display: block;
          width: 100%;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          text-align: center;
        }

        /* Selected state style: blue background, white text */
        .agent-config-tabs .ant-tabs-tab-active {
          background-color: #1890ff !important;
        }

        .agent-config-tabs .ant-tabs-tab-active .ant-tabs-tab-btn {
          color: #fff !important;
        }
        .agent-config-tabs .ant-tabs-content {
          height: 100% !important;
        }

        /* Ensure the form and its nested Ant components use a flex layout so textarea can grow */
        .agent-config-form,
        .agent-config-form .ant-form-item,
        .agent-config-form .ant-form-item .ant-row,
        .agent-config-form .ant-form-item .ant-row .ant-col,
        .agent-config-form
          .ant-form-item
          .ant-row
          .ant-col
          .ant-form-item-control-input,
        .agent-config-form
          .ant-form-item
          .ant-row
          .ant-col
          .ant-form-item-control-input
          .ant-form-item-control-input-content,
        .agent-config-form .ant-form-item-control-input-content {
          height: 100% !important;
        }
      `}</style>

      {/* Expand Edit Modal */}
      <ExpandEditModal
        open={expandModalOpen}
        title={getExpandModalTitle()}
        content={getExpandModalContent()}
        onClose={handleCloseExpandModal}
        onSave={handleSaveExpandModal}
      />
    </Flex>
  );
}
