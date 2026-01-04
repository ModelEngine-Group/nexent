"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { motion, AnimatePresence } from "framer-motion";
import {
  Input,
  Button,
  Card,
  Typography,
  Tooltip,
} from "antd";
import {
  Settings,
  PenLine,
  X,
} from "lucide-react";

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
  /** Main modal top position */
  mainModalTop: number;
  /** Main modal right position */
  mainModalRight: number;
  /** Window width for position calculation */
  windowWidth: number;
  /** Callback when panel is closed */
  onClose: () => void;
  /** Callback when panel visibility changes (for parent modal positioning) */
  onVisibilityChange?: (visible: boolean) => void;
}

export default function ToolTestPanel({
  visible,
  tool,
  currentParams,
  mainModalTop,
  mainModalRight,
  windowWidth,
  onClose,
  onVisibilityChange,
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

  // Notify parent when visibility changes
  useEffect(() => {
    onVisibilityChange?.(visible);
  }, [visible, onVisibilityChange]);

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
  }, [visible, tool]);

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

  // Calculate test panel position to center both panels together
  const testPanelWidth = 500;
  const gap = windowWidth * 0.05;
  const offsetForCentering = (testPanelWidth + gap) / 2;
  
  // Calculate test panel left position
  const testPanelLeft = mainModalRight > 0
    ? mainModalRight + gap - offsetForCentering
    : windowWidth / 2 + 300 + windowWidth * 0.05 - offsetForCentering;

  if (!tool) return null;

  return (
    <AnimatePresence>
      {visible && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            style={{
              position: "fixed",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: "rgba(0, 0, 0, 0.5)",
              zIndex: 1000,
            }}
            onClick={handleClose}
          />

          {/* Test Panel */}
          <motion.div
            className="tool-test-panel"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
            style={{
              position: "fixed",
              top: mainModalTop > 0 ? `${mainModalTop}px` : "10vh", // Align with main modal top or fallback to 10vh
              left: `${testPanelLeft}px`, // Position adjusted to center both panels together
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
                icon={< X size={16} />}
                onClick={handleClose}
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
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

