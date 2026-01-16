"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { motion, AnimatePresence } from "framer-motion";
import { Input, Button, Card, Typography, Tooltip, Modal } from "antd";
import { Settings, PenLine, X } from "lucide-react";

import { ToolParam, Tool } from "@/types/agentConfig";
import {
  validateTool,
  parseToolInputs,
  extractParameterNames,
} from "@/services/agentConfigService";
import log from "@/lib/logger";
import { DEFAULT_TYPE } from "@/const/constants";

const { Text, Title } = Typography;

export interface ToolTestPanelProps {
  /** Whether the test panel is visible */
  visible: boolean;
  /** Tool to test */
  tool: Tool | null;
  /** Current configuration parameters */
  currentParams: ToolParam[];
  /** Callback when panel is closed */
  onClose: () => void;
}

export default function ToolTestPanel({
  visible,
  tool,
  currentParams,
  onClose,
}: ToolTestPanelProps) {
  const { t } = useTranslation("common");

  // Tool test related state
  const [testExecuting, setTestExecuting] = useState<boolean>(false);
  const [testResult, setTestResult] = useState<string>("");
  const [parsedInputs, setParsedInputs] = useState<Record<string, any>>({});
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [dynamicInputParams, setDynamicInputParams] = useState<string[]>([]);
  const [isManualInputMode, setIsManualInputMode] = useState(false);
  const [manualJsonInput, setManualJsonInput] = useState<string>("");
  const [isParseSuccessful, setIsParseSuccessful] = useState<boolean>(false);

  const modalRef = useRef<HTMLDivElement>(null);

  // Initialize test panel when opened
  useEffect(() => {
    if (!visible || !tool) {
      // Reset state when closed
      setTestResult("");
      setParsedInputs({});
      setParamValues({});
      setDynamicInputParams([]);
      setTestExecuting(false);
      setIsManualInputMode(false);
      setManualJsonInput("");
      setIsParseSuccessful(false);
      return;
    }

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
  }, [tool]);

  // Close test panel
  const handleClose = () => {
    onClose();
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
      const configParams = currentParams.reduce(
        (acc, param) => {
          acc[param.name] = param.value;
          return acc;
        },
        {} as Record<string, any>
      );

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

  if (!tool) return null;

  return (
    <Modal
      title={
        <div className="flex justify-between items-center w-full pr-8">
          <span>{`${tool?.name}`}</span>
        </div>
      }
      open={visible}
      onCancel={onClose}
      width={600}
      className="tool-config-modal-content"
      style={{
        top: 100,
        left: 320,
        zIndex: 1040, // lower than ToolConfigModal so it won't block clicks
      }}
      mask={false}
      maskClosable={false}
      wrapProps={{ style: { pointerEvents: "none", zIndex: 1040 } }} // do not block pointer events outside modal content
      footer={<div></div>}
    >
      <div className="mb-4" style={{ pointerEvents: "auto" }}>
        <p className="text-sm text-gray-500 mb-4">{tool?.description}</p>
        <div>
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
        </div>
        <div>
          {/* Input parameters section with conditional toggle */}
          {dynamicInputParams.length > 0 && (
            <>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginBottom: 8,
                }}
              >
                <Text strong style={{ display: "block", marginBottom: 8 }}>
                  {t("toolConfig.toolTest.inputParams")}
                </Text>
                {/* Only show toggle button if parsing was successful */}
                {isParseSuccessful && (
                  <Button
                    type="text"
                    size="small"
                    icon={
                      isManualInputMode ? (
                        <Settings size={16} />
                      ) : (
                        <PenLine size={16} />
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
                                  currentParamsJson[paramName] = JSON.parse(
                                    value.trim()
                                  );
                                  break;
                                default:
                                  currentParamsJson[paramName] = value.trim();
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
                          const manualParams = JSON.parse(manualJsonInput);
                          const updatedParamValues: Record<string, string> = {};
                          dynamicInputParams.forEach((paramName) => {
                            const manualValue = manualParams[paramName];
                            const paramInfo = parsedInputs[paramName];
                            const paramType = paramInfo?.type || DEFAULT_TYPE;

                            if (manualValue !== undefined) {
                              // Convert to string for display based on parameter type
                              switch (paramType) {
                                case "boolean":
                                  updatedParamValues[paramName] = manualValue
                                    ? "true"
                                    : "false";
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
                          <Text style={{ minWidth: 100 }}>{paramName}</Text>
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
        <div className="mt-3">
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
    </Modal>
  );
}
