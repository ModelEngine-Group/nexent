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
import { useTranslation } from "react-i18next";

import {
  Alert,
  Button,
  Col,
  Row,
  App,
  Input,
  Select,
  Pagination,
  Empty,
  Tooltip,
  Tag,
} from "antd";
import {
  Plus,
  ShieldCheck,
  RefreshCw,
  PenLine,
  SlidersHorizontal,
} from "lucide-react";
import { ExclamationCircleFilled } from "@ant-design/icons";

import {
  MODEL_TYPES,
  MODEL_STATUS,
  LAYOUT_CONFIG,
  CARD_THEMES,
  MODEL_SOURCES,
} from "@/const/modelConfig";
import { useConfig } from "@/hooks/useConfig";
import { modelService } from "@/services/modelService";
import { loadMemoryConfig } from "@/services/memoryService";
import {
  CapacityCoverage,
  ModelOption,
  ModelType,
  ModelSource,
  ModelConnectStatus,
} from "@/types/modelConfig";
import log from "@/lib/logger";

import { ModelAddDialog } from "./model/ModelAddDialog";
import { ModelDeleteDialog } from "./model/ModelDeleteDialog";
import { ModelEditDialog } from "./model/ModelEditDialog";
import { ModelItemCard } from "./model/ModelItemCard";
import { DefaultModelDialog } from "./model/DefaultModelDialog";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { Can } from "@/components/permission/Can";
import { ModelError } from "@/services/modelService";

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

  const { skipVerification = false } = props;
  const { modelConfig, updateModelConfig, appConfig, saveConfig } = useConfig();
  const modelEngineEnable = appConfig?.modelEngineEnabled ?? false;

  const { confirm } = useConfirmModal();

  /* ------------------ State ------------------ */
  const [models, setModels] = useState<ModelOption[]>([]);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [addModalDefaultIsBatch, setAddModalDefaultIsBatch] =
    useState<boolean>(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const [capacityCoverage, setCapacityCoverage] =
    useState<CapacityCoverage | null>(null);

  // Default model dialog
  const [isDefaultDialogOpen, setIsDefaultDialogOpen] = useState(false);
  // Single model edit dialog
  const [editingCardModel, setEditingCardModel] = useState<ModelOption | null>(
    null
  );

  // Filter & pagination
  const [searchKeyword, setSearchKeyword] = useState<string>("");
  const [filterType, setFilterType] = useState<ModelType | "all">("all");
  const [filterSource, setFilterSource] = useState<ModelSource | "all">("all");
  const [filterStatus, setFilterStatus] = useState<
    ModelConnectStatus | "all"
  >("all");
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(12);

  // Error state management
  const [errorFields, setErrorFields] = useState<{ [key: string]: boolean }>({
    "llm.main": false,
    "embedding.embedding": false,
    "embedding.multi_embedding": false,
  });

  const abortControllerRef = useRef<AbortController | null>(null);
  const throttleTimerRef = useRef<NodeJS.Timeout | null>(null);
  const saveTimerRef = useRef<NodeJS.Timeout | null>(null);

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
    multimodal: { vlm: "", vlm2: "", vlm3: "" },
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
  useEffect(() => {
    const handleHighlightMissingField = (event: any) => {
      const { field } = event.detail;
      if (field === "llm.main" || field === "embedding.embedding") {
        setErrorFields((prev) => ({ ...prev, [field]: true }));
        setIsDefaultDialogOpen(true);
        setTimeout(() => {
          const el = document.querySelector<HTMLElement>(
            `[data-error-field="${field}"]`
          );
          el?.scrollIntoView({ behavior: "smooth", block: "center" });
        }, 100);
      }
    };
    window.addEventListener("highlightMissingField", handleHighlightMissingField);
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

  /* ------------------ Derived: filter & pagination ------------------ */
  const filteredModels = useMemo<ModelOption[]>(() => {
    const kw = searchKeyword.trim().toLowerCase();
    return models.filter((m) => {
      if (filterType !== "all" && m.type !== filterType) return false;
      if (filterSource !== "all" && m.source !== filterSource) return false;
      if (filterStatus !== "all" && m.connect_status !== filterStatus)
        return false;
      if (kw) {
        const hay = [m.name, m.displayName, m.apiUrl, m.apiKey]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!hay.includes(kw)) return false;
      }
      return true;
    });
  }, [models, searchKeyword, filterType, filterSource, filterStatus]);

  const pagedModels = useMemo<ModelOption[]>(() => {
    const start = (page - 1) * pageSize;
    return filteredModels.slice(start, start + pageSize);
  }, [filteredModels, page, pageSize]);

  // Auto jump to page 1 when filters change
  useEffect(() => {
    setPage(1);
  }, [searchKeyword, filterType, filterSource, filterStatus, pageSize]);

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

  /* ------------------ Load model lists ------------------ */
  const loadModelLists = async (skipVerify: boolean = false) => {
    if (!modelConfig) return;
    try {
      const [allModels, coverage] = await Promise.all([
        modelService.getAllModels(),
        modelService.getCapacityCoverage(),
      ]);
      setModels(allModels);
      setCapacityCoverage(coverage);

      const exists = (
        disp: string,
        typeChecker: (m: ModelOption) => boolean
      ) =>
        disp
          ? allModels.some((m) => m.displayName === disp && typeChecker(m))
          : true;

      const llmMain = modelConfig.llm.displayName;
      const llmMainExists = exists(llmMain, (m) => m.type === MODEL_TYPES.LLM);
      const embedding = modelConfig.embedding.displayName;
      const embeddingExists = exists(embedding, (m) =>
        m.type === MODEL_TYPES.EMBEDDING
      );
      const multiEmbedding = modelConfig.multiEmbedding.displayName;
      const multiEmbeddingExists = exists(multiEmbedding, (m) =>
        m.type === MODEL_TYPES.MULTI_EMBEDDING
      );
      const rerank = modelConfig.rerank.displayName;
      const rerankExists = exists(rerank, (m) => m.type === MODEL_TYPES.RERANK);
      const vlm = modelConfig.vlm.displayName;
      const vlm2 = modelConfig.vlm2?.displayName || "";
      const vlm3 = modelConfig.vlm3?.displayName || "";
      const vlmExists = exists(vlm, (m) => m.type === MODEL_TYPES.VLM);
      const vlm2Exists = exists(vlm2, (m) => m.type === MODEL_TYPES.VLM2);
      const vlm3Exists = exists(vlm3, (m) => m.type === MODEL_TYPES.VLM3);
      const stt = modelConfig.stt.displayName;
      const sttExists = exists(stt, (m) => m.type === MODEL_TYPES.STT);
      const tts = modelConfig.tts.displayName;
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
      if (!vlmExists && vlm) configUpdates.vlm = blank();
      if (!vlm2Exists && vlm2) configUpdates.vlm2 = blank();
      if (!vlm3Exists && vlm3) configUpdates.vlm3 = blank();
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
        !!modelConfig.llm.modelName ||
        !!modelConfig.embedding.modelName ||
        !!modelConfig.multiEmbedding.modelName ||
        !!modelConfig.rerank.modelName ||
        !!modelConfig.vlm.modelName ||
        !!modelConfig.vlm2?.modelName ||
        !!modelConfig.vlm3?.modelName ||
        !!modelConfig.tts.modelName ||
        !!modelConfig.stt.modelName;

      if (allModels.length > 0 && hasConfiguredModels && !skipVerify) {
        verifyModelsInternal(allModels, updatedSelectedModels);
      }
    } catch (error) {
      log.error(t("modelConfig.error.loadList"), error);
      message.error(t("modelConfig.error.loadListFailed"));
    }
  };

  /* ------------------ Verify models ------------------ */
  const verifyModelsInternal = async (
    allModels: ModelOption[],
    modelsToCheck?: Record<string, Record<string, string>>
  ) => {
    if (isVerifying) return;
    if (allModels.length === 0) return;
    const currentSelectedModels =
      modelsToCheck || JSON.parse(JSON.stringify(selectedModels));

    let hasSelectedModels = false;
    outer: for (const cat in currentSelectedModels) {
      for (const opt in currentSelectedModels[cat]) {
        if (currentSelectedModels[cat][opt]) {
          hasSelectedModels = true;
          break outer;
        }
      }
    }
    if (!hasSelectedModels && modelConfig) {
      const has =
        !!modelConfig.llm.modelName ||
        !!modelConfig.embedding.modelName ||
        !!modelConfig.multiEmbedding.modelName ||
        !!modelConfig.rerank.modelName ||
        !!modelConfig.vlm.modelName ||
        !!modelConfig.vlm2?.modelName ||
        !!modelConfig.vlm3?.modelName ||
        !!modelConfig.tts.modelName ||
        !!modelConfig.stt.modelName;
      if (!has) return;
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
      currentSelectedModels.voice.tts = modelConfig.tts.modelName;
      currentSelectedModels.voice.stt = modelConfig.stt.modelName;
    } else if (!hasSelectedModels) {
      return;
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
    if (isVerifying || models.length === 0) return;
    await verifyModelsInternal(models, selectedModels);
  };

  /* ------------------ Sync ModelEngine ------------------ */
  const handleSyncModels = () => {
    setAddModalDefaultIsBatch(true);
    setIsAddModalOpen(true);
  };

  /* ------------------ Verify single ------------------ */
  const verifyOneModel = async (
    displayName: string,
    modelType: ModelType
  ) => {
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

  /* ------------------ Card-level edit / delete ------------------ */
  const handleCardEdit = useCallback(
    (model: ModelOption) => {
      setEditingCardModel(model);
    },
    []
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
          // Clear default selections if they reference this model
          const disp = model.displayName;
          let configUpdates: any = {};
          const selectedPairs: [string, string, string][] = [
            ["llm", "main", "llm"],
            ["embedding", "embedding", "embedding"],
            ["embedding", "multi_embedding", "multiEmbedding"],
            ["reranker", "reranker", "rerank"],
            ["multimodal", "vlm", "vlm"],
            ["multimodal", "vlm2", "vlm2"],
            ["multimodal", "vlm3", "vlm3"],
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
            if (selectedModels[cat]?.[opt] === disp) {
              setSelectedModels((p) => ({
                ...p,
                [cat]: { ...p[cat], [opt]: "" },
              }));
              if (cfgKey === "embedding" || cfgKey === "multiEmbedding") {
                configUpdates[cfgKey] = {
                  ...blank(false),
                  dimension: 0,
                };
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
          message.success(
            t("model.message.deleteSuccess", {
              name: disp,
              defaultValue: `已删除：${disp}`,
            })
          );
          await loadModelLists(true);
        },
      });
    },
    [message, modal, modelConfig, selectedModels, t, updateModelConfig]
  );

  /* ------------------ Select options ------------------ */
  const modelTypeOptions = useMemo(() => {
    const list: { value: ModelType | "all"; label: string }[] = [
      { value: "all", label: t("model.filter.allTypes", { defaultValue: "全部类型" }) },
    ];
    const map: [ModelType, string][] = [
      [MODEL_TYPES.LLM, t("model.type.llm", { defaultValue: "大语言模型" })],
      [MODEL_TYPES.EMBEDDING, t("model.type.embedding", { defaultValue: "文本嵌入" })],
      [
        MODEL_TYPES.MULTI_EMBEDDING,
        t("model.type.multiEmbedding", { defaultValue: "多模态嵌入" }),
      ],
      [MODEL_TYPES.RERANK, t("model.type.rerank", { defaultValue: "重排" })],
      [MODEL_TYPES.VLM, t("model.type.imageUnderstanding", { defaultValue: "图像理解" })],
      [MODEL_TYPES.VLM2, t("model.type.imageGeneration", { defaultValue: "图像生成" })],
      [MODEL_TYPES.VLM3, t("model.type.videoUnderstanding", { defaultValue: "视频理解" })],
      [MODEL_TYPES.STT, t("model.type.stt", { defaultValue: "语音识别" })],
      [MODEL_TYPES.TTS, t("model.type.tts", { defaultValue: "语音合成" })],
    ];
    map.forEach(([v, l]) => list.push({ value: v, label: l }));
    return list;
  }, [t]);

  const modelSourceOptions = useMemo(() => {
    const list: { value: ModelSource | "all"; label: string }[] = [
      { value: "all", label: t("model.filter.allSources", { defaultValue: "全部来源" }) },
    ];
    const sMap: [ModelSource, string][] = [
      [MODEL_SOURCES.MODELENGINE, "ModelEngine"],
      [MODEL_SOURCES.SILICON, "SiliconFlow"],
      [MODEL_SOURCES.OPENAI, "OpenAI"],
      [MODEL_SOURCES.OPENAI_API_COMPATIBLE, "OpenAI-API-Compatible"],
      [MODEL_SOURCES.CUSTOM, t("model.source.custom", { defaultValue: "自定义" })],
      [MODEL_SOURCES.DASHSCOPE, "DashScope"],
      [MODEL_SOURCES.TOKENPONY, "TokenPony"],
      [MODEL_SOURCES.VOLCENGINE, "VolcEngine"],
    ];
    sMap.forEach(([v, l]) => list.push({ value: v, label: l }));
    return list;
  }, [t]);

  const statusOptions = useMemo<
    { value: ModelConnectStatus | "all"; label: string }[]
  >(
    () => [
      {
        value: "all",
        label: t("model.filter.allStatus", { defaultValue: "全部状态" }),
      },
      {
        value: MODEL_STATUS.AVAILABLE,
        label: t("model.status.available", { defaultValue: "可用" }),
      },
      {
        value: MODEL_STATUS.UNAVAILABLE,
        label: t("model.status.unavailable", { defaultValue: "不可用" }),
      },
      {
        value: MODEL_STATUS.CHECKING,
        label: t("model.status.detecting", { defaultValue: "检测中" }),
      },
      {
        value: MODEL_STATUS.UNCHECKED,
        label: t("model.status.notDetected", { defaultValue: "未检测" }),
      },
    ],
    [t]
  );

  /* ==================== Render ==================== */
  return (
    <>
      <div
        style={{
          width: "100%",
          margin: "0 auto",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        {/* -------------------- Button row -------------------- */}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "flex-start",
            gap: 8,
            paddingRight: 12,
            paddingTop: 16,
            marginLeft: 4,
            minHeight: LAYOUT_CONFIG.BUTTON_AREA_HEIGHT,
            marginBottom: 16,
          }}
        >
          <Button
            type="primary"
            size="middle"
            icon={<SlidersHorizontal size={16} />}
            onClick={() => setIsDefaultDialogOpen(true)}
            ghost
          >
            <span className="button-text-full">
              {t("modelConfig.button.setDefaultModels", {
                defaultValue: "设置默认模型",
              })}
            </span>
          </Button>
          {modelEngineEnable && (
            <Button
              type="primary"
              size="middle"
              onClick={handleSyncModels}
              icon={<RefreshCw size={16} />}
            >
              <span className="button-text-full">
                {t("modelConfig.button.syncModelEngine")}
              </span>
            </Button>
          )}
          <Can permission="model:create">
            <Button
              type="primary"
              size="middle"
              icon={<Plus size={16} />}
              onClick={() => {
                setAddModalDefaultIsBatch(false);
                setIsAddModalOpen(true);
              }}
            >
              <span className="button-text-full">
                {t("modelConfig.button.addCustomModel")}
              </span>
            </Button>
          </Can>
          <Can permission="model:update">
            <Button
              type="primary"
              size="middle"
              icon={<PenLine size={16} />}
              onClick={() => setIsDeleteModalOpen(true)}
            >
              <span className="button-text-full">
                {t("modelConfig.button.editCustomModel")}
              </span>
            </Button>
          </Can>
          <Button
            type="primary"
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

        {/* -------------------- Capacity coverage warning -------------------- */}
        {capacityCoverage && capacityCoverage.bareCount > 0 && (
          <Alert
            type="warning"
            showIcon
            message={t("modelConfig.capacityCoverage.warning", {
              bareCount: capacityCoverage.bareCount,
              total: capacityCoverage.totalLlmVlm,
            })}
            description={t("modelConfig.capacityCoverage.description", {
              suggestionCount: capacityCoverage.bareModels.filter(
                (m) => m.suggestionAvailable
              ).length,
            })}
            action={
              <Button size="small" onClick={() => setIsDeleteModalOpen(true)}>
                {t("modelConfig.capacityCoverage.manage")}
              </Button>
            }
          />
        )}

        {/* -------------------- Filter bar -------------------- */}
        <Row gutter={[12, 8]} style={{ padding: "0 4px" }} align="middle">
          <Col xs={24} md={8} lg={8}>
            <Input.Search
              allowClear
              enterButton
              placeholder={t("modelConfig.search.placeholder", {
                defaultValue: "搜索模型名 / 自定义名称 / API 地址",
              })}
              value={searchKeyword}
              onChange={(e) => setSearchKeyword(e.target.value)}
              onSearch={(v) => setSearchKeyword(v)}
            />
          </Col>
          <Col xs={12} sm={8} md={5} lg={5}>
            <Select
              style={{ width: "100%" }}
              value={filterType}
              onChange={(v) => setFilterType(v as ModelType | "all")}
              options={modelTypeOptions}
            />
          </Col>
          <Col xs={12} sm={8} md={5} lg={5}>
            <Select
              style={{ width: "100%" }}
              value={filterSource}
              onChange={(v) => setFilterSource(v as ModelSource | "all")}
              options={modelSourceOptions}
            />
          </Col>
          <Col xs={12} sm={8} md={5} lg={5}>
            <Select
              style={{ width: "100%" }}
              value={filterStatus}
              onChange={(v) =>
                setFilterStatus(v as ModelConnectStatus | "all")
              }
              options={statusOptions}
            />
          </Col>
          <Col
            xs={12}
            sm={24}
            md={1}
            lg={1}
            style={{ textAlign: "right", color: "#94a3b8", fontSize: 12 }}
          >
            <Tooltip
              title={t("modelConfig.search.totalCount", {
                count: filteredModels.length,
                defaultValue: `共 ${filteredModels.length} 条匹配`,
              })}
            >
              <Tag color="geekblue" style={{ margin: 0 }}>
                {filteredModels.length}/{models.length}
              </Tag>
            </Tooltip>
          </Col>
        </Row>

        {/* -------------------- Model grid -------------------- */}
        <div
          style={{
            width: "100%",
            padding: "0 4px",
            flex: 1,
            display: "flex",
            flexDirection: "column",
            minHeight: 240,
          }}
        >
          {filteredModels.length === 0 ? (
            <div
              style={{
                flex: 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Empty
                description={t("modelConfig.list.empty", {
                  defaultValue: "暂无匹配的模型，请更换筛选条件或新增模型",
                })}
              />
            </div>
          ) : (
            <>
              <Row gutter={[12, 12]} style={{ flex: 1 }}>
                {pagedModels.map((m) => (
                  <Col
                    key={`${m.id}-${m.displayName}-${m.type}`}
                    xs={24}
                    sm={12}
                    md={8}
                    lg={6}
                    xl={6}
                  >
                    <ModelItemCard
                      model={m}
                      isDefaultFor={defaultSlotMap[m.displayName] || []}
                      onVerify={verifyOneModel}
                      onEdit={handleCardEdit}
                      onDelete={handleCardDelete}
                      canUpdate={true}
                    />
                  </Col>
                ))}
              </Row>

              <div
                style={{
                  display: "flex",
                  justifyContent: "center",
                  padding: "16px 0 8px 0",
                }}
              >
                <Pagination
                  current={page}
                  pageSize={pageSize}
                  total={filteredModels.length}
                  showSizeChanger
                  pageSizeOptions={["8", "12", "24", "48"]}
                  showTotal={(total, range) =>
                    t("modelConfig.pagination.showTotal", {
                      range0: range[0],
                      range1: range[1],
                      total,
                      defaultValue: `第 ${range[0]}-${range[1]} / 共 ${total} 条`,
                    })
                  }
                  onChange={(p, ps) => {
                    setPage(p);
                    setPageSize(ps);
                  }}
                />
              </div>
            </>
          )}
        </div>

        {/* -------------------- Dialogs -------------------- */}
        <DefaultModelDialog
          open={isDefaultDialogOpen}
          models={models}
          selectedModels={selectedModels}
          errorFields={errorFields}
          onClose={() => setIsDefaultDialogOpen(false)}
          onChange={handleModelChange}
          onVerifyModel={verifyOneModel}
        />

        <ModelAddDialog
          isOpen={isAddModalOpen}
          onClose={() => setIsAddModalOpen(false)}
          onSuccess={async (newModel) => {
            await loadModelLists(true);
            message.success(t("modelConfig.message.addSuccess"));
            if (newModel && newModel.name && newModel.type) {
              setTimeout(() => {
                verifyOneModel(newModel.name, newModel.type);
              }, 100);
            }
          }}
          defaultProvider="modelengine"
          defaultIsBatchImport={addModalDefaultIsBatch}
        />

        <ModelDeleteDialog
          isOpen={isDeleteModalOpen}
          onClose={() => setIsDeleteModalOpen(false)}
          onSuccess={async () => {
            await loadModelLists(true);
          }}
          models={models}
          capacityCoverage={capacityCoverage}
        />

        <ModelEditDialog
          isOpen={!!editingCardModel}
          model={editingCardModel}
          onClose={() => setEditingCardModel(null)}
          onSuccess={async () => {
            setEditingCardModel(null);
            await loadModelLists(true);
          }}
        />
      </div>
    </>
  );
});
