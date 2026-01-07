"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
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
import { Zap } from "lucide-react";

import log from "@/lib/logger";
import { EditableAgent } from "@/stores/agentConfigStore";
import { AgentProfileInfo, AgentBusinessInfo } from "@/types/agentConfig";
import {
  checkAgentName,
  checkAgentDisplayName,
} from "@/services/agentConfigService";
import {
  NAME_CHECK_STATUS,
  GENERATE_PROMPT_STREAM_TYPES,
} from "@/const/agentConfig";
import { generatePromptStream } from "@/services/promptService";
import { useAuth } from "@/hooks/useAuth";
import { useModelList } from "@/hooks/model/useModelList";

const { TextArea } = Input;

export interface AgentGenerateDetailProps {
  editable: boolean;
  editedAgent: EditableAgent;
  currentAgentId?: number | null;
  onUpdateProfile: (updates: AgentProfileInfo) => void;
  onUpdateBusinessInfo: (updates: AgentBusinessInfo) => void;
}

export default function AgentGenerateDetail({
  editable = false,
  editedAgent,
  currentAgentId,
  onUpdateProfile,
  onUpdateBusinessInfo,
}: AgentGenerateDetailProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { user, isSpeedMode } = useAuth();
  const [form] = Form.useForm();

  // Model data from React Query
  const { availableLlmModels, isLoading: loadingModels } = useModelList();

  // State management
  const [activeTab, setActiveTab] = useState<string>("agent-info");

  // Generation state
  const [isGenerating, setIsGenerating] = useState(false);


  const userManuallySwitchedTabRef = useRef(false);

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

  

  // Initialize form values when component mounts or currentAgentId changes
  useEffect(() => {
    const initialAgentInfo = {
      agentName: editedAgent.name || "",
      agentDisplayName: editedAgent.display_name || "",
      agentAuthor: editedAgent.author || "",
      mainAgentModel:
        editedAgent.model || availableLlmModels[0]?.displayName || "",
      mainAgentMaxStep: editedAgent.max_step || 5,
      agentDescription: editedAgent.description || "",
      dutyPrompt: editedAgent.duty_prompt || "",
      constraintPrompt: editedAgent.constraint_prompt || "",
      fewShotsPrompt: editedAgent.few_shots_prompt || "",
    };

    const initialBusinessInfo = {
      businessDescription: editedAgent.business_description || "",
      businessLogicModelName:
        editedAgent.business_logic_model_name ||
        availableLlmModels[0]?.displayName ||
        "",
      businessLogicModelId:
        editedAgent.business_logic_model_id || availableLlmModels[0]?.id || 0,
    };
    // Initialize local business description state
    setBusinessInfo(initialBusinessInfo);

    form.setFieldsValue(initialAgentInfo);
  }, [currentAgentId, editedAgent, availableLlmModels]);

  // Handle business description change
  const handleBusinessDescriptionChange = (value: string) => {
    onUpdateBusinessInfo({
      business_description: value,
      business_logic_model_id: editedAgent.business_logic_model_id || 0,
      business_logic_model_name: editedAgent.business_logic_model_name || "",
    });
  };

  // Handle model selection for generation
  const handleModelChange = (modelName: string) => {
    const selectedModel = availableLlmModels.find(
      (m) => m.name === modelName || m.displayName === modelName
    );
    onUpdateBusinessInfo({
      business_description: businessInfo.businessDescription || "",
      business_logic_model_id: selectedModel?.id || 0,
      business_logic_model_name: modelName,
    });
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
    userManuallySwitchedTabRef.current = false; // Reset manual switch tracking when generation starts

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
              !userManuallySwitchedTabRef.current && setActiveTab("duty");
              form.setFieldsValue({ dutyPrompt: data.content });
              break;
            case GENERATE_PROMPT_STREAM_TYPES.CONSTRAINT:
              form.setFieldsValue({ constraintPrompt: data.content });
              !userManuallySwitchedTabRef.current && setActiveTab("constraint");
              break;
            case GENERATE_PROMPT_STREAM_TYPES.FEW_SHOTS:
              !userManuallySwitchedTabRef.current && setActiveTab("few-shots");
              form.setFieldsValue({ fewShotsPrompt: data.content });
              break;
            case GENERATE_PROMPT_STREAM_TYPES.AGENT_VAR_NAME:
              !userManuallySwitchedTabRef.current && setActiveTab("agent-info");
              // Only update if current agent name is empty
              if (!form.getFieldValue("agentName")?.trim()) {
                form.setFieldsValue({ agentName: data.content });
              }
              break;
            case GENERATE_PROMPT_STREAM_TYPES.AGENT_DESCRIPTION:
              !userManuallySwitchedTabRef.current && setActiveTab("agent-info");
              form.setFieldsValue({ agentDescription: data.content });
              break;
            case GENERATE_PROMPT_STREAM_TYPES.AGENT_DISPLAY_NAME:
              !userManuallySwitchedTabRef.current && setActiveTab("agent-info");
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
          userManuallySwitchedTabRef.current = false; // Reset manual switch tracking when generation fails
        },
        () => {
          // 生成完成后，获取所有 form 值并更新父组件状态
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

          // 更新父组件状态
          onUpdateProfile(profileUpdates);

          message.success(t("businessLogic.config.message.generateSuccess"));
          setIsGenerating(false);
          userManuallySwitchedTabRef.current = false; // Reset manual switch tracking when generation completes
        }
      );
    } catch (error) {
      log.error("Generate agent error:", error);
      message.error(t("businessLogic.config.message.generateError"));
      setIsGenerating(false);
      userManuallySwitchedTabRef.current = false; // Reset manual switch tracking when generation fails
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

                <Form.Item
                  name="agentAuthor"
                  label={t("agent.author")}
                  help={
                    !isSpeedMode &&
                    !form.getFieldValue("agentAuthor") &&
                    user?.email &&
                    t("agent.author.hint", {
                      defaultValue: "Default: {{email}}",
                      email: user.email,
                    })
                  }
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
                    onChange={(value) => onUpdateProfile({ model: value })}
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
            </Col>
          </Row>
        </div>
      ),
    },
    {
      key: "duty",
      label: t("systemPrompt.card.duty.title"),
      children: (
        <div className="overflow-y-auto overflow-x-hidden h-full">
          <Form
            form={form}
            layout="vertical"
            className="h-full agent-config-form"
          >
            <Form.Item name="dutyPrompt" className="mb-0 h-full">
              <TextArea
                placeholder={t("systemPrompt.card.duty.title")}
                style={{
                  width: "100%",
                  height: "100%",
                  resize: "none",
                  border: "none",
                  outline: "none",
                  boxShadow: "none",
                  display: "block",
                  flex: 1,
                  minHeight: 0,
                }}
                onBlur={(e) => onUpdateProfile({ duty_prompt: e.target.value })}
              />
            </Form.Item>
          </Form>
        </div>
      ),
    },
    {
      key: "constraint",
      label: t("systemPrompt.card.constraint.title"),
      children: (
        <div className="overflow-y-auto overflow-x-hidden h-full">
          <Form
            form={form}
            layout="vertical"
            className="h-full agent-config-form"
          >
            <Form.Item name="constraintPrompt" className="mb-0 h-full">
              <TextArea
                placeholder={t("systemPrompt.card.constraint.title")}
                style={{
                  width: "100%",
                  height: "100%",
                  resize: "none",
                  border: "none",
                  outline: "none",
                  boxShadow: "none",
                  display: "block",
                  flex: 1,
                  minHeight: 0,
                }}
                onBlur={(e) =>
                  onUpdateProfile({ constraint_prompt: e.target.value })
                }
              />
            </Form.Item>
          </Form>
        </div>
      ),
    },
    {
      key: "few-shots",
      label: t("systemPrompt.card.fewShots.title"),
      children: (
        <div className="overflow-y-auto overflow-x-hidden h-full">
          <Form
            form={form}
            layout="vertical"
            className="h-full agent-config-form"
          >
            <Form.Item name="fewShotsPrompt" className="mb-0 h-full">
              <TextArea
                placeholder={t("systemPrompt.card.fewShots.title")}
                style={{
                  width: "100%",
                  height: "100%",
                  resize: "none",
                  border: "none",
                  outline: "none",
                  boxShadow: "none",
                  display: "block",
                  flex: 1,
                  minHeight: 0,
                }}
                onBlur={(e) =>
                  onUpdateProfile({ few_shots_prompt: e.target.value })
                }
              />
            </Form.Item>
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

              {/* Control area */}
              <Flex justify="space-between" align="center">
                <div>
                  <span className="text-xs text-gray-600 mr-3">
                    {t("model.type.llm")}:
                  </span>
                  <Select
                    value={businessInfo.businessLogicModelName}
                    onChange={handleModelChange}
                    loading={loadingModels}
                    placeholder={t("model.select.placeholder")}
                    style={{ width: 200 }}
                    options={modelSelectOptions}
                    size="middle"
                    disabled={!editable || isGenerating}
                  />
                </div>

                <button
                  onClick={handleGenerateAgent}
                  disabled={!editable || loadingModels || isGenerating}
                  className="px-3 py-1.5 rounded-md flex items-center justify-center text-sm bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{ border: "none" }}
                >
                  <Zap size={16} className="mr-1" />
                  {isGenerating
                    ? t("businessLogic.config.button.generating")
                    : t("businessLogic.config.button.generatePrompt")}
                </button>
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
              // If user manually switches tabs during generation, track it
              if (isGenerating) {
                userManuallySwitchedTabRef.current = true;
              }
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
          transform: none !important; /* 禁用 JS 动态平移（注意会影响滚动行为） */
          transition: none !important;
          justify-content: center !important;
        }

        /* 每个 tab 固定为父宽度的 1/4 */
        .agent-config-tabs .ant-tabs-tab {
          flex: 0 0 25% !important;
          max-width: 25% !important;
          box-sizing: border-box;
        }

        /* 保证 tab 内文字水平居中并在超出时展示省略号 */
        .agent-config-tabs .ant-tabs-tab-btn {
          display: block;
          width: 100%;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          text-align: center;
        }

        /* 选中状态样式：背景蓝色，文字白色 */
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
    </Flex>
  );
}
