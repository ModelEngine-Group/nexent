"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Input, Button, Card, Typography, Tooltip, Modal, Form, Tag } from "antd";
import { Settings, PenLine, X } from "lucide-react";

import { Tool, ToolParam } from "@/types/agentConfig";
import { KnowledgeBase } from "@/types/knowledgeBase";
import {
  validateTool,
  parseToolInputs,
  extractParameterNames,
} from "@/services/agentConfigService";
import log from "@/lib/logger";
import { DEFAULT_TYPE } from "@/const/constants";
import { getLocalizedDescription, mapKbIdsToDisplayNames } from "@/lib/utils";

const { Text, Title } = Typography;

// Component to display KB selector
const KbSelectorDisplay = ({
  selectedKbIds,
  selectedKbDisplayNames,
  kbPlaceholder,
  onOpenKbSelector,
  onRemoveKb,
  onKbSelect,
  onKbRemove,
}: {
  selectedKbIds: string[];
  selectedKbDisplayNames: string[];
  kbPlaceholder: string;
  onOpenKbSelector?: (paramIndex: number) => void;
  onRemoveKb?: (index: number, paramIndex: number) => void;
  onKbSelect?: (ids: string[], displayNames: string[]) => void;
  onKbRemove?: (index: number) => void;
}) => (
  <div>
    <div
      className="cursor-pointer bg-white border rounded px-3 py-2 transition-colors hover:border-[#8C68CD] min-h-[40px]"
      onClick={() => onOpenKbSelector?.(-1)}
    >
      {selectedKbIds.length > 0 ? (
        selectedKbIds.map((id, i) => (
          <Tag
            key={id}
            closable
            onClose={(e) => {
              e.preventDefault();
              if (onKbRemove) {
                onKbRemove(i);
              } else {
                onRemoveKb?.(i, -1);
              }
            }}
            style={{ marginBottom: 4 }}
          >
            {selectedKbDisplayNames[i] || id}
          </Tag>
        ))
      ) : (
        <span className="text-gray-400 text-sm">{kbPlaceholder}</span>
      )}
    </div>
  </div>
);

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
  /** Callback for test panel's own KB selection (for tools like aidp_search that need independent KB selection) */
  onTestPanelKbSelect?: (ids: string[], displayNames: string[]) => void;
  /** Callback to remove a KB from test panel's selection (doesn't affect selectedKbIds) */
  onTestPanelKbRemove?: (index: number) => void;
  /** Test panel's own KB IDs (for tools like aidp_search) */
  testPanelKbIds?: string[];
  /** Test panel's own KB display names (for tools like aidp_search) */
  testPanelKbDisplayNames?: string[];
  /** Callback to notify parent when testPanelKbIds should change (e.g., from manual JSON edit) */
  onTestPanelKbIdsChange?: (ids: string[], displayNames: string[]) => void;
  /** Tool type for KB selection (used to determine parameter name) */
  toolKbType?: "knowledge_base_search" | "dify_search" | "datamate_search" | "idata_search" | "haotian_search" | "aidp_search" | "ragflow_search" | null;
  /** Haotian knowledge sets for display name resolution */
  haotianKnowledgeSets?: Array<{
    name: string;
    knowledge_bases: Array<{ dify_dataset_id: string; name: string }>;
  }>;
}

