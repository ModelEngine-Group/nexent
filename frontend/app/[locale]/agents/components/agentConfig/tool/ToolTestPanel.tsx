"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Input, Button, Card, Typography, Tooltip, Modal, Form } from "antd";
import { Settings, PenLine, X } from "lucide-react";

import { Tool, ToolParam } from "@/types/agentConfig";
import {
  validateTool,
  parseToolInputs,
  extractParameterNames,
} from "@/services/agentConfigService";
import log from "@/lib/logger";
import { DEFAULT_TYPE } from "@/const/constants";
import { getLocalizedDescription } from "@/lib/utils";

const { Text, Title } = Typography;

export interface ToolTestPanelProps {
  /** Whether the test panel is visible */
  visible: boolean;
  /** Tool to test */
  tool: Tool | null;
  /** Current configuration parameters */
  configParams: ToolParam[];
  /** Callback when panel is closed */
  onClose: () => void;
}

export default function ToolTestPanel({
  visible,
  tool,
  configParams,
  onClose,
}: ToolTestPanelProps) {
  const { t } = useTranslation("common");
  const [form] = Form.useForm();

  // Tool test related state
  const [testExecuting, setTestExecuting] = useState<boolean>(false);
  const [testResult, setTestResult] = useState<string>("");
  const [parsedInputs, setParsedInputs] = useState<Record<string, any>>({});
  const [parameterValues, setParameterValues] = useState<Record<string, any>>({});
  const [isManualInputMode, setIsManualInputMode] = useState(false);
  const [manualJsonInput, setManualJsonInput] = useState<string>("");
  const [isParseSuccessful, setIsParseSuccessful] = useState<boolean>(false);

  // Initialize test panel when opened
  useEffect(() => {
    if (!visible || !tool) {
      // Reset state when closed
      setTestResult("");
      setParsedInputs({});
      setParameterValues({});
      setTestExecuting(false);
      setIsManualInputMode(false);
      setManualJsonInput("");
      setIsParseSuccessful(false);
      form.resetFields();
      return;
    }

    // Parse inputs definition from tool inputs field
    try {
      const parsedInputs = parseToolInputs(tool.inputs || "");
      // Check if parsing was successful (not empty object)
      const isSuccessful = Object.keys(parsedInputs).length > 0;
      setIsParseSuccessful(isSuccessful);
      if (isSuccessful) {
        setParsedInputs(parsedInputs);

        // Initialize parameter values and form values from parsed inputs
        const parameterValues: Record<string, any> = {};
        const formValues: Record<string, any> = {};

        Object.entries(parsedInputs).forEach(([paramName, paramInfo]) => {
          const paramType = paramInfo?.type || DEFAULT_TYPE;

          if (
            paramInfo &&
            typeof paramInfo === "object" &&
            paramInfo.default != null
          ) {
            // Store actual default value
            parameterValues[paramName] = paramInfo.default;

            // Convert to string for form display
            switch (paramType) {
              case "boolean":
                formValues[`param_${paramName}`] = paramInfo.default ? "true" : "false";
                break;
              case "array":
              case "object":
                // JSON.stringify with indentation of 2 spaces for better readability
                formValues[`param_${paramName}`] = JSON.stringify(
                  paramInfo.default,
                  null,
                  2
                );
                break;
              default:
                formValues[`param_${paramName}`] = String(paramInfo.default);
            }
          } else {
            parameterValues[paramName] = "";
            formValues[`param_${paramName}`] = "";
          }
        });

        setParameterValues(parameterValues);
        form.setFieldsValue(formValues);
        // Reset to parsed mode when parsing succeeds
        setIsManualInputMode(false);
        // Set manual input to current parsed values as default
        setManualJsonInput(JSON.stringify(parameterValues, null, 2));
      } else {
        // Parsing returned empty object, treat as failed
        setParsedInputs({});
        setParameterValues({});
        setIsManualInputMode(true);
        setManualJsonInput("{}");
      }
    } catch (error) {
      log.error("Parameter parsing error:", error);
      setParsedInputs({});
      setParameterValues({});
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
        // Use parsed parameters from form
        const formValues = form.getFieldsValue();
        Object.keys(parameterValues).forEach((paramName) => {
          const value = formValues[`param_${paramName}`];
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

      // Prepare configuration parameters from currentParams
      const configs = (configParams || []).reduce(
        (acc: Record<string, any>, param: ToolParam) => {
          acc[param.name] = param.value;
          return acc;
        },
        {} as Record<string, any>
      );

      // Call validateTool with parameters
      const toolName = tool.origin_name || tool.name || "";
      const toolSource = tool.source || "";
      const result = await validateTool(
        toolName,
        toolSource, // Tool source
        tool.usage || "", // Tool usage
        toolParams, // tool input parameters
        configs // tool configuration parameters
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

    <div className="mb-4" >
      <div>
        {/* Input parameters section with conditional toggle */}
        {Object.keys(parameterValues).length > 0 && (
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
                    const newMode = !isManualInputMode;
                    setIsManualInputMode(newMode);

                    if (newMode) {
                      // Switching to manual mode - get values from form
                      const currentFormValues = form.getFieldsValue();
                      const currentParamsJson: Record<string, any> = {};

                      Object.keys(parameterValues).forEach((paramName) => {
                        const formValue = currentFormValues[`param_${paramName}`];
                        if (formValue && formValue.trim() !== "") {
                          const paramInfo = parsedInputs[paramName];
                          const paramType = paramInfo?.type || DEFAULT_TYPE;

                          try {
                            switch (paramType) {
                              case "integer":
                              case "number":
                                currentParamsJson[paramName] = Number(
                                  formValue.trim()
                                );
                                break;
                              case "boolean":
                                currentParamsJson[paramName] =
                                  formValue.trim().toLowerCase() === "true";
                                break;
                              case "array":
                              case "object":
                                currentParamsJson[paramName] = JSON.parse(
                                  formValue.trim()
                                );
                                break;
                              default:
                                currentParamsJson[paramName] = formValue.trim();
                            }
                          } catch {
                            currentParamsJson[paramName] = formValue.trim();
                          }
                        }
                      });
                      setManualJsonInput(
                        JSON.stringify(currentParamsJson, null, 2)
                      );
                    } else {
                      // Switching to parsed mode - parse manual JSON and set to form
                      try {
                        const manualParams = JSON.parse(manualJsonInput);
                        const formValues: Record<string, any> = {};

                        Object.keys(parameterValues).forEach((paramName) => {
                          const manualValue = manualParams[paramName];
                          const paramInfo = parsedInputs[paramName];
                          const paramType = paramInfo?.type || DEFAULT_TYPE;

                          if (manualValue !== undefined) {
                            // Convert to string for display based on parameter type
                            switch (paramType) {
                              case "boolean":
                                formValues[`param_${paramName}`] = manualValue
                                  ? "true"
                                  : "false";
                                break;
                              case "array":
                              case "object":
                                formValues[`param_${paramName}`] =
                                  JSON.stringify(manualValue, null, 2);
                                break;
                              default:
                                formValues[`param_${paramName}`] =
                                  String(manualValue);
                            }
                          } else {
                            formValues[`param_${paramName}`] = "";
                          }
                        });
                        form.setFieldsValue(formValues);
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

            <Form
              form={form}
              layout="horizontal"
              labelAlign="left"
              labelCol={{ span: 6 }}
              wrapperCol={{ span: 18 }}
            >
              {isManualInputMode ? (
                // Manual JSON input mode
              <Form.Item className="w-full" wrapperCol={{ span: 24 }}>
                <Input.TextArea
                  value={manualJsonInput}
                  onChange={(e) => setManualJsonInput(e.target.value)}
                  rows={6}
                  style={{ fontFamily: "monospace", width: "100%" }}
                />
              </Form.Item>
              ) : (
                // Parsed parameters mode
                Object.keys(parameterValues).length > 0 && (
                  <>
                    {Object.keys(parameterValues).map((paramName) => {
                      const paramInfo = parsedInputs[paramName];
                      const description =
                        paramInfo &&
                        typeof paramInfo === "object" &&
                        paramInfo.description
                          ? paramInfo.description
                          : paramName;
                      const description_zh =
                        paramInfo &&
                        typeof paramInfo === "object" &&
                        paramInfo.description_zh
                          ? paramInfo.description_zh
                          : undefined;

                      const fieldName = `param_${paramName}`;
                      const rules: any[] = [];

                      // Add type-specific validation rules
                      switch (paramInfo?.type || DEFAULT_TYPE) {
                        case "array":
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
                        case "object":
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
                          key={paramName}
                          label={
                            <span
                              style={{ width: "100%" }}
                              title={paramName}
                            >
                              {paramName}
                            </span>
                          }
                          name={fieldName}
                          rules={rules}
                          tooltip={{
                            title: getLocalizedDescription(description, description_zh),
                            placement: "topLeft",
                            styles: { root: { maxWidth: 400 } },
                          }}
                        >
                          <Input
                            placeholder={getLocalizedDescription(description, description_zh)}
                          />
                        </Form.Item>
                      );
                    })}
                  </>
                )
              )}
            </Form>
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
  );
}
