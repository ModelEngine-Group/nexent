import { forwardRef, useEffect, useImperativeHandle, useState, useRef, ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { Button, Card, Col, Row, Space, App } from 'antd'
import {
  PlusOutlined,
  SafetyCertificateOutlined,
  SyncOutlined,
  EditOutlined,
} from "@ant-design/icons";

import {
  MODEL_TYPES,
  MODEL_STATUS,
  LAYOUT_CONFIG,
  CARD_THEMES,
} from "@/const/modelConfig";
import { useConfig } from "@/hooks/useConfig";
import { modelService } from "@/services/modelService";
import { configService } from "@/services/configService";
import { ModelOption, ModelType } from "@/types/modelConfig";
import { configStore } from "@/lib/config";
import log from "@/lib/logger";

import { ModelListCard } from "./model/ModelListCard";
import { ModelAddDialog } from "./model/ModelAddDialog";
import { ModelDeleteDialog } from "./model/ModelDeleteDialog";
import EmbedderCheckModal from "./model/EmbedderCheckModal";

// ModelConnectStatus type definition
type ModelConnectStatus = (typeof MODEL_STATUS)[keyof typeof MODEL_STATUS];

// Model data structure
const getModelData = (t: any) => ({
  llm: {
    title: t("modelConfig.category.llm"),
    options: [
      { id: "main", name: t('modelConfig.option.mainModel') },
    ],
  },
  embedding: {
    title: t("modelConfig.category.embedding"),
    options: [
      {
        id: MODEL_TYPES.EMBEDDING,
        name: t("modelConfig.option.embeddingModel"),
      },
      {
        id: MODEL_TYPES.MULTI_EMBEDDING,
        name: t("modelConfig.option.multiEmbeddingModel"),
      },
    ],
  },
  reranker: {
    title: t("modelConfig.category.reranker"),
    options: [{ id: "reranker", name: t("modelConfig.option.rerankerModel") }],
  },
  multimodal: {
    title: t("modelConfig.category.multimodal"),
    options: [{ id: MODEL_TYPES.VLM, name: t("modelConfig.option.vlmModel") }],
  },
  voice: {
    title: t("modelConfig.category.voice"),
    options: [
      { id: MODEL_TYPES.TTS, name: t("modelConfig.option.ttsModel") },
      { id: MODEL_TYPES.STT, name: t("modelConfig.option.sttModel") },
    ],
  },
});

// Define the methods exposed by the component
export interface ModelConfigSectionRef {
  verifyModels: () => Promise<void>;
  getSelectedModels: () => Record<string, Record<string, string>>;
  getEmbeddingConnectivity: () => {
    embedding?: ModelConnectStatus;
    multi_embedding?: ModelConnectStatus;
  };
  // Programmatically simulate a dropdown change and trigger onChange logic
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
  const { message } = App.useApp();
  const { skipVerification = false } = props;
  const { modelConfig, updateModelConfig } = useConfig();
  const modelData = getModelData(t);

  // State management
  const [officialModels, setOfficialModels] = useState<ModelOption[]>([]);
  const [customModels, setCustomModels] = useState<ModelOption[]>([]);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const [isModifyWarningOpen, setIsModifyWarningOpen] = useState(false);

  // Error state management
  const [errorFields, setErrorFields] = useState<{ [key: string]: boolean }>({
    "llm.main": false,
    "embedding.embedding": false,
    "embedding.multi_embedding": false,
  });

  // Controller for canceling API requests
  const abortControllerRef = useRef<AbortController | null>(null);
  // Throttle timer
  const throttleTimerRef = useRef<NodeJS.Timeout | null>(null);
  const saveTimerRef = useRef<NodeJS.Timeout | null>(null);
  const pendingChangeRef = useRef<{
    category: string;
    option: string;
    displayName: string;
  } | null>(null);

  // Debounced auto-save scheduler
  const scheduleAutoSave = () => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
    }
    saveTimerRef.current = setTimeout(async () => {
      try {
        const currentConfig = configStore.getConfig();
        await configService.saveConfigToBackend(currentConfig as any);
      } catch (e) {
        // Errors are logged in configService
      } finally {
        saveTimerRef.current = null;
      }
    }, 600);
  };

  // Model selection state
  const [selectedModels, setSelectedModels] = useState<
    Record<string, Record<string, string>>
  >({
    llm: { main: "" },
    embedding: { embedding: "", multi_embedding: "" },
    reranker: { reranker: "" },
    multimodal: { vlm: "" },
    voice: { tts: "", stt: "" },
  });

  // Initialize loading
  useEffect(() => {
    // Load configuration from backend first, then load model lists when component mounts
    const fetchData = async () => {
      await configService.loadConfigToFrontend();
      configStore.reloadFromStorage();
      await loadModelLists(true);
    };

    fetchData();
  }, [skipVerification]);

  // Listen to field error highlight events
  useEffect(() => {
    const handleHighlightMissingField = (event: any) => {
      const { field } = event.detail;

      if (field === "llm.main" || field === "embedding.embedding") {
        setErrorFields((prev) => ({
          ...prev,
          [field]: true,
        }));

        // Find the corresponding card and scroll it into view
        setTimeout(() => {
          const fieldParts = field.split(".");
          const cardType = fieldParts[0];

          const selector =
            cardType === MODEL_TYPES.EMBEDDING
              ? ".model-card:nth-child(2)"
              : ".model-card:nth-child(1)";

          const card = document.querySelector(selector);
          if (card) {
            card.scrollIntoView({ behavior: "smooth", block: "center" });
          }
        }, 100);
      }
    };

    window.addEventListener(
      "highlightMissingField",
      handleHighlightMissingField
    );
    return () => {
      window.removeEventListener(
        "highlightMissingField",
        handleHighlightMissingField
      );
    };
  }, []);

  // Compute current embedding connectivity from selected models and model lists
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
      const isOfficial = officialModels.some(
        (m) => m.displayName === displayName && m.type === modelType
      );
      if (isOfficial) return MODEL_STATUS.AVAILABLE;
      const custom = customModels.find(
        (m) => m.displayName === displayName && m.type === modelType
      );
      return custom?.connect_status as ModelConnectStatus | undefined;
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

  // Expose methods to parent component
  useImperativeHandle(ref, () => ({
    verifyModels,
    getSelectedModels: () => selectedModels,
    getEmbeddingConnectivity,
    simulateDropdownChange: async (
      category: string,
      option: string,
      displayName: string
    ) => {
      // Directly apply model change to mimic Select onChange behavior
      await applyModelChange(category, option, displayName);
    },
  }));

  // Load model lists
  const loadModelLists = async (skipVerify: boolean = false) => {
    const modelConfig = configStore.getConfig().models;

    try {
      const [official, custom] = await Promise.all([
        modelService.getOfficialModels(),
        modelService.getCustomModels(),
      ]);

      // Ensure all official models have "available" status
      const officialWithStatus = official.map((model) => ({
        ...model,
        connect_status: MODEL_STATUS.AVAILABLE,
      }));

      // Update state
      setOfficialModels(officialWithStatus);
      setCustomModels(custom);

      // Merge all available model lists (official and custom)
      const allModels = [...officialWithStatus, ...custom];

      // Load selected models from configuration and check if models still exist
      const llmMain = modelConfig.llm.displayName;
      const llmMainExists = llmMain
        ? allModels.some(
            (m) => m.displayName === llmMain && m.type === MODEL_TYPES.LLM
          )
        : true;


      const embedding = modelConfig.embedding.displayName;
      const embeddingExists = embedding
        ? allModels.some(
            (m) =>
              m.displayName === embedding && m.type === MODEL_TYPES.EMBEDDING
          )
        : true;

      const multiEmbedding = modelConfig.multiEmbedding.displayName;
      const multiEmbeddingExists = multiEmbedding
        ? allModels.some(
            (m) =>
              m.displayName === multiEmbedding &&
              m.type === MODEL_TYPES.MULTI_EMBEDDING
          )
        : true;

      const rerank = modelConfig.rerank.displayName;
      const rerankExists = rerank
        ? allModels.some(
            (m) => m.displayName === rerank && m.type === MODEL_TYPES.RERANK
          )
        : true;

      const vlm = modelConfig.vlm.displayName;
      const vlmExists = vlm
        ? allModels.some(
            (m) => m.displayName === vlm && m.type === MODEL_TYPES.VLM
          )
        : true;

      const stt = modelConfig.stt.displayName;
      const sttExists = stt
        ? allModels.some(
            (m) => m.displayName === stt && m.type === MODEL_TYPES.STT
          )
        : true;

      const tts = modelConfig.tts.displayName;
      const ttsExists = tts
        ? allModels.some(
            (m) => m.displayName === tts && m.type === MODEL_TYPES.TTS
          )
        : true;

      // Create updated selected models object
      const updatedSelectedModels = {
        llm: {
          main: llmMainExists ? llmMain : "",
        },
        embedding: {
          embedding: embeddingExists ? embedding : "",
          multi_embedding: multiEmbeddingExists ? multiEmbedding : "",
        },
        reranker: {
          reranker: rerankExists ? rerank : "",
        },
        multimodal: {
          vlm: vlmExists ? vlm : "",
        },
        voice: {
          tts: ttsExists ? tts : "",
          stt: sttExists ? stt : "",
        },
      };

      // Update state
      setSelectedModels(updatedSelectedModels);

      // If any models were deleted, synchronize and update locally stored configuration
      const configUpdates: any = {};

      if (!llmMainExists && llmMain) {
        configUpdates.llm = {
          modelName: "",
          displayName: "",
          apiConfig: { apiKey: "", modelUrl: "" },
        };
      }


      if (!embeddingExists && embedding) {
        configUpdates.embedding = {
          modelName: "",
          displayName: "",
          apiConfig: { apiKey: "", modelUrl: "" },
        };
      }

      if (!multiEmbeddingExists && multiEmbedding) {
        configUpdates.multiEmbedding = {
          modelName: "",
          displayName: "",
          apiConfig: { apiKey: "", modelUrl: "" },
        };
      }

      if (!rerankExists && rerank) {
        configUpdates.rerank = { modelName: "", displayName: "" };
      }

      if (!vlmExists && vlm) {
        configUpdates.vlm = { modelName: "", displayName: "" };
      }

      if (!sttExists && stt) {
        configUpdates.stt = { modelName: "", displayName: "" };
      }

      if (!ttsExists && tts) {
        configUpdates.tts = { modelName: "", displayName: "" };
      }

      // If there are configurations to update, update localStorage
      if (Object.keys(configUpdates).length > 0) {
        updateModelConfig(configUpdates);
        // Persist cleared/adjusted selections
        scheduleAutoSave();
      }

      // Check if there are configured models that need connectivity verification
      const hasConfiguredModels =
        !!modelConfig.llm.modelName ||
        !!modelConfig.embedding.modelName ||
        !!modelConfig.multiEmbedding.modelName ||
        !!modelConfig.rerank.modelName ||
        !!modelConfig.vlm.modelName ||
        !!modelConfig.tts.modelName ||
        !!modelConfig.stt.modelName;

      // Perform verification directly here instead of using setTimeout
      // This ensures we use model data from the current function scope instead of relying on state updates
      if (officialWithStatus.length > 0 || custom.length > 0) {
        if (hasConfiguredModels && !skipVerify) {
          // Call internal verification function, passing model data and latest selected model information
          verifyModelsInternal(
            officialWithStatus,
            custom,
            updatedSelectedModels
          );
        }
      }
    } catch (error) {
      log.error(t("modelConfig.error.loadList"), error);
      message.error(t("modelConfig.error.loadListFailed"));
    }
  };

  // Internal verification function that accepts model data as parameters and doesn't depend on state
  const verifyModelsInternal = async (
    officialData: ModelOption[],
    customData: ModelOption[],
    modelsToCheck?: Record<string, Record<string, string>> // Optional parameter to pass latest selected models
  ) => {
    // If already verifying, don't execute again
    if (isVerifying) {
      return;
    }

    // Ensure model data is loaded
    if (officialData.length === 0 && customData.length === 0) {
      return;
    }

    // Use passed model selection data or current state
    const currentSelectedModels = modelsToCheck || selectedModels;

    // Check if there are selected models that need verification
    let hasSelectedModels = false;
    for (const category in currentSelectedModels) {
      for (const optionId in currentSelectedModels[category]) {
        if (currentSelectedModels[category][optionId]) {
          hasSelectedModels = true;
          break;
        }
      }
      if (hasSelectedModels) break;
    }

    // If no selected models in state, try to get directly from configuration
    if (!hasSelectedModels) {
      // Directly check if each model exists in configuration
      const hasLlmMain = !!modelConfig.llm.modelName;
      const hasEmbedding = !!modelConfig.embedding.modelName;
      const hasReranker = !!modelConfig.rerank.modelName;
      const hasVlm = !!modelConfig.vlm.modelName;
      const hasTts = !!modelConfig.tts.modelName;
      const hasStt = !!modelConfig.stt.modelName;

      hasSelectedModels =
        hasLlmMain ||
        hasEmbedding ||
        hasReranker ||
        hasVlm ||
        hasTts ||
        hasStt;

      if (hasSelectedModels) {
        // Override current selected models with models from configuration
        currentSelectedModels.llm.main = modelConfig.llm.modelName;
        currentSelectedModels.embedding.embedding =
          modelConfig.embedding.modelName;
        currentSelectedModels.embedding.multi_embedding =
          modelConfig.multiEmbedding.modelName || "";
        currentSelectedModels.reranker.reranker = modelConfig.rerank.modelName;
        currentSelectedModels.multimodal.vlm = modelConfig.vlm.modelName;
        currentSelectedModels.voice.tts = modelConfig.tts.modelName;
        currentSelectedModels.voice.stt = modelConfig.stt.modelName;
      } else {
        return;
      }
    }

    setIsVerifying(true);

    // Prepare a new AbortController
    const abortController = new AbortController();
    const signal = abortController.signal;

    // Save reference for cancellation
    abortControllerRef.current = abortController;

    try {
      // Prepare list of models to verify
      const modelsToVerify: Array<{
        category: string;
        optionId: string;
        modelName: string;
        modelType: ModelType;
        isOfficialModel: boolean;
      }> = [];

      // Collect all models that need verification, using passed selected model data
      for (const [category, options] of Object.entries(currentSelectedModels)) {
        for (const [optionId, modelName] of Object.entries(options)) {
          if (!modelName) continue;

          let modelType = category as ModelType;
          if (category === "voice") {
            modelType =
              optionId === MODEL_TYPES.TTS ? MODEL_TYPES.TTS : MODEL_TYPES.STT;
          } else if (category === MODEL_TYPES.RERANK) {
            modelType = MODEL_TYPES.RERANK;
          } else if (category === "multimodal") {
            modelType = MODEL_TYPES.VLM;
          } else if (category === MODEL_TYPES.EMBEDDING) {
            modelType =
              optionId === MODEL_TYPES.MULTI_EMBEDDING
                ? MODEL_TYPES.MULTI_EMBEDDING
                : MODEL_TYPES.EMBEDDING;
          }

          // Find model in officialData or customData
          const isOfficialModel = officialData.some(
            (model) => model.name === modelName && model.type === modelType
          );

          // Add model to verification list
          modelsToVerify.push({
            category,
            optionId,
            modelName,
            modelType,
            isOfficialModel,
          });

          // Only update custom model status to "checking", official models are always "available"
          if (!isOfficialModel) {
            updateCustomModelStatus(
              modelName,
              modelType,
              MODEL_STATUS.CHECKING
            );
          }
        }
      }

      // If no models need verification, show message and return
      if (modelsToVerify.length === 0) {
        message.info({ content: "没有需要验证的模型", key: "verifying" });
        setIsVerifying(false);
        abortControllerRef.current = null;
        return;
      }

      // Verify all models in parallel
      await Promise.all(
        modelsToVerify.map(
          async ({ modelName, modelType, isOfficialModel }) => {
            // Call different verification methods based on model source
            let isConnected = false;

            if (isOfficialModel) {
              // Official models are always considered "available"
              isConnected = true;
            } else {
              // Custom models, verify using modelService
              try {
                isConnected = await modelService.verifyCustomModel(
                  modelName,
                  signal
                );

                // Update model status
                updateCustomModelStatus(
                  modelName,
                  modelType,
                  isConnected
                    ? MODEL_STATUS.AVAILABLE
                    : MODEL_STATUS.UNAVAILABLE
                );
              } catch (error: any) {
                // Check if request was cancelled
                if (error.name === "AbortError") {
                  return;
                }

                log.error(
                  `Failed to verify custom model ${modelName}:`,
                  error
                );
                updateCustomModelStatus(
                  modelName,
                  modelType,
                  MODEL_STATUS.UNAVAILABLE
                );
              }
            }
          }
        )
      );
    } catch (error: any) {
      // Check if request was cancelled
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

  // Verify all selected models
  const verifyModels = async () => {
    // If already verifying, don't execute again
    if (isVerifying) {
      return;
    }

    // Ensure model data is loaded
    if (officialModels.length === 0 && customModels.length === 0) {
      // Model data not yet loaded, skip verification
      return;
    }

    // Call internal verification function
    await verifyModelsInternal(officialModels, customModels, selectedModels);
  };

  // Synchronize model lists
  const handleSyncModels = async () => {
    setIsSyncing(true);
    try {
      await loadModelLists(true);
      message.success(t("modelConfig.message.syncSuccess"));
    } catch (error) {
      log.error(t("modelConfig.error.syncFailed"), error);
      message.error(t("modelConfig.error.syncFailed"));
    } finally {
      setIsSyncing(false);
    }
  };

  // Verify single model connection status (with throttling logic)
  const verifyOneModel = async (displayName: string, modelType: ModelType) => {
    // If empty model name, return directly
    if (!displayName) return;

    // Find model in officialModels or customModels
    const isOfficialModel = officialModels.some(
      (model) => model.displayName === displayName && model.type === modelType
    );

    // Official models are always considered "available"
    if (isOfficialModel) return;

    // If in throttling, clear previous timer
    if (throttleTimerRef.current) {
      clearTimeout(throttleTimerRef.current);
    }

    // Use throttling, delay 1s before verification to avoid repeated verification when switching models frequently
    throttleTimerRef.current = setTimeout(async () => {
      // Update custom model status to "checking"
      updateCustomModelStatus(displayName, modelType, MODEL_STATUS.CHECKING);

      try {
        // Use modelService to verify custom model
        const isConnected = await modelService.verifyCustomModel(displayName);

        // Update model status
        updateCustomModelStatus(
          displayName,
          modelType,
          isConnected ? MODEL_STATUS.AVAILABLE : MODEL_STATUS.UNAVAILABLE
        );
      } catch (error: any) {
        log.error(
          t("modelConfig.error.verifyCustomModel", { model: displayName }),
          error
        );
        updateCustomModelStatus(
          displayName,
          modelType,
          MODEL_STATUS.UNAVAILABLE
        );
      } finally {
        throttleTimerRef.current = null;
      }
    }, 1000);
  };

  // Apply model change logic (used by confirm modal)
  const applyModelChange = async (
    category: string,
    option: string,
    displayName: string
  ) => {
    // Update selected models
    setSelectedModels((prev) => ({
      ...prev,
      [category]: {
        ...prev[category],
        [option]: displayName,
      },
    }));

    // If has value, clear error state
    if (displayName) {
      setErrorFields((prev) => ({
        ...prev,
        [`${category}.${option}`]: false,
      }));
    }

    // Find complete model information to get API configuration
    let modelType = category as ModelType;
    if (category === "voice") {
      modelType =
        option === MODEL_TYPES.TTS ? MODEL_TYPES.TTS : MODEL_TYPES.STT;
    } else if (category === MODEL_TYPES.RERANK) {
      modelType = MODEL_TYPES.RERANK;
    } else if (category === "multimodal") {
      modelType = MODEL_TYPES.VLM;
    } else if (category === MODEL_TYPES.EMBEDDING) {
      modelType =
        option === MODEL_TYPES.MULTI_EMBEDDING
          ? MODEL_TYPES.MULTI_EMBEDDING
          : MODEL_TYPES.EMBEDDING;
    }

    const modelInfo = [...officialModels, ...customModels].find(
      (m) => m.displayName === displayName && m.type === modelType
    );

    // If newly selected model is a custom model and no status was previously set, set to "unchecked"
    if (
      modelInfo &&
      modelInfo.source === "custom" &&
      !modelInfo.connect_status
    ) {
      updateCustomModelStatus(displayName, modelType, MODEL_STATUS.UNCHECKED);
    }

    // Update configuration
    let configKey = category;
    if (
      category === MODEL_TYPES.EMBEDDING &&
      option === MODEL_TYPES.MULTI_EMBEDDING
    ) {
      configKey = "multiEmbedding";
    } else if (category === "multimodal") {
      configKey = MODEL_TYPES.VLM;
    } else if (category === MODEL_TYPES.RERANK) {
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
      // Clearing selection should actively clear stored config
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
    } else {
      configUpdate = {
        [configKey]: {
          modelName: modelInfo?.name || "",
          displayName: displayName,
          apiConfig,
        },
      };
      // embedding needs dimension field
      if (configKey === "embedding" || configKey === "multiEmbedding") {
        configUpdate[configKey].dimension = modelInfo?.maxTokens || 0;
      }
    };

    // embedding needs dimension field
    if (configKey === "embedding" || configKey === "multiEmbedding") {
      configUpdate[configKey].dimension = modelInfo?.maxTokens || undefined;
    }

    // Model configuration update
    updateModelConfig(configUpdate);

    // When selecting a new model, automatically verify the model connectivity
    if (displayName) {
      await verifyOneModel(displayName, modelType);
    }

    // Schedule auto-save of the updated configuration to backend
    scheduleAutoSave();
  };

  // Handle model changes (with confirmation for embedding changes)
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
      // Only prompt when modifying from a non-empty value to a different value
      if (currentValue && currentValue !== displayName) {
        pendingChangeRef.current = { category, option, displayName };
        setIsModifyWarningOpen(true);
        return;
      }
      if (currentValue === displayName) {
        return;
      }
    }

    await applyModelChange(category, option, displayName);
  };

  const handleModifyOk = async () => {
    const pending = pendingChangeRef.current;
    if (pending) {
      await handleModelChange(
        pending.category,
        pending.option,
        pending.displayName,
        true
      );
    }
    pendingChangeRef.current = null;
    setIsModifyWarningOpen(false);
  };

  const handleModifyCancel = () => {
    pendingChangeRef.current = null;
    setIsModifyWarningOpen(false);
  };

  // Only update local UI state, no database operations involved
  const updateCustomModelStatus = (
    displayName: string,
    modelType: string,
    status: ModelConnectStatus
  ) => {
    setCustomModels((prev) => {
      const idx = prev.findIndex(
        (model) => model.displayName === displayName && model.type === modelType
      );
      if (idx === -1) return prev;
      const updated = [...prev];
      updated[idx] = {
        ...updated[idx],
        connect_status: status,
      };
      return updated;
    });
  };

  return (
    <>
      <div
        style={{
          width: "100%",
          margin: "0 auto",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          gap: "12px",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "flex-start",
            paddingRight: 12,
            marginLeft: "4px",
            height: LAYOUT_CONFIG.BUTTON_AREA_HEIGHT,
          }}
        >
          <Space size={10}>
            <Button type="primary" size="middle" onClick={handleSyncModels}>
              <SyncOutlined spin={isSyncing} />{" "}
              {t("modelConfig.button.syncModelEngine")}
            </Button>
            <Button
              type="primary"
              size="middle"
              icon={<PlusOutlined />}
              onClick={() => setIsAddModalOpen(true)}
            >
              {t("modelConfig.button.addCustomModel")}
            </Button>
            <Button
              type="primary"
              size="middle"
              icon={<EditOutlined />}
              onClick={() => setIsDeleteModalOpen(true)}
            >
              {t("modelConfig.button.editCustomModel")}
            </Button>
            <Button
              type="primary"
              size="middle"
              icon={<SafetyCertificateOutlined />}
              onClick={verifyModels}
              loading={isVerifying}
            >
              {t("modelConfig.button.checkConnectivity")}
            </Button>
          </Space>
        </div>

        <div
          style={{
            width: "100%",
            padding: "0 4px",
            flex: 1,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <Row
            gutter={[LAYOUT_CONFIG.CARD_GAP, LAYOUT_CONFIG.CARD_GAP]}
            style={{ flex: 1 }}
          >
            {Object.entries(modelData).map(([key, category]) => (
              <Col
                xs={24}
                md={8}
                lg={8}
                key={key}
                style={{ height: "calc((100% - 12px) / 2)" }}
              >
                <Card
                  title={
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        margin: "-12px -24px",
                        padding: LAYOUT_CONFIG.CARD_HEADER_PADDING,
                        paddingBottom: "12px",
                        backgroundColor:
                          CARD_THEMES[key as keyof typeof CARD_THEMES]
                            .backgroundColor,
                        borderBottom: `1px solid ${
                          CARD_THEMES[key as keyof typeof CARD_THEMES]
                            .borderColor
                        }`,
                        height: `${LAYOUT_CONFIG.HEADER_HEIGHT - 12}px`, // Subtract paddingBottom
                      }}
                    >
                      <h5
                        style={{
                          margin: 0,
                          marginLeft: LAYOUT_CONFIG.MODEL_TITLE_MARGIN_LEFT,
                          fontSize: "14px",
                          lineHeight: "32px",
                        }}
                      >
                        {category.title}
                      </h5>
                    </div>
                  }
                  variant="outlined"
                  className="model-card"
                  styles={{
                    body: {
                      padding: LAYOUT_CONFIG.CARD_BODY_PADDING,
                      height: `calc(100% - ${LAYOUT_CONFIG.HEADER_HEIGHT}px)`,
                    },
                  }}
                  style={{
                    height: "100%",
                    backgroundColor: "#ffffff",
                    display: "flex",
                    flexDirection: "column",
                  }}
                >
                  <Space
                    direction="vertical"
                    style={{
                      width: "100%",
                      height: "100%",
                    }}
                    size={12}
                  >
                    {category.options.map((option) => (
                      <ModelListCard
                        key={option.id}
                        type={
                          key === "voice"
                            ? option.id === MODEL_TYPES.TTS
                              ? MODEL_TYPES.TTS
                              : MODEL_TYPES.STT
                            : key === "multimodal"
                            ? MODEL_TYPES.VLM
                            : key === MODEL_TYPES.EMBEDDING &&
                              option.id === MODEL_TYPES.MULTI_EMBEDDING
                            ? MODEL_TYPES.MULTI_EMBEDDING
                            : (key as ModelType)
                        }
                        modelId={option.id}
                        modelTypeName={option.name}
                        selectedModel={selectedModels[key]?.[option.id] || ""}
                        onModelChange={(modelName) =>
                          handleModelChange(key, option.id, modelName)
                        }
                        officialModels={officialModels}
                        customModels={customModels}
                        onVerifyModel={verifyOneModel}
                        errorFields={errorFields}
                      />
                    ))}
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>
        </div>

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
        />

        <ModelDeleteDialog
          isOpen={isDeleteModalOpen}
          onClose={() => setIsDeleteModalOpen(false)}
          onSuccess={async () => {
            await loadModelLists(true);
            return;
          }}
          customModels={customModels}
        />

        <EmbedderCheckModal
          emptyWarningOpen={false}
          onEmptyOk={() => {}}
          onEmptyCancel={() => {}}
          connectivityWarningOpen={false}
          onConnectivityOk={() => {}}
          onConnectivityCancel={() => {}}
          modifyWarningOpen={isModifyWarningOpen}
          onModifyOk={handleModifyOk}
          onModifyCancel={handleModifyCancel}
        />
      </div>
    </>
  );
});