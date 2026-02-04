"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  Modal,
  Input,
  Switch,
  InputNumber,
  Tag,
  Form,
  message,
  Select,
  Skeleton,
} from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { CloseOutlined } from "@ant-design/icons";
import { ConfigStore } from "@/lib/config";

import { TOOL_PARAM_TYPES, getToolParamOptions } from "@/const/agentConfig";
import { ToolParam, Tool } from "@/types/agentConfig";
import { KnowledgeBase } from "@/types/knowledgeBase";
import ToolTestPanel from "./ToolTestPanel";
import { updateToolConfig } from "@/services/agentConfigService";
import KnowledgeBaseSelectorModal from "@/components/tool-config/KnowledgeBaseSelectorModal";
import {
  useKnowledgeBasesForToolConfig,
  useSyncKnowledgeBases,
} from "@/hooks/useKnowledgeBaseSelector";

export interface ToolConfigModalProps {
  isOpen: boolean;
  onCancel: () => void;
  onSave?: (params: ToolParam[]) => void;
  tool: Tool;
  initialParams: ToolParam[];
  selectedTool?: Tool | null;
  isCreatingMode?: boolean;
  currentAgentId?: number;
}

// Tool types that require knowledge base selection
const TOOLS_REQUIRING_KB_SELECTION = [
  "knowledge_base_search",
  "dify_search",
  "datamate_search",
];

