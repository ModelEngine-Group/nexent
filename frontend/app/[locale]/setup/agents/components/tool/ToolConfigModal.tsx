"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Input, Switch, Select, InputNumber, Tag, App } from "antd";

import { TOOL_PARAM_TYPES } from "@/const/agentConfig";
import { ToolParam, ToolConfigModalProps } from "@/types/agentConfig";
import {
  updateToolConfig,
  searchToolConfig,
} from "@/services/agentConfigService";
import log from "@/lib/logger";

export default function ToolConfigModal({
  isOpen,
  onCancel,
  onSave,
  tool,
  mainAgentId,
  selectedTools = [],
}: ToolConfigModalProps) {
  const [currentParams, setCurrentParams] = useState<ToolParam[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  // load tool config
  useEffect(() => {
    const loadToolConfig = async () => {
      if (tool && mainAgentId) {
        setIsLoading(true);
        try {
          const result = await searchToolConfig(parseInt(tool.id), mainAgentId);
          if (result.success) {
            if (result.data?.params) {
              // use backend returned config content
              const savedParams = tool.initParams.map((param) => {
                // if backend returned config has this param value, use backend returned value
                // otherwise use param default value
                const savedValue = result.data.params[param.name];
                return {
                  ...param,
                  value: savedValue !== undefined ? savedValue : param.value,
                };
              });
              setCurrentParams(savedParams);
            } else {
              // if backend returned params is null, means no saved config, use default config
              setCurrentParams(
                tool.initParams.map((param) => ({
                  ...param,
                  value: param.value, // use default value
                }))
              );
            }
          } else {
            message.error(result.message || t("toolConfig.message.loadError"));
            // when load failed, use default config
            setCurrentParams(
              tool.initParams.map((param) => ({
                ...param,
                value: param.value,
              }))
            );
          }
        } catch (error) {
          log.error(t("toolConfig.message.loadError"), error);
          message.error(t("toolConfig.message.loadErrorUseDefault"));
          // when error occurs, use default config
          setCurrentParams(
            tool.initParams.map((param) => ({
              ...param,
              value: param.value,
            }))
          );
        } finally {
          setIsLoading(false);
        }
      } else {
        // if there is no tool or mainAgentId, clear params
        setCurrentParams([]);
      }
    };

    if (isOpen && tool) {
      loadToolConfig();
    } else {
      // when modal is closed, clear params
      setCurrentParams([]);
    }
  }, [isOpen, tool, mainAgentId, t]);

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

  const handleSave = async () => {
    if (!tool || !checkRequiredFields()) return;

    try {
      // convert params to backend format
      const params = currentParams.reduce((acc, param) => {
        acc[param.name] = param.value;
        return acc;
      }, {} as Record<string, any>);

      // decide enabled status based on whether the tool is in selectedTools
      const isEnabled = selectedTools.some((t) => t.id === tool.id);

      const result = await updateToolConfig(
        parseInt(tool.id),
        mainAgentId,
        params,
        isEnabled
      );

      if (result.success) {
        message.success(t("toolConfig.message.saveSuccess"));
        onSave({
          ...tool,
          initParams: currentParams,
        });
      } else {
        message.error(result.message || t("toolConfig.message.saveError"));
      }
    } catch (error) {
      log.error(t("toolConfig.message.saveFailed"), error);
      message.error(t("toolConfig.message.saveFailed"));
    }
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
                name: param.name,
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
              name: param.name,
            })}
          />
        );
      case TOOL_PARAM_TYPES.NUMBER:
        return (
          <InputNumber
            value={param.value as number}
            onChange={(value) => handleParamChange(index, value)}
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
    <Modal
      title={
        <div className="flex justify-between items-center w-full pr-8">
          <span>{`${tool?.name}`}</span>
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
      }
      open={isOpen}
      onCancel={onCancel}
      onOk={handleSave}
      width={600}
      confirmLoading={isLoading}
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
                    {param.description ? (
                      <div className="text-sm text-gray-600">
                        {param.description}
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
                    {renderParamInput(param, index)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Modal>
  );
}