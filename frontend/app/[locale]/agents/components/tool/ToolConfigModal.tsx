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
  Button,
  Card,
  Typography,
  Tooltip,
} from "antd";
import {
  CloseOutlined,
  SettingOutlined,
  EditOutlined,
} from "@ant-design/icons";

import { TOOL_PARAM_TYPES } from "@/const/agentConfig";
import { ToolParam, ToolConfigModalProps } from "@/types/agentConfig";

const { Text, Title } = Typography;
import {
  updateToolConfig,
  searchToolConfig,
  loadLastToolConfig,
  validateTool,
  parseToolInputs,
  extractParameterNames,
} from "@/services/agentConfigService";
import log from "@/lib/logger";
import { useModalPosition } from "@/hooks/useModalPosition";
import { DEFAULT_TYPE } from "@/const/constants";

export default function ToolConfigModal({
  isOpen,
  onCancel,
  onSave,
  tool,
  mainAgentId,
  selectedTools = [],
  isEditingMode = true,
}: ToolConfigModalProps) {
  const [currentParams, setCurrentParams] = useState<ToolParam[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  // Tool test related state
  const [testPanelVisible, setTestPanelVisible] = useState(false);
  const [testExecuting, setTestExecuting] = useState<boolean>(false);
  const [testResult, setTestResult] = useState<string>("");
  const [parsedInputs, setParsedInputs] = useState<Record<string, any>>({});
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [dynamicInputParams, setDynamicInputParams] = useState<string[]>([]);
  const [isManualInputMode, setIsManualInputMode] = useState(false);
  const [manualJsonInput, setManualJsonInput] = useState<string>("");
  const [isParseSuccessful, setIsParseSuccessful] = useState<boolean>(false);
  const { windowWidth, mainModalTop, mainModalRight } =
    useModalPosition(isOpen);

  const normalizedAgentId =
    typeof mainAgentId === "number" && !Number.isNaN(mainAgentId)
      ? mainAgentId
      : null;
  const canPersistToolConfig =
    typeof normalizedAgentId === "number" && normalizedAgentId > 0;

  // load tool config
  useEffect(() => {
    const buildDefaultParams = () =>
      (tool?.initParams || []).map((param) => ({
        ...param,
        value: param.value,
      }));

    const loadToolConfig = async () => {
      if (!tool) {
        setCurrentParams([]);
        return;
      }

      // In creation mode (no agent ID), always use backend-provided default params
      if (!normalizedAgentId) {
        setCurrentParams(buildDefaultParams());
        return;
      }

      setIsLoading(true);
      try {
        // In edit mode, load tool config for the specific agent
        const result = await searchToolConfig(
          parseInt(tool.id),
          normalizedAgentId
        );
        if (result.success) {
          if (result.data?.params) {
            const savedParams = tool.initParams.map((param) => {
              const savedValue = result.data.params[param.name];
              return {
                ...param,
                value: savedValue !== undefined ? savedValue : param.value,
              };
            });
            setCurrentParams(savedParams);
          } else {
            setCurrentParams(buildDefaultParams());
          }
        } else {
          message.error(result.message || t("toolConfig.message.loadError"));
          setCurrentParams(buildDefaultParams());
        }
      } catch (error) {
        log.error(t("toolConfig.message.loadError"), error);
        message.error(t("toolConfig.message.loadErrorUseDefault"));
        setCurrentParams(buildDefaultParams());
      } finally {
        setIsLoading(false);
      }
    };

    if (isOpen && tool) {
      loadToolConfig();
    } else {
      setCurrentParams([]);
    }
  }, [isOpen, tool, normalizedAgentId, t, message]);

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

  // load last tool config
  const handleLoadLastConfig = async () => {
    if (!tool) return;

    try {
      const result = await loadLastToolConfig(parseInt(tool.id));
      if (result.success && result.data) {
        // Parse the last config data
        const lastConfig = result.data;
        
        // Update current params with last config values
        const updatedParams = currentParams.map((param) => {
          const lastValue = lastConfig[param.name];
          return {
            ...param,
            value: lastValue !== undefined ? lastValue : param.value,
          };
        });
        
        setCurrentParams(updatedParams);
        message.success(t("toolConfig.message.loadLastConfigSuccess"));
      } else {
        message.warning(t("toolConfig.message.loadLastConfigNotFound"));
      }
    } catch (error) {
      log.error(t("toolConfig.message.loadLastConfigFailed"), error);
      message.error(t("toolConfig.message.loadLastConfigFailed"));
    }
  };

  const handleSave = async () => {
    if (!tool || !checkRequiredFields()) return;

    try {
      // convert params to backend format
      const params = currentParams.reduce((acc, param) => {
        acc[param.name] = param.value;
        return acc;
      }, {} as Record<string, any>);

      if (!canPersistToolConfig) {
        message.success(t("toolConfig.message.saveSuccess"));
        onSave({
          ...tool,
          initParams: currentParams,
        });
        return;
      }

      // decide enabled status based on whether the tool is in selectedTools
      const isEnabled = selectedTools.some((t) => t.id === tool.id);

      const result = await updateToolConfig(
        parseInt(tool.id),
        normalizedAgentId,
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

  // Handle tool testing
  const handleTestTool = () => {
    if (!tool) return;
    setTestResult("");
    // Parse inputs definition from tool inputs field
    try {
      const parsedInputs = parseToolInputs(tool.inputs || "");
      const paramNames = extractParameterNames(parsedInputs);

      // Check if parsing was successful (not empty object)
      const isSuccessful = Object.keys(parsedInputs).length > 0;
      setIsParseSuccessful(isSuccessful);
      if (isSuccessful) {
        setParsedInputs(parsedInputs);
        setDynamicInputParams(paramNames);

        // Initialize parameter values with appropriate defaults based on type
        const initialValues: Record<string, string> = {};
        paramNames.forEach((paramName) => {
          const paramInfo = parsedInputs[paramName];
          const paramType = paramInfo?.type || DEFAULT_TYPE;

          if (
            paramInfo &&
            typeof paramInfo === "object" &&
            paramInfo.default != null
          ) {
            // Use provided default value, convert to string for UI display
            switch (paramType) {
              case "boolean":
                initialValues[paramName] = paramInfo.default ? "true" : "false";
                break;
              case "array":
              case "object":
                // JSON.stringify with indentation of 2 spaces for better readability
                initialValues[paramName] = JSON.stringify(
                  paramInfo.default,
                  null,
                  2
                );
                break;
              default:
                initialValues[paramName] = String(paramInfo.default);
            }
          }
        });
        setParamValues(initialValues);
        // Reset to parsed mode when parsing succeeds
        setIsManualInputMode(false);
        setManualJsonInput("");
      } else {
        // Parsing returned empty object, treat as failed
        setParsedInputs({});
        setParamValues({});
        setDynamicInputParams([]);
        setIsManualInputMode(true);
        setManualJsonInput("{}");
      }
    } catch (error) {
      log.error("Parameter parsing error:", error);
      setParsedInputs({});
      setParamValues({});
      setDynamicInputParams([]);
      setIsParseSuccessful(false);
      // When parsing fails, automatically switch to manual input mode
      setIsManualInputMode(true);
      setManualJsonInput("{}");
    }

    setTestPanelVisible(true);
  };

  // Close test panel
  const closeTestPanel = () => {
    setTestPanelVisible(false);
    setTestResult("");
    setParsedInputs({});
    setParamValues({});
    setDynamicInputParams([]);
    setTestExecuting(false);
    setIsManualInputMode(false);
    setManualJsonInput("");
    setIsParseSuccessful(false);
  };

  // Execute tool test
  const executeTest = async () => {
    if (!tool) return;

    setTestExecuting(true);

    try {
      // Prepare parameters for tool validation with correct types
      const toolParams: Record<string, any> = {};

      if (isManualInputMode) {
        // Use manual JSON input
        try {
          const manualParams = JSON.parse(manualJsonInput);
          Object.assign(toolParams, manualParams);
        } catch (error) {
          log.error("Failed to parse manual JSON input:", error);
          setTestResult(`Test failed: Invalid JSON format in manual input`);
          return;
        }
      } else {
        // Use parsed parameters
        dynamicInputParams.forEach((paramName) => {
          const value = paramValues[paramName];
          const paramInfo = parsedInputs[paramName];
          const paramType = paramInfo?.type || DEFAULT_TYPE;

          if (value && value.trim() !== "") {
            // Convert value to correct type based on parameter type from inputs
            switch (paramType) {
              case "integer":
              case "number":
                const numValue = Number(value.trim());
                if (!isNaN(numValue)) {
                  toolParams[paramName] = numValue;
                } else {
                  toolParams[paramName] = value.trim(); // fallback to string if conversion fails
                }
                break;
              case "boolean":
                toolParams[paramName] = value.trim().toLowerCase() === "true";
                break;
              case "array":
              case "object":
                try {
                  toolParams[paramName] = JSON.parse(value.trim());
                } catch {
                  toolParams[paramName] = value.trim(); // fallback to string if JSON parsing fails
                }
                break;
              default:
                toolParams[paramName] = value.trim();
            }
          }
        });
      }

      // Prepare configuration parameters from current params
      const configParams = currentParams.reduce((acc, param) => {
        acc[param.name] = param.value;
        return acc;
      }, {} as Record<string, any>);

      // Call validateTool with parameters
      const result = await validateTool(
        tool.origin_name || tool.name,
        tool.source, // Tool source
        tool.usage || "", // Tool usage
        toolParams, // tool input parameters
        configParams // tool configuration parameters
      );

      // Format the JSON string response
      let formattedResult: string;
      try {
        const parsedResult =
          typeof result === "string" ? JSON.parse(result) : result;
        formattedResult = JSON.stringify(parsedResult, null, 2);
      } catch (parseError) {
        log.error("Failed to parse JSON result:", parseError);
        formattedResult = typeof result === "string" ? result : String(result);
      }
      setTestResult(formattedResult);
    } catch (error) {
      log.error("Tool test execution failed:", error);
      setTestResult(`Test failed: ${error}`);
    } finally {
      setTestExecuting(false);
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
    <>
      <Modal
        title={
          <div className="flex justify-between items-center w-full pr-8">
            <span>{`${tool?.name}`}</span>
            <div className="flex items-center gap-2">
              <button
                onClick={handleLoadLastConfig}
                className="px-2 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200"
              >
                {t("toolConfig.message.loadLastConfig")}
              </button>
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
        footer={
          <div className="flex justify-end items-center">
            {isEditingMode && (
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

      {/* Tool Test Panel */}
      {testPanelVisible && (
        <>
          {/* Backdrop */}
          <div
            style={{
              position: "fixed",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: "rgba(0, 0, 0, 0.5)",
              zIndex: 1000,
            }}
            onClick={closeTestPanel}
          />

          {/* Test Panel */}
          <div
            className="tool-test-panel"
            style={{
              position: "fixed",
              top: mainModalTop > 0 ? `${mainModalTop}px` : "10vh", // Align with main modal top or fallback to 10vh
              left:
                mainModalRight > 0
                  ? `${mainModalRight + windowWidth * 0.05}px`
                  : "calc(50% + 300px + 5vw)", // Position to the right of main modal with 5% viewport width gap
              width: "500px",
              height: "auto",
              maxHeight: "80vh",
              overflowY: "auto",
              backgroundColor: "#fff",
              border: "1px solid #d9d9d9",
              borderRadius: "8px",
              boxShadow: "0 4px 12px rgba(0, 0, 0, 0.15)",
              zIndex: 1001,
              display: "flex",
              flexDirection: "column",
            }}
          >
            {/* Test panel header */}
            <div
              style={{
                padding: "16px",
                borderBottom: "1px solid #f0f0f0",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div style={{ display: "flex", flexDirection: "column" }}>
                <Title level={5} style={{ margin: 0 }}>
                  {tool?.name}
                </Title>
              </div>
              <Button
                type="text"
                icon={<CloseOutlined />}
                onClick={closeTestPanel}
                size="small"
              />
            </div>

            {/* Test panel content */}
            <div
              style={{
                padding: "16px",
                flex: 1,
                display: "flex",
                flexDirection: "column",
              }}
            >
              <Text strong>{t("toolConfig.toolTest.toolInfo")}</Text>
              <Card size="small" style={{ marginTop: 8, marginBottom: 16 }}>
                <Text>{tool?.description}</Text>
              </Card>

              {/* Test parameter input */}
              <div style={{ marginBottom: 16 }}>
                {/* Show current form parameters */}
                {currentParams.length > 0 && (
                  <>
                    <Text strong style={{ display: "block", marginBottom: 8 }}>
                      {t("toolConfig.toolTest.configParams")}
                    </Text>
                    <div
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: 12,
                        marginBottom: 15,
                      }}
                    >
                      {currentParams.map((param) => (
                        <div
                          key={param.name}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                          }}
                        >
                          <Text style={{ minWidth: 100 }}>{param.name}</Text>
                          <Tooltip
                            title={param.description}
                            placement="topLeft"
                            styles={{ root: { maxWidth: 400 } }}
                          >
                            <Input
                              placeholder={param.description || param.name}
                              value={String(param.value || "")}
                              readOnly
                              style={{ flex: 1, backgroundColor: "#f5f5f5" }}
                            />
                          </Tooltip>
                        </div>
                      ))}
                    </div>
                  </>
                )}

                {/* Input parameters section with conditional toggle */}
                {(dynamicInputParams.length > 0 || isManualInputMode) && (
                  <>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        marginBottom: 8,
                      }}
                    >
                      <Text strong>{t("toolConfig.toolTest.inputParams")}</Text>
                      {/* Only show toggle button if parsing was successful */}
                      {isParseSuccessful && (
                        <Button
                          type="text"
                          size="small"
                          icon={
                            isManualInputMode ? (
                              <SettingOutlined />
                            ) : (
                              <EditOutlined />
                            )
                          }
                          onClick={() => {
                            setIsManualInputMode(!isManualInputMode);
                            if (!isManualInputMode) {
                              const currentParamsJson: Record<string, any> = {};
                              dynamicInputParams.forEach((paramName) => {
                                const value = paramValues[paramName];
                                if (value && value.trim() !== "") {
                                  const paramInfo = parsedInputs[paramName];
                                  const paramType = paramInfo?.type || DEFAULT_TYPE;

                                  try {
                                    switch (paramType) {
                                      case "integer":
                                      case "number":
                                        currentParamsJson[paramName] = Number(
                                          value.trim()
                                        );
                                        break;
                                      case "boolean":
                                        currentParamsJson[paramName] =
                                          value.trim().toLowerCase() === "true";
                                        break;
                                      case "array":
                                      case "object":
                                        currentParamsJson[paramName] =
                                          JSON.parse(value.trim());
                                        break;
                                      default:
                                        currentParamsJson[paramName] =
                                          value.trim();
                                    }
                                  } catch {
                                    currentParamsJson[paramName] = value.trim();
                                  }
                                }
                              });
                              setManualJsonInput(
                                JSON.stringify(currentParamsJson, null, 2)
                              );
                            } else {
                              // From manual input mode to parsed mode
                              try {
                                const manualParams =
                                  JSON.parse(manualJsonInput);
                                const updatedParamValues: Record<
                                  string,
                                  string
                                > = {};
                                dynamicInputParams.forEach((paramName) => {
                                  const manualValue = manualParams[paramName];
                                  const paramInfo = parsedInputs[paramName];
                                  const paramType =
                                    paramInfo?.type || DEFAULT_TYPE;

                                  if (manualValue !== undefined) {
                                    // Convert to string for display based on parameter type
                                    switch (paramType) {
                                      case "boolean":
                                        updatedParamValues[paramName] =
                                          manualValue ? "true" : "false";
                                        break;
                                      case "array":
                                      case "object":
                                        updatedParamValues[paramName] =
                                          JSON.stringify(manualValue, null, 2);
                                        break;
                                      default:
                                        updatedParamValues[paramName] =
                                          String(manualValue);
                                    }
                                  }
                                });
                                setParamValues(updatedParamValues);
                              } catch (error) {
                                log.error(
                                  "Failed to sync manual input to parsed mode:",
                                  error
                                );
                              }
                            }
                          }}
                        >
                          {isManualInputMode
                            ? t("toolConfig.toolTest.parseMode")
                            : t("toolConfig.toolTest.manualInput")}
                        </Button>
                      )}
                    </div>

                    {isManualInputMode ? (
                      // Manual JSON input mode
                      <div style={{ marginBottom: 15 }}>
                        <Input.TextArea
                          value={manualJsonInput}
                          onChange={(e) => setManualJsonInput(e.target.value)}
                          rows={6}
                          style={{ fontFamily: "monospace" }}
                        />
                      </div>
                    ) : (
                      // Parsed parameters mode
                      dynamicInputParams.length > 0 && (
                        <div
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 12,
                            marginBottom: 15,
                          }}
                        >
                          {dynamicInputParams.map((paramName) => {
                            const paramInfo = parsedInputs[paramName];
                            const description =
                              paramInfo &&
                              typeof paramInfo === "object" &&
                              paramInfo.description
                                ? paramInfo.description
                                : paramName;

                            return (
                              <div
                                key={paramName}
                                style={{
                                  display: "flex",
                                  alignItems: "center",
                                  gap: 8,
                                }}
                              >
                                <Text style={{ minWidth: 100 }}>
                                  {paramName}
                                </Text>
                                <Tooltip
                                  title={description}
                                  placement="topLeft"
                                  styles={{ root: { maxWidth: 400 } }}
                                >
                                  <Input
                                    placeholder={description}
                                    value={paramValues[paramName] || ""}
                                    onChange={(e) => {
                                      setParamValues((prev) => ({
                                        ...prev,
                                        [paramName]: e.target.value,
                                      }));
                                    }}
                                    style={{ flex: 1 }}
                                  />
                                </Tooltip>
                              </div>
                            );
                          })}
                        </div>
                      )
                    )}
                  </>
                )}

                <Button
                  type="primary"
                  onClick={executeTest}
                  loading={testExecuting}
                  disabled={testExecuting}
                  style={{ width: "100%" }}
                >
                  {testExecuting
                    ? t("toolConfig.toolTest.executing")
                    : t("toolConfig.toolTest.execute")}
                </Button>
              </div>

              {/* Test result */}
              <div style={{ flex: 1 }}>
                <Text strong style={{ display: "block", marginBottom: 8 }}>
                  {t("toolConfig.toolTest.result")}
                </Text>
                <Input.TextArea
                  value={testResult}
                  readOnly
                  rows={8}
                  style={{
                    backgroundColor: "#f5f5f5",
                    resize: "none",
                  }}
                />
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
