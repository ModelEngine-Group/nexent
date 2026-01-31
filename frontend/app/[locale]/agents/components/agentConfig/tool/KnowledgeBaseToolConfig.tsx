"use client";

import { useState, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Spin, Select, Form, Input, InputNumber, Switch } from "antd";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { ToolParam } from "@/types/agentConfig";
import KnowledgeBaseSelectionModal from "./KnowledgeBaseSelectionModal";

export interface KnowledgeBaseToolConfigProps {
  currentParams: ToolParam[];
  setCurrentParams: (p: ToolParam[]) => void;
  form: any;
  toolName?: string;
}

// Parameter groups for knowledge base tools
const SERVER_PARAM_NAMES = ["server_url", "api_key", "verify_ssl"];
const RETRIEVAL_PARAM_NAMES = [
  "top_k",
  "threshold",
  "kb_page",
  "kb_page_size",
  "search_mode",
  "search_method",
];

export default function KnowledgeBaseToolConfig({
  currentParams,
  setCurrentParams,
  form,
  toolName,
}: KnowledgeBaseToolConfigProps) {
  const { t } = useTranslation("common");
  const [kbOptions, setKbOptions] = useState<
    { label: React.ReactNode; value: string }[]
  >([]);
  const [kbLoading, setKbLoading] = useState<boolean>(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [nameIdMap, setNameIdMap] = useState<Record<string, string> | null>(
    null
  );

  // Check if current tool is a Dify tool
  const isDifyTool = toolName?.startsWith("dify_");

  // Get Dify API configuration from current params
  const getDifyApiBase = () => {
    const serverUrlParam = currentParams.find((p) => p.name === "server_url");
    return serverUrlParam?.value || "";
  };

  const getDifyApiKey = () => {
    const apiKeyParam = currentParams.find((p) => p.name === "api_key");
    return apiKeyParam?.value || "";
  };

  // Render input component based on parameter type
  const renderParamInput = (param: ToolParam, index: number) => {
    const inputComponent = (() => {
      switch (param.type) {
        case "number":
          return (
            <InputNumber
              placeholder={t("toolConfig.input.string.placeholder", {
                name: param.description,
              })}
            />
          );

        case "boolean":
          return <Switch />;

        case "string":
        case "array":
        case "object":
        default:
          // Special-case: render `search_mode` as a Select dropdown with fixed options
          if (param.name === "search_mode") {
            return (
              <Select
                options={[
                  { label: "hybrid", value: "hybrid" },
                  { label: "accurate", value: "accurate" },
                  { label: "semantic", value: "semantic" },
                ]}
                placeholder={t("toolConfig.input.string.placeholder", {
                  name: param.description,
                })}
                allowClear
              />
            );
          }

          // Special-case: render `search_method` as a Select dropdown
          if (param.name === "search_method") {
            return (
              <Select
                defaultValue="semantic_search"
                options={[
                  { label: "keyword_search", value: "keyword_search" },
                  { label: "semantic_search", value: "semantic_search" },
                  { label: "full_text_search", value: "full_text_search" },
                  { label: "hybrid_search", value: "hybrid_search" },
                ]}
                placeholder={t("toolConfig.input.string.placeholder", {
                  name: param.description,
                })}
                allowClear
              />
            );
          }

          // Default Input.TextArea for all other types
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

  useEffect(() => {
    const loadKbOptions = async () => {
      setKbLoading(true);
      try {
        let kbMap: Record<string, string> = {};

        if (toolName === "datamate_search") {
          // For datamate_search, sync DataMate knowledge bases and build map
          // Use index_name as key, display_name as value
          const syncResult =
            await knowledgeBaseService.syncDataMateAndCreateRecords();
          if (syncResult && syncResult.indices_info) {
            syncResult.indices_info.forEach((indexInfo: any) => {
              const kbId = indexInfo.name; // index_name
              const kbName = indexInfo.display_name || indexInfo.name; // display_name or fallback
              kbMap[kbId] = kbName;
            });
          }
        } else {
          // For other tools, use the standard cached map
          kbMap = await knowledgeBaseService.ensureIdNameMap();
        }

        if (Object.keys(kbMap).length > 0) {
          // Build reverse map: display_name -> index_name
          const reverseMap: Record<string, string> = {};
          Object.entries(kbMap).forEach(([id, name]) => {
            reverseMap[name] = id;
          });
          setNameIdMap(reverseMap);
          const options = Object.entries(kbMap).map(([id, name]) => ({
            value: id, // index_name (for saving)
            label: name, // display_name (for display)
          }));
          setKbOptions(options);
        }
      } catch (error) {
        console.error("Failed to load KB options:", error);
      } finally {
        setKbLoading(false);
      }
    };

    loadKbOptions();
  }, [toolName]);

  const handleSaveSelection = (selectedIds: string[]) => {
    const paramName = getKbParamName();
    let idx = currentParams.findIndex((p) => p.name === paramName);
    const newParams = [...currentParams];

    // For Dify tools, save as JSON string; for others, save as array
    const valueToSave = isDifyTool
      ? JSON.stringify(selectedIds)
      : selectedIds.map((id) => nameIdMap?.[id] || id);

    if (idx === -1) {
      const newParam: ToolParam = {
        name: paramName,
        type: "array",
        required: false,
        description: isDifyTool
          ? "List of Dify dataset IDs"
          : "List of knowledge base IDs",
        value: valueToSave,
      } as ToolParam;
      newParams.push(newParam);
      idx = newParams.length - 1;
    } else {
      newParams[idx] = { ...newParams[idx], value: valueToSave };
    }
    setCurrentParams(newParams);
    const fieldName = `param_${idx}`;
    form.setFieldsValue({ [fieldName]: valueToSave });
    setIsModalOpen(false);
  };

  const effectiveRetrievalParamNames = useMemo(() => {
    const names = [...RETRIEVAL_PARAM_NAMES];
    const hasSearchModeInParams =
      currentParams.findIndex((p) => p.name === "search_mode") !== -1;
    if (hasSearchModeInParams && !names.includes("search_mode")) {
      names.push("search_mode");
    }
    return names;
  }, [currentParams]);

  // Get the knowledge base param name based on tool type
  const getKbParamName = () => {
    return isDifyTool ? "dataset_ids" : "index_names";
  };

  // Get placeholder text based on tool type
  const getKbPlaceholder = () => {
    if (isDifyTool) {
      return t("toolConfig.dify.datasetIdsPlaceholder") || "Select datasets";
    }
    return t("toolConfig.placeholder.selectKb") || "Select knowledge bases";
  };

  // Get selected values from params
  const getSelectedValues = (): string[] => {
    const paramName = getKbParamName();
    const idx = currentParams.findIndex((p) => p.name === paramName);
    if (idx === -1) return [];

    const value = currentParams[idx].value;
    if (!value) return [];

    // For Dify, value is JSON string; for Nexent, value is array
    if (isDifyTool && typeof value === "string") {
      try {
        return JSON.parse(value);
      } catch {
        return [];
      }
    }
    return Array.isArray(value) ? value : [];
  };

  // Filter params for each group
  const serverParams = currentParams.filter((p) =>
    SERVER_PARAM_NAMES.includes(p.name)
  );
  const retrievalParams = currentParams.filter((p) =>
    RETRIEVAL_PARAM_NAMES.includes(p.name)
  );

  return (
    <>
      {/* Server parameters */}
      <div className="mb-4">
        <div className="text-sm font-medium mb-2">
          {t("toolConfig.group.serverParameters", "Server Parameters")}
        </div>
        {serverParams.map((param, idx) => {
          const paramIndex = currentParams.findIndex((p) => p.name === param.name);
          const fieldName = `param_${paramIndex}`;
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
              tooltip={{
                title: param.description,
                placement: "topLeft",
                styles: { root: { maxWidth: 400 } },
              }}
            >
              {renderParamInput(param, paramIndex)}
            </Form.Item>
          );
        })}
      </div>

      {/* Retrieval parameters */}
      <div className="mb-4">
        <div className="text-sm font-medium mb-2">
          {t("toolConfig.group.retrievalParameters", "Retrieval Parameters")}
        </div>
        {retrievalParams.map((param) => {
          const paramIndex = currentParams.findIndex((p) => p.name === param.name);
          const fieldName = `param_${paramIndex}`;
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
              tooltip={{
                title: param.description,
                placement: "topLeft",
                styles: { root: { maxWidth: 400 } },
              }}
            >
              {renderParamInput(param, paramIndex)}
            </Form.Item>
          );
        })}
      </div>

      {/* Knowledge base selection - unified for all tool types */}
      <div className="mb-4">
        {(() => {
          const paramName = getKbParamName();
          const idx = currentParams.findIndex((p) => p.name === paramName);
          const fieldName = idx === -1 ? undefined : `param_${idx}`;
          const selectedValue = getSelectedValues();

          return (
            <div className="flex items-start gap-2">
              <div className="flex-1">
                <Form.Item
                  key={`${paramName}_preview`}
                  label={
                    <span
                      className="inline-block w-full truncate"
                      title={idx !== -1 ? currentParams[idx].name : paramName}
                    >
                      {idx !== -1
                        ? currentParams[idx].name
                        : t(`toolConfig.field.${paramName}`, paramName)}
                    </span>
                  }
                  name={fieldName}
                  tooltip={
                    idx !== -1
                      ? {
                          title: currentParams[idx].description,
                          placement: "topLeft",
                          styles: { root: { maxWidth: 400 } },
                        }
                      : undefined
                  }
                  className="mb-0"
                >
                  <Select
                    mode="multiple"
                    allowClear
                    options={kbOptions}
                    placeholder={getKbPlaceholder()}
                    notFoundContent={kbLoading ? <Spin size="small" /> : null}
                    open={false}
                    onClick={() => setIsModalOpen(true)}
                    value={selectedValue}
                    className="w-full"
                  />
                </Form.Item>
              </div>
              {kbLoading && (
                <div className="pt-2">
                  <Spin size="small" />
                </div>
              )}
            </div>
          );
        })()}
      </div>

      {/* Unified knowledge base selection modal */}
      <KnowledgeBaseSelectionModal
        isOpen={isModalOpen}
        onCancel={() => setIsModalOpen(false)}
        onSave={handleSaveSelection}
        initialSelectedIds={getSelectedValues()}
        toolName={toolName}
        difyApiBase={isDifyTool ? getDifyApiBase() : undefined}
        difyApiKey={isDifyTool ? getDifyApiKey() : undefined}
      />
    </>
  );
}