export default function ToolTestPanel({
  visible,
  tool,
  configParams,
  onClose,
  toolRequiresKbSelection = false,
  selectedKbIds = [],
  selectedKbDisplayNames = [],
  onOpenKbSelector,
  onRemoveKb,
  onTestPanelKbSelect,
  onTestPanelKbRemove,
  testPanelKbIds = [],
  testPanelKbDisplayNames = [],
  onTestPanelKbIdsChange,
  toolKbType = null,
}: ToolTestPanelProps) {
  const { t } = useTranslation("common");
  const [form] = Form.useForm();

  // Track if form has been initialized (to avoid resetting user input)
  const formInitializedRef = useRef<boolean>(false);
  // Track the last known tool to detect tool changes
  const lastToolRef = useRef<string>("");
  // Track the last config params JSON to detect config changes
  const lastConfigParamsJsonRef = useRef<string>("");
  // Track previous manual input mode to detect transitions (for syncing testPanelKbIds)
  const prevManualInputModeRef = useRef(false);

  // Tool test related state
  const [testExecuting, setTestExecuting] = useState<boolean>(false);
  const [testResult, setTestResult] = useState<string>("");
  const [parsedInputs, setParsedInputs] = useState<Record<string, any>>({});
  const [parameterValues, setParameterValues] = useState<Record<string, any>>({});
  const [isManualInputMode, setIsManualInputMode] = useState(false);
  const [manualJsonInput, setManualJsonInput] = useState<string>("");
  const [isParseSuccessful, setIsParseSuccessful] = useState<boolean>(false);
  const isKnowledgeBaseSearchTool =
    tool?.origin_name === "knowledge_base_search" ||
    tool?.name === "knowledge_base_search";

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

    // Detect if tool has changed. Note: we intentionally do NOT include
    // configParams in this check, because configParams is a parent-controlled
    // object that gets rebuilt whenever the parent re-renders (e.g. when the
    // user picks a knowledge base and the parent calls setCurrentParams).
    // Treating that as a "tool change" would clobber the user's runtime
    // input fields (e.g. resetting the "query" string they typed, which
    // triggers "missing 1 required positional argument: 'query'" on submit).
    const currentToolName = tool.origin_name || tool.name || "";
    const toolChanged = lastToolRef.current !== currentToolName;

    if (toolChanged) {
      lastToolRef.current = currentToolName;
      // Snapshot the current configParams so subsequent parent-driven
      // updates don't accidentally re-trigger initialization logic.
      lastConfigParamsJsonRef.current = JSON.stringify(configParams || []);
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

          // Check if this is the KB selector parameter and KB selection is enabled.
          // - index_names: used by knowledge_base_search, dify_search, datamate_search, ragflow_search
          // - dataset_ids: used by haotian_search, idata_search, dify_search, ragflow_search
          // - kds_list: used by aidp_search
          const isKbSelectorParam = (paramName === "index_names" && toolRequiresKbSelection && toolKbType !== "haotian_search" && toolKbType !== "idata_search" && toolKbType !== "aidp_search")
            || (paramName === "dataset_ids" && toolRequiresKbSelection && (toolKbType === "haotian_search" || toolKbType === "idata_search" || toolKbType === "ragflow_search" || toolKbType === "dify_search"))
            || (paramName === "kds_list" && toolRequiresKbSelection && toolKbType === "aidp_search");

          if (isKbSelectorParam) {
            // For aidp_search kds_list: use testPanelKbIds (independent from config's selectedKbIds)
            // For other tools: use selectedKbIds
            const kbIds = (paramName === "kds_list" && toolKbType === "aidp_search")
              ? testPanelKbIds
              : selectedKbIds;
            if (kbIds.length > 0) {
              parameterValues[paramName] = kbIds;
              formValues[`param_${paramName}`] = kbIds;
            }
          } else {
            // Priority: configParams (user's saved value) > parsedInputs default
            const configParam = (configParams || []).find((p) => p.name === paramName);
            const hasSavedValue = configParam != null && configParam.value !== undefined && configParam.value !== null;

            if (hasSavedValue) {
              // Use saved value from configParams
              const savedValue = configParam.value;
              parameterValues[paramName] = savedValue;
              switch (paramType) {
                case "boolean":
                  formValues[`param_${paramName}`] = savedValue ? "true" : "false";
                  break;
                case "array":
                case "object":
                  formValues[`param_${paramName}`] = JSON.stringify(savedValue, null, 2);
                  break;
                default:
                  formValues[`param_${paramName}`] = String(savedValue);
              }
            } else if (
              paramInfo &&
              typeof paramInfo === "object" &&
              paramInfo.default != null
            ) {
              // Store actual default value
              parameterValues[paramName] = paramInfo.default;
              switch (paramType) {
                case "boolean":
                  formValues[`param_${paramName}`] = paramInfo.default ? "true" : "false";
                  break;
                case "array":
                case "object":
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
        // Parsing returned empty object - try to fall back to configParams so the
        // form still has fields the user can edit (otherwise executeTest would
        // send an empty inputs payload and the SDK forward() would error with
        // "missing 1 required positional argument" for tools like knowledge_base_search).
        const fallbackNames = (configParams || []).map((p) => p.name);
        if (fallbackNames.length > 0) {
          const parameterValues: Record<string, any> = {};
          const formValues: Record<string, any> = {};
          (configParams || []).forEach((p) => {
            const value = p.value;
            parameterValues[p.name] = value;
            formValues[`param_${p.name}`] = value != null ? String(value) : "";
          });
          setParameterValues(parameterValues);
          form.setFieldsValue(formValues);
          setManualJsonInput(JSON.stringify(parameterValues, null, 2));
        } else {
          setParameterValues({});
        }
        setParsedInputs({});
        setIsManualInputMode(true);
        setManualJsonInput((prev) => (prev && prev !== "{}" ? prev : "{}"));
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
  }, [tool, toolRequiresKbSelection, visible, form, configParams]);

  // Sync KB selection with form values when the relevant IDs change.
  // - aidp_search: uses testPanelKbIds (independent test panel state)
  // - other tools: uses selectedKbIds (shared config state)
  useEffect(() => {
    if (!toolRequiresKbSelection) return;

    const isHaotianOrIdata = toolKbType === "haotian_search" || toolKbType === "idata_search";
    const isAidpOrKbSearch = toolKbType === "aidp_search" || isKnowledgeBaseSearchTool;

    // Determine source of truth, field name, and state key for each tool type
    let ids: string[];
    let fieldName: string;
    let stateKey: string;

    if (isAidpOrKbSearch) {
      // aidp_search and knowledge_base_search use independent test panel KB state
      ids = testPanelKbIds;
      fieldName = toolKbType === "aidp_search" ? "param_kds_list" : "param_index_names";
      stateKey = toolKbType === "aidp_search" ? "kds_list" : "index_names";
    } else if (isHaotianOrIdata) {
      ids = selectedKbIds;
      fieldName = "param_dataset_ids";
      stateKey = "dataset_ids";
    } else {
      ids = selectedKbIds;
      fieldName = "param_index_names";
      stateKey = "index_names";
    }

    const currentValue = form.getFieldValue(fieldName);
    const idsMatch =
      Array.isArray(currentValue) &&
      currentValue.length === ids.length &&
      currentValue.every((id: string, i: number) => id === ids[i]);

    if (idsMatch) return;

    form.setFieldValue(fieldName, ids);
    setParameterValues((prev) => ({ ...prev, [stateKey]: ids }));
    setManualJsonInput((prev) => {
      try {
        const parsed = JSON.parse(prev);
        parsed[stateKey] = ids;
        return JSON.stringify(parsed, null, 2);
      } catch {
        return prev;
      }
    });
  }, [selectedKbIds, testPanelKbIds, toolRequiresKbSelection, toolKbType, form]);

  // Handle aidp_search testPanelKbIds that may arrive after initial form setup.
  // This runs when testPanelKbIds transitions from [] to non-empty so the form
  // and parameterValues are pre-populated before the user sees the panel.
  // For both aidp_search and knowledge_base_search, when testPanelKbIds arrives
  // (after modal reopens or parent sync), pre-populate the form and manual JSON.
  useEffect(() => {
    if (!visible) return;
    if (!toolRequiresKbSelection) return;
    if (testPanelKbIds.length === 0) return;
    if (toolKbType !== "aidp_search" && !isKnowledgeBaseSearchTool) return;

    const fieldName = toolKbType === "aidp_search" ? "param_kds_list" : "param_index_names";
    const stateKey = toolKbType === "aidp_search" ? "kds_list" : "index_names";

    const currentValue = form.getFieldValue(fieldName);
    const idsMatch =
      Array.isArray(currentValue) &&
      currentValue.length === testPanelKbIds.length &&
      currentValue.every((id: string, i: number) => id === testPanelKbIds[i]);

    if (idsMatch) return;

    form.setFieldValue(fieldName, testPanelKbIds);
    setParameterValues((prev) => ({ ...prev, [stateKey]: testPanelKbIds }));
    setManualJsonInput((prev) => {
      try {
        const parsed = JSON.parse(prev);
        parsed[stateKey] = testPanelKbIds;
        return JSON.stringify(parsed, null, 2);
      } catch {
        return prev;
      }
    });
  }, [testPanelKbIds, visible, toolKbType, toolRequiresKbSelection, form]);

  // When switching back from manual mode to parsed mode, extract kds_list/index_names from
  // the manual JSON and notify the parent so testPanelKbIds stays in sync.
  useEffect(() => {
    if (prevManualInputModeRef.current && !isManualInputMode) {
      // Transitioned from manual → parsed mode
      if ((toolKbType === "aidp_search" || isKnowledgeBaseSearchTool) && onTestPanelKbIdsChange) {
        try {
          const parsed = JSON.parse(manualJsonInput);
          const kbIds = toolKbType === "aidp_search" ? parsed.kds_list : parsed.index_names;
          if (Array.isArray(kbIds) && kbIds.length > 0) {
            onTestPanelKbIdsChange(kbIds, kbIds);
          }
        } catch {
          // ignore invalid JSON
        }
      }
    }
    prevManualInputModeRef.current = isManualInputMode;
  }, [isManualInputMode, manualJsonInput, toolKbType, onTestPanelKbIdsChange]);

  // Close test panel
  const handleClose = () => {
    onClose();
  };

  // Execute tool test
  const executeTest = async () => {
    if (!tool) return;

    // Validate that knowledge base is selected when required
    // For aidp_search and knowledge_base_search, use test panel's independent KB state
    const kbIds = (toolKbType === "aidp_search" || isKnowledgeBaseSearchTool)
      ? testPanelKbIds
      : selectedKbIds;
    if (toolRequiresKbSelection && !isKnowledgeBaseSearchTool && kbIds.length === 0) {
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
        // Use parsed parameters from form, iterating over parsedInputs keys.
        // Fallback to configParams if parsedInputs is empty (e.g. knowledge_base_search
        // whose DB inputs may be empty or stale).
        const formValues = form.getFieldsValue();
        const useConfigParamsFallback =
          Object.keys(parsedInputs).length === 0;
        const paramNames = useConfigParamsFallback
          ? (configParams || []).map((p) => p.name)
          : Object.keys(parsedInputs);

        paramNames.forEach((paramName) => {
          const value = formValues[`param_${paramName}`];
          const paramInfo = parsedInputs[paramName];
          // When falling back to configParams (parsedInputs is empty), infer
          // param type from the saved value's JS type since the SDK inputs
          // definition isn't available in this branch.
          const paramType =
            paramInfo?.type ||
            (useConfigParamsFallback && value !== undefined && value !== null
              ? typeof value === "number"
                ? "number"
                : typeof value === "boolean"
                ? "boolean"
                : Array.isArray(value)
                ? "array"
                : "string"
              : DEFAULT_TYPE);

          // If form value is empty (e.g. configParams fallback path), use
          // the saved configParam value as the source of truth.
          let effectiveValue = value;
          if (useConfigParamsFallback && (value === undefined || value === "")) {
            const cfg = (configParams || []).find((p) => p.name === paramName);
            if (cfg && cfg.value !== undefined && cfg.value !== null) {
              effectiveValue = cfg.value;
            }
          }

          // KB selector params for non-knowledge_base_search tools
          const isKbSelectorParam =
            (paramName === "index_names" ||
              paramName === "dataset_ids" ||
              paramName === "kds_list") && toolRequiresKbSelection;

          // For knowledge_base_search: index_names is a runtime input (not config).
          // The KB selector uses testPanelKbIds (independent from config).
          // Handle explicitly: read from form if available, else from testPanelKbIds.
          if (isKnowledgeBaseSearchTool && paramName === "index_names") {
            if (Array.isArray(effectiveValue) && effectiveValue.length > 0) {
              toolParams.index_names = effectiveValue;
            } else if (testPanelKbIds.length > 0) {
              toolParams.index_names = testPanelKbIds;
            }
            return;
          }

          // For aidp_search kds_list: prioritize testPanelKbIds (from test panel KB selector)
          // over form value (which may be [] from initialization timing).
          // Fallback to form value if testPanelKbIds is also empty.
          if (paramName === "kds_list" && toolKbType === "aidp_search") {
            if (Array.isArray(effectiveValue) && effectiveValue.length > 0) {
              toolParams[paramName] = effectiveValue;
            } else if (testPanelKbIds.length > 0) {
              toolParams[paramName] = testPanelKbIds;
            }
            return;
          }

          if (isKbSelectorParam && !isKnowledgeBaseSearchTool) {
            // For tools like dify_search, ragflow_search, datamate_search,
            // haotian_search, and idata_search, the KB selection parameter
            // (index_names / dataset_ids) is a configuration-only init param
            // that goes through kbSelectionConfig, not a runtime input to
            // the tool's forward() method. Skip it in toolParams.
            // (aidp_search kds_list is handled above at the dedicated block.)
            return;
          }

          // Handle string values
          if (typeof effectiveValue === "string" && effectiveValue.trim() !== "") {
            switch (paramType) {
              case "integer":
              case "number":
                const numValue = Number(effectiveValue.trim());
                if (!isNaN(numValue)) {
                  toolParams[paramName] = numValue;
                } else {
                  toolParams[paramName] = effectiveValue.trim();
                }
                break;
              case "boolean":
                toolParams[paramName] = effectiveValue.trim().toLowerCase() === "true";
                break;
              case "array":
              case "object":
                try {
                  toolParams[paramName] = JSON.parse(effectiveValue.trim());
                } catch {
                  toolParams[paramName] = effectiveValue.trim();
                }
                break;
              default:
                toolParams[paramName] = effectiveValue.trim();
            }
          } else if (Array.isArray(effectiveValue) && effectiveValue.length > 0) {
            toolParams[paramName] = effectiveValue;
          } else if (typeof effectiveValue === "object" && effectiveValue !== null) {
            toolParams[paramName] = effectiveValue;
          }
        });
      }

      if (isKnowledgeBaseSearchTool) {
        if (!Array.isArray(toolParams.index_names) || toolParams.index_names.length === 0) {
          setTestResult(`Test failed: Please provide non-empty index_names in input params`);
          return;
        }
      }

      // Prepare KB selection parameter based on tool type
      // These are init-time configuration parameters, not forward() parameters
      let kbSelectionConfig: Record<string, any> = {};
      // Determine KB selection config based on tool type
      // For aidp_search, use testPanelKbIds (independent from config's selectedKbIds)
      const aidpKbIds = toolKbType === "aidp_search" ? testPanelKbIds : selectedKbIds;
      if (toolRequiresKbSelection && aidpKbIds.length > 0) {
        // Determine the correct parameter name based on tool type
        if (tool?.name === "dify_search" || tool?.name === "ragflow_search") {
          kbSelectionConfig = { dataset_ids: JSON.stringify(aidpKbIds) };
        } else if (tool?.name === "haotian_search" || tool?.name === "idata_search") {
          // Haotian and iData use dataset_ids as an array
          kbSelectionConfig = { dataset_ids: aidpKbIds };
        } else if (tool?.name === "aidp_search") {
          // AIDP uses kds_list as an array
          kbSelectionConfig = { kds_list: aidpKbIds };
        } else if (!isKnowledgeBaseSearchTool) {
          // datamate_search uses index_names in config
          kbSelectionConfig = { index_names: aidpKbIds };
        }
      }

      // Prepare configuration parameters from currentParams
      // Filter out index_names/dataset_ids from configs when KB selection is enabled
      // since KB IDs are provided via kbSelectionConfig above
      const configs = (configParams || []).reduce(
        (acc: Record<string, any>, param: ToolParam) => {
          // Skip index_names when KB selection is enabled (provided via kbSelectionConfig)
          // For haotian_search and idata_search: skip only index_names (dataset_ids is handled by kbSelectionConfig)
          // For other KB tools: skip both index_names and dataset_ids
          if (toolRequiresKbSelection) {
            if (param.name === "index_names" && !isKnowledgeBaseSearchTool) {
              return acc;
            }
            if (
              param.name === "dataset_ids" &&
              tool?.name !== "haotian_search" &&
              tool?.name !== "idata_search"
            ) {
              return acc;
            }
            if (param.name === "kds_list" && tool?.name !== "aidp_search") {
              return acc;
            }
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

      // Merge KB selection config into configs
      const finalConfigs = { ...configs, ...kbSelectionConfig };
      // Call validateTool with parameters
      const toolName = tool.origin_name || tool.name || "";
      const toolSource = tool.source || "";
      const result = await validateTool(
        toolName,
        toolSource, // Tool source
        tool.usage || "", // Tool usage
        toolParams, // tool input parameters
        finalConfigs // tool configuration parameters
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
                        const isKbSelectorParam =
            (paramName === "index_names" ||
              paramName === "dataset_ids" ||
              paramName === "kds_list") && toolRequiresKbSelection;

                        // Handle KB selector parameters.
                        // For aidp_search: kds_list is a runtime input, include in manual JSON.
                        // For other tools (dify, ragflow, datamate, haotian, idata):
                        // KB params are config-only, skip in runtime manual JSON.
                        if (isKbSelectorParam && !isKnowledgeBaseSearchTool) {
                          if (paramName === "kds_list" && toolKbType === "aidp_search") {
                            if (testPanelKbIds.length > 0) {
                              currentParamsJson[paramName] = testPanelKbIds;
                            }
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
                          const isKbSelectorParam =
            (paramName === "index_names" ||
              paramName === "dataset_ids" ||
              paramName === "kds_list") && toolRequiresKbSelection;

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

                      // Check if this is the KB selector parameter and KB selection is enabled
                      // Haotian uses dataset_ids, others use index_names
                      // For aidp_search, kds_list should be shown in both config AND input areas
                      const isKbSelectorParam =
                        (paramName === "index_names" ||
                          paramName === "dataset_ids" ||
                          paramName === "kds_list") && toolRequiresKbSelection;

                      // KB selection is configured in the upper config area.
                      // For index_names/dataset_ids: do not render duplicated KB params in test input area.
                      // For aidp_search kds_list: render it in test input area so user can override KB selection.
                      const shouldHideKbSelector =
                        isKbSelectorParam &&
                        !isKnowledgeBaseSearchTool &&
                        !(toolKbType === "aidp_search" && paramName === "kds_list");

                      if (shouldHideKbSelector) {
                        return null;
                      }

                      // Add type-specific validation rules
                      switch (paramInfo?.type || DEFAULT_TYPE) {
                        case "array":
                          rules.push({
                            validator: async (_: any, value: any) => {
                              if (!value) return;
                              try {
                                const parsed =
                                  typeof value === "string"
                                    ? JSON.parse(value)
                                    : value;
                                if (!Array.isArray(parsed)) {
                                  throw new Error(t("toolConfig.validation.array.invalid"));
                                }
                              } catch (e) {
                                throw new Error(t("toolConfig.validation.array.invalid"));
                              }
                            },
                          });
                          break;
                        case "object":
                          rules.push({
                            validator: async (_: any, value: any) => {
                              if (!value) return;
                              try {
                                const parsed =
                                  typeof value === "string"
                                    ? JSON.parse(value)
                                    : value;
                                if (
                                  typeof parsed !== "object" ||
                                  Array.isArray(parsed)
                                ) {
                                  throw new Error(t("toolConfig.validation.object.invalid"));
                                }
                              } catch {
                                throw new Error(t("toolConfig.validation.object.invalid"));
                              }
                            },
                          });
                          break;
                      }

                      return (
                        (() => {
                          const kbPlaceholder = t(
                            "toolConfig.input.knowledgeBaseSelector.placeholder",
                            {
                              name:
                                getLocalizedDescription(description, description_zh) ||
                                paramName,
                            }
                          );
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
                          {/* KB selector for knowledge_base_search tool */}
                          {isKnowledgeBaseSearchTool && paramName === "index_names" ? (
                            <KbSelectorDisplay
                              selectedKbIds={testPanelKbIds}
                              selectedKbDisplayNames={testPanelKbDisplayNames}
                              kbPlaceholder={kbPlaceholder}
                              onOpenKbSelector={onOpenKbSelector}
                              onKbRemove={onTestPanelKbRemove}
                            />
                          ) : toolKbType === "aidp_search" && paramName === "kds_list" ? (
                            <KbSelectorDisplay
                              selectedKbIds={testPanelKbIds}
                              selectedKbDisplayNames={testPanelKbDisplayNames}
                              kbPlaceholder={kbPlaceholder}
                              onOpenKbSelector={onOpenKbSelector}
                              onKbRemove={onTestPanelKbRemove}
                            />
                          ) : (
                            <Input
                              placeholder={getLocalizedDescription(description, description_zh)}
                            />
                          )}
                        </Form.Item>
                          );
                        })()
                      );
                    })}
                  </>
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
