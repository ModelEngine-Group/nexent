"use client";

import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  Form,
  Input,
  Select,
  InputNumber,
  Row,
  Col,
  Flex,
  Card,
  App,
  Alert,
} from "antd";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Zap, Maximize2, Settings2, Sparkles } from "lucide-react";

import {
  AgentConfigUpdate,
  PromptTemplate,
} from "@/types/agentConfig";
import {
  clearExpiredGenerationCaches
} from "@/lib/agentGenerationCache";
import { GENERATE_PROMPT_STREAM_TYPES } from "@/const/agentConfig";
import { useAgentList } from "@/hooks/agent/useAgentList";
import { useAgentGeneration } from "@/hooks/agent/useAgentGeneration";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useModelList } from "@/hooks/model/useModelList";
import { useConfig } from "@/hooks/useConfig";
import { useGroupList, useGroupDetails } from "@/hooks/group/useGroupList";
import { usePromptTemplateList } from "@/hooks/agent/usePromptTemplateList";
import { Can } from "@/components/permission/Can";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import ExpandEditModal from "./ExpandEditModal";
import PromptTemplateManagerModal from "./PromptTemplateManagerModal";
import PromptOptimizeModal from "./PromptOptimizeModal";
import { isAgentPromptsHidden } from "@/lib/agentPromptVisibility";

const { TextArea } = Input;

