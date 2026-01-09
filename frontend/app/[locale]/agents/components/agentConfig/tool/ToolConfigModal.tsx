"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import {
  Modal,
  Input,
  Switch,
  InputNumber,
  Tag,
  App,
  Tooltip
} from "antd";

import { TOOL_PARAM_TYPES } from "@/const/agentConfig";
import { ToolParam, Tool } from "@/types/agentConfig";
import { useModalPosition } from "@/hooks/useModalPosition";
import ToolTestPanel from "./ToolTestPanel";
export interface ToolConfigModalProps {
  isOpen: boolean;
  onCancel: () => void;
  onSave: (params: ToolParam[]) => void; // 修改：返回参数数组
  tool?: Tool;
  initialParams: ToolParam[]; // 修改：变为必需，移除currentAgentId
}

export default function ToolConfigModal({
  isOpen,
  onCancel,
  onSave,
  tool,
  initialParams,
}: ToolConfigModalProps) {
  const [currentParams, setCurrentParams] = useState<ToolParam[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  // Tool test panel visibility state
  const [testPanelVisible, setTestPanelVisible] = useState(false);
  const { windowWidth, mainModalTop, mainModalRight } =
    useModalPosition(isOpen);

  // Apply transform to modal when test panel is visible
  // Move main modal to the left to center both panels together
  useEffect(() => {
    if (!isOpen) return;

    const testPanelWidth = 500;
    const gap = windowWidth * 0.05;
    // Move left by half of (test panel width + gap) to center both panels
    const offsetX = testPanelVisible
      ? -(testPanelWidth + gap) / 2
      : 0;

    // Find the modal wrap element (Ant Design renders Modal in a wrap container)
    // Use a small delay to ensure Modal is rendered
    const timer = setTimeout(() => {
      const modalContent = document.querySelector(
        ".tool-config-modal-content"
      );
      if (modalContent) {
        const modalWrap = modalContent.closest(".ant-modal-wrap") as HTMLElement;
        if (modalWrap) {
          modalWrap.style.transform = `translateX(${offsetX}px)`;
          modalWrap.style.transition = "transform 0.3s ease-in-out";
        }
      }
    }, 0);

    return () => {
      clearTimeout(timer);
      const modalContent = document.querySelector(
        ".tool-config-modal-content"
      );
      if (modalContent) {
        const modalWrap = modalContent.closest(".ant-modal-wrap") as HTMLElement;
        if (modalWrap) {
          modalWrap.style.transform = "";
          modalWrap.style.transition = "";
        }
      }
    };
  }, [testPanelVisible, isOpen, windowWidth]);

  // Initialize with provided params
  useEffect(() => {
    if (isOpen && tool && initialParams) {
      setCurrentParams(initialParams);
      setIsLoading(false);
    } else {
      setCurrentParams([]);
    }
  }, [tool, initialParams, isOpen]);

  // check required fields
  const checkRequiredFields = () => {
    if (!tool) return false;

    const missingRequiredFields = currentParams
      .filter(
        (param) =>
          param.required &&
          (param.value === undefined ||
            param.value === "" ||
            param.value === null)
      )
      .map((param) => param.name);

    if (missingRequiredFields.length > 0) {
      message.error(
        `${t("toolConfig.message.requiredFields")}${missingRequiredFields.join(
          ", "
        )}`
      );
      return false;
    }
    return true;
  };

  const handleParamChange = (index: number, value: any) => {
    const newParams = [...currentParams];
    newParams[index] = { ...newParams[index], value };
    setCurrentParams(newParams);
  };


  const handleSave = () => {
    if (!checkRequiredFields()) return;
    onSave(currentParams);
  };

  // Handle tool testing - open test panel
  const handleTestTool = () => {
    if (!tool || !checkRequiredFields()) return;
    setTestPanelVisible(true);
  };

  // Close test panel
  const handleCloseTestPanel = () => {
    setTestPanelVisible(false);
  };

  const renderParamInput = (param: ToolParam, index: number) => {
    switch (param.type) {
      case TOOL_PARAM_TYPES.STRING:
        const stringValue = param.value as string;
        // if string length is greater than 15, use TextArea
        if (stringValue && stringValue.length > 15) {
          return (
            <Input.TextArea
              value={stringValue}
              onChange={(e) => handleParamChange(index, e.target.value)}
              placeholder={t("toolConfig.input.string.placeholder", {
                name: param.description,
              })}
              autoSize={{ minRows: 1, maxRows: 8 }}
              style={{ resize: "vertical" }}
            />
          );
        }
        return (
          <Input
            value={stringValue}
            onChange={(e) => handleParamChange(index, e.target.value)}
            placeholder={t("toolConfig.input.string.placeholder", {
              name: param.description,
            })}
          />
        );
      case TOOL_PARAM_TYPES.NUMBER:
        return (
          <InputNumber
            value={param.value as number}
            onChange={(value) => handleParamChange(index, value)}
            placeholder={t("toolConfig.input.string.placeholder", {
              name: param.description,
            })}
            className="w-full"
          />
        );
      case TOOL_PARAM_TYPES.BOOLEAN:
        return (
          <Switch
            checked={param.value as boolean}
            onChange={(checked) => handleParamChange(index, checked)}
          />
        );
      case TOOL_PARAM_TYPES.ARRAY:
        const arrayValue = Array.isArray(param.value)
          ? JSON.stringify(param.value, null, 2)
          : (param.value as string);
        return (
          <Input.TextArea
            value={arrayValue}
            onChange={(e) => {
              try {
                const value = JSON.parse(e.target.value);
                handleParamChange(index, value);
              } catch {
                handleParamChange(index, e.target.value);
              }
            }}
            placeholder={t("toolConfig.input.array.placeholder")}
            autoSize={{ minRows: 1, maxRows: 8 }}
            style={{ resize: "vertical" }}
          />
        );
      case TOOL_PARAM_TYPES.OBJECT:
        const objectValue =
          typeof param.value === "object"
            ? JSON.stringify(param.value, null, 2)
            : (param.value as string);
        return (
          <Input.TextArea
            value={objectValue}
            onChange={(e) => {
              try {
                const value = JSON.parse(e.target.value);
                handleParamChange(index, value);
              } catch {
                handleParamChange(index, e.target.value);
              }
            }}
            placeholder={t("toolConfig.input.object.placeholder")}
            autoSize={{ minRows: 1, maxRows: 8 }}
            style={{ resize: "vertical" }}
          />
        );
      default:
        return (
          <Input
            value={param.value as string}
            onChange={(e) => handleParamChange(index, e.target.value)}
          />
        );
    }
  };

  if (!tool) return null;

  return (
    <>
      <Modal
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
        footer={
          <div className="flex justify-end items-center">
            {(
              <button
                onClick={handleTestTool}
                disabled={!tool}
                className="flex items-center justify-center px-4 py-2 text-sm border border-gray-300 text-gray-700 rounded hover:bg-gray-50 transition-colors duration-200 h-8 mr-auto"
              >
                {t("toolConfig.button.testTool")}
              </button>
            )}
            <div className="flex gap-2">
              <button
                onClick={onCancel}
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
            <div className="space-y-4 pr-2">
              {currentParams.map((param, index) => (
                <div
                  key={param.name}
                  className="border-b pb-4 mb-4 last:border-b-0 last:mb-0"
                >
                  <div className="flex items-start gap-4">
                    <div className="flex-[0.3] pt-1">
                      {param.name ? (
                        <div className="text-sm text-gray-600">
                          {param.name}
                          {param.required && (
                            <span className="text-red-500 ml-1">*</span>
                          )}
                        </div>
                      ) : (
                        <div className="text-sm text-gray-600">
                          {param.name}
                          {param.required && (
                            <span className="text-red-500 ml-1">*</span>
                          )}
                        </div>
                      )}
                    </div>
                    <div className="flex-[0.7]">
                      <Tooltip
                        title={param.description}
                        placement="topLeft"
                        styles={{ root: { maxWidth: 400 } }}
                      >
                        {renderParamInput(param, index)}
                      </Tooltip>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </Modal>

      {/* Tool Test Panel */}
      <ToolTestPanel
        visible={testPanelVisible}
        tool={tool}
        currentParams={currentParams}
        mainModalTop={mainModalTop}
        mainModalRight={mainModalRight}
        windowWidth={windowWidth}
        onClose={handleCloseTestPanel}
        onVisibilityChange={(visible) => setTestPanelVisible(visible)}
      />
    </>
  );
}
