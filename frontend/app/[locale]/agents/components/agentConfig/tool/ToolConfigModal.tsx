"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Input, Switch, InputNumber, Tag, Form, message } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useAgentConfigStore } from "@/stores/agentConfigStore";

import { TOOL_PARAM_TYPES } from "@/const/agentConfig";
import { ToolParam, Tool } from "@/types/agentConfig";
import ToolTestPanel from "./ToolTestPanel";
import { updateToolConfig } from "@/services/agentConfigService";
import { getToolDescription } from "@/lib/agentLabelMapper";

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
  // Initialize with provided params
  useEffect(() => {
    // Initialize form values
    setCurrentParams(initialParams);
    const formValues: Record<string, any> = {};
    initialParams.forEach((param, index) => {
      formValues[`param_${index}`] = param.value;
    });
    form.setFieldsValue(formValues);
  }, [initialParams]);

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
      await form.validateFields();
      if (!selectedTool) return;

      // Convert params to backend format
      const paramsObj = currentParams.reduce(
        (acc, param) => {
          acc[param.name] = param.value;
          return acc;
        },
        {} as Record<string, any>
      );

      // Update local state: Add tool to selected tools with updated params
      const updatedTool = { ...selectedTool, initParams: currentParams };
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

      if (isCreatingMode) {
        // In creating mode, just update local state
        updateTools(newSelectedTools);
        message.success(t("toolConfig.message.saveSuccess"));
        handleClose(); // Close modal
      } else if (currentAgentId) {
        try {
          const isEnabled = true; //  New tool is enabled by default
          const result = await updateToolConfig(
            parseInt(selectedTool.id),
            currentAgentId,
            paramsObj,
            isEnabled
          );

          if (result.success) {
            // Update local state and invalidate queries
            updateTools(newSelectedTools);
            queryClient.invalidateQueries({
              queryKey: ["toolInfo", parseInt(selectedTool.id), currentAgentId],
            });
            message.success(t("toolConfig.message.saveSuccess"));
            handleClose(); // Close modal
          } else {
            message.error(result.message || t("toolConfig.message.saveError"));
          }
        } catch (error) {
          message.error(t("toolConfig.message.saveError"));
        }
      }

      // Call original onSave if provided
      if (onSave) {
        onSave(currentParams);
      }
    } catch (error) {
      // Form validation failed, error will be shown by antd Form
      message.error("Form validation failed:");
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

  const renderParamInput = (param: ToolParam, index: number) => {
    const inputComponent = (() => {
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
                {testPanelVisible ? t("toolConfig.button.closeTest") : t("toolConfig.button.testTool")}
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
          <p className="text-sm text-gray-500 mb-4">
            {getToolDescription(tool?.name || "", tool?.description || "", t)}
          </p>
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
                        validator: (_: any, value: any) => {
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
                        validator: (_: any, value: any) => {
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
                      label={
                        <span
                          className="inline-block w-full truncate"
                          title={param.name}
                        >
                          {param.name}
                        </span>
                      }
                      name={fieldName}
                      rules={rules}
                      tooltip={{
                        title: t(`tool.param.${tool.name}.${param.name}`, { defaultValue: param.description }),
                        placement: "topLeft",
                        styles: { root: { maxWidth: 400 } },
                      }}
                    >
                      {renderParamInput(param, index)}
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

    </>
  );
}