export default function AgentGenerateDetail({}) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { user, getAccessibleGroupIds } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();
  const [form] = Form.useForm();

  // Group data - get all groups for tenant, then filter to accessible ones
  const { data: groupData } = useGroupList(user?.tenantId ?? null);
  const allGroups = groupData?.groups ?? [];
  const accessibleGroupIds = getAccessibleGroupIds();
  const { groups: filteredGroups } = useGroupDetails(allGroups, accessibleGroupIds);

  const isCreatingMode = useAgentConfigStore((state) => state.isCreatingMode);
  const editedAgent = useAgentConfigStore((state) => state.editedAgent);
  const currentAgentId = useAgentConfigStore((state) => state.currentAgentId);
  const forceRefreshKey = useAgentConfigStore((state) => state.forceRefreshKey);
  const isReadOnly = useAgentConfigStore((state) => state.isReadOnly());
  const updateAgentConfig = useAgentConfigStore((state) => state.updateAgentConfig);
  const isGenerating = useAgentConfigStore((state) => state.isGenerating);

  // Determine if form should be editable (based on isReadOnly only, isGenerating handled separately)
  const editable = !isReadOnly;

  const { defaultLlmModelConfig } = useConfig();
  const { availableLlmModels, models, isLoading: loadingModels } = useModelList();
  const {
    templates: promptTemplates,
    isLoading: loadingPromptTemplates,
    invalidate: invalidatePromptTemplates,
  } = usePromptTemplateList();

  const defaultLlmModel = useMemo(() => {
    if (!defaultLlmModelConfig) return undefined;
    const configName = defaultLlmModelConfig.modelName || defaultLlmModelConfig.displayName || "";
    if (!configName) return undefined;
    const found = availableLlmModels.find(
      (m) => m.name === configName || m.displayName === configName
    );
    if (found) return found;
    return models.find(
      (m) =>
        m.type === "llm" &&
        (m.name === configName || m.displayName === configName)
    );
  }, [defaultLlmModelConfig, availableLlmModels, models]);

  // Agent list for name uniqueness validation (auth-scoped, same as agent dev sidebar)
  const { agents: agentList } = useAgentList("");

  // State management
  const [activeTab, setActiveTab] = useState<string>("agent-info");

  // Streaming field values (accumulated from SSE, bypasses Form disabled state)

  // Modal states
  const [expandModalOpen, setExpandModalOpen] = useState(false);
  const [expandModalType, setExpandModalType] = useState<'duty' | 'constraint' | 'few-shots' | null>(null);
  const [promptTemplateManagerOpen, setPromptTemplateManagerOpen] = useState(false);
  const [optimizeModalOpen, setOptimizeModalOpen] = useState(false);
  const [optimizeModalType, setOptimizeModalType] = useState<'duty' | 'constraint' | 'few-shots' | null>(null);

  // Cleanup invalid cache on mount to prevent stuck "generating" state
  useEffect(() => {
    clearExpiredGenerationCaches();
  }, []);


  // (e.g. business_description from a previously edited agent)
  useEffect(() => {
    if (isCreatingMode) {
      form.resetFields();
    }
  }, [isCreatingMode]);

  // Use agent generation hook
  const { handleGenerateAgent } = useAgentGeneration({
    setActiveTab,
    onStreamUpdate: ({ type, content }) => {
      const fieldMap: Record<string, string> = {
        [GENERATE_PROMPT_STREAM_TYPES.DUTY]: 'dutyPrompt',
        [GENERATE_PROMPT_STREAM_TYPES.CONSTRAINT]: 'constraintPrompt',
        [GENERATE_PROMPT_STREAM_TYPES.FEW_SHOTS]: 'fewShotsPrompt',
        [GENERATE_PROMPT_STREAM_TYPES.AGENT_VAR_NAME]: 'agentName',
        [GENERATE_PROMPT_STREAM_TYPES.AGENT_DESCRIPTION]: 'agentDescription',
        [GENERATE_PROMPT_STREAM_TYPES.AGENT_DISPLAY_NAME]: 'agentDisplayName',
      };

      const fieldName = fieldMap[type];
      if (fieldName) {
        form.setFieldsValue({ [fieldName]: content });
      }
    },
  });

  const normalizeNumberArray = (value: unknown): number[] => {
    const arr = Array.isArray(value) ? value : [];
    return Array.from(
      new Set(arr.map((id) => Number(id)).filter((id) => Number.isFinite(id)))
    ).sort((a, b) => a - b);
  };

  const groupSelectOptions = useMemo(() => {
    return filteredGroups.map((g) => ({
      label: g.group_name,
      value: g.group_id,
    }));
  }, [filteredGroups]);

  // Initialize form values when currentAgentId changes or forceRefreshKey updates
  // Cached generation data is already merged into editedAgent by setCurrentAgent
  useEffect(() => {
    const initialAgentInfo: Record<string, any> = {
      agentName: editedAgent.name || "",
      agentDisplayName: editedAgent.display_name || "",
      agentAuthor: editedAgent.author || user?.email || (isSpeedMode ? "Default User" : ""),
      mainAgentModel: editedAgent.model,
      mainAgentModelId: editedAgent.model_id,
      mainAgentMaxStep: editedAgent.max_step || 15,
      agentDescription: editedAgent.description || "",
      group_ids: normalizeNumberArray(editedAgent.group_ids || []),
      ingroup_permission: editedAgent.ingroup_permission || "READ_ONLY",
      dutyPrompt: editedAgent.duty_prompt || "",
      constraintPrompt: editedAgent.constraint_prompt || "",
      fewShotsPrompt: editedAgent.few_shots_prompt || "",
      provideRunSummary: editedAgent.provide_run_summary || false,
      businessDescription: editedAgent.business_description || "",
      businessLogicModelName:editedAgent.business_logic_model_name,
      businessLogicModelId: editedAgent.business_logic_model_id,
      promptTemplateId: editedAgent.prompt_template_id,
      promptTemplateName: editedAgent.prompt_template_name || "system_default",
    };
    form.setFieldsValue(initialAgentInfo);

  }, [form, currentAgentId, editedAgent, isCreatingMode, defaultLlmModel, accessibleGroupIds, forceRefreshKey]);

  // Handle business description change
  const handleBusinessDescriptionChange = (value: string) => {

    updateAgentConfig({
      business_description: value,
    });
  };

  // Handle model selection for generation
  const handleModelChange = (modelName: string) => {
    const selectedModel = availableLlmModels.find(
      (m) => m.name === modelName || m.displayName === modelName
    );

    updateAgentConfig({
      business_logic_model_id: selectedModel?.id,
      business_logic_model_name: modelName
    });
  };

  const handlePromptTemplateChange = (templateId: number) => {
    const selectedTemplate = promptTemplates.find(
      (template) => template.template_id === templateId
    );
    if (!selectedTemplate) {
      return;
    }
    handleSelectPromptTemplate(selectedTemplate);
  };

  const handleSelectPromptTemplate = (template: PromptTemplate) => {

    updateAgentConfig({
      prompt_template_id: template.template_id,
      prompt_template_name: template.template_name,
    });
  };

  // Handle expand modal functions
  const handleOpenExpandModal = (type: 'duty' | 'constraint' | 'few-shots') => {
    if (!editable) return;
    setExpandModalType(type);
    setExpandModalOpen(true);
  };

  const handleOpenOptimizeModal = (type: 'duty' | 'constraint' | 'few-shots') => {
    const modelId = form.getFieldValue("businessLogicModelId") || editedAgent.business_logic_model_id || 0;
    if (!editable || isGenerating || !modelId) {
      return;
    }
    setOptimizeModalType(type);
    setOptimizeModalOpen(true);
  };

  const renderExpandButton = (type: "duty" | "constraint" | "few-shots") => {
    return (
      <Button
        onClick={() => handleOpenExpandModal(type)}
        title={t("systemPrompt.button.expand")}
        icon={<Maximize2 size={11} />}
        size="small"
        type="text"
        className="prompt-toolbar-button"
        style={{
          color: "#475569",
          width: 24,
          minWidth: 24,
          height: 24,
          borderRadius: 9999,
        }}
        disabled={!editable || isGenerating}
      />
    );
  };

  const renderOptimizeButton = (type: "duty" | "constraint" | "few-shots") => {
    const modelId = form.getFieldValue("businessLogicModelId") || editedAgent.business_logic_model_id || 0;
    return (
      <Button
        onClick={() => handleOpenOptimizeModal(type)}
        title={t("systemPrompt.button.optimize")}
        icon={<Sparkles size={11} />}
        size="small"
        type="text"
        className="prompt-toolbar-button"
        style={{
          color: "#475569",
          width: 24,
          minWidth: 24,
          height: 24,
          borderRadius: 9999,
        }}
        disabled={!editable || isGenerating || !modelId}
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
    padding: "12px",
  };

  const promptToolbarStyle: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "2px 10px 4px",
    borderBottom: "1px solid #eef2f7",
    backgroundColor: "#fff",
    flexShrink: 0,
  };

  const promptToolbarTitleStyle: React.CSSProperties = {
    fontSize: "12px",
    fontWeight: 500,
    color: "#64748b",
    lineHeight: "18px",
    letterSpacing: "0.01em",
  };

  const promptActionGroupStyle: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: "2px",
    padding: "1px",
    borderRadius: 9999,
    border: "1px solid #e2e8f0",
    backgroundColor: "#ffffff",
    boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
  };

  const renderPromptToolbar = (
    type: "duty" | "constraint" | "few-shots",
    title: string
  ) => {
    return (
      <div style={promptToolbarStyle}>
        <span style={promptToolbarTitleStyle}>{title}</span>
        <div style={promptActionGroupStyle}>
          {renderOptimizeButton(type)}
          {renderExpandButton(type)}
        </div>
      </div>
    );
  };

  const promptsHidden = isAgentPromptsHidden(editedAgent);

  const renderPromptSection = (
    type: "duty" | "constraint" | "few-shots",
    fieldName: "dutyPrompt" | "constraintPrompt" | "fewShotsPrompt",
    title: string,
    onBlurUpdate: (value: string) => void
  ) => {
    return (
      <div className="flex flex-col h-full">
        {promptsHidden && (
          <Alert
            type="warning"
            showIcon
            className="mb-3 shrink-0"
            message={t("agent.prompts.noPermission", "You do not have permission to view prompts.")}
          />
        )}
        {renderPromptToolbar(type, title)}
        <Form
          form={form}
          layout="vertical"
          className="flex flex-col flex-1 min-h-0 h-full"
          disabled={isGenerating}
        >
          {renderPromptEditor(fieldName, title, onBlurUpdate)}
        </Form>
      </div>
    );
  };

  const renderPromptEditor = (
    fieldName: "dutyPrompt" | "constraintPrompt" | "fewShotsPrompt",
    placeholder: string,
    onBlurUpdate: (value: string) => void
  ) => {
    return (
      <Form.Item name={fieldName} className="mb-0 h-full [&_.ant-row]:!h-full [&_.ant-col]:!h-full [&_.ant-form-item-control-input]:!h-full [&_.ant-form-item-control-input-content]:!h-full">
        <TextArea
          placeholder={placeholder}
          style={promptEditorStyle}
          disabled={!editable || isGenerating || promptsHidden}
          onBlur={(e) => onBlurUpdate(e.target.value)}
        />
      </Form.Item>
    );
  };

  const handleCloseExpandModal = () => {
    setExpandModalOpen(false);
    setExpandModalType(null);
  };

  const handleCloseOptimizeModal = () => {
    setOptimizeModalOpen(false);
    setOptimizeModalType(null);
  };

  const handleSaveExpandModal = (content: string) => {
    switch (expandModalType) {
      case 'duty':
        form.setFieldsValue({ dutyPrompt: content });
        updateAgentConfig({ duty_prompt: content });
        break;
      case 'constraint':
        form.setFieldsValue({ constraintPrompt: content });
        updateAgentConfig({ constraint_prompt: content });
        break;
      case 'few-shots':
        form.setFieldsValue({ fewShotsPrompt: content });
        updateAgentConfig({ few_shots_prompt: content });
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

  const getPromptFieldKey = (type: 'duty' | 'constraint' | 'few-shots') => {
    switch (type) {
      case "duty":
        return "dutyPrompt";
      case "constraint":
        return "constraintPrompt";
      case "few-shots":
        return "fewShotsPrompt";
    }
  };

  const getStoreFieldKey = (type: 'duty' | 'constraint' | 'few-shots') => {
    switch (type) {
      case "duty":
        return "duty_prompt";
      case "constraint":
        return "constraint_prompt";
      case "few-shots":
        return "few_shots_prompt";
    }
  };

  const handleReplaceOptimizedContent = (content: string) => {
    if (!optimizeModalType) {
      return;
    }

    const formFieldKey = getPromptFieldKey(optimizeModalType);
    const storeFieldKey = getStoreFieldKey(optimizeModalType);

    form.setFieldsValue({ [formFieldKey]: content });
    updateAgentConfig({ [storeFieldKey]: content } as AgentConfigUpdate);
    handleCloseOptimizeModal();
  };

  // Generic validator for agent field uniqueness - use local agent list instead of API call
  const validateAgentFieldUnique = async (
    _: any,
    value: string,
    fieldName: "name" | "display_name",
    errorKey: "nameExists" | "displayNameExists"
  ) => {
    if (!value) return Promise.resolve();

    // Check if field value already exists in local agent list (excluding current agent)
    const isDuplicated = agentList?.some(
      (agent: { name?: string; display_name?: string; id?: string | number }) =>
        (agent as any)[fieldName] === value &&
        Number(agent.id) !== currentAgentId
    );

    if (isDuplicated) {
      return Promise.reject(
        new Error(t(`agent.error.${errorKey}`, { [fieldName]: value }))
      );
    }
    return Promise.resolve();
  };

  // Custom validator for agent name uniqueness
  const validateAgentNameUnique = async (_: any, value: string) => {
    return validateAgentFieldUnique(_, value, "name", "nameExists");
  };

  // Custom validator for agent display name uniqueness
  const validateAgentDisplayNameUnique = async (_: any, value: string) => {
    return validateAgentFieldUnique(_, value, "display_name", "displayNameExists");
  };

  // Select options for available models
  const modelSelectOptions = availableLlmModels.map((model) => ({
    value: model.displayName || model.name,
    label: model.displayName || model.name,
    disabled: model.connect_status !== "available",
  }));

  const promptTemplateSelectOptions = useMemo(() => {
    const options = promptTemplates.map((template) => ({
      value: template.template_id,
      label: template.is_system_default
        ? t("businessLogic.config.template.systemDefault")
        : template.template_name,
    }));

    const templateId = form.getFieldValue("promptTemplateId") || editedAgent.prompt_template_id || 0;
    const templateName = form.getFieldValue("promptTemplateName") || editedAgent.prompt_template_name || "";

    if (
      templateId &&
      !options.some((option) => option.value === templateId)
    ) {
      options.unshift({
        value: templateId,
        label: templateName || t("businessLogic.config.template.label"),
      });
    }

    return options;
  }, [editedAgent.prompt_template_id, editedAgent.prompt_template_name, promptTemplates, t, form]);

  const generationControlLabelStyle = {
    width: 84,
    minWidth: 84,
    flexShrink: 0,
  };

  return (
    <Flex vertical className="h-full">
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
              <Form form={form}>
                <Form.Item name="businessDescription" className="mb-2">
                  <Input.TextArea
                    placeholder={t("businessLogic.placeholder")}
                    className="w-full resize-none text-sm"
                    style={{
                      minHeight: "80px",
                      maxHeight: "170px",
                      border: "none",
                      boxShadow: "none",
                      padding: 0,
                      background: "transparent",
                      overflowX: "hidden",
                      overflowY: "auto",
                    }}
                    autoSize={false}
                    disabled={!editable || isGenerating}
                    onBlur={(e) => handleBusinessDescriptionChange(e.target.value)}
                  />
                </Form.Item>

                {/* Control area */}
                <Flex vertical gap={12} style={{ width: "100%" }}>
                  <Flex align="center" justify="space-between" gap={12} wrap="wrap">
                    <div
                      style={{
                        flex: "1 1 auto",
                        display: "flex",
                        alignItems: "center",
                        minWidth: 0,
                        gap: 12,
                      }}
                    >
                      <span
                        className="text-xs text-gray-600"
                        style={generationControlLabelStyle}
                      >
                        {t("businessLogic.config.template.label")}:
                      </span>
                      <Form.Item name="promptTemplateId" className="mb-0" style={{ flex: "1 1 200px", minWidth: 0 }}>
                        <Select
                          onChange={handlePromptTemplateChange}
                          loading={loadingPromptTemplates}
                          options={promptTemplateSelectOptions}
                          size="middle"
                          disabled={!editable || isGenerating}
                        />
                      </Form.Item>
                    </div>
                    <Button
                      type="primary"
                      size="middle"
                      icon={<Settings2 size={16} />}
                      onClick={() => setPromptTemplateManagerOpen(true)}
                      disabled={!editable || isGenerating}
                    >
                      {t("businessLogic.config.template.manage")}
                    </Button>
                  </Flex>

                  <Flex align="center" justify="space-between" gap={12} wrap="wrap">
                    <div
                      style={{
                        flex: "1 1 auto",
                        display: "flex",
                        alignItems: "center",
                        minWidth: 0,
                        gap: 12,
                      }}
                    >
                      <span
                        className="text-xs text-gray-600"
                        style={generationControlLabelStyle}
                      >
                        {t("model.type.llm")}:
                      </span>
                      <Form.Item name="businessLogicModelName" className="mb-0" style={{ flex: "1 1 200px", minWidth: 0 }}>
                        <Select
                          onChange={handleModelChange}
                          loading={loadingModels}
                          placeholder={t("model.select.placeholder")}
                          options={modelSelectOptions}
                          size="middle"
                          disabled={!editable || isGenerating}
                        />
                      </Form.Item>
                    </div>
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
                  </Flex>
                </Flex>
              </Form>
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
      <Row className="flex-1 min-h-0" style={{ height: 0 }}>
        <Col className="w-full h-full">
          <Tabs
            value={activeTab}
            onValueChange={(value: string) => {
              setActiveTab(value);
            }}
            className="agent-config-tabs flex flex-col h-full w-full"
          >
            <TabsList className="grid w-full grid-cols-4 flex-shrink-0">
              <TabsTrigger value="agent-info">{t("agent.info.title")}</TabsTrigger>
              <TabsTrigger value="duty">{t("systemPrompt.card.duty.title")}</TabsTrigger>
              <TabsTrigger value="constraint">{t("systemPrompt.card.constraint.title")}</TabsTrigger>
              <TabsTrigger value="few-shots">{t("systemPrompt.card.fewShots.title")}</TabsTrigger>
            </TabsList>

            <TabsContent value="agent-info" className="flex-1 min-h-0 overflow-y-auto">
              <div className="overflow-y-auto overflow-x-hidden h-full px-3 pb-3">
                <Row gutter={[16, 16]}>
                  <Col span={24}>
                    <Form form={form} layout="vertical" disabled={!editable || isGenerating}>
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
                            updateAgentConfig({ display_name: e.target.value })
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
                        validateTrigger={["onBlur"]}
                        className="mb-3"
                      >
                        <Input
                          placeholder={t("agent.namePlaceholder")}
                          onChange={(e) =>
                            updateAgentConfig({ name: e.target.value })
                          }
                        />
                      </Form.Item>

                      <Can permission="group:read">
                        <Row gutter={16}>
                          <Col span={12}>
                            <Form.Item
                              name="group_ids"
                              label={t("agent.userGroup")}
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
                                  updateAgentConfig({ group_ids: nextGroupIds });
                                }}
                              />
                            </Form.Item>
                          </Col>
                          <Col span={12}>
                            <Form.Item
                              name="ingroup_permission"
                              label={t("tenantResources.knowledgeBase.permission")}
                            >
                              <Select
                                placeholder={t("tenantResources.knowledgeBase.permission")}
                                options={[
                                  { value: "EDIT", label: t("tenantResources.knowledgeBase.permission.EDIT") },
                                  { value: "READ_ONLY", label: t("tenantResources.knowledgeBase.permission.READ_ONLY") },
                                  { value: "PRIVATE", label: t("tenantResources.knowledgeBase.permission.PRIVATE") },
                                ]}
                                onChange={(value) => {
                                  updateAgentConfig({ ingroup_permission: value });
                                }}
                              />
                            </Form.Item>
                          </Col>
                        </Row>
                      </Can>

                      <Row gutter={16}>
                        <Col span={12}>
                          <Form.Item
                            name="agentAuthor"
                            label={t("agent.author")}
                            rules={[
                              {
                                required: true,
                                message: t("agent.authorPlaceholder"),
                              },
                            ]}
                          >
                            <Input
                              placeholder={t("agent.authorPlaceholder")}
                              onBlur={(e) =>
                                updateAgentConfig({ author: e.target.value })
                              }
                            />
                          </Form.Item>
                        </Col>
                        <Col span={12}>
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
                          >
                            <Select
                              placeholder={t("businessLogic.config.modelPlaceholder")}
                              value={form.getFieldValue("mainAgentModel") || editedAgent.model || ""}
                              onChange={(value) => {
                                const selectedModel = availableLlmModels.find(
                                  (m) => m.displayName === value
                                );
                                form.setFieldsValue({
                                  mainAgentModel: value,
                                  mainAgentModelId: selectedModel?.id || 0,
                                });
                                updateAgentConfig({
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
                        </Col>
                      </Row>

                      <Row gutter={16}>
                        <Col span={12}>
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
                                max: 30,
                                message: t("businessLogic.config.maxSteps"),
                              },
                            ]}
                          >
                            <InputNumber
                              min={1}
                              max={30}
                              style={{ width: "100%" }}
                              onBlur={() => {
                                const value = form.getFieldValue("mainAgentMaxStep");
                                updateAgentConfig({ max_step: value || 1 });
                              }}
                            />
                          </Form.Item>
                        </Col>
                        <Col span={12}>
                          <Form.Item
                            name="provideRunSummary"
                            label={t("agent.provideRunSummary")}
                            rules={[
                              {
                                required: true,
                                message: t("agent.provideRunSummary.error"),
                              },
                            ]}
                          >
                            <Select
                              options={[
                                { value: true, label: t("common.yes") },
                                { value: false, label: t("common.no") },
                              ]}
                              onChange={(value) => {
                                updateAgentConfig({ provide_run_summary: value });
                              }}
                            />
                          </Form.Item>
                        </Col>
                      </Row>

                      <Form.Item
                        name="agentDescription"
                        label={t("agent.description")}
                        className="mb-3"
                      >
                        <TextArea
                          placeholder={t("agent.descriptionPlaceholder")}
                          rows={6}
                          style={{ minHeight: "140px" }}
                          onBlur={(e) =>
                            updateAgentConfig({ description: e.target.value })
                          }
                        />
                      </Form.Item>
                    </Form>
                  </Col>
                </Row>
              </div>
            </TabsContent>

            <TabsContent value="duty" className="flex-1 min-h-0 overflow-y-auto">
              {renderPromptSection(
                "duty",
                "dutyPrompt",
                t("systemPrompt.card.duty.title"),
                (value) => updateAgentConfig({ duty_prompt: value })
              )}
            </TabsContent>

            <TabsContent value="constraint" className="flex-1 min-h-0 overflow-y-auto">
              {renderPromptSection(
                "constraint",
                "constraintPrompt",
                t("systemPrompt.card.constraint.title"),
                (value) => updateAgentConfig({ constraint_prompt: value })
              )}
            </TabsContent>

            <TabsContent value="few-shots" className="flex-1 min-h-0 overflow-y-auto">
              {renderPromptSection(
                "few-shots",
                "fewShotsPrompt",
                t("systemPrompt.card.fewShots.title"),
                (value) => updateAgentConfig({ few_shots_prompt: value })
              )}
            </TabsContent>
          </Tabs>
        </Col>
      </Row>

      {/* Expand Edit Modal */}
      <ExpandEditModal
        open={expandModalOpen}
        title={getExpandModalTitle()}
        content={getExpandModalContent()}
        onClose={handleCloseExpandModal}
        onSave={handleSaveExpandModal}
      />

      <PromptTemplateManagerModal
        open={promptTemplateManagerOpen}
        editable={editable}
        templates={promptTemplates}
        selectedTemplateId={form.getFieldValue("promptTemplateId") || editedAgent.prompt_template_id || 0}
        onClose={() => setPromptTemplateManagerOpen(false)}
        onSelectTemplate={handleSelectPromptTemplate}
        onTemplatesChanged={invalidatePromptTemplates}
      />
      {optimizeModalType ? (
        <PromptOptimizeModal
          open={optimizeModalOpen}
          title={
            optimizeModalType === "duty"
              ? t("systemPrompt.card.duty.title")
              : optimizeModalType === "constraint"
                ? t("systemPrompt.card.constraint.title")
                : t("systemPrompt.card.fewShots.title")
          }
          sectionType={
            optimizeModalType === "few-shots" ? "few_shots" : optimizeModalType
          }
          taskDescription={form.getFieldValue("businessDescription") || editedAgent.business_description || ""}
          currentContent={
            form.getFieldValue(getPromptFieldKey(optimizeModalType)) || ""
          }
          modelId={form.getFieldValue("businessLogicModelId")}
          agentId={currentAgentId ?? 0}
          toolIds={
            Array.isArray(editedAgent.tools)
              ? editedAgent.tools.map((tool: any) =>
                Number(typeof tool === "object" ? tool.id : tool)
              ).filter((id: number) => Number.isFinite(id))
              : []
          }
          subAgentIds={editedAgent.sub_agent_id_list || []}
          knowledgeBaseDisplayNames={
            Array.isArray(editedAgent.tools)
              ? editedAgent.tools.flatMap((tool: any) =>
                typeof tool === "object" && Array.isArray(tool.display_names)
                  ? tool.display_names
                  : []
              )
              : []
          }
          onClose={handleCloseOptimizeModal}
          onReplace={handleReplaceOptimizedContent}
        />
      ) : null}
    </Flex>
  );
}
