import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useState,
  useRef,
  ReactNode,
  useMemo,
  useCallback,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Alert, App, Button, Card, Tag } from "antd";
import { Plus, ShieldCheck, RefreshCw, Pencil, Trash2 } from "lucide-react";
import { ExclamationCircleFilled } from "@ant-design/icons";

import { MODEL_TYPES, MODEL_STATUS } from "@/const/modelConfig";
import { useConfig, CONFIG_QUERY_KEY } from "@/hooks/useConfig";
import { modelService, ModelError } from "@/services/modelService";
import { loadMemoryConfig } from "@/services/memoryService";
import {
  CapacityCoverage,
  ModelOption,
  ModelType,
  ModelConnectStatus,
} from "@/types/modelConfig";
import log from "@/lib/logger";

import { ModelAddDialogV2 } from "./model/ModelAddDialogV2";
import { ModelSlotSelect, buildModelSlots } from "./model/ModelSlotSelect";
import { ModelLibraryList } from "./model/ModelLibraryList";
import {
  ModelManagerDialog,
  ConnectionGroup,
} from "./model/ModelManagerDialog";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { Can } from "@/components/permission/Can";
import { useModelList } from "@/hooks/model/useModelList";

// Define the methods exposed by the component
export interface ModelConfigSectionRef {
  verifyModels: () => Promise<void>;
  getSelectedModels: () => Record<string, Record<string, string>>;
  getEmbeddingConnectivity: () => {
    embedding?: ModelConnectStatus;
    multi_embedding?: ModelConnectStatus;
  };
  simulateDropdownChange: (
    category: string,
    option: string,
    displayName: string
  ) => Promise<void>;
}

interface ModelConfigSectionProps {
  skipVerification?: boolean;
}

export const ModelConfigSection = forwardRef<
  ModelConfigSectionRef,
  ModelConfigSectionProps