export default function ToolConfigModal({
  isOpen,
  onCancel,
  onSave,
  tool,
  initialParams,
  selectedTool,
  isCreatingMode,
  currentAgentId,
}: ToolConfigModalProps) {
  const [currentParams, setCurrentParams] = useState<ToolParam[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const { t } = useTranslation("common");
  const [form] = Form.useForm();
  const queryClient = useQueryClient();
  const updateTools = useAgentConfigStore((state) => state.updateTools);

  // Tool test panel visibility state
  const [testPanelVisible, setTestPanelVisible] = useState(false);

  // Knowledge base selector state
  const [kbSelectorVisible, setKbSelectorVisible] = useState(false);
  const [currentKbParamIndex, setCurrentKbParamIndex] = useState<number | null>(
    null
  );
  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  const [selectedKbDisplayNames, setSelectedKbDisplayNames] = useState<
    string[]
  >([]);

  // Dify configuration state
  const [difyConfig, setDifyConfig] = useState<{
    serverUrl: string;
    apiKey: string;
  }>({
    serverUrl: "",
    apiKey: "",
  });

  // Check if current tool requires knowledge base selection (must be declared before toolKbType)
  const toolRequiresKbSelection = useMemo(() => {
    return TOOLS_REQUIRING_KB_SELECTION.includes(tool?.name);
  }, [tool?.name]);

  // Get tool type for knowledge base selection
  const toolKbType = useMemo(():
    | "knowledge_base_search"
    | "dify_search"
    | "datamate_search"
    | null => {
    if (!toolRequiresKbSelection) return null;
    const name = tool?.name;
    if (name === "dify_search") return "dify_search";
    if (name === "datamate_search") return "datamate_search";
    return "knowledge_base_search";
  }, [tool?.name, toolRequiresKbSelection]);

  // Get Dify configuration from initial params
  const difyServerUrlParam = useMemo(() => {
    return currentParams.find((param) => param.name === "server_url");
  }, [currentParams]);

  const difyApiKeyParam = useMemo(() => {
    return currentParams.find((param) => param.name === "api_key");
  }, [currentParams]);

  // Initialize Dify config from params
  useEffect(() => {
    if (toolKbType === "dify_search") {
      const serverUrl = difyServerUrlParam?.value || "";
      const apiKey = difyApiKeyParam?.value || "";

      setDifyConfig({
        serverUrl,
        apiKey,
      });
    }
  }, [toolKbType, difyServerUrlParam, difyApiKeyParam]);

  // Fetch knowledge bases for tool config based on tool type (now uses React Query caching)
  const {
    data: knowledgeBases = [],
    isLoading: kbLoading,
    refetch: refetchKnowledgeBases,
  } = useKnowledgeBasesForToolConfig(
    toolKbType,
    toolKbType === "dify_search" ? difyConfig : undefined
  );

  // Sync knowledge bases hook
  const { syncKnowledgeBases, isSyncing } = useSyncKnowledgeBases();

  // Get current embedding model from config for model matching
  const currentEmbeddingModel = useMemo(() => {
    try {
      const configStore = ConfigStore.getInstance();
      const modelConfig = configStore.getModelConfig();
      // Use modelName if available, otherwise try displayName
      return (
        modelConfig.embedding?.modelName ||
        modelConfig.embedding?.displayName ||
        null
      );
    } catch {
      return null;
    }
  }, []);

  // Check if a knowledge base can be selected
  const canSelectKnowledgeBase = useCallback(
    (kb: KnowledgeBase): boolean => {
      // Empty knowledge bases cannot be selected
      const isEmpty =
        (kb.documentCount || 0) === 0 && (kb.chunkCount || 0) === 0;
      if (isEmpty) {
        return false;
      }

      // For nexent source, check model matching
      if (kb.source === "nexent" && currentEmbeddingModel) {
        if (
          kb.embeddingModel &&
          kb.embeddingModel !== "unknown" &&
          kb.embeddingModel !== currentEmbeddingModel
        ) {
          return false;
        }
      }

      return true;
    },
    [currentEmbeddingModel]
  );

  // Initialize with provided params and sync display names when knowledgeBases is ready
  useEffect(() => {
    // Initialize form values
    setCurrentParams(initialParams);
    const formValues: Record<string, any> = {};
    initialParams.forEach((param, index) => {
      formValues[`param_${index}`] = param.value;
    });
    form.setFieldsValue(formValues);

    // Parse initial index_names/dataset_ids value for knowledge base selection
    if (toolRequiresKbSelection) {
      // Support both index_names and dataset_ids
      const kbParam = initialParams.find(
        (p) => p.name === "index_names" || p.name === "dataset_ids"
      );
      if (kbParam?.value) {
        let ids: string[] = [];
        // Value can be an array or a JSON string
        if (Array.isArray(kbParam.value)) {
          ids = kbParam.value.map(String);
        } else if (typeof kbParam.value === "string") {
          try {
            const parsed = JSON.parse(kbParam.value);
            if (Array.isArray(parsed)) {
              ids = parsed.map(String);
            }
          } catch {
            ids = kbParam.value.split(",").filter(Boolean);
          }
        }

        if (ids.length > 0) {
          setSelectedKbIds(ids);
          // If knowledgeBases is already loaded, sync display names immediately
          if (knowledgeBases.length > 0) {
            const displayNames = ids.map((id) => {
              const kb = knowledgeBases.find((k) => k.id === id);
              return kb?.display_name || kb?.name || id;
            });
            setSelectedKbDisplayNames(displayNames);
          }
        }
      }
    }
  }, [initialParams, toolRequiresKbSelection]);

  // Sync selectedKbDisplayNames when knowledgeBases or selectedKbIds changes
  useEffect(() => {
    if (selectedKbIds.length > 0 && knowledgeBases.length > 0) {
      const displayNames = selectedKbIds.map((id) => {
        const kb = knowledgeBases.find((k) => k.id === id);
        return kb?.display_name || kb?.name || id;
      });
      setSelectedKbDisplayNames(displayNames);
    }
  }, [knowledgeBases, selectedKbIds]);

  // Trigger refetch when opening for knowledge base tools (with loading state support)
  useEffect(() => {
    if (toolRequiresKbSelection && isOpen) {
      // For Dify, only refetch if we have valid config
      if (toolKbType === "dify_search") {
        if (difyConfig.serverUrl && difyConfig.apiKey) {
          refetchKnowledgeBases();
        }
      } else {
        refetchKnowledgeBases();
      }
    }
  }, [
    toolRequiresKbSelection,
    isOpen,
    refetchKnowledgeBases,
    toolKbType,
    difyConfig,
  ]);

  // Watch all form values and sync to currentParams
  const formValues = Form.useWatch([], form);
  useEffect(() => {
    if (formValues) {
      const newParams = [...currentParams];
      Object.entries(formValues).forEach(([fieldName, value]) => {
        const index = parseInt(fieldName.replace("param_", ""));
        if (!isNaN(index) && newParams[index]) {
          newParams[index] = { ...newParams[index], value };
        }
      });
      setCurrentParams(newParams);
    }
  }, [formValues]);

  const handleSave = async () => {
    try {
      // Force sync form values to currentParams before validation
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

      await form.validateFields();

      // Use selectedTool if available, otherwise use tool
      const toolToSave = selectedTool || tool;
      if (!toolToSave) {
        message.error("No tool selected");
        return;
      }

      // Convert params to backend format (use the synced params)
      const paramsObj = currentParams.reduce(
        (acc, param) => {
          acc[param.name] = param.value;
          return acc;
        },
        {} as Record<string, any>
      );

      // Update local state: Add tool to selected tools with updated params
      const updatedTool = { ...toolToSave, initParams: currentParams };
      const currentTools = useAgentConfigStore.getState().editedAgent.tools;

      // Check if tool already exists, if so replace it, otherwise add it
      const existingToolIndex = currentTools.findIndex(
        (t) => parseInt(t.id) === parseInt(updatedTool.id)
      );

      let newSelectedTools;
      if (existingToolIndex >= 0) {
        // Replace existing tool
        newSelectedTools = [...currentTools];
        newSelectedTools[existingToolIndex] = updatedTool;
      } else {
        // Add new tool
        newSelectedTools = [...currentTools, updatedTool];
      }

      // For editing mode (when currentAgentId exists), always call API
      // For creating mode (isCreatingMode=true), update local state only
      if (isCreatingMode) {
        // In creating mode, just update local state
        updateTools(newSelectedTools);
        message.success(t("toolConfig.message.saveSuccess"));
        handleClose(); // Close modal
        return;
      }

      if (!currentAgentId) {
        // Should not happen in normal editing mode, but handle gracefully
        updateTools(newSelectedTools);
        message.success(t("toolConfig.message.saveSuccess"));
        handleClose(); // Close modal
        return;
      }

      // Edit mode: call API to persist changes
      try {
        setIsLoading(true);
        const isEnabled = true; //  New tool is enabled by default
        const result = await updateToolConfig(
          parseInt(toolToSave.id),
          currentAgentId,
          paramsObj,
          isEnabled
        );
        setIsLoading(false);

        if (result.success) {
          // Update local state and invalidate queries
          updateTools(newSelectedTools);
          queryClient.invalidateQueries({
            queryKey: ["toolInfo", parseInt(toolToSave.id), currentAgentId],
          });
          message.success(t("toolConfig.message.saveSuccess"));
          handleClose(); // Close modal
        } else {
          message.error(result.message || t("toolConfig.message.saveError"));
        }
      } catch (error) {
        setIsLoading(false);
        message.error(t("toolConfig.message.saveError"));
      }

      // Call original onSave if provided
      if (onSave) {
        onSave(currentParams);
      }
    } catch (error) {
      // Form validation failed, error will be shown by antd Form
      message.error("Form validation failed");
    }
  };

  const handleClose = () => {
    setTestPanelVisible(false);
    onCancel();
  };

  // Handle tool testing - toggle test panel
  const handleTestTool = () => {
    setTestPanelVisible(!testPanelVisible);
  };

  // Close test panel
  const handleCloseTestPanel = () => {
    setTestPanelVisible(false);
  };

  // Open knowledge base selector
  const openKbSelector = (paramIndex: number) => {
    setCurrentKbParamIndex(paramIndex);
    setKbSelectorVisible(true);
  };

  // Handle knowledge base selection confirm
  const handleKbConfirm = (selectedKnowledgeBases: KnowledgeBase[]) => {
    const ids = selectedKnowledgeBases.map((kb) => kb.id);
    // Use display_name if available, otherwise fall back to name
    const displayNames = selectedKnowledgeBases.map(
      (kb) => kb.display_name || kb.name
    );

    setSelectedKbIds(ids);
    setSelectedKbDisplayNames(displayNames);

    // Update form value
    if (currentKbParamIndex !== null) {
      const param = currentParams[currentKbParamIndex];
      if (param) {
        // Store as array
        const formFieldName = `param_${currentKbParamIndex}`;
        form.setFieldValue(formFieldName, ids);

        // Also update currentParams directly since Form.Item has no name for index_names/dataset_ids
        const updatedParams = [...currentParams];
        updatedParams[currentKbParamIndex] = {
          ...updatedParams[currentKbParamIndex],
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

    // Update form value
    const formFieldName = `param_${paramIndex}`;
    form.setFieldValue(formFieldName, newIds);

    // Also update currentParams directly since Form.Item has no name for index_names/dataset_ids
    const updatedParams = [...currentParams];
    updatedParams[paramIndex] = {
      ...updatedParams[paramIndex],
      value: newIds,
    };
    setCurrentParams(updatedParams);
  };

  // Get tool type for knowledge base selector
  const getToolType = ():
    | "knowledge_base_search"
    | "dify_search"
    | "datamate_search" => {
    return toolKbType || "knowledge_base_search";
  };

  // Render knowledge base selector input (no button, just clickable input)
  const renderKbSelectorInput = useCallback(
    (param: ToolParam, index: number) => {
      const fieldName = `param_${index}`;
      const formValue = form.getFieldValue(fieldName);

      // Get display names based on current form value and knowledgeBases
      let displayNames: string[] = [];
      let ids: string[] = [];
      if (formValue) {
        // Value can be an array or a JSON string
        if (Array.isArray(formValue)) {
          ids = formValue.map((id) => String(id));
        } else if (typeof formValue === "string") {
          try {
            const parsed = JSON.parse(formValue);
            if (Array.isArray(parsed)) {
              ids = parsed.map((id) => String(id));
            }
          } catch {
            ids = formValue.split(",").filter(Boolean);
          }
        }

        // Map IDs to display names
        if (ids.length > 0 && knowledgeBases.length > 0) {
          displayNames = ids.map((id) => {
            const cleanId = id.trim();
            const kb = knowledgeBases.find((k) => k.id === cleanId);
            return kb?.display_name || kb?.name || cleanId;
          });
        }
      }

      // Fallback to selectedKbDisplayNames if displayNames is empty
      if (displayNames.length === 0 && selectedKbDisplayNames.length > 0) {
        displayNames = selectedKbDisplayNames;
        ids = selectedKbIds;
      }

      // Use the actual ids and displayNames for rendering
      const tagsToRender = ids.length > 0 ? ids : [];
      const namesToRender = displayNames;

      const placeholder = t(
        "toolConfig.input.knowledgeBaseSelector.placeholder",
        {
          name: param.description || param.name,
        }
      );

      return (
        <div
          className="cursor-pointer bg-white border border-gray-300 rounded px-3 py-2 hover:border-blue-400 transition-colors"
          onClick={() => openKbSelector(index)}
          style={{
            width: "100%",
            minHeight: "32px",
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: "4px",
          }}
          title={namesToRender.join(", ")}
        >
          {kbLoading && knowledgeBases.length === 0 ? (
            // Show skeleton loading when fetching knowledge bases
            <div className="flex items-center gap-2 w-full">
              <Skeleton.Input active size="small" style={{ width: "60%" }} />
            </div>
          ) : namesToRender.length > 0 ? (
            namesToRender.map((name, i) => (
              <Tag
                key={tagsToRender[i]}
                closeIcon={
                  <span className="ant-tag-close-icon">
                    <CloseOutlined style={{ fontSize: "10px" }} />
                  </span>
                }
                onClose={(e) => {
                  e.stopPropagation();
                  removeKbFromSelection(i, index);
                }}
                style={{
                  marginRight: 0,
                  display: "inline-flex",
                  alignItems: "center",
                  lineHeight: "20px",
                  padding: "0 8px",
                  fontSize: "13px",
                }}
              >
                {name}
              </Tag>
            ))
          ) : (
            <span className="text-gray-400 text-sm">{placeholder}</span>
          )}
        </div>
      );
    },
    [form, knowledgeBases, selectedKbIds, selectedKbDisplayNames, kbLoading, t]
  );

  const renderParamInput = (param: ToolParam, index: number) => {
    // Get options from frontend configuration based on tool name and parameter name
    const options = getToolParamOptions(tool.name, param.name);

    // Determine if this parameter should be rendered as a select dropdown
    const isSelectType = options && options.length > 0;

    const inputComponent = (() => {
      // Handle select type - when options are defined in frontend config
      if (isSelectType) {
        return (
          <Select
            placeholder={t("toolConfig.input.string.placeholder", {
              name: param.description,
            })}
            options={options.map((option) => ({
              value: option,
              label: option,
            }))}
          />
        );
      }

      switch (param.type) {
        case TOOL_PARAM_TYPES.NUMBER:
          return (
            <InputNumber
              placeholder={t("toolConfig.input.string.placeholder", {
                name: param.description,
              })}
            />
          );

        case TOOL_PARAM_TYPES.BOOLEAN:
          return <Switch />;

        case TOOL_PARAM_TYPES.STRING:
        case TOOL_PARAM_TYPES.ARRAY:
        case TOOL_PARAM_TYPES.OBJECT:
        default:
          // Check if parameter name contains "password" for secure input
          const isPasswordType = param.name.toLowerCase().includes("password");

          if (isPasswordType) {
            return (
              <Input.Password
                placeholder={t("toolConfig.input.string.placeholder", {
                  name: param.description,
                })}
              />
            );
          }

          // Default TextArea for all text-like types and unknown types
          return (
            <Input.TextArea
              placeholder={t(`toolConfig.input.${param.type}.placeholder`, {
                name: param.description,
              })}
              autoSize={{ minRows: 1, maxRows: 8 }}
              style={{ resize: "vertical" }}
            />
          );
      }
    })();

    return inputComponent;
  };

  if (!tool) return null;

  return (
    <>
      <Modal
        mask={true}
        maskClosable={false}
        title={
          <div className="flex justify-between items-center w-full pr-8">
            <span>{`${tool?.name}`}</span>
            <div className="flex items-center gap-2">
              <Tag
                color={
                  tool?.source === "mcp"
                    ? "blue"
                    : tool?.source === "langchain"
                      ? "orange"
                      : "green"
                }
              >
                {tool?.source === "mcp"
                  ? t("toolPool.tag.mcp")
                  : tool?.source === "langchain"
                    ? t("toolPool.tag.langchain")
                    : t("toolPool.tag.local")}
              </Tag>
            </div>
          </div>
        }
        open={isOpen}
        onCancel={onCancel}
        onOk={handleSave}
        okText={t("common.button.save")}
        cancelText={t("common.button.cancel")}
        width={600}
        confirmLoading={isLoading}
        className="tool-config-modal-content"
        wrapProps={{ style: { pointerEvents: "auto" } }}
        footer={
          <div className="flex justify-end items-center">
            {
              <button
                onClick={handleTestTool}
                disabled={!tool}
                className="flex items-center justify-center px-4 py-2 text-sm border border-gray-300 text-gray-700 rounded hover:bg-gray-50 transition-colors duration-200 h-8 mr-auto"
              >
                {testPanelVisible
                  ? t("toolConfig.button.closeTest")
                  : t("toolConfig.button.testTool")}
              </button>
            }
            <div className="flex gap-2">
              <button
                onClick={handleClose}
                className="flex items-center justify-center px-4 py-2 text-sm border border-gray-300 text-gray-700 rounded hover:bg-gray-50 transition-colors duration-200 h-8"
              >
                {t("common.button.cancel")}
              </button>
              <button
                onClick={handleSave}
                disabled={isLoading}
                className="flex items-center justify-center px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200 h-8"
              >
                {isLoading
                  ? t("common.button.saving")
                  : t("common.button.save")}
              </button>
            </div>
          </div>
        }
      >
        <div className="mb-4">
          <p className="text-sm text-gray-500 mb-4">{tool?.description}</p>
          <div className="text-sm font-medium mb-2">
            {t("toolConfig.title.paramConfig")}
          </div>
          <div style={{ maxHeight: "500px", overflow: "auto" }}>
            <Form
              form={form}
              layout="horizontal"
              labelAlign="left"
              labelCol={{ span: 6 }}
              wrapperCol={{ span: 18 }}
            >
              <div className="pr-2 mt-3">
                {currentParams.map((param, index) => {
                  const fieldName = `param_${index}`;
                  const rules: any[] = [];

                  // Add required validation rule
                  if (param.required) {
                    rules.push({
                      required: true,
                      message: t("toolConfig.validation.required", {
                        name: param.name,
                      }),
                    });
                  }

                  // Add type-specific validation rules
                  switch (param.type) {
                    case TOOL_PARAM_TYPES.ARRAY:
                      rules.push({
                        validator: async (_: any, value: any) => {
                          if (!value) return Promise.resolve();
                          try {
                            const parsed =
                              typeof value === "string"
                                ? JSON.parse(value)
                                : value;
                            if (!Array.isArray(parsed)) {
                              return Promise.reject(
                                t("toolConfig.validation.array.invalid")
                              );
                            }
                            return Promise.resolve();
                          } catch {
                            return Promise.reject(
                              t("toolConfig.validation.array.invalid")
                            );
                          }
                        },
                      });
                      break;
                    case TOOL_PARAM_TYPES.OBJECT:
                      rules.push({
                        validator: async (_: any, value: any) => {
                          if (!value) return Promise.resolve();
                          try {
                            const parsed =
                              typeof value === "string"
                                ? JSON.parse(value)
                                : value;
                            if (
                              typeof parsed !== "object" ||
                              Array.isArray(parsed)
                            ) {
                              return Promise.reject(
                                t("toolConfig.validation.object.invalid")
                              );
                            }
                            return Promise.resolve();
                          } catch {
                            return Promise.reject(
                              t("toolConfig.validation.object.invalid")
                            );
                          }
                        },
                      });
                      break;
                  }

                  return (
                    <Form.Item
                      key={param.name}
                      required={param.required}
                      label={
                        <span
                          className="inline-block w-full truncate"
                          title={param.name}
                        >
                          {param.name}
                        </span>
                      }
                      name={
                        toolRequiresKbSelection &&
                        (param.name === "index_names" ||
                          param.name === "dataset_ids")
                          ? undefined
                          : fieldName
                      }
                      rules={rules}
                      tooltip={{
                        title: param.description,
                        placement: "topLeft",
                        styles: { root: { maxWidth: 400 } },
                      }}
                    >
                      {/* For KB selector, use custom display (Form.Item doesn't control value) */}
                      {toolRequiresKbSelection &&
                      (param.name === "index_names" ||
                        param.name === "dataset_ids")
                        ? renderKbSelectorInput(param, index)
                        : renderParamInput(param, index)}
                    </Form.Item>
                  );
                })}
              </div>
            </Form>
          </div>
          <div>
            {testPanelVisible && (
              <ToolTestPanel
                visible={testPanelVisible}
                tool={tool}
                onClose={handleCloseTestPanel}
                configParams={currentParams}
              />
            )}
          </div>
        </div>
      </Modal>

      {/* Knowledge Base Selector Modal */}
      <KnowledgeBaseSelectorModal
        isOpen={kbSelectorVisible}
        onClose={() => setKbSelectorVisible(false)}
        onConfirm={handleKbConfirm}
        selectedIds={selectedKbIds}
        toolType={getToolType()}
        knowledgeBases={knowledgeBases}
        isLoading={kbLoading}
        showCheckbox={true}
        onSync={(toolType) => syncKnowledgeBases(toolType, difyConfig)}
        syncLoading={isSyncing === getToolType()}
        isSelectable={canSelectKnowledgeBase}
        currentEmbeddingModel={currentEmbeddingModel}
        difyConfig={toolKbType === "dify_search" ? difyConfig : undefined}
      />
    </>
  );
}
