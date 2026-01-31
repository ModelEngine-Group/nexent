"use client";

import { useState, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Spin, Select, Form } from "antd";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { ToolParam } from "@/types/agentConfig";
import KnowledgeBaseSelectionModal from "./KnowledgeBaseSelectionModal";

export interface KnowledgeBaseToolConfigProps {
  currentParams: ToolParam[];
  setCurrentParams: (p: ToolParam[]) => void;
  form: any;
  serverParamNames: string[];
  retrievalParamNames: string[];
  renderParamInput: (param: ToolParam, index: number) => React.ReactNode;
  toolName?: string;
}

export default function KnowledgeBaseToolConfig({
  currentParams,
  setCurrentParams,
  form,
  serverParamNames,
  retrievalParamNames,
  renderParamInput,
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
        } else if (toolName === "dify_search") {
          // For dify_search, we need to get dify_api_base and api_key from current params
          const difyApiBaseIdx = currentParams.findIndex(
            (p) => p.name === "dify_api_base"
          );
          const apiKeyIdx = currentParams.findIndex((p) => p.name === "api_key");

          const difyApiBase =
            difyApiBaseIdx !== -1 ? currentParams[difyApiBaseIdx]?.value : null;
          const apiKey = apiKeyIdx !== -1 ? currentParams[apiKeyIdx]?.value : null;

          if (difyApiBase && apiKey) {
            try {
              const difyResult = await knowledgeBaseService.fetchDifyDatasets(
                difyApiBase,
                apiKey,
                1,
                100
              );
              if (difyResult && difyResult.indices_info) {
                difyResult.indices_info.forEach((indexInfo: any) => {
                  const kbId = indexInfo.name; // dataset_id
                  const kbName = indexInfo.display_name || indexInfo.name;
                  kbMap[kbId] = kbName;
                });
              }
            } catch (e) {
              // Silently fail, kbMap remains empty
            }
          }
        } else {
          // For other tools (nexent knowledge_base_search), fetch knowledge bases
          const kbs = await knowledgeBaseService.getKnowledgeBasesInfo(
            true, // skipHealthCheck
            false, // includeDataMateSync
            null // tenantId
          );
          kbs.forEach((kb: any) => {
            kbMap[kb.id] = kb.name;
          });
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
  }, [toolName, currentParams]);

  const handleSaveSelection = (selectedIds: string[]) => {
    let idx = currentParams.findIndex((p) => p.name === "index_names");
    const newParams = [...currentParams];
    // Convert display_name back to index_name for saving
    const actualIds = selectedIds.map((id) => nameIdMap?.[id] || id);
    if (idx === -1) {
      const newParam: ToolParam = {
        name: "index_names",
        type: "array",
        required: false,
        description: "List of knowledge base ids",
        value: actualIds,
      } as ToolParam;
      newParams.push(newParam);
      idx = newParams.length - 1;
    } else {
      newParams[idx] = { ...newParams[idx], value: actualIds };
    }
    setCurrentParams(newParams);
    const fieldName = `param_${idx}`;
    form.setFieldsValue({ [fieldName]: actualIds });
    setIsModalOpen(false);
  };

  const effectiveRetrievalParamNames = useMemo(() => {
    const names = Array.isArray(retrievalParamNames)
      ? [...retrievalParamNames]
      : [];
    const hasSearchModeInParams =
      currentParams.findIndex((p) => p.name === "search_mode") !== -1;
    if (hasSearchModeInParams && !names.includes("search_mode")) {
      names.push("search_mode");
    }
    return names;
  }, [retrievalParamNames, currentParams]);

  // Get dify configuration for dify_search tool
  const difyApiBase = useMemo(() => {
    if (toolName !== "dify_search") return undefined;
    const idx = currentParams.findIndex((p) => p.name === "dify_api_base");
    return idx !== -1 ? currentParams[idx]?.value : undefined;
  }, [toolName, currentParams]);

  const difyApiKey = useMemo(() => {
    if (toolName !== "dify_search") return undefined;
    const idx = currentParams.findIndex((p) => p.name === "api_key");
    return idx !== -1 ? currentParams[idx]?.value : undefined;
  }, [toolName, currentParams]);

  return (
    <>
      {/* Server parameters */}
      <div className="mb-4">
        <div className="text-sm font-medium mb-2">
          {t("toolConfig.group.serverParameters", "Server Parameters")}
        </div>
        {serverParamNames.map((name) => {
          const idx = currentParams.findIndex((p) => p.name === name);
          if (idx === -1) return null;
          const fieldName = `param_${idx}`;
          return (
            <Form.Item
              key={name}
              label={
                <span
                  className="inline-block w-full truncate"
                  title={currentParams[idx].name}
                >
                  {currentParams[idx].name}
                </span>
              }
              name={fieldName}
              tooltip={{
                title: currentParams[idx].description,
                placement: "topLeft",
                styles: { root: { maxWidth: 400 } },
              }}
            >
              {renderParamInput(currentParams[idx], idx)}
            </Form.Item>
          );
        })}
      </div>

      {/* Retrieval parameters */}
      <div className="mb-4">
        <div className="text-sm font-medium mb-2">
          {t("toolConfig.group.retrievalParameters", "Retrieval Parameters")}
        </div>
        {effectiveRetrievalParamNames.map((name) => {
          const idx = currentParams.findIndex((p) => p.name === name);
          if (idx === -1) return null;
          const fieldName = `param_${idx}`;
          return (
            <Form.Item
              key={name}
              label={
                <span
                  className="inline-block w-full truncate"
                  title={currentParams[idx].name}
                >
                  {currentParams[idx].name}
                </span>
              }
              name={fieldName}
              tooltip={{
                title: currentParams[idx].description,
                placement: "topLeft",
                styles: { root: { maxWidth: 400 } },
              }}
            >
              {renderParamInput(currentParams[idx], idx)}
            </Form.Item>
          );
        })}
      </div>

      {/* Knowledge base selection */}
      <div className="mb-4">
        {(() => {
          const idx = currentParams.findIndex((p) => p.name === "index_names");
          const fieldName = idx === -1 ? undefined : `param_${idx}`;
          const selectedValue =
            idx === -1 ? [] : currentParams[idx].value || [];

          return (
            <div className="flex items-start gap-2">
              <div className="flex-1">
                <Form.Item
                  key={"index_names_preview"}
                  label={
                    <span
                      className="inline-block w-full truncate"
                      title={
                        idx !== -1 ? currentParams[idx].name : "index_names"
                      }
                    >
                      {idx !== -1
                        ? currentParams[idx].name
                        : t("toolConfig.field.indexNames", "index_names")}
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
                    placeholder={
                      !selectedValue || selectedValue.length === 0
                        ? t(
                            "toolConfig.placeholder.selectKb",
                            "Select knowledge bases"
                          )
                        : t("toolConfig.input.array.placeholder", {
                            name: currentParams[idx]?.description,
                          })
                    }
                    notFoundContent={kbLoading ? <Spin size="small" /> : null}
                    open={false}
                    onClick={() => setIsModalOpen(true)}
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

      <KnowledgeBaseSelectionModal
        isOpen={isModalOpen}
        onCancel={() => setIsModalOpen(false)}
        onSave={handleSaveSelection}
        initialSelectedIds={
          currentParams.find((p) => p.name === "index_names")?.value || []
        }
        toolName={toolName}
        difyApiBase={difyApiBase}
        difyApiKey={difyApiKey}
      />
    </>
  );
}
