"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Input, Button, Card, Typography, Tooltip, Modal, Form, Tag, Skeleton } from "antd";
import { Settings, PenLine, X } from "lucide-react";
import { CloseOutlined } from "@ant-design/icons";

import { Tool, ToolParam } from "@/types/agentConfig";
import { KnowledgeBase } from "@/types/knowledgeBase";
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
  /** Whether the tool requires knowledge base selection */
  toolRequiresKbSelection?: boolean;
  /** Knowledge bases for selection */
  knowledgeBases?: KnowledgeBase[];
  /** Whether knowledge bases are loading */
  kbLoading?: boolean;
  /** Callback to open knowledge base selector modal */
  onOpenKbSelector?: (paramIndex: number) => void;
  /** Selected knowledge base IDs for the index_names parameter */
  selectedKbIds?: string[];
  /** Selected knowledge base display names */
  selectedKbDisplayNames?: string[];
  /** Callback when knowledge base selection changes */
  onKbSelectionChange?: (ids: string[], displayNames: string[]) => void;
  /** Callback to remove a knowledge base from selection */
  onRemoveKb?: (index: number, paramIndex: number) => void;
}

export default function ToolTestPanel({
  visible,
  tool,
  configParams,
  onClose,
  toolRequiresKbSelection = false,
  knowledgeBases = [],
  kbLoading = false,
  onOpenKbSelector,
  selectedKbIds = [],
  selectedKbDisplayNames = [],
  onKbSelectionChange,
  onRemoveKb,
}: ToolTestPanelProps) {
  const { t } = useTranslation("common");
  const [form] = Form.useForm();

  // Track if form has been initialized (to avoid resetting user input)
  const formInitializedRef = useRef<boolean>(false);
  // Track the last known tool to detect tool changes
  const lastToolRef = useRef<string>("");

  // Tool test related state
  const [testExecuting, setTestExecuting] = useState<boolean>(false);
  const [testResult, setTestResult] = useState<string>("");
  const [parsedInputs, setParsedInputs] = useState<Record<string, any>>({});
  const [parameterValues, setParameterValues] = useState<Record<string, any>>({});
  const [isManualInputMode, setIsManualInputMode] = useState(false);
  const [manualJsonInput, setManualJsonInput] = useState<string>("");
  const [isParseSuccessful, setIsParseSuccessful] = useState<boolean>(false);

  // Reset form initialization flag when modal is closed or tool changes
  useEffect(() => {
    if (!visible) {
      formInitializedRef.current = false;
    }
  }, [visible]);

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
      formInitializedRef.current = false;
      return;
    }

    // Detect if tool has changed
    const currentToolName = tool.origin_name || tool.name || "";
    const toolChanged = lastToolRef.current !== currentToolName;

    // Only re-initialize if the tool has changed, not just selectedKbIds
    if (toolChanged) {
      lastToolRef.current = currentToolName;
      formInitializedRef.current = false;
    }

    // Skip if form is already initialized and tool hasn't changed
    if (formInitializedRef.current && !toolChanged) {
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

          // Check if this is the index_names parameter and KB selection is enabled
          const isIndexNamesParam = paramName === "index_names" && toolRequiresKbSelection;
          if (isIndexNamesParam) {
            // index_names is provided by KB selector config, no need to duplicate in input params.
            return;
          }

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
        // Mark form as initialized
        formInitializedRef.current = true;
      } else {
        // Parsing returned empty object, treat as failed
        setParsedInputs({});
        setParameterValues({});
        setIsManualInputMode(true);
        setManualJsonInput("{}");
        formInitializedRef.current = true;
      }
    } catch (error) {
      log.error("Parameter parsing error:", error);
      setParsedInputs({});
      setParameterValues({});
      setIsParseSuccessful(false);
      // When parsing fails, automatically switch to manual input mode
      setIsManualInputMode(true);
      setManualJsonInput("{}");
      formInitializedRef.current = true;
    }
  }, [tool, toolRequiresKbSelection, visible, form]);

  // Sync KB selection with form values when selectedKbIds changes (but don't reset other fields)
  useEffect(() => {
    if (!toolRequiresKbSelection) return;

    const fieldName = `param_index_names`;
    const currentValue = form.getFieldValue(fieldName);

    // Only update if the value is different
    const idsMatch = Array.isArray(currentValue) &&
      currentValue.length === selectedKbIds.length &&
      currentValue.every((id: string, i: number) => id === selectedKbIds[i]);

    if (!idsMatch) {
      form.setFieldValue(fieldName, selectedKbIds);
    }
  }, [selectedKbIds, toolRequiresKbSelection, form]);

  // Close test panel
  const handleClose = () => {
    onClose();
  };

  // Execute tool test
  const executeTest = async () => {
    if (!tool) return;

    // Validate that knowledge base is selected when required
    if (toolRequiresKbSelection && selectedKbIds.length === 0) {
      setTestResult(`Test failed: Please select at least one knowledge base`);
      return;
    }

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

          // Check if this is a KB selector parameter (index_names with KB selection enabled)
          const isKbSelectorParam = paramName === "index_names" && toolRequiresKbSelection;

          // Skip KB selector parameters - they will be handled separately
          if (isKbSelectorParam) {
            return;
          }

          // Handle string values
          if (typeof value === "string" && value.trim() !== "") {
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
          } else if (Array.isArray(value) && value.length > 0) {
            // Handle array values (for non-KB selector array parameters)
            toolParams[paramName] = value;
          } else if (typeof value === "object" && value !== null) {
            // Handle object values
            toolParams[paramName] = value;
          }
        });
      }

      // Override index_names with selectedKbIds if KB selection is enabled
      if (toolRequiresKbSelection && selectedKbIds.length > 0) {
        toolParams.index_names = selectedKbIds;
      }

      // Prepare configuration parameters from currentParams
      // Filter out index_names from configs when KB selection is enabled since it's passed via toolParams
      const configs = (configParams || []).reduce(
        (acc: Record<string, any>, param: ToolParam) => {
          // Skip index_names when KB selection is enabled (it's passed via toolParams)
          if (toolRequiresKbSelection && (param.name === "index_names" || param.name === "dataset_ids")) {
            return acc;
          }
          // Ensure top_k is always a number, not an array
          if (param.name === "top_k" && Array.isArray(param.value)) {
            acc[param.name] = param.value[0] || 3;
          } else {
            acc[param.name] = param.value;
          }
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

                        // Check if this is a KB selector parameter
                        const isKbSelectorParam = paramName === "index_names" && toolRequiresKbSelection;

                        // Handle KB selector parameters - use selectedKbIds
                        if (isKbSelectorParam) {
                          if (selectedKbIds.length > 0) {
                            currentParamsJson[paramName] = selectedKbIds;
                          }
                          return;
                        }

                        // Handle string values
                        if (typeof formValue === "string" && formValue.trim() !== "") {
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
                        } else if (Array.isArray(formValue) && formValue.length > 0) {
                          // Handle array values
                          currentParamsJson[paramName] = formValue;
                        } else if (typeof formValue === "object" && formValue !== null) {
                          // Handle object values
                          currentParamsJson[paramName] = formValue;
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

                          // Check if this is a KB selector parameter
                          const isKbSelectorParam = paramName === "index_names" && toolRequiresKbSelection;

                          if (manualValue !== undefined) {
                            // KB selector parameters should keep their array form
                            if (isKbSelectorParam) {
                              formValues[`param_${paramName}`] = Array.isArray(manualValue)
                                ? manualValue
                                : [];
                            } else {
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
                            }
                          } else {
                            formValues[`param_${paramName}`] = isKbSelectorParam ? [] : "";
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

                      // Check if this is the index_names parameter and KB selection is enabled
                      const isKbSelectorParam = paramName === "index_names" && toolRequiresKbSelection;

                      // Get display names based on selected KB IDs and knowledge bases
                      let displayNames: string[] = [];
                      if (isKbSelectorParam && selectedKbIds.length > 0 && knowledgeBases.length > 0) {
                        displayNames = selectedKbIds.map((id) => {
                          const cleanId = id.trim();
                          const kb = knowledgeBases.find((k) => k.id === cleanId);
                          return kb?.display_name || kb?.name || cleanId;
                        });
                      }

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

                      // Render knowledge base selector for index_names parameter
                      if (isKbSelectorParam) {
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
                            <div>
                              <div
                                className="cursor-pointer bg-white border rounded px-3 py-2 transition-colors border-gray-300 hover:border-blue-400"
                                onClick={() => onOpenKbSelector?.(-1)} // -1 indicates this is from test panel
                                style={{
                                  width: "100%",
                                  minHeight: "32px",
                                  display: "flex",
                                  flexWrap: "wrap",
                                  alignItems: "center",
                                  gap: "4px",
                                }}
                                title={displayNames.join(", ")}
                              >
                                {kbLoading && knowledgeBases.length === 0 ? (
                                  <div className="flex items-center gap-2 w-full">
                                    <Skeleton.Input active size="small" style={{ width: "60%" }} />
                                  </div>
                                ) : displayNames.length > 0 ? (
                                  displayNames.map((name, i) => (
                                    <Tag
                                      key={selectedKbIds[i]}
                                      closeIcon={
                                        <span className="ant-tag-close-icon">
                                          <CloseOutlined style={{ fontSize: "10px" }} />
                                        </span>
                                      }
                                      onClose={(e) => {
                                        e.stopPropagation();
                                        onRemoveKb?.(i, -1); // -1 indicates this is from test panel
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
                                  <span className="text-gray-400 text-sm">
                                    {t("toolConfig.input.knowledgeBaseSelector.placeholder", {
                                      name: getLocalizedDescription(description, description_zh) || paramName,
                                    })}
                                  </span>
                                )}
                              </div>
                            </div>
                          </Form.Item>
                        );
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
