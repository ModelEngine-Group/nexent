import { useState, useEffect, useRef, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Alert, Modal, Select, Input, Button, Switch, App, Tag } from "antd";
import { Settings2 } from "lucide-react";

import { MODEL_TYPES, MODEL_STATUS } from "@/const/modelConfig";
import { useConfig } from "@/hooks/useConfig";
import { useCapacitySuggestion } from "@/hooks/useCapacitySuggestion";
import { modelService } from "@/services/modelService";
import {
  ModelOption,
  ModelType,
  InferenceFieldSpecsByType,
} from "@/types/modelConfig";
import { getConnectivityMeta, ConnectivityStatusType } from "@/lib/utils";
import {
  ModelChunkSizeSlider,
  DEFAULT_EXPECTED_CHUNK_SIZE,
  DEFAULT_MAXIMUM_CHUNK_SIZE,
} from "./ModelChunkSizeSilder";
import {
  isValidMaxTokens,
  ModelMaxTokensInput,
  parseMaxTokens,
} from "./ModelMaxTokensInput";
import {
  buildCapacityPayload,
  capacityFormFromSuggestion,
  capacityFormFromModel,
  emptyCapacityForm,
  ModelCapacityFields,
  ModelCapacityFormState,
  validateCapacityForm,
} from "./ModelCapacityFields";
import {
  ModelAdvancedSettings,
  ModelAdvancedSettingsValue,
  buildInferenceParamsPayload,
  advancedSettingsValueFromRecord,
} from "./ModelAdvancedSettings";

const { Option } = Select;

interface ModelEditDialogV2Props {
  isOpen: boolean;
  model: ModelOption | null;
  onClose: () => void;
  onSuccess: () => Promise<void>;
  tenantId?: string; // Optional tenant ID for manage operations
}

