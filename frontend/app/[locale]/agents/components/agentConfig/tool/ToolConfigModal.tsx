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
import { API_ENDPOINTS } from "@/services/api";
import log from "@/lib/logger";

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
  // Track if user has attempted to submit the form
  const [hasSubmitted, setHasSubmitted] = useState(false);

  // Dify configuration state
  const [difyConfig, setDifyConfig] = useState<{
    serverUrl: string;
    apiKey: string;
  }>({
    serverUrl: "",
    apiKey: "",
  });

  // DataMate URL from knowledge base configuration
  const [knowledgeBaseDataMateUrl, setKnowledgeBaseDataMateUrl] =
    useState<string>("");
  // Track if user has manually modified the datamate URL field
  const [hasUserModifiedDatamateUrl, setHasUserModifiedDatamateUrl] =
    useState(false);

  // Helper function to get authorization headers
  const getAuthHeaders = () => {
    const session =
      typeof window !== "undefined" ? localStorage.getItem("session") : null;
    const sessionObj = session ? JSON.parse(session) : null;
    return {
      "Content-Type": "application/json",
      "User-Agent": "AgentFrontEnd/1.0",
      ...(sessionObj?.access_token && {
        Authorization: `Bearer ${sessionObj.access_token}`,
      }),
    };
  };

  // Load DataMate URL from knowledge base configuration
  const loadKnowledgeBaseDataMateUrl = useCallback(async () => {
    try {
      const response = await fetch(API_ENDPOINTS.config.load, {
        method: "GET",
        headers: getAuthHeaders(),
      });

      if (response.ok) {
        const result = await response.json();
        const config = result.config;
        if (
          config &&
          config.app &&
          typeof config.app.datamateUrl === "string"
        ) {
          setKnowledgeBaseDataMateUrl(config.app.datamateUrl);
        }
      }
    } catch (error) {
      log.error(
        "Failed to load DataMate URL from knowledge base config:",
        error
      );
    }
  }, []);

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
  // For datamate_search, use the server_url from the form as config
  const datamateServerUrl = useMemo(() => {
    if (toolKbType === "datamate_search") {
      const serverUrlParam = currentParams.find((p) => p.name === "server_url");
      return serverUrlParam?.value || "";
    }
    return "";
  }, [toolKbType, currentParams]);

  const {
    data: knowledgeBases = [],
    isLoading: kbLoading,
    refetch: refetchKnowledgeBases,
  } = useKnowledgeBasesForToolConfig(
    toolKbType,
    toolKbType === "dify_search"
      ? difyConfig
      : toolKbType === "datamate_search"
        ? { serverUrl: datamateServerUrl }
        : undefined
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

  // Track whether this is the first time opening the modal (reset when modal closes)
  const [modalOpened, setModalOpened] = useState(false);

  // Reset modal state when modal closes
  useEffect(() => {
    if (!isOpen) {
      setModalOpened(false);
      setKnowledgeBaseDataMateUrl("");
    }
  }, [isOpen]);

  // Initialize with provided params and sync display names when knowledgeBases is ready
  useEffect(() => {
    // Load DataMate URL from knowledge base configuration
    // This should run every time the modal opens for datamate_search tool
    if (tool?.name === "datamate_search" && isOpen && !modalOpened) {
      loadKnowledgeBaseDataMateUrl().then(() => {
        // After loading, check if we need to apply the URL
        // The other useEffect will handle the application
      });
    }
  }, [tool?.name, isOpen, modalOpened]);

  // Apply DataMate URL default value for datamate_search tool
  // This should only run ONCE when modal first opens
  useEffect(() => {
    if (!isOpen || !tool || tool.name !== "datamate_search") {
      return;
    }

    // Mark modal as opened
    if (!modalOpened) {
      setModalOpened(true);
    }

    // Only apply default URL if:
    // 1. server_url has NO saved value (empty)
    // 2. knowledgeBaseDataMateUrl IS available
    // 3. This is the first time opening (modalOpened is false)
    const serverUrlParam = initialParams.find((p) => p.name === "server_url");

    // If server_url already has a saved value, use it
    if (serverUrlParam?.value) {
      // Initialize form with saved values (including server_url)
      setCurrentParams(initialParams);
      const formValues: Record<string, any> = {};
      initialParams.forEach((param, index) => {
        formValues[`param_${index}`] = param.value;
      });
      form.setFieldsValue(formValues);

      // Parse initial index_names/dataset_ids value for knowledge base selection
      const kbParam = initialParams.find(
        (p) => p.name === "index_names" || p.name === "dataset_ids"
      );
      if (kbParam?.value) {
        let ids: string[] = [];
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
        }
      }
      return;
    }

    // If we reach here, server_url has no saved value
    // Apply default from knowledgeBaseDataMateUrl if available
    // Only apply if user has NOT manually modified the URL field
    if (knowledgeBaseDataMateUrl && !hasUserModifiedDatamateUrl) {
      const updatedParams = initialParams.map((param) => {
        if (param.name === "server_url") {
          return { ...param, value: knowledgeBaseDataMateUrl };
        }
        return param;
      });

      setCurrentParams(updatedParams);

      const formValues: Record<string, any> = {};
      updatedParams.forEach((param, index) => {
        formValues[`param_${index}`] = param.value;
      });
      form.setFieldsValue(formValues);
    } else {
      // Either no default available OR user has modified the URL, initialize with initialParams
      setCurrentParams(initialParams);
      const formValues: Record<string, any> = {};
      initialParams.forEach((param, index) => {
        formValues[`param_${index}`] = param.value;
      });
      form.setFieldsValue(formValues);
    }

    // Parse initial index_names/dataset_ids value for knowledge base selection
    const kbParam = initialParams.find(
      (p) => p.name === "index_names" || p.name === "dataset_ids"
    );
    if (kbParam?.value) {
      let ids: string[] = [];
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
      }
    }
  }, [
    isOpen,
    tool,
    initialParams,
    knowledgeBaseDataMateUrl,
    form,
    modalOpened,
  ]);

  // When knowledgeBaseDataMateUrl is loaded, check if we need to apply it to the form
  // This handles the case where the URL was loaded after the initial form setup
  useEffect(() => {
    // Only run for datamate_search tool when modal is open
    if (!isOpen || !tool || tool.name !== "datamate_search") {
      return;
    }

    // Skip if server_url already has a saved value
    const serverUrlParam = initialParams.find((p) => p.name === "server_url");
    if (serverUrlParam?.value) {
      return;
    }

    // Skip if no knowledgeBaseDataMateUrl available
    if (!knowledgeBaseDataMateUrl) {
      return;
    }

    // Skip if user has manually modified the URL field
    if (hasUserModifiedDatamateUrl) {
      return;
    }

    // Skip if form is already initialized with this URL
    const existingUrlParam = currentParams.find((p) => p.name === "server_url");
    if (existingUrlParam?.value === knowledgeBaseDataMateUrl) {
      return;
    }

    // Apply the loaded URL to the form
    const updatedParams = initialParams.map((param) => {
      if (param.name === "server_url") {
        return { ...param, value: knowledgeBaseDataMateUrl };
      }
      return param;
    });

    setCurrentParams(updatedParams);

    const formValues: Record<string, any> = {};
    updatedParams.forEach((param, index) => {
      formValues[`param_${index}`] = param.value;
    });
    form.setFieldsValue(formValues);
  }, [
    isOpen,
    tool,
    initialParams,
    knowledgeBaseDataMateUrl,
    form,
    currentParams,
    hasUserModifiedDatamateUrl,
  ]);

  // Initialize form values for non-datamate tools
  useEffect(() => {
    // Skip if it's datamate_search tool (handled by other useEffects above)
    if (tool?.name === "datamate_search") {
      return;
    }

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
  }, [initialParams, toolRequiresKbSelection, tool?.name, form]);

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
    // Mark that user has attempted to submit the form
    setHasSubmitted(true);

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

      // Check if knowledge base selector has valid selection (for index_names/dataset_ids fields)
      // Since these fields use custom UI without form control, we need manual validation
      if (toolRequiresKbSelection && selectedKbIds.length === 0) {
        const kbParam = currentParams.find(
          (p) =>
            p.required && (p.name === "index_names" || p.name === "dataset_ids")
        );
        if (kbParam) {
          message.error(t("toolConfig.validation.selectKb"));
          return;
        }
      }

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
    } catch {
      // Form validation failed, error will be shown by antd Form
    }
  };

  const handleClose = () => {
    setTestPanelVisible(false);
    // Reset user modification tracking state for datamate URL
    setHasUserModifiedDatamateUrl(false);
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
    // Reset submit state when user makes a selection
    setHasSubmitted(false);

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
    // Reset submit state when user modifies selection
    setHasSubmitted(false);

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

      // Check if this field has validation error
      // Only show error after user has attempted to submit the form
      const hasError =
        hasSubmitted && param.required && selectedKbIds.length === 0;

      return (
        <div>
          <div
            className={`cursor-pointer bg-white border rounded px-3 py-2 transition-colors ${
              hasError
                ? "border-red-500 hover:border-red-500"
                : "border-gray-300 hover:border-blue-400"
            }`}
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
          {/* Show error message when validation fails */}
          {hasError && (
            <div
              className="ant-form-item-explain-error"
              style={{ marginTop: "4px" }}
            >
              {t("toolConfig.validation.selectKb")}
            </div>
          )}
        </div>
      );
    },
    [
      form,
      knowledgeBases,
      selectedKbIds,
      selectedKbDisplayNames,
      kbLoading,
      hasSubmitted,
      t,
    ]
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
              onValuesChange={(changedValues, allValues) => {
                // Track if user has modified the datamate server_url field
                if (
                  tool?.name === "datamate_search" &&
                  knowledgeBaseDataMateUrl &&
                  !hasUserModifiedDatamateUrl
                ) {
                  const serverUrlFieldIndex = currentParams.findIndex(
                    (p) => p.name === "server_url"
                  );
                  if (serverUrlFieldIndex >= 0) {
                    const fieldName = `param_${serverUrlFieldIndex}`;
                    if (changedValues[fieldName] !== undefined) {
                      setHasUserModifiedDatamateUrl(true);
                    }
                  }
                }
              }}
            >
              <div className="pr-2 mt-3">
                {currentParams.map((param, index) => {
                  const fieldName = `param_${index}`;
                  const rules: any[] = [];

                  // Add required validation rule
                  if (param.required) {
                    rules.push({
                      required: true,
                      message: t("toolConfig.validation.required"),
                    });
                  }

                  // Add URL validation for server_url parameter
                  if (param.name === "server_url") {
                    rules.push({
                      validator: async (_: any, value: any) => {
                        if (!value) return Promise.resolve();
                        try {
                          // Check if value is a valid URL
                          let url: URL;
                          try {
                            url = new URL(value);
                          } catch {
                            return Promise.reject(
                              t("knowledgeBase.error.invalidUrlFormat")
                            );
                          }
                          // Check if protocol is http or https
                          if (url.protocol !== "http:" && url.protocol !== "https:") {
                            return Promise.reject(
                              t("knowledgeBase.error.invalidUrlProtocol")
                            );
                          }
                          return Promise.resolve();
                        } catch {
                          return Promise.reject(
                            t("knowledgeBase.error.invalidUrlFormat")
                          );
                        }
                      },
                    });
                  }

                  // Add custom validator for knowledge base selector fields (index_names/dataset_ids)
                  // Since these fields use custom display without form control, we need custom validation
                  if (
                    toolRequiresKbSelection &&
                    (param.name === "index_names" ||
                      param.name === "dataset_ids")
                  ) {
                    rules.push({
                      validator: async () => {
                        // Check if any knowledge base has been selected
                        if (selectedKbIds.length === 0) {
                          return Promise.reject(
                            t("toolConfig.validation.selectKb")
                          );
                        }
                        return Promise.resolve();
                      },
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
        onSync={(toolType) =>
          syncKnowledgeBases(
            toolType,
            toolType === "datamate_search"
              ? { serverUrl: datamateServerUrl }
              : toolType === "dify_search"
                ? difyConfig
                : undefined
          )
        }
        syncLoading={isSyncing === getToolType()}
        isSelectable={canSelectKnowledgeBase}
        currentEmbeddingModel={currentEmbeddingModel}
        difyConfig={
          toolKbType === "dify_search"
            ? difyConfig
            : toolKbType === "datamate_search"
              ? { serverUrl: datamateServerUrl }
              : undefined
        }
      />
    </>
  );
}
