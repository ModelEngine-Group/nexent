"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Spin, Select, Form, message } from "antd";
import KnowledgeBaseList from "../../../../knowledges/components/knowledge/KnowledgeBaseList";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { ToolParam } from "@/types/agentConfig";
import { KnowledgeBase } from "@/types/knowledgeBase";
import { ConfigStore } from "@/lib/config";

export interface KnowledgeBaseToolConfigProps {
  currentParams: ToolParam[];
  setCurrentParams: (p: ToolParam[]) => void;
  form: any;
  serverParamNames: string[];
  retrievalParamNames: string[];
  renderParamInput: (param: ToolParam, index: number) => React.ReactNode;
  externalKbOptions?: { label: React.ReactNode; value: string; description?: string }[];
  externalKbRawList?: any[];
  externalKbLoading?: boolean;
  includeDataMateSync?: boolean;
  toolName?: string;
  toolSource?: string;
}

export default function KnowledgeBaseToolConfig({
  currentParams,
  setCurrentParams,
  form,
  serverParamNames,
  retrievalParamNames,
  renderParamInput,
  externalKbOptions,
  externalKbRawList,
  externalKbLoading = false,
  includeDataMateSync = false,
  toolName,
  toolSource,
}: KnowledgeBaseToolConfigProps) {
  const { t } = useTranslation("common");
  const [kbOptions, setKbOptions] = useState<
    { label: React.ReactNode; value: string; description?: string }[]
  >(externalKbOptions || []);
  const [kbLoading, setKbLoading] = useState<boolean>(externalKbLoading);
  const [kbModalVisible, setKbModalVisible] = useState(false);
  const [kbModalSelected, setKbModalSelected] = useState<string[]>([]);
  const [kbRawList, setKbRawList] = useState<any[]>(externalKbRawList || []);
  const [idNameMap, setIdNameMap] = useState<Record<string, string> | null>(() =>
    typeof window !== "undefined" ? knowledgeBaseService.getCachedIdNameMapSync() : null
  );
  // Prevent immediate re-opening of modal when Select regains focus after confirm
  // Use useRef for synchronous state checking to avoid race conditions
  const suppressOpenRef = useRef(false);
  const suppressTimerRef = useRef<number | null>(null);

  // Memoize current embedding model to prevent unnecessary re-renders
  const currentEmbeddingModel = useMemo(() => {
    return ConfigStore.getInstance().getModelConfig().embedding?.modelName || null;
  }, []);

  // Helper function to check if a knowledge base is selectable
  const isKbSelectable = (kb: KnowledgeBase): boolean => {
    const docCount = typeof kb.documentCount === "number" ? kb.documentCount : 0;
    const chunkCount = typeof kb.chunkCount === "number" ? kb.chunkCount : 0;
    const hasContent = (docCount + chunkCount) > 0;

    // Check model compatibility - only for local knowledge bases (nexent source)
    const isModelCompatible =
      kb.source !== "nexent" || // Non-local knowledge bases (e.g., DataMate) don't need model check
      kb.embeddingModel === "unknown" ||
      kb.embeddingModel === currentEmbeddingModel;

    return hasContent && isModelCompatible;
  };

  const buildKbOptions = (kbs: any[]) => {
    // For the preview/select we only need the KB name (no description).
    return kbs.map((kb) => ({
      value: kb.id,
      label: kb.name,
      description: kb.description || "",
    }));
  };

  const openKbModal = async () => {
    // Capture suppress state at the start of the function to prevent race conditions
    // This snapshot will be used later to verify we should still open the modal
    const suppressSnapshot = suppressOpenRef.current;

    // If suppress was active at the start of this call, clear it and return
    if (suppressSnapshot) {
      suppressOpenRef.current = false;
      if (suppressTimerRef.current) {
        window.clearTimeout(suppressTimerRef.current);
        suppressTimerRef.current = null;
      }
      return;
    }

    // Clear any pending suppress timer since we're intentionally opening the modal
    if (suppressTimerRef.current) {
      window.clearTimeout(suppressTimerRef.current);
      suppressTimerRef.current = null;
    }

    // If parent provided KB list, use it; otherwise fetch
    setKbLoading(true);
    try {
      let kbs: any[] = [];
      if (externalKbRawList && externalKbRawList.length > 0) {
        kbs = externalKbRawList;
      } else if (includeDataMateSync || toolName === "datamate_search") {
        // Fetch DataMate knowledge bases only
        try {
          const syncResult = await knowledgeBaseService.syncDataMateAndCreateRecords();
          if (syncResult && syncResult.indices_info) {
            kbs = syncResult.indices_info.map((indexInfo: any) => {
              const stats = indexInfo.stats?.base_info || {};
              const kbId = indexInfo.name;
              const kbName = indexInfo.display_name || indexInfo.name;
              return {
                id: kbId,
                name: kbName,
                description: "DataMate knowledge base",
                documentCount: stats.doc_count || 0,
                chunkCount: stats.chunk_count || 0,
                createdAt: stats.creation_date || null,
                updatedAt: stats.update_date || stats.creation_date || null,
                embeddingModel: stats.embedding_model || "unknown",
                avatar: "",
                chunkNum: 0,
                language: "",
                nickname: "",
                parserId: "",
                permission: "",
                tokenNum: 0,
                source: "datamate",
              };
            });
          }
        } catch (e) {
          // fallback to empty list on error
          kbs = [];
        }
      } else {
        // Default: fetch local Elasticsearch indices (no DataMate sync)
        kbs = await knowledgeBaseService.getKnowledgeBasesInfo(true, false, true);
      }
      if (!externalKbRawList || externalKbRawList.length === 0) {
        setKbRawList(kbs);
        setKbOptions(buildKbOptions(kbs));
      } else {
        // Ensure local options reflect external options
        setKbOptions(externalKbOptions || buildKbOptions(kbs));
        setKbRawList(externalKbRawList || kbs);
      }

      // initialize modal selection from current form value
      const idx = currentParams.findIndex((p) => p.name === "index_names");
      const currentVal = idx !== -1 ? currentParams[idx].value : undefined;
      setKbModalSelected(Array.isArray(currentVal) ? currentVal : []);

      // Double-check suppress snapshot before showing modal to prevent race conditions
      // If suppress was set during the async operation, don't open the modal
      if (suppressSnapshot) {
        setKbLoading(false);
        return;
      }
      setKbModalVisible(true);
    } catch (e) {
      message.error(t("toolConfig.message.kbRefreshFailed", "Failed to refresh KB list"));
    } finally {
      setKbLoading(false);
    }
  };

  useEffect(() => {
    return () => {
      if (suppressTimerRef.current) {
        window.clearTimeout(suppressTimerRef.current);
      }
    };
  }, []);

  // Fill id->name map in background (if not already available)
  useEffect(() => {
    let cancelled = false;
    if (idNameMap) return;
    (async () => {
      try {
        const map = await knowledgeBaseService.ensureIdNameMap();
        if (cancelled) return;
        setIdNameMap(map && Object.keys(map).length > 0 ? map : null);
      } catch (_e) {
        // ignore
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [idNameMap]);

  // Load KB info if there are existing selected ids but options don't include their labels
  useEffect(() => {
    const idx = currentParams.findIndex((p) => p.name === "index_names");
    if (idx === -1) return;
    const val = currentParams[idx].value;
    if (!Array.isArray(val) || val.length === 0) return;
    // If external options provided, check them first
    const optionsSource = externalKbOptions || kbOptions;
    const missing = val.some((id: string) => !optionsSource.find((o) => o.value === id));
    if (!missing) return;

    let cancelled = false;
    (async () => {
      setKbLoading(true);
      try {
        let kbs: any[] = [];
        if (externalKbRawList && externalKbRawList.length > 0) {
          kbs = externalKbRawList;
        } else if (includeDataMateSync || toolName === "datamate_search") {
          try {
            const syncResult = await knowledgeBaseService.syncDataMateAndCreateRecords();
            if (syncResult && syncResult.indices_info) {
              kbs = syncResult.indices_info.map((indexInfo: any) => {
                const stats = indexInfo.stats?.base_info || {};
                const kbId = indexInfo.name;
                const kbName = indexInfo.display_name || indexInfo.name;
                return {
                  id: kbId,
                  name: kbName,
                  description: "DataMate knowledge base",
                  documentCount: stats.doc_count || 0,
                  chunkCount: stats.chunk_count || 0,
                  createdAt: stats.creation_date || null,
                  updatedAt: stats.update_date || stats.creation_date || null,
                  embeddingModel: stats.embedding_model || "unknown",
                  avatar: "",
                  chunkNum: 0,
                  language: "",
                  nickname: "",
                  parserId: "",
                  permission: "",
                  tokenNum: 0,
                  source: "datamate",
                };
              });
            }
          } catch (e) {
            kbs = [];
          }
        } else {
          kbs = await knowledgeBaseService.getKnowledgeBasesInfo(true, false, true);
        }
        if (cancelled) return;
        setKbRawList(kbs);
        setKbOptions(buildKbOptions(kbs));
      } catch (e) {
        // ignore - we don't want to surface a user-facing error here
      } finally {
        if (!cancelled) setKbLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [currentParams]);

  const effectiveRetrievalParamNames = useMemo(() => {
    const names = Array.isArray(retrievalParamNames) ? [...retrievalParamNames] : [];
    const hasSearchModeInParams = currentParams.findIndex((p) => p.name === "search_mode") !== -1;
    if (hasSearchModeInParams && !names.includes("search_mode")) {
      names.push("search_mode");
    }
    return names;
  }, [retrievalParamNames, currentParams]);

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
          // Always render the index_names preview field. If the param does not exist yet,
          // we render a disabled Select with placeholder and keep the "Add" button inline.
          const idx = currentParams.findIndex((p) => p.name === "index_names");
          const fieldName = idx === -1 ? undefined : `param_${idx}`;
          const selectedValue = idx === -1 ? [] : currentParams[idx].value || [];

          return (
            <div className="flex items-start gap-2">
              <div className="flex-1">
                <Form.Item
                  key={"index_names_preview"}
                  label={
                    <span className="inline-block w-full truncate" title={idx !== -1 ? currentParams[idx].name : "index_names"}>
                      {idx !== -1 ? currentParams[idx].name : t("toolConfig.field.indexNames", "index_names")}
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
                  {(() => {
                    const selectedValue = idx === -1 ? [] : currentParams[idx].value || [];
                    const optionsSource =
                      externalKbOptions && externalKbOptions.length > 0
                        ? externalKbOptions
                        : kbOptions;
                    const isLoadingOptions = externalKbLoading || kbLoading;

                    // If mapping is available, create quickOptions for selected ids to show labels immediately
                    const quickOptions =
                      idNameMap && Array.isArray(selectedValue) && selectedValue.length > 0
                        ? selectedValue.map((id: string) => ({
                            value: id,
                            label: idNameMap[id] || id,
                          }))
                        : [];

                    const missingForSelected =
                      Array.isArray(selectedValue) &&
                      selectedValue.length > 0 &&
                      selectedValue.some((id: string) => {
                        // check if optionsSource has the id OR idNameMap has label
                        const inOptions = optionsSource.find((o) => o.value === id);
                        const inMap = idNameMap && idNameMap[id];
                        return !inOptions && !inMap;
                      });

                    // If we have saved ids but the mapping/options are not ready,
                    // show a loading placeholder to avoid rendering raw ids then swapping to names.
                    if (idx !== -1 && missingForSelected && isLoadingOptions) {
                      return (
                        <div className="flex items-center gap-2 text-sm text-gray-500">
                          <Spin size="small" />
                          <span>{t("toolConfig.message.loadingKbNames", "Loading knowledge base names...")}</span>
                        </div>
                      );
                    }

                    return (
                      <Select
                        mode="multiple"
                        allowClear
                        options={optionsSource.length > 0 ? optionsSource : quickOptions}
                        disabled={idx === -1}
                        placeholder={
                          idx !== -1
                            ? t("toolConfig.input.array.placeholder", { name: currentParams[idx].description })
                            : t("toolConfig.placeholder.selectKb", "Select knowledge bases")
                        }
                        notFoundContent={isLoadingOptions ? <Spin size="small" /> : null}
                        open={false}
                        onClick={openKbModal}
                        onFocus={openKbModal}
                      />
                    );
                  })()}
                </Form.Item>
              </div>

              {/* Inline loading indicator shown while KB list loads */}
              <div className="pt-2">
                {kbLoading && <Spin size="small" />}
              </div>
            </div>
          );
        })()}

        <Modal
          getContainer={() => document.body}
          zIndex={1200}
          open={kbModalVisible}
          title={t("toolConfig.modal.selectKbTitle", "Select Knowledge Bases")}
        onCancel={() => {
          setKbModalVisible(false);
          // suppress immediate reopen caused by focus/click after cancel
          suppressOpenRef.current = true;
          if (suppressTimerRef.current) {
            window.clearTimeout(suppressTimerRef.current);
          }
          suppressTimerRef.current = window.setTimeout(() => {
            suppressOpenRef.current = false;
            suppressTimerRef.current = null;
          }, 300);
          if (document.activeElement instanceof HTMLElement) {
            document.activeElement.blur();
          }
        }}
        cancelText={t("common.button.cancel")}
          okText={t("common.confirm")}
          onOk={() => {
            let idx2 = currentParams.findIndex((p) => p.name === "index_names");
            const newParams = [...currentParams];
            if (idx2 === -1) {
              const newParam: ToolParam = {
                name: "index_names",
                type: "array",
                required: false,
                description: "List of knowledge base ids",
                value: kbModalSelected,
              } as ToolParam;
              newParams.push(newParam);
              setCurrentParams(newParams);
              const fieldName2 = `param_${newParams.length - 1}`;
              form.setFieldsValue({ [fieldName2]: kbModalSelected });
            } else {
              newParams[idx2] = { ...newParams[idx2], value: kbModalSelected };
              setCurrentParams(newParams);
              const fieldName2 = `param_${idx2}`;
              form.setFieldsValue({ [fieldName2]: kbModalSelected });
            }
            // Close modal and briefly suppress open to avoid immediate re-open via focus/click
            setKbModalVisible(false);
            suppressOpenRef.current = true;
            if (suppressTimerRef.current) {
              window.clearTimeout(suppressTimerRef.current);
            }
            suppressTimerRef.current = window.setTimeout(() => {
              suppressOpenRef.current = false;
              suppressTimerRef.current = null;
            }, 300);
            // Blur active element to reduce chance of immediate focus triggering open
            if (document.activeElement instanceof HTMLElement) {
              document.activeElement.blur();
            }
          }}
          width={800}
        >
          {/* Ensure selected KB names are loaded into options so Select shows names instead of raw IDs */}
          {/* If index_names exists but options missing those ids, load KB info once */}
          {/* This effect will run when currentParams changes */}
          {/* We put it here inside the JSX file scope (top-level) via useEffect below */}
          <div style={{ height: "50vh" }}>
            <KnowledgeBaseList
              knowledgeBases={kbRawList as KnowledgeBase[]}
              selectedIds={kbModalSelected}
              activeKnowledgeBase={null}
              currentEmbeddingModel={currentEmbeddingModel}
              isLoading={kbLoading}
              syncLoading={false}
              onSelect={(id: string) => {
                const exists = kbModalSelected.includes(id);
                const newSelected = exists
                  ? kbModalSelected.filter((s) => s !== id)
                  : [...kbModalSelected, id];
                setKbModalSelected(newSelected);
              }}
              onClick={() => {}}
              showDataMateConfig={false}
              isSelectable={isKbSelectable}
              getModelDisplayName={(m: string) => m}
              containerHeight="50vh"
            />
          </div>
        </Modal>
      </div>
    </>
  );
}