export const ModelEditDialogV2 = ({
  isOpen,
  model,
  onClose,
  onSuccess,
  tenantId,
}: ModelEditDialogV2Props) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { updateModelConfig } = useConfig();
  const {
    suggestion: capacitySuggestion,
    setSuggestion: setCapacitySuggestion,
    acceptedSuggestion: acceptedCapacitySuggestion,
    setAcceptedSuggestion: setAcceptedCapacitySuggestion,
    checking: checkingCapacitySuggestion,
    suggest: suggestCapacity,
    reset: resetCapacitySuggestion,
  } = useCapacitySuggestion();
  const [form, setForm] = useState({
    type: MODEL_TYPES.LLM as ModelType,
    name: "",
    displayName: "",
    url: "",
    apiKey: "",
    maxTokens: "",
    timeoutSeconds: "120",
    concurrencyLimit: "",
    vectorDimension: "1024",
    chunkSizeRange: [
      DEFAULT_EXPECTED_CHUNK_SIZE,
      DEFAULT_MAXIMUM_CHUNK_SIZE,
    ] as [number, number],
    chunkingBatchSize: "10",
    // Voice model fields (STT/TTS)
    modelFactory: "",
    modelAppid: "",
    accessToken: "",
    ...emptyCapacityForm,
  });
  const [loading, setLoading] = useState(false);
  const [verifyingConnectivity, setVerifyingConnectivity] = useState(false);
  const [capacitySuggestionEnabled, setCapacitySuggestionEnabled] =
    useState(true);
  const [connectivityStatus, setConnectivityStatus] = useState<{
    status: ConnectivityStatusType;
    message: string;
  }>({
    status: null,
    message: "",
  });

  // v2.6.0 inference params state (LLM only: temperature / top_p /
  // enable_thinking / __custom__ KV pairs)
  const [advanced, setAdvanced] = useState<ModelAdvancedSettingsValue>({});
  const [inferenceSpecs, setInferenceSpecs] =
    useState<InferenceFieldSpecsByType>({});
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // Load inference field specs once per dialog open. Only LLM type has
  // spec fields beyond capacity/embedding/voice, so the ModelAdvancedSettings
  // panel is only rendered for LLM.
  useEffect(() => {
    if (!isOpen) return;
    modelService
      .getInferenceFieldSpecs()
      .then((specs) => setInferenceSpecs(specs))
      .catch(() => setInferenceSpecs({}));
  }, [isOpen]);

  // Auto-suggest fires at most once per dialog instance. With the parent's
  // key remount, "per instance" == "per model", which is the desired
  // semantic. The fired-once guard is needed because the auto-suggest
  // effect depends on `form.name` and `form.url`, which change as the
  // [model] effect populates the form on first mount AND every time the
  // operator types in those inputs -- only the populate transition
  // should trigger an API call.
  const autoSuggestFiredRef = useRef(false);

  useEffect(() => {
    if (model) {
      setForm({
        type: model.type,
        name: model.name,
        displayName: model.displayName || model.name,
        url: model.apiUrl || "",
        apiKey: model.apiKey || "",
        maxTokens: model.maxTokens?.toString() || "",
        timeoutSeconds: model.timeoutSeconds?.toString() || "120",
        concurrencyLimit: model.concurrencyLimit?.toString() || "",
        vectorDimension: model.maxTokens?.toString() || "1024",
        chunkSizeRange: [
          model.expectedChunkSize || DEFAULT_EXPECTED_CHUNK_SIZE,
          model.maximumChunkSize || DEFAULT_MAXIMUM_CHUNK_SIZE,
        ] as [number, number],
        chunkingBatchSize: (model.chunkingBatchSize || 10).toString(),
        modelFactory: model.modelFactory || "",
        modelAppid: model.modelAppid || "",
        accessToken: model.accessToken || "",
        ...capacityFormFromModel(model),
      });
      // Initialize inference params (LLM only). inferenceSpecs is in the
      // dependency list so that a late specs load (after model is set)
      // re-runs this effect and populates `advanced` correctly.
      // display_name is filtered out because the main dialog body already
      // collects it via the displayName input — no need to also seed it
      // into the advanced-settings popup state.
      if (model.type === MODEL_TYPES.LLM) {
        const filteredSpecs: InferenceFieldSpecsByType = {
          ...inferenceSpecs,
          [model.type]: (inferenceSpecs[model.type] || []).filter(
            (spec) => spec.key !== "display_name"
          ),
        };
        const advancedValue = advancedSettingsValueFromRecord(
          {
            temperature: model.temperature,
            top_p: model.topP,
            extra_params: model.extraParams,
          },
          filteredSpecs,
          model.type
        );
        setAdvanced(advancedValue);
      } else {
        setAdvanced({});
      }
      setCapacitySuggestionEnabled(true);
      resetCapacitySuggestion();
    }
  }, [model, resetCapacitySuggestion, inferenceSpecs]);

  const handleFormChange = (field: string, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
    // If the key configuration item changes, clear the verification status
    if (
      [
        "url",
        "apiKey",
        "maxTokens",
        "timeoutSeconds",
        "concurrencyLimit",
        "vectorDimension",
        "modelFactory",
        "modelAppid",
        "accessToken",
        "name",
      ].includes(field)
    ) {
      setConnectivityStatus({ status: null, message: "" });
      if (["url", "apiKey", "modelFactory", "name"].includes(field)) {
        setCapacitySuggestion(null);
        setAcceptedCapacitySuggestion(null);
      }
    }
  };

  const isEmbeddingModel =
    form.type === MODEL_TYPES.EMBEDDING ||
    form.type === MODEL_TYPES.MULTI_EMBEDDING;
  const isRerankModel = form.type === MODEL_TYPES.RERANK;
  const connectivityModelType =
    form.type === MODEL_TYPES.VLM2 || form.type === MODEL_TYPES.VLM3
      ? (MODEL_TYPES.VLM as ModelType)
      : form.type;
  const isVoiceModel =
    form.type === MODEL_TYPES.STT || form.type === MODEL_TYPES.TTS;
  const supportsCapacityFields =
    !isEmbeddingModel && !isRerankModel && !isVoiceModel;
  const capacityValidationError = supportsCapacityFields
    ? validateCapacityForm(form, [])
    : null;
  // v2.6.0: inference params panel only renders for LLM (only LLM has
  // temperature/top_p/enable_thinking in FIXED_INFERENCE_FIELDS_BY_TYPE).
  const supportsInferenceParams = form.type === MODEL_TYPES.LLM;
  // Edit dialog already has a displayName input on the main body, so
  // strip display_name from the inference specs to avoid a duplicate field
  // inside the advanced-settings popup. Mirrors the add dialog's behavior
  // where display_name is collected on the main form, not in advanced.
  const editInferenceSpecs = useMemo<InferenceFieldSpecsByType>(() => {
    const list = inferenceSpecs[form.type];
    if (!list || list.length === 0) return inferenceSpecs;
    const filtered = list.filter((spec) => spec.key !== "display_name");
    return { ...inferenceSpecs, [form.type]: filtered };
  }, [inferenceSpecs, form.type]);

  const canSuggestCapacity = () =>
    supportsCapacityFields && form.name.trim() !== "" && form.url.trim() !== "";

  const applyCapacitySuggestion = (
    suggestion: typeof acceptedCapacitySuggestion
  ) => {
    const next = capacityFormFromSuggestion(suggestion);
    if (!next || Object.keys(next).length === 0) return;
    setForm((prev) => ({
      ...prev,
      ...next,
      name: suggestion?.canonicalModelName || prev.name,
      // Do NOT overwrite `modelFactory` from the catalog suggestion. The
      // catalog's `suggested_provider` namespace (deepseek, openai, jina,
      // ...) is a superset of the frontend dropdown's allowed values; writing
      // an unknown one back into `model_factory` makes the model disappear
      // from the active list and the edit dropdown.
    }));
    setAcceptedCapacitySuggestion(suggestion);
  };

  // W11 V1.5: when the dialog opens on a bare-capacity LLM/VLM row
  // (per-row badge condition: context_window_tokens or max_output_tokens
  // is null), auto-fire /suggest-capacity once so the operator does not
  // have to also click "Check". The trigger is derived from `model`
  // itself rather than a caller-supplied flag, so any entry path (row
  // click, badge click, future gear-icon shortcut) gets the same
  // affordance. No-op if the model already has capacity, the suggestion
  // switch is off, or required form fields are missing at open time.
  //
  // form.name and form.url are in the dependency list because the
  // [model] effect above populates them asynchronously after this
  // component mounts. With the parent's key remount, the first render
  // here has form.name == "" / form.url == "", so canSuggestCapacity()
  // is false and we cannot fire yet. The [model] effect's setForm
  // then re-renders with populated values, this effect re-runs, and
  // canSuggestCapacity() finally returns true. The autoSuggestFiredRef
  // guards against re-firing later when the operator types into name
  // or url -- only the populate transition should kick off auto-suggest.
  const isBareCapacityModel = Boolean(
    model &&
    supportsCapacityFields &&
    (!model.contextWindowTokens || !model.maxOutputTokens)
  );
  useEffect(() => {
    if (autoSuggestFiredRef.current) return;
    if (!isOpen || !isBareCapacityModel) return;
    if (!capacitySuggestionEnabled) return;
    if (!canSuggestCapacity()) return;
    autoSuggestFiredRef.current = true;
    suggestCapacity({
      modelName: form.name.trim(),
      baseUrl: form.url.trim(),
      providerHint: form.modelFactory || model?.source,
      apiKey: form.apiKey.trim() || undefined,
      modelType: connectivityModelType,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    isOpen,
    isBareCapacityModel,
    capacitySuggestionEnabled,
    form.name,
    form.url,
  ]);

  const isFormValid = () => {
    if (
      supportsCapacityFields &&
      // context_window/max_output not required; only data-shape checks gate Save.
      validateCapacityForm(form, [])
    ) {
      return false;
    }

    // Capacity panel replaces the legacy max_tokens field for LLM/VLM, so
    // the standalone max_tokens is only required for the types that still
    // render that field (voice and rerank-style).
    const needsMaxTokens =
      !supportsCapacityFields && !isEmbeddingModel && !isRerankModel;

    if (isVoiceModel) {
      if (needsMaxTokens && !isValidMaxTokens(form.maxTokens)) {
        return false;
      }
      if (form.modelFactory === "volcengine") {
        return form.modelAppid.trim() !== "" && form.accessToken.trim() !== "";
      } else {
        // v2.6.0: TTS/STT non-volcengine no longer requires apiKey to
        // align with ModelAddDialogV2 custom-access behavior (voice
        // types don't surface the apiKey input).
        return form.name.trim() !== "";
      }
    }
    return (
      form.name.trim() !== "" &&
      form.url.trim() !== "" &&
      (!needsMaxTokens || isValidMaxTokens(form.maxTokens))
    );
  };

  // Verify model connectivity
  const handleVerifyConnectivity = async () => {
    if (!isFormValid()) {
      message.warning(t("model.dialog.warning.incompleteForm"));
      return;
    }

    setVerifyingConnectivity(true);
    setConnectivityStatus({
      status: "checking",
      message: t("model.dialog.status.verifying"),
    });

    try {
      // For LLM/VLM the legacy form.maxTokens field is no longer rendered;
      // use form.maxOutputTokens (capacity panel) for the connectivity-probe
      // budget. Do NOT fall back to form.maxTokens for capacity types --
      // the W1/W2 plan deprecates that field for LLM/VLM, and isFormValid
      // already guarantees form.maxOutputTokens is filled before this
      // probe runs.
      const llmProbeMaxTokens = supportsCapacityFields
        ? Number.parseInt(form.maxOutputTokens || "0", 10)
        : parseMaxTokens(form.maxTokens);
      // v2.6.0: include inference params (temperature/top_p/extra_params)
      // in the connectivity probe for LLM so the probe reflects the
      // configured runtime behavior.
      const inferencePayload = supportsInferenceParams
        ? buildInferenceParamsPayload(advanced)
        : {};
      const config: any = {
        modelName: form.name,
        modelType: connectivityModelType,
        baseUrl: form.url,
        apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
        maxTokens:
          form.type === MODEL_TYPES.EMBEDDING
            ? parseInt(form.vectorDimension)
            : form.type === MODEL_TYPES.RERANK
              ? 0
              : llmProbeMaxTokens,
        embeddingDim:
          form.type === MODEL_TYPES.EMBEDDING
            ? parseInt(form.vectorDimension)
            : undefined,
        ...inferencePayload,
      };

      // Add voice model fields for STT/TTS
      if (isVoiceModel) {
        config.modelFactory = form.modelFactory;
        if (form.modelFactory === "volcengine") {
          config.modelAppid = form.modelAppid;
          config.accessToken = form.accessToken;
        }
      }

      const result = await modelService.verifyModelConfigConnectivity(config);
      if (
        capacitySuggestionEnabled &&
        supportsCapacityFields &&
        result.capacitySuggestion
      ) {
        setCapacitySuggestion(result.capacitySuggestion);
      }

      // Set connectivity status
      let connectivityMessage = "";
      if (result.connectivity) {
        connectivityMessage = t("model.dialog.connectivity.status.available");
      } else {
        connectivityMessage = t("model.dialog.connectivity.status.unavailable");
      }
      setConnectivityStatus({
        status: result.connectivity
          ? MODEL_STATUS.AVAILABLE
          : MODEL_STATUS.UNAVAILABLE,
        message: connectivityMessage,
      });
    } catch (error) {
      setConnectivityStatus({
        status: "unavailable",
        message: t("model.dialog.connectivity.status.unavailable"),
      });
    } finally {
      setVerifyingConnectivity(false);
    }
  };

  const handleSave = async () => {
    if (!model) return;
    // Defensive gate: the Save button is already disabled via
    // `!isFormValid()`, but disabled state can lag a tick behind state
    // updates and the handler is also reachable from non-click paths.
    // Re-check here so we never persist a row whose required W2 capacity
    // fields are empty (this is how production glm-5.2 rows ended up with
    // context_window_tokens=NULL and max_output_tokens=NULL).
    if (!isFormValid()) return;
    setLoading(true);
    try {
      // Use update interface instead of delete + add
      const modelType = form.type as ModelType;
      // Determine max tokens.
      // For LLM/VLM (supportsCapacityFields), the legacy form.maxTokens
      // input is hidden and must not be read here per the W1/W2 plan
      // ("Never use legacy max_tokens"). Seed the legacy column with 0;
      // buildCapacityPayload(form) spreads max_tokens := max_output_tokens
      // a few lines below, keeping the deprecated NOT NULL column aligned
      // with the W2 source of truth.
      let maxTokensValue = supportsCapacityFields
        ? 0
        : parseMaxTokens(form.maxTokens) || 0;
      if (isEmbeddingModel || isRerankModel) maxTokensValue = 0;

      // Use original displayName for lookup, pass new displayName in body if changed
      const originalDisplayName = model.displayName || model.name;
      const newDisplayName = form.displayName;
      const acceptedModelName =
        acceptedCapacitySuggestion?.canonicalModelName || form.name;
      // `acceptedCapacitySuggestion?.suggestedProvider` is intentionally NOT
      // used here. See applyCapacitySuggestion above for the rationale.

      // v2.6.0: build inference params payload (LLM only). Translates the
      // editing state (temperature / top_p / enable_thinking / __custom__)
      // into the wire shape consumed by the backend update endpoints.
      const inferencePayload = supportsInferenceParams
        ? buildInferenceParamsPayload(advanced)
        : {};
      const inferenceUpdate = {
        temperature: inferencePayload.temperature as number | undefined,
        topP: inferencePayload.top_p as number | undefined,
        extraParams: inferencePayload.extra_params as
          | Record<string, unknown>
          | undefined,
      };

      // Use manage interface if tenantId is provided
      if (tenantId) {
        await modelService.updateManageTenantModel({
          tenantId,
          currentDisplayName: originalDisplayName,
          name: acceptedCapacitySuggestion ? acceptedModelName : undefined,
          displayName:
            newDisplayName !== originalDisplayName ? newDisplayName : undefined,
          url: form.url,
          apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
          maxTokens: maxTokensValue !== 0 ? maxTokensValue : undefined,
          expectedChunkSize: isEmbeddingModel
            ? form.chunkSizeRange[0]
            : undefined,
          maximumChunkSize: isEmbeddingModel
            ? form.chunkSizeRange[1]
            : undefined,
          chunkingBatchSize: isEmbeddingModel
            ? parseInt(form.chunkingBatchSize) || 10
            : undefined,
          modelFactory: isVoiceModel ? form.modelFactory : undefined,
          modelAppid:
            isVoiceModel && form.modelFactory === "volcengine"
              ? form.modelAppid
              : undefined,
          accessToken:
            isVoiceModel && form.modelFactory === "volcengine"
              ? form.accessToken
              : undefined,
          timeoutSeconds:
            !isEmbeddingModel && !isRerankModel
              ? parseInt(form.timeoutSeconds) || 120
              : undefined,
          concurrencyLimit:
            !isEmbeddingModel && !isRerankModel
              ? form.concurrencyLimit
                ? parseInt(form.concurrencyLimit)
                : undefined
              : undefined,
          ...(supportsCapacityFields ? buildCapacityPayload(form) : {}),
          ...(acceptedCapacitySuggestion
            ? {
                acceptedSuggestionMatchKind:
                  acceptedCapacitySuggestion.matchKind,
                ...(acceptedCapacitySuggestion.capabilityProfileVersion
                  ? {
                      acceptedCapabilityProfileVersion:
                        acceptedCapacitySuggestion.capabilityProfileVersion,
                    }
                  : {}),
              }
            : {}),
          ...inferenceUpdate,
        });
      } else {
        await modelService.updateSingleModel({
          currentDisplayName: originalDisplayName,
          // Only send displayName if it changed
          ...(newDisplayName !== originalDisplayName
            ? { displayName: newDisplayName }
            : {}),
          ...(acceptedCapacitySuggestion ? { name: acceptedModelName } : {}),
          url: form.url,
          apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
          ...(maxTokensValue !== 0 ? { maxTokens: maxTokensValue } : {}),
          source: model.source,
          // Send chunk size range for embedding models
          ...(isEmbeddingModel
            ? {
                expectedChunkSize: form.chunkSizeRange[0],
                maximumChunkSize: form.chunkSizeRange[1],
                chunkingBatchSize: parseInt(form.chunkingBatchSize) || 10,
              }
            : {}),
          // Send voice model fields
          ...(isVoiceModel
            ? {
                modelFactory: form.modelFactory,
                modelAppid:
                  form.modelFactory === "volcengine"
                    ? form.modelAppid
                    : undefined,
                accessToken:
                  form.modelFactory === "volcengine"
                    ? form.accessToken
                    : undefined,
              }
            : {}),
          // Send timeout for non-embedding models
          ...(!isEmbeddingModel && !isRerankModel
            ? {
                timeoutSeconds: parseInt(form.timeoutSeconds) || 120,
                concurrencyLimit: form.concurrencyLimit
                  ? parseInt(form.concurrencyLimit)
                  : undefined,
              }
            : {}),
          ...(supportsCapacityFields ? buildCapacityPayload(form) : {}),
          ...(acceptedCapacitySuggestion
            ? {
                acceptedSuggestionMatchKind:
                  acceptedCapacitySuggestion.matchKind,
                ...(acceptedCapacitySuggestion.capabilityProfileVersion
                  ? {
                      acceptedCapabilityProfileVersion:
                        acceptedCapacitySuggestion.capabilityProfileVersion,
                    }
                  : {}),
              }
            : {}),
          ...inferenceUpdate,
        });
      }

      // Update local configuration (only when currently edited model is selected in configuration)
      const modelConfigKeyMap: Record<ModelType, string> = {
        llm: MODEL_TYPES.LLM,
        embedding: MODEL_TYPES.EMBEDDING,
        multi_embedding: MODEL_TYPES.MULTI_EMBEDDING,
        vlm: MODEL_TYPES.VLM,
        vlm2: MODEL_TYPES.VLM2,
        vlm3: MODEL_TYPES.VLM3,
        rerank: MODEL_TYPES.RERANK,
        tts: MODEL_TYPES.TTS,
        stt: MODEL_TYPES.STT,
      };
      const configKey = modelConfigKeyMap[modelType];
      updateModelConfig({
        [configKey]: {
          modelName: acceptedModelName,
          displayName: form.displayName || form.name,
          apiConfig: {
            apiKey: form.apiKey,
            modelUrl: form.url,
          },
          ...(supportsCapacityFields ? buildCapacityPayload(form) : {}),
          ...(isEmbeddingModel
            ? { dimension: parseInt(form.vectorDimension) }
            : {}),
          ...(isVoiceModel
            ? {
                modelFactory: form.modelFactory,
                modelAppid:
                  form.modelFactory === "volcengine" ? form.modelAppid : "",
                accessToken:
                  form.modelFactory === "volcengine" ? form.accessToken : "",
              }
            : {}),
        },
      });

      await onSuccess();
      message.success(t("model.dialog.editSuccess"));
      onClose();
    } catch (error: any) {
      if (error.code === 409) {
        message.error(
          t("model.dialog.error.nameConflict", {
            name: form.displayName || form.name,
          })
        );
      } else if (error.code === 404) {
        message.error(t("model.dialog.error.modelNotFound"));
      } else if (error.code === 500) {
        message.error(t("model.dialog.error.serverError"));
      } else {
        message.error(t("model.dialog.error.editFailed"));
        console.error(error);
      }
    } finally {
      setLoading(false);
    }
  };

  if (!model) return null;

  return (
    <>
    <Modal
      title={t("model.dialog.editTitle")}
      open={isOpen}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
    >
      <div className="space-y-4">
        {/* Model Name */}
        <div>
          <label className="block mb-1 text-sm font-medium text-gray-700">
            {t("model.dialog.label.displayName")}
          </label>
          <Input
            value={form.displayName}
            onChange={(e) => handleFormChange("displayName", e.target.value)}
          />
        </div>

        {/* URL */}
        {!isVoiceModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.label.url")}
            </label>
            <Input
              value={form.url}
              onChange={(e) => handleFormChange("url", e.target.value)}
            />
          </div>
        )}

        {/* Voice Model Factory */}
        {isVoiceModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {form.type === MODEL_TYPES.TTS
                ? t("model.dialog.label.ttsProvider")
                : t("model.dialog.label.sttProvider")}
            </label>
            <Select
              style={{ width: "100%" }}
              value={form.modelFactory || "dashscope"}
              onChange={(value) => handleFormChange("modelFactory", value)}
            >
              <Option value="dashscope">{t("model.provider.dashscope")}</Option>
              <Option value="volcengine">
                {t("model.provider.volcengine")}
              </Option>
            </Select>
          </div>
        )}

        {/* Voice Model App ID and Access Token (Volcengine) */}
        {isVoiceModel && form.modelFactory === "volcengine" && (
          <>
            <div>
              <label className="block mb-1 text-sm font-medium text-gray-700">
                {t("model.dialog.label.modelAppid")}
              </label>
              <Input
                value={form.modelAppid}
                onChange={(e) => handleFormChange("modelAppid", e.target.value)}
                autoComplete="new-password"
              />
            </div>
            <div>
              <label className="block mb-1 text-sm font-medium text-gray-700">
                {t("model.dialog.label.accessToken")}
              </label>
              <Input.Password
                value={form.accessToken}
                onChange={(e) =>
                  handleFormChange("accessToken", e.target.value)
                }
                autoComplete="new-password"
                visibilityToggle={false}
              />
            </div>
          </>
        )}

        {/* API Key - v2.6.0: hidden for TTS/STT to align with ModelAddDialogV2
            custom-access behavior (voice types don't use apiKey auth). */}
        {!isVoiceModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.label.apiKey")}
            </label>
            <Input.Password
              value={form.apiKey}
              onChange={(e) => handleFormChange("apiKey", e.target.value)}
              autoComplete="new-password"
              visibilityToggle={false}
            />
          </div>
        )}

        {supportsCapacityFields && (
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3 rounded-md border border-gray-200 bg-gray-50 p-3">
              <div className="text-sm font-medium text-gray-700">
                {t("model.dialog.capacity.suggestion.title")}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Switch
                  size="small"
                  checked={capacitySuggestionEnabled}
                  onChange={setCapacitySuggestionEnabled}
                />
                <Button
                  size="small"
                  onClick={() =>
                    suggestCapacity({
                      modelName: form.name.trim(),
                      baseUrl: form.url.trim(),
                      providerHint: form.modelFactory || model?.source,
                      apiKey: form.apiKey.trim() || undefined,
                      modelType: connectivityModelType,
                    })
                  }
                  loading={checkingCapacitySuggestion}
                  disabled={!capacitySuggestionEnabled || !canSuggestCapacity()}
                >
                  {t("model.dialog.capacity.suggestion.check")}
                </Button>
              </div>
            </div>
            <ModelCapacityFields
              value={form}
              onChange={(field, value) => handleFormChange(field, value)}
              validationError={capacityValidationError}
              capacitySource={model.capacitySource}
              capabilityProfileVersion={model.capabilityProfileVersion}
              // context_window/max_output no longer required; empty input
              // lands DEFAULT_* via buildCapacityPayload at save time.
              suggestion={capacitySuggestionEnabled ? capacitySuggestion : null}
              suggestionLoading={checkingCapacitySuggestion}
              onUseSuggestion={() =>
                applyCapacitySuggestion(capacitySuggestion)
              }
              acceptedSuggestion={acceptedCapacitySuggestion}
              // Legacy max_tokens is now surfaced via the actionable
              // legacyMaxTokensCandidate prompt with two-target buttons
              // (Context Window vs Max Output). The prompt is offered while
              // EITHER target field is still empty -- ModelCapacityFields
              // hides individual buttons once that column is filled, and the
              // whole alert disappears once both are filled. The plain
              // deprecation banner only kicks in if both targets are filled
              // but the legacy column still has a value.
              legacyMaxTokensCandidate={
                model.contextWindowTokens && model.maxOutputTokens
                  ? undefined
                  : model.maxTokens
              }
            />
          </div>
        )}

        {/* v2.6.0: Inference params (temperature / top_p / enable_thinking /
            __custom__ KV pairs). Only rendered for LLM -- other types either
            have no spec fields beyond capacity/embedding/voice (vlm/rerank)
            or have their fields already rendered by dedicated UI controls
            (TTS/STT model_factory/app_id rendered above).
            Layout aligns with ModelAddDialogV2: a "高级设置" button opens a
            popup Modal containing ModelAdvancedSettings, rather than inlining
            the form on the main dialog body. */}
        {supportsInferenceParams && editInferenceSpecs[form.type]?.length > 0 && (
          <div className="flex items-center gap-2">
            <Button
              size="small"
              icon={<Settings2 size={14} />}
              onClick={() => setAdvancedOpen(true)}
            >
              {t("model.advanced.title", { defaultValue: "高级设置" })}
            </Button>
            {Object.keys(advanced).length > 0 && (
              <Tag color="blue">
                {t("model.advanced.configured", { defaultValue: "已配置" })}
              </Tag>
            )}
          </div>
        )}

        {/* maxTokens (legacy; only kept for types not covered by the capacity panel) */}
        {!isEmbeddingModel && !isRerankModel && !supportsCapacityFields && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.label.maxTokens")}{" "}
              <span className="text-red-500">*</span>
            </label>
            <ModelMaxTokensInput
              value={form.maxTokens}
              placeholder={t("model.dialog.placeholder.maxTokens")}
              onChange={(value) => handleFormChange("maxTokens", value)}
            />
          </div>
        )}

        {/* Timeout Seconds */}
        {!isEmbeddingModel && !isRerankModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.label.timeoutSeconds")}
            </label>
            <Input
              type="number"
              min="1"
              value={form.timeoutSeconds}
              onChange={(e) =>
                handleFormChange("timeoutSeconds", e.target.value)
              }
            />
          </div>
        )}

        {/* Concurrency Limit */}
        {!isEmbeddingModel && !isRerankModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.label.concurrencyLimit")}
            </label>
            <Input
              type="number"
              min="1"
              value={form.concurrencyLimit}
              onChange={(e) =>
                handleFormChange("concurrencyLimit", e.target.value)
              }
              placeholder={t("model.dialog.placeholder.concurrencyLimit")}
            />
            <div className="text-xs text-gray-500 mt-1">
              {t("model.dialog.hint.concurrencyLimit")}
            </div>
          </div>
        )}

        {/* Chunk Size Range for embedding models */}
        {isEmbeddingModel && (
          <div>
            <label className="block mb-2 text-sm font-medium text-gray-700">
              {t("modelConfig.slider.chunkingSize")}
            </label>
            <ModelChunkSizeSlider
              value={form.chunkSizeRange}
              onChange={(value) => {
                setForm((prev) => ({
                  ...prev,
                  chunkSizeRange: value,
                }));
              }}
            />
          </div>
        )}

        {/* Concurrent Request Count (Embedding model only) */}
        {isEmbeddingModel && (
          <div>
            <label
              htmlFor="chunkingBatchSize"
              className="block mb-1 text-sm font-medium text-gray-700"
            >
              {t("modelConfig.input.chunkingBatchSize")}
            </label>
            <Input
              id="chunkingBatchSize"
              type="number"
              min="1"
              placeholder="10"
              value={form.chunkingBatchSize}
              onChange={(e) =>
                handleFormChange("chunkingBatchSize", e.target.value)
              }
            />
          </div>
        )}

        {/* Connectivity verification area */}
        <div className="p-3 bg-gray-50 border border-gray-200 rounded-md">
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center">
              <span className="text-sm font-medium text-gray-700">
                {t("model.dialog.connectivity.title")}
              </span>
              {connectivityStatus.status && (
                <div className="ml-2 flex items-center">
                  {getConnectivityMeta(connectivityStatus.status).icon}
                  <span
                    className="ml-1 text-xs"
                    style={{
                      color: getConnectivityMeta(connectivityStatus.status)
                        .color,
                    }}
                  >
                    {connectivityStatus.status === "available" &&
                      t("model.dialog.connectivity.status.available")}
                    {connectivityStatus.status === "unavailable" &&
                      t("model.dialog.connectivity.status.unavailable")}
                    {connectivityStatus.status === "checking" &&
                      t("model.dialog.status.verifying")}
                  </span>
                </div>
              )}
            </div>
            <Button
              size="small"
              type="default"
              onClick={handleVerifyConnectivity}
              loading={verifyingConnectivity}
              disabled={!isFormValid() || verifyingConnectivity}
            >
              {verifyingConnectivity
                ? t("model.dialog.button.verifying")
                : t("model.dialog.button.verify")}
            </Button>
          </div>
        </div>

        <div className="flex justify-end space-x-3">
          <Button onClick={onClose}>{t("common.button.cancel")}</Button>
          <Button
            type="primary"
            onClick={handleSave}
            loading={loading}
            disabled={!isFormValid()}
          >
            {t("common.button.save")}
          </Button>
        </div>
      </div>
    </Modal>

      {/* v2.6.0: Advanced settings popup (inference params).
          Layout aligns with ModelAddDialogV2 custom-access: a separate Modal
          contains ModelAdvancedSettings so the main dialog body stays compact.
          Only rendered for LLM (supportsInferenceParams). */}
      <Modal
        open={advancedOpen}
        onCancel={() => setAdvancedOpen(false)}
        onOk={() => setAdvancedOpen(false)}
        title={`${t("model.advanced.title", { defaultValue: "高级设置" })} - ${form.displayName || form.name || form.type}`}
        okText={t("common.confirm", { defaultValue: "确定" })}
        cancelText={t("common.cancel", { defaultValue: "取消" })}
        width={640}
        centered
        destroyOnClose={false}
        styles={{ body: { maxHeight: "60vh", overflowY: "auto" } }}
      >
        <div className="space-y-4">
          <ModelAdvancedSettings
            modelType={form.type}
            specs={editInferenceSpecs}
            value={advanced}
            onChange={setAdvanced}
            mode="default"
          />
        </div>
      </Modal>
    </>
  );
};