>((props, ref): ReactNode => {
  const { t } = useTranslation();
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();

  const { skipVerification = false } = props;
  const { modelConfig, updateModelConfig, appConfig, saveConfig } = useConfig();
  const modelEngineEnable = appConfig?.modelEngineEnabled ?? false;

  const { confirm } = useConfirmModal();

  /* ------------------ State ------------------ */
  const [models, setModels] = useState<ModelOption[]>([]);
  const [isAddModalV2Open, setIsAddModalV2Open] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const [capacityCoverage, setCapacityCoverage] =
    useState<CapacityCoverage | null>(null);

  // Single model edit dialog
  const [editingCardModel, setEditingCardModel] = useState<ModelOption | null>(
    null
  );

  // v2.6.1 redesign: batch edit / delete dialog
  const [managerMode, setManagerMode] = useState<"editGroup" | "deleteGroup">(
    "editGroup"
  );
  const [isManagerOpen, setIsManagerOpen] = useState(false);
  const [batchUpdating, setBatchUpdating] = useState(false);
  const [batchDeleting, setBatchDeleting] = useState(false);

  const { invalidate } = useModelList();
  // Error state management
  const [errorFields, setErrorFields] = useState<{ [key: string]: boolean }>({
    "llm.main": false,
    "embedding.embedding": false,
    "embedding.multi_embedding": false,
  });

  const abortControllerRef = useRef<AbortController | null>(null);
  const throttleTimerRef = useRef<NodeJS.Timeout | null>(null);
  const saveTimerRef = useRef<NodeJS.Timeout | null>(null);
  const capacityCoverageRequestIdRef = useRef(0);

  const scheduleAutoSave = () => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(async () => {
      try {
        await saveConfig();
      } finally {
        saveTimerRef.current = null;
      }
    }, 600);
  };

  const [selectedModels, setSelectedModels] = useState<
    Record<string, Record<string, string>>
  >({
    llm: { main: "" },
    embedding: { embedding: "", multi_embedding: "" },
    reranker: { reranker: "" },
    multimodal: { vlm: "", vlm2: "", vlm3: "", vlm4: "" },
    voice: { tts: "", stt: "" },
  });

  /* ------------------ Init load ------------------ */
  const initialLoadDoneRef = useRef(false);
  useEffect(() => {
    if (modelConfig && !initialLoadDoneRef.current) {
      initialLoadDoneRef.current = true;
      loadModelLists(true);
    }
  }, [modelConfig]);

  /* ------------------ Missing field highlight ------------------ */
  // v2.6.1 redesign: the default-model slots are always visible inline (the
  // old flow opened the DefaultModelDialog first), so highlighting only needs
  // to mark the slot and scroll it into view.
  useEffect(() => {
    const handleHighlightMissingField = (event: any) => {
      const { field } = event.detail;
      if (field === "llm.main" || field === "embedding.embedding") {
        setErrorFields((prev) => ({ ...prev, [field]: true }));
        setTimeout(() => {
          const el = document.querySelector<HTMLElement>(
            `[data-error-field="${field}"]`
          );
          el?.scrollIntoView({ behavior: "smooth", block: "center" });
        }, 100);
      }
    };
    window.addEventListener(
      "highlightMissingField",
      handleHighlightMissingField
    );
    return () =>
      window.removeEventListener(
        "highlightMissingField",
        handleHighlightMissingField
      );
  }, []);

  /* ------------------ Derived: isDefaultFor mapping ------------------ */
  const defaultSlotMap = useMemo<Record<string, string[]>>(() => {
    const result: Record<string, string[]> = {};
    for (const [cat, opts] of Object.entries(selectedModels)) {
      for (const [opt, disp] of Object.entries(opts)) {
        if (!disp) continue;
        const key = `${cat}.${opt}`;
        if (!result[disp]) result[disp] = [];
        result[disp].push(key);
      }
    }
    return result;
  }, [selectedModels]);

  /* ------------------ Card-level edit / delete ------------------ */
  const handleCardEdit = useCallback((model: ModelOption) => {
    setEditingCardModel(model);
  }, []);

  /**
   * Blank the default-model slots that reference any of the given display
   * names (deleted models must not keep occupying a slot). Shared by the
   * single delete confirm and the batch delete dialog.
   */
  const clearDefaultSlotsFor = useCallback(
    (displayNames: string[]) => {
      const removed = new Set(displayNames);
      let configUpdates: any = {};
      const selectedPairs: [string, string, string][] = [
        ["llm", "main", "llm"],
        ["embedding", "embedding", "embedding"],
        ["embedding", "multi_embedding", "multiEmbedding"],
        ["reranker", "reranker", "rerank"],
        ["multimodal", "vlm", "vlm"],
        ["multimodal", "vlm2", "vlm2"],
        ["multimodal", "vlm3", "vlm3"],
        ["multimodal", "vlm4", "vlm4"],
        ["voice", "stt", "stt"],
        ["voice", "tts", "tts"],
      ];
      const blank = (voice: boolean) => {
        const base = {
          modelName: "",
          displayName: "",
          apiConfig: { apiKey: "", modelUrl: "" },
        };
        if (voice) {
          return {
            ...base,
            modelFactory: "",
            modelAppid: "",
            accessToken: "",
          };
        }
        return base;
      };
      selectedPairs.forEach(([cat, opt, cfgKey]) => {
        const current = selectedModels[cat]?.[opt];
        if (current && removed.has(current)) {
          setSelectedModels((p) => ({
            ...p,
            [cat]: { ...p[cat], [opt]: "" },
          }));
          if (cfgKey === "embedding" || cfgKey === "multiEmbedding") {
            configUpdates[cfgKey] = { ...blank(false), dimension: 0 };
          } else if (cfgKey === "stt" || cfgKey === "tts") {
            configUpdates[cfgKey] = blank(true);
          } else {
            configUpdates[cfgKey] = blank(false);
          }
        }
      });
      if (Object.keys(configUpdates).length > 0) {
        updateModelConfig(configUpdates);
        scheduleAutoSave();
      }
    },
    [selectedModels, updateModelConfig]
  );

  const handleCardDelete = useCallback(
    async (model: ModelOption) => {
      modal.confirm({
        title: t("model.deleteConfirm.title", {
          defaultValue: "确认删除该模型？",
        }),
        icon: <ExclamationCircleFilled />,
        content: (
          <div>
            <div style={{ marginBottom: 4 }}>
              {t("model.deleteConfirm.content", {
                name: model.displayName || model.name,
                defaultValue: `删除后，如该模型被作为默认模型使用将一并被清空。`,
              })}
            </div>
          </div>
        ),
        okText: t("common.confirm", { defaultValue: "删除" }),
        cancelText: t("common.cancel", { defaultValue: "取消" }),
        okButtonProps: { danger: true },
        onOk: async () => {
          try {
            await modelService.deleteCustomModel(
              model.displayName,
              model.source
            );
          } catch (e: any) {
            log.error("delete custom model failed", e);
            const msg =
              e instanceof ModelError
                ? e.message
                : t("modelConfig.error.deleteModelFailed", {
                    defaultValue: "删除模型失败",
                  });
            message.error(msg);
            throw e;
          }
          clearDefaultSlotsFor([model.displayName]);
          message.success(
            t("model.message.deleteSuccess", {
              name: model.displayName,
              defaultValue: `已删除：${model.displayName}`,
            })
          );
          await loadModelLists(true);
        },
      });
    },
    [message, modal, t, clearDefaultSlotsFor]
  );

  /* ------------------ v2.6.1 redesign: batch operations ------------------ */

  const handleBatchUpdateGroup = useCallback(
    async (group: ConnectionGroup, patch: { apiKey: string; url: string }) => {
      setBatchUpdating(true);
      let failed = 0;
      for (const m of group.models) {
        try {
          // Partial update: only api_key + base_url are sent; the backend
          // leaves every other field untouched.
          await modelService.updateSingleModel({
            currentDisplayName: m.displayName,
            url: patch.url,
            apiKey: patch.apiKey,
            source: m.source,
          });
        } catch (e: any) {
          failed += 1;
          log.error("batch update model failed", m.displayName, e);
        }
      }
      setBatchUpdating(false);
      if (failed === 0) {
        message.success(
          t("modelConfig.batchEdit.success", {
            count: group.models.length,
            defaultValue: `已更新 ${group.models.length} 个模型`,
          })
        );
      } else {
        message.warning(
          t("modelConfig.batchEdit.partialFailure", {
            failed,
            total: group.models.length,
            defaultValue: `${group.models.length} 个模型中 ${failed} 个更新失败`,
          })
        );
      }
      await loadModelLists(true);
    },
    [message, t]
  );

  const handleBatchDeleteModels = useCallback(
    async (targets: ModelOption[]) => {
      setBatchDeleting(true);
      const failed: string[] = [];
      for (const m of targets) {
        try {
          await modelService.deleteCustomModel(m.displayName, m.source);
        } catch (e: any) {
          failed.push(m.displayName);
          log.error("batch delete model failed", m.displayName, e);
        }
      }
      setBatchDeleting(false);
      clearDefaultSlotsFor(
        targets
          .filter((m) => !failed.includes(m.displayName))
          .map((m) => m.displayName)
      );
      if (failed.length === 0) {
        message.success(
          t("modelConfig.batchDelete.success", {
            count: targets.length,
            defaultValue: `已删除 ${targets.length} 个模型`,
          })
        );
      } else {
        message.warning(
          t("modelConfig.batchDelete.partialFailure", {
            failed: failed.length,
            total: targets.length,
            defaultValue: `${targets.length} 个模型中 ${failed.length} 个删除失败`,
          })
        );
      }
      await loadModelLists(true);
    },
    [message, t, clearDefaultSlotsFor]
  );

  /* ------------------ Connectivity resolution ------------------ */
  const getEmbeddingConnectivity = () => {
    const result: {
      embedding?: ModelConnectStatus;
      multi_embedding?: ModelConnectStatus;
    } = {};
    const resolveStatus = (
      displayName: string,
      modelType: ModelType
    ): ModelConnectStatus | undefined => {
      if (!displayName) return undefined;
      const model = models.find(
        (m) => m.displayName === displayName && m.type === modelType
      );
      return model?.connect_status as ModelConnectStatus | undefined;
    };
    result.embedding = resolveStatus(
      selectedModels.embedding?.embedding,
      MODEL_TYPES.EMBEDDING as unknown as ModelType
    );
    result.multi_embedding = resolveStatus(
      selectedModels.embedding?.multi_embedding,
      MODEL_TYPES.MULTI_EMBEDDING as unknown as ModelType
    );
    return result;
  };

  useImperativeHandle(ref, () => ({
    verifyModels,
    getSelectedModels: () => selectedModels,
    getEmbeddingConnectivity,
    simulateDropdownChange: async (
      category: string,
      option: string,
      displayName: string
    ) => {
      await applyModelChange(category, option, displayName);
    },
  }));

  // Load model lists
  const loadModelLists = async (
    skipVerify: boolean = false,
    refreshAgentQueries: boolean = false
  ) => {
    // Prefer the freshest cached config over the render-time closure value:
    // callers may have just invalidated CONFIG_QUERY_KEY (e.g. a model create
    // auto-configured default-model slots) and this component's cfg
    // still points at the previous render's snapshot.
    const cachedConfig = queryClient.getQueryData<any>(CONFIG_QUERY_KEY);
    const cfg = cachedConfig?.models ?? modelConfig;
    if (!cfg) return;
    try {
      await invalidate();

      // Capacity coverage only drives the warning banner, so keep it off the
      // critical path for rendering the model table.
      const coverageRequestId = ++capacityCoverageRequestIdRef.current;
      setCapacityCoverage(null);
      void modelService
        .getCapacityCoverage()
        .then((coverage) => {
          if (coverageRequestId === capacityCoverageRequestIdRef.current) {
            setCapacityCoverage(coverage);
          }
        })
        .catch((error) => {
          log.warn("Failed to apply model capacity coverage:", error);
        });

      const allModels = await modelService.getAllModels();
      setModels(allModels);

      const exists = (
        disp: string,
        typeChecker: (m: ModelOption) => boolean
      ) =>
        disp
          ? allModels.some((m) => m.displayName === disp && typeChecker(m))
          : true;

      if (refreshAgentQueries) {
        await queryClient.invalidateQueries({ queryKey: ["agents"] });
      }

      // Load selected models from configuration and check if models still exist
      const llmMain = cfg.llm.displayName;
      const llmMainExists = exists(llmMain, (m) => m.type === MODEL_TYPES.LLM);
      const embedding = cfg.embedding.displayName;
      const embeddingExists = exists(
        embedding,
        (m) => m.type === MODEL_TYPES.EMBEDDING
      );
      const multiEmbedding = cfg.multiEmbedding.displayName;
      const multiEmbeddingExists = exists(
        multiEmbedding,
        (m) => m.type === MODEL_TYPES.MULTI_EMBEDDING
      );
      const rerank = cfg.rerank.displayName;
      const rerankExists = exists(rerank, (m) => m.type === MODEL_TYPES.RERANK);
      const vlm = cfg.vlm.displayName;
      const vlm2 = cfg.vlm2?.displayName || "";
      const vlm3 = cfg.vlm3?.displayName || "";
      const vlm4 = cfg.vlm4?.displayName || "";
      const vlmExists = exists(vlm, (m) => m.type === MODEL_TYPES.VLM);
      const vlm2Exists = exists(vlm2, (m) => m.type === MODEL_TYPES.VLM2);
      const vlm3Exists = exists(vlm3, (m) => m.type === MODEL_TYPES.VLM3);
      const vlm4Exists = exists(vlm4, (m) => m.type === MODEL_TYPES.VLM4);
      const stt = cfg.stt.displayName;
      const sttExists = exists(stt, (m) => m.type === MODEL_TYPES.STT);
      const tts = cfg.tts.displayName;
      const ttsExists = exists(tts, (m) => m.type === MODEL_TYPES.TTS);

      const updatedSelectedModels = {
        llm: { main: llmMainExists ? llmMain : "" },
        embedding: {
          embedding: embeddingExists ? embedding : "",
          multi_embedding: multiEmbeddingExists ? multiEmbedding : "",
        },
        reranker: { reranker: rerankExists ? rerank : "" },
        multimodal: {
          vlm: vlmExists ? vlm : "",
          vlm2: vlm2Exists ? vlm2 : "",
          vlm3: vlm3Exists ? vlm3 : "",
          vlm4: vlm4Exists ? vlm4 : "",
        },
        voice: { tts: ttsExists ? tts : "", stt: sttExists ? stt : "" },
      };
      setSelectedModels(updatedSelectedModels);

      const configUpdates: any = {};
      const blank = () => ({
        modelName: "",
        displayName: "",
        apiConfig: { apiKey: "", modelUrl: "" },
      });
      if (!llmMainExists && llmMain) configUpdates.llm = blank();
      if (!embeddingExists && embedding) {
        configUpdates.embedding = { ...blank(), dimension: 0 };
      }
      if (!multiEmbeddingExists && multiEmbedding) {
        configUpdates.multiEmbedding = { ...blank(), dimension: 0 };
      }
      if (!rerankExists && rerank) {
        configUpdates.rerank = { modelName: "", displayName: "" };
      }
      if (!vlmExists && vlm) {
        configUpdates.vlm = { modelName: "", displayName: "" };
      }

      if (!vlm2Exists && vlm2) {
        configUpdates.vlm2 = { modelName: "", displayName: "" };
      }

      if (!vlm3Exists && vlm3) {
        configUpdates.vlm3 = { modelName: "", displayName: "" };
      }

      if (!vlm4Exists && vlm4) {
        configUpdates.vlm4 = { modelName: "", displayName: "" };
      }
      if (!sttExists && stt) {
        configUpdates.stt = {
          modelName: "",
          displayName: "",
          modelFactory: "",
          modelAppid: "",
          accessToken: "",
        };
      }
      if (!ttsExists && tts) {
        configUpdates.tts = {
          modelName: "",
          displayName: "",
          modelFactory: "",
          modelAppid: "",
          accessToken: "",
        };
      }
      if (Object.keys(configUpdates).length > 0) {
        updateModelConfig(configUpdates);
        scheduleAutoSave();
      }

      const hasConfiguredModels =
        !!cfg.llm.modelName ||
        !!cfg.embedding.modelName ||
        !!cfg.multiEmbedding.modelName ||
        !!cfg.rerank.modelName ||
        !!cfg.vlm.modelName ||
        !!cfg.vlm2?.modelName ||
        !!cfg.vlm3?.modelName ||
        !!cfg.vlm4?.modelName ||
        !!cfg.tts.modelName ||
        !!cfg.stt.modelName;

      if (allModels.length > 0 && hasConfiguredModels && !skipVerify) {
        verifyModelsInternal(allModels, updatedSelectedModels);
      }
    } catch (error) {
      log.error(t("cfg.error.loadList"), error);
      message.error(t("cfg.error.loadListFailed"));
    }
  };

  /* ------------------ Verify models ------------------ */
  const verifyModelsInternal = async (
    allModels: ModelOption[],
    modelsToCheck?: Record<string, Record<string, string>>
  ) => {
    if (isVerifying) return;
    if (allModels.length === 0) return;
    const currentSelectedModels: Record<
      string,
      Record<string, string>
    > = modelsToCheck || structuredClone(selectedModels);

    let hasSelectedModels = false;
    outer: for (const cat in currentSelectedModels) {
      for (const opt in currentSelectedModels[cat]) {
        if (currentSelectedModels[cat][opt]) {
          hasSelectedModels = true;
          break outer;
        }
      }
    }

    // If no selected models in state, try to get directly from configuration
    if (!hasSelectedModels) {
      if (!modelConfig) return;

      // Directly check if each model exists in configuration
      const hasLlmMain = !!modelConfig.llm.modelName;
      const hasEmbedding = !!modelConfig.embedding.modelName;
      const hasReranker = !!modelConfig.rerank.modelName;
      const hasVlm = !!modelConfig.vlm.modelName;
      const hasVlm2 = !!modelConfig.vlm2?.modelName;
      const hasVlm3 = !!modelConfig.vlm3?.modelName;
      const hasVlm4 = !!modelConfig.vlm4?.modelName;
      const hasTts = !!modelConfig.tts.modelName;
      const hasStt = !!modelConfig.stt.modelName;

      hasSelectedModels =
        hasLlmMain ||
        hasEmbedding ||
        hasReranker ||
        hasVlm ||
        hasVlm2 ||
        hasVlm3 ||
        hasVlm4 ||
        hasTts ||
        hasStt;

      if (hasSelectedModels) {
        currentSelectedModels.llm.main = modelConfig.llm.modelName;
        currentSelectedModels.embedding.embedding =
          modelConfig.embedding.modelName;
        currentSelectedModels.embedding.multi_embedding =
          modelConfig.multiEmbedding.modelName || "";
        currentSelectedModels.reranker.reranker = modelConfig.rerank.modelName;
        currentSelectedModels.multimodal.vlm = modelConfig.vlm.modelName;
        currentSelectedModels.multimodal.vlm2 =
          modelConfig.vlm2?.modelName || "";
        currentSelectedModels.multimodal.vlm3 =
          modelConfig.vlm3?.modelName || "";
        currentSelectedModels.multimodal.vlm4 =
          modelConfig.vlm4?.modelName || "";
        currentSelectedModels.voice.tts = modelConfig.tts.modelName;
        currentSelectedModels.voice.stt = modelConfig.stt.modelName;
      } else {
        return;
      }
    }

    setIsVerifying(true);
    const abortController = new AbortController();
    const signal = abortController.signal;
    abortControllerRef.current = abortController;

    try {
      const modelsToVerify: Array<{
        category: string;
        optionId: string;
        modelName: string;
        modelType: ModelType;
      }> = [];
      for (const [category, options] of Object.entries(currentSelectedModels)) {
        for (const [optionId, modelName] of Object.entries(options)) {
          if (!modelName) continue;
          let modelType = category as ModelType;
          if (category === "voice") {
            modelType =
              optionId === MODEL_TYPES.TTS ? MODEL_TYPES.TTS : MODEL_TYPES.STT;
          } else if (category === "reranker") {
            modelType = MODEL_TYPES.RERANK;
          } else if (category === "multimodal") {
            modelType = optionId as ModelType;
          } else if (category === MODEL_TYPES.EMBEDDING) {
            modelType =
              optionId === MODEL_TYPES.MULTI_EMBEDDING
                ? MODEL_TYPES.MULTI_EMBEDDING
                : MODEL_TYPES.EMBEDDING;
          }
          modelsToVerify.push({
            category,
            optionId,
            modelName,
            modelType,
          });
          updateModelStatus(modelName, modelType, MODEL_STATUS.CHECKING);
        }
      }
      if (modelsToVerify.length === 0) {
        message.info({
          content: t("modelConfig.message.noModelToVerify", {
            defaultValue: "没有需要验证的模型",
          }),
          key: "verifying",
        });
        setIsVerifying(false);
        abortControllerRef.current = null;
        return;
      }
      await Promise.all(
        modelsToVerify.map(async ({ modelName, modelType }) => {
          try {
            const isConnected = await modelService.verifyCustomModel(
              modelName,
              modelType,
              signal
            );
            updateModelStatus(
              modelName,
              modelType,
              isConnected ? MODEL_STATUS.AVAILABLE : MODEL_STATUS.UNAVAILABLE
            );
          } catch (error: any) {
            if (error.name === "AbortError") return;
            log.error(`Failed to verify model ${modelName}:`, error);
            updateModelStatus(modelName, modelType, MODEL_STATUS.UNAVAILABLE);
          }
        })
      );
    } catch (error: any) {
      if (error.name === "AbortError") {
        log.log("Verification cancelled by user");
        return;
      }
      log.error("Model verification failed:", error);
    } finally {
      if (!signal.aborted) {
        setIsVerifying(false);
        abortControllerRef.current = null;
      }
    }
  };

  const verifyModels = async () => {
    // v0 redesign: the button lives in the 默认配置 section, so it verifies
    // only the models currently occupying default slots — not the whole
    // library. Non-default models are checked per-row via the list action.
    await verifyModelsInternal(models);
  };

  /* ------------------ Sync ModelEngine ------------------ */
  const handleSyncModels = () => {
    setIsAddModalV2Open(true);
  };

  /* ------------------ Verify single ------------------ */
  const verifyOneModel = async (displayName: string, modelType: ModelType) => {
    if (!displayName) return;
    updateModelStatus(displayName, modelType, MODEL_STATUS.CHECKING);
    if (throttleTimerRef.current) clearTimeout(throttleTimerRef.current);
    throttleTimerRef.current = setTimeout(async () => {
      try {
        const isConnected = await modelService.verifyCustomModel(
          displayName,
          modelType
        );
        updateModelStatus(
          displayName,
          modelType,
          isConnected ? MODEL_STATUS.AVAILABLE : MODEL_STATUS.UNAVAILABLE
        );
      } catch (error: any) {
        log.error(
          t("modelConfig.error.verifyCustomModel", { model: displayName }),
          error
        );
        updateModelStatus(displayName, modelType, MODEL_STATUS.UNAVAILABLE);
      } finally {
        throttleTimerRef.current = null;
      }
    }, 1000);
  };

  /* ------------------ Apply change ------------------ */
  const applyModelChange = async (
    category: string,
    option: string,
    displayName: string
  ) => {
    setSelectedModels((prev) => ({
      ...prev,
      [category]: { ...prev[category], [option]: displayName },
    }));
    if (displayName) {
      setErrorFields((prev) => ({
        ...prev,
        [`${category}.${option}`]: false,
      }));
    }
    let modelType = category as ModelType;
    if (category === "voice") {
      modelType =
        option === MODEL_TYPES.TTS ? MODEL_TYPES.TTS : MODEL_TYPES.STT;
    } else if (category === "reranker") {
      modelType = MODEL_TYPES.RERANK;
    } else if (category === "multimodal") {
      modelType = option as ModelType;
    } else if (category === MODEL_TYPES.EMBEDDING) {
      modelType =
        option === MODEL_TYPES.MULTI_EMBEDDING
          ? MODEL_TYPES.MULTI_EMBEDDING
          : MODEL_TYPES.EMBEDDING;
    }
    const modelInfo = models.find(
      (m) => m.displayName === displayName && m.type === modelType
    );
    if (modelInfo && !modelInfo.connect_status) {
      updateModelStatus(displayName, modelType, MODEL_STATUS.UNCHECKED);
    }
    let configKey = category;
    if (
      category === MODEL_TYPES.EMBEDDING &&
      option === MODEL_TYPES.MULTI_EMBEDDING
    ) {
      configKey = "multiEmbedding";
    } else if (category === "multimodal") {
      configKey = option;
    } else if (category === "reranker") {
      configKey = MODEL_TYPES.RERANK;
    } else if (category === "voice" && option === "tts") {
      configKey = MODEL_TYPES.TTS;
    } else if (category === "voice" && option === "stt") {
      configKey = MODEL_TYPES.STT;
    }
    const apiConfig = modelInfo?.apiKey
      ? { apiKey: modelInfo.apiKey, modelUrl: modelInfo.apiUrl || "" }
      : { apiKey: "", modelUrl: "" };
    let configUpdate: any;
    if (!displayName) {
      if (configKey === "embedding" || configKey === "multiEmbedding") {
        configUpdate = {
          [configKey]: {
            modelName: "",
            displayName: "",
            apiConfig: { apiKey: "", modelUrl: "" },
            dimension: 0,
          },
        };
      } else {
        configUpdate = {
          [configKey]: {
            modelName: "",
            displayName: "",
            apiConfig: { apiKey: "", modelUrl: "" },
          },
        };
      }
      if (configKey === MODEL_TYPES.STT || configKey === MODEL_TYPES.TTS) {
        configUpdate[configKey].modelFactory = "";
        configUpdate[configKey].modelAppid = "";
        configUpdate[configKey].accessToken = "";
      }
    } else {
      configUpdate = {
        [configKey]: {
          modelName: modelInfo?.name || "",
          displayName,
          apiConfig,
        },
      };
      if (configKey === "embedding" || configKey === "multiEmbedding") {
        configUpdate[configKey].dimension = modelInfo?.maxTokens || 0;
      }
      if (configKey === MODEL_TYPES.STT || configKey === MODEL_TYPES.TTS) {
        configUpdate[configKey].modelFactory = modelInfo?.source || "";
        configUpdate[configKey].modelAppid = modelInfo?.modelAppid || "";
        configUpdate[configKey].accessToken = modelInfo?.accessToken || "";
      }
    }
    if (configKey === "embedding" || configKey === "multiEmbedding") {
      configUpdate[configKey].dimension = modelInfo?.maxTokens || undefined;
    }
    updateModelConfig(configUpdate);
    if (displayName) {
      await verifyOneModel(displayName, modelType);
    }
    scheduleAutoSave();
  };

  /* ------------------ Handle model change (w/ confirm for embedding) ------------------ */
  const handleModelChange = async (
    category: string,
    option: string,
    displayName: string,
    skipConfirm: boolean = false
  ) => {
    const isEmbeddingCategory =
      category === MODEL_TYPES.EMBEDDING &&
      (option === MODEL_TYPES.EMBEDDING ||
        option === MODEL_TYPES.MULTI_EMBEDDING);
    if (isEmbeddingCategory && !skipConfirm) {
      const currentValue = selectedModels[category]?.[option] || "";
      if (currentValue && currentValue !== displayName) {
        const memoryEnabled =
          option === MODEL_TYPES.EMBEDDING
            ? (await loadMemoryConfig()).memoryEnabled
            : false;
        confirm({
          title: t("embedding.modifyWarningModal.title"),
          content: (
            <div className="py-2">
              <div className="text-sm leading-6">
                {t(
                  memoryEnabled
                    ? "embedding.memoryModelSwitchWarningModal.content"
                    : "embedding.modifyWarningModal.content"
                )}
              </div>
            </div>
          ),
          okText: t("embedding.modifyWarningModal.ok_proceed"),
          cancelText: t("common.cancel"),
          danger: false,
          onOk: async () => {
            await applyModelChange(category, option, displayName);
          },
        });
        return;
      }
      if (currentValue === displayName) return;
    }
    await applyModelChange(category, option, displayName);
  };

  /* ------------------ Update model status (UI only) ------------------ */
  const updateModelStatus = (
    displayName: string,
    modelType: string,
    status: ModelConnectStatus
  ) => {
    setModels((prev) => {
      const idx = prev.findIndex(
        (m) => m.displayName === displayName && m.type === modelType
      );
      if (idx === -1) return prev;
      const updated = [...prev];
      updated[idx] = { ...updated[idx], connect_status: status };
      return updated;
    });
  };

  /* ------------------ Select options ------------------ */

  /* ==================== v2.6.1 redesign: derived slot data ==================== */
  const modelSlots = useMemo(() => buildModelSlots(t), [t]);
  const configuredSlotCount = useMemo(
    () =>
      Object.values(selectedModels).reduce(
        (acc, opts) => acc + Object.values(opts).filter(Boolean).length,
        0
      ),
    [selectedModels]
  );

  /* ==================== Render ==================== */
  return (
    <>
      <div className="flex w-full flex-col gap-8">
        {/* ========== Section 1: 默认配置 (inline slots, v0 redesign) ========== */}
        <section>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-baseline gap-2">
              <h3 className="text-base font-semibold text-foreground">
                {t("modelConfig.section.defaultConfig", {
                  defaultValue: "默认配置",
                })}
              </h3>
              <span className="text-xs text-muted-foreground">
                {t("modelConfig.section.defaultConfigHint", {
                  defaultValue: "未配置模型时默认选用以下模型",
                })}
              </span>
              <Tag color="blue" className="m-0 tabular-nums">
                {t("modelConfig.section.configuredCount", {
                  configured: configuredSlotCount,
                  total: modelSlots.length,
                  defaultValue: `已配置 ${configuredSlotCount}/${modelSlots.length}`,
                })}
              </Tag>
            </div>
            <Button
              size="middle"
              icon={<ShieldCheck size={16} />}
              onClick={verifyModels}
              loading={isVerifying}
            >
              <span className="button-text-full">
                {t("modelConfig.button.checkConnectivity")}
              </span>
            </Button>
          </div>

          <Card styles={{ body: { padding: 20 } }}>
            {/* Legend */}
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b pb-4 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">
                {t("modelConfig.section.legendTitle", {
                  defaultValue: "配置说明",
                })}
              </span>
              <span>
                {t("modelConfig.section.legendRequired", {
                  defaultValue: "标注（必填）的模型系统运行必须配置",
                })}
              </span>
              <span>
                {t("modelConfig.section.legendRecommended", {
                  defaultValue: "标注（推荐）的模型按需推荐配置",
                })}
              </span>
              <span className="flex items-center gap-1.5">
                <span className="size-2 rounded-full bg-emerald-500" />
                {t("modelConfig.section.legendDot", {
                  defaultValue: "圆点代表已连通",
                })}
              </span>
            </div>

            {/* Flat slot grid (replaces the DefaultModelDialog) */}
            <div className="grid grid-cols-1 gap-x-8 gap-y-5 pt-5 md:grid-cols-2 xl:grid-cols-3">
              {modelSlots.map((slot) => (
                <ModelSlotSelect
                  key={slot.fieldKey}
                  slot={slot}
                  models={models}
                  value={selectedModels[slot.category]?.[slot.option] ?? ""}
                  error={!!errorFields[slot.fieldKey]}
                  onChange={(displayName) =>
                    handleModelChange(slot.category, slot.option, displayName)
                  }
                />
              ))}
            </div>
          </Card>
        </section>

        {/* ========== Section 2: 模型库 ========== */}
        <section className="flex w-full flex-col gap-3">
          <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-baseline gap-2">
              <h3 className="text-base font-semibold text-foreground">
                {t("modelConfig.section.modelLibrary", {
                  defaultValue: "模型库",
                })}
              </h3>
              <span className="text-xs text-muted-foreground">
                {t("modelConfig.section.modelLibraryHint", {
                  defaultValue: "管理已添加的全部模型",
                })}
              </span>
              <Tag color="geekblue" className="m-0 tabular-nums">
                {models.length}
              </Tag>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {modelEngineEnable && (
                <Button
                  size="middle"
                  onClick={handleSyncModels}
                  icon={<RefreshCw size={16} />}
                >
                  <span className="button-text-full">
                    {t("modelConfig.button.syncModelEngine")}
                  </span>
                </Button>
              )}
              <Button
                size="middle"
                icon={<Pencil size={14} />}
                onClick={() => {
                  setManagerMode("editGroup");
                  setIsManagerOpen(true);
                }}
              >
                {t("modelConfig.batchEdit.title", { defaultValue: "批量修改" })}
              </Button>
              <Button
                size="middle"
                danger
                icon={<Trash2 size={14} />}
                onClick={() => {
                  setManagerMode("deleteGroup");
                  setIsManagerOpen(true);
                }}
              >
                {t("modelConfig.batchDelete.title", {
                  defaultValue: "批量删除",
                })}
              </Button>
              {/* v2.6.0: new Add Model dialog with Tabs (batch import + custom access) */}
              <Can permission="model:create">
                <Button
                  type="primary"
                  size="middle"
                  icon={<Plus size={16} />}
                  onClick={() => setIsAddModalV2Open(true)}
                >
                  <span className="button-text-full">
                    {t("modelConfig.button.addModel", {
                      defaultValue: "添加模型",
                    })}
                  </span>
                </Button>
              </Can>
            </div>
          </div>

          {/* -------------------- Capacity coverage warning -------------------- */}
          {capacityCoverage && capacityCoverage.bareCount > 0 && (
            <Alert
              type="warning"
              showIcon
              title={t("modelConfig.capacityCoverage.warning", {
                bareCount: capacityCoverage.bareCount,
                total: capacityCoverage.totalLlmVlm,
              })}
              description={t("modelConfig.capacityCoverage.description", {
                suggestionCount: capacityCoverage.bareModels.filter(
                  (m) => m.suggestionAvailable
                ).length,
              })}
            />
          )}

          {/* -------------------- Model library list (v0 redesign) -------------------- */}
          <ModelLibraryList
            models={models}
            defaultSlotMap={defaultSlotMap}
            onCheck={verifyOneModel}
            onEdit={handleCardEdit}
            onDelete={handleCardDelete}
          />
        </section>

        {/* -------------------- Dialogs -------------------- */}
        {/* v2.6.0: new Add Model dialog (Tabs: batch import / custom access) */}
        <ModelAddDialogV2
          isOpen={isAddModalV2Open}
          onClose={() => setIsAddModalV2Open(false)}
          onSuccess={async (newModel) => {
            // Invalidate FIRST so the refetch completes before loadModelLists
            // reads the cache (a model create may have auto-configured
            // default-model slots that must be reflected immediately).
            await queryClient.invalidateQueries({ queryKey: CONFIG_QUERY_KEY });
            await loadModelLists(true);
            message.success(t("modelConfig.message.addSuccess"));
            if (newModel && newModel.name && newModel.type) {
              setTimeout(() => {
                verifyOneModel(newModel.name, newModel.type);
              }, 100);
            }
          }}
        />

        {/* v2.6.1 redesign: batch edit / delete by connection group */}
        <ModelManagerDialog
          open={isManagerOpen}
          mode={managerMode}
          models={models}
          onClose={() => setIsManagerOpen(false)}
          onUpdateGroup={handleBatchUpdateGroup}
          onDeleteModels={handleBatchDeleteModels}
          updating={batchUpdating}
          deleting={batchDeleting}
        />

        <ModelAddDialogV2
          isOpen={!!editingCardModel}
          model={editingCardModel}
          onClose={() => setEditingCardModel(null)}
          onConnectivityChange={(displayName, modelType, status) => {
            // Refresh the list row's connect_status in place when the edit
            // dialog's connectivity probe finishes, so the list doesn't show
            // a stale status from the last loadModelLists.
            setModels((prev) =>
              prev.map((m) =>
                m.displayName === displayName && m.type === modelType
                  ? { ...m, connect_status: status }
                  : m
              )
            );
          }}
          onSuccess={async () => {
            setEditingCardModel(null);
            await loadModelLists(true);
          }}
        />
      </div>
    </>
  );
});
