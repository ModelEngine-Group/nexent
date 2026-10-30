// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { profileOutputLimit } from "@/lib/modelProfileLimits";

import { ModelCapacityFields } from "@/components/model/ModelCapacityFields";
import { ModelParameterPanel } from "@/components/model/ModelParameterPanel";

import { ModelOutletForm } from "@/components/model/ModelOutletForm";

import {
  ModelThinkingSettings,
  thinkingDegreeKeys,
} from "@/components/model/ModelThinkingSettings";
import { parseRequestParameters } from "@/components/model/RequestParametersEditor";
import { ModelRequestSettings } from "@/components/model/ModelRequestSettings";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, App, Button, Form, Input, Select } from "antd";
import { useTranslation } from "react-i18next";

import { ShieldCheck } from "lucide-react";
import { ModelCheckSummary } from "@/components/model/ModelCheckSummary";
import { modelCheckFailure } from "@/lib/modelCheckIssues";
import { StandardButton } from "@/components/common/StandardButton";
import { StandardInput } from "@/components/common/StandardInput";
import {
  outletSamplingRules,
  outletSamplingValues,
  samplingComplete,
} from "@/lib/modelSamplingParameters";
import { ModelParameterField } from "@/components/model/ModelParameterField";
import { ApiError } from "@/services/api";
import {
  createModelOutlet,
  confirmModelOutletMigration,
  updateModelOutlet,
  previewModelOutletPatch,
  listModelProfiles,
  listProviderProfiles,
  previewModelProfile,
  validateModelOutlet,
} from "@/services/modelProfileService";
import type {
  ModelOutletValidationResponse,
  ModelOutletResponse,
  ModelOutletPatchRequest,
  ModelProfileDraftRequest,
  ModelProfileDraftResponse,
  ModelParameterRule,
  ThinkingControlFormat,
  ThinkingDegreeMode,
} from "@/types/modelProfile";

import {
  suggestModelProfile,
  isApproximateProfile,
  matchesProfileKeywords,
} from "./profileSuggestion";

interface ModelOutletAddFormProps {
  editing?: ModelOutletResponse;
  reviewMigration?: boolean;
  typeControl?: ReactNode;
  configuration?: {
    profileLocked?: boolean;
    draft: ModelProfileDraftRequest;
    onApply: (draft: ModelProfileDraftRequest) => void;
  };
  onDone: () => void;
  onPendingChange: (pending: boolean) => void;
  onSuccess: (model: { name: string; type: "llm" }) => void;
}

export function ModelOutletAddForm({
  editing,
  reviewMigration = false,
  onDone,
  onSuccess,
  onPendingChange,
  configuration,
  typeControl,
}: ModelOutletAddFormProps) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const initial = useMemo<ModelProfileDraftRequest | undefined>(() => {
    if (!editing) return configuration?.draft;
    const p = editing.profile;
    const refs = p.provenance?.atomic_refs;
    return {
      selection_mode: "manual",
      model_profile: refs?.model
        ? { key: refs.model.key, revision: "saved" }
        : null,
      provider_profile: refs?.provider
        ? { key: refs.provider.key, revision: "saved" }
        : null,
      provider_info: { ...p.connection, provider_id: p.identity.provider_id },
      request_model_id: p.identity.request_model_id,
      display_name: p.identity.display_name,
      parameter_values: p.parameter_values,
      context_limits: p.capabilities.context,
      context_configuration: p.context_configuration,
      extra_api_parameters: p.extra_api_parameters,
      thinking_control:
        p.provenance?.provider_metadata?.operator_thinking?.preset ??
        "profile_default",
      thinking_mode:
        p.provenance?.provider_metadata?.operator_thinking_degree?.mode,
    };
  }, [editing, configuration?.draft]);
  const [selectionChanged, setSelectionChanged] = useState(false);
  const [resetParameters, setResetParameters] = useState(false);
  const [keyEdited, setKeyEdited] = useState(false);
  const [keyVisible, setKeyVisible] = useState(false);
  const [headersEdited, setHeadersEdited] = useState(false);
  const [baseUrl, setBaseUrl] = useState(initial?.provider_info.base_url ?? "");
  const [name, setName] = useState(initial?.request_model_id ?? "");
  const [displayName, setDisplayName] = useState(initial?.display_name ?? "");
  const [apiKey, setApiKey] = useState(
    editing?.has_credential ? "********" : ""
  );
  const maskedKey = !!editing?.has_credential && /^\*+$/.test(apiKey);
  const invalidKey = !maskedKey && apiKey.includes("********");
  const [providerKey, setProviderKey] = useState<string>(
    initial?.provider_profile?.key ?? "__custom__"
  );
  const [modelKey, setModelKey] = useState<string | undefined>(
    initial?.model_profile?.key ??
      (initial?.selection_mode === "manual" ? "__other__" : undefined)
  );
  const [advanced, setAdvanced] = useState<string[]>(
    !editing && initial?.selection_mode === "manual" && !initial.model_profile
      ? ["advanced"]
      : []
  );
  const [sslVerify, setSslVerify] = useState(
    initial?.provider_info.ssl_verify ?? true
  );
  const [timeout, setTimeoutValue] = useState(
    initial?.provider_info.timeout_seconds ?? 120
  );
  const [values, setValues] = useState<Record<string, unknown>>(
    initial?.parameter_values ?? {}
  );
  const [thinkingControl, setThinkingControl] = useState<ThinkingControlFormat>(
    initial?.thinking_control ?? "profile_default"
  );
  const [thinkingMode, setThinkingMode] = useState<
    ThinkingDegreeMode | undefined
  >(initial?.thinking_mode);
  const [headers, setHeaders] = useState<Record<string, string | null>>(
    editing
      ? Object.fromEntries(
          (editing.http_header_names ?? []).map((name) => [name, null])
        )
      : (initial?.http_headers ?? {})
  );
  const [headersValid, setHeadersValid] = useState(true);
  const [extrasValid, setExtrasValid] = useState(true);
  const [extras, setExtras] = useState(
    JSON.stringify(initial?.extra_api_parameters ?? [], null, 2)
  );
  const [reserve] = useState<number | null>(
    initial?.context_configuration?.output_reserve_tokens ?? null
  );
  const [tokenizer] = useState(
    initial?.context_configuration?.tokenizer_family ?? ""
  );
  const [limits, setLimits] = useState<
    NonNullable<ModelProfileDraftRequest["context_limits"]>
  >(initial?.context_limits ?? {});
  const editState = JSON.stringify([
    baseUrl,
    name,
    displayName,
    maskedKey ? "__saved_key__" : apiKey,
    providerKey,
    modelKey,
    sslVerify,
    timeout,
    values,
    thinkingControl,
    thinkingMode,
    headers,
    extras,
    limits,
    resetParameters,
    selectionChanged,
    headersEdited,
  ]);
  const [initialEditState] = useState(editState);
  const reviewOnly =
    !!editing && reviewMigration && editState === initialEditState;
  const providers = useQuery({
    queryKey: ["provider-profiles"],
    queryFn: ({ signal }) => listProviderProfiles({ page_size: 100 }, signal),
  });
  const models = useQuery({
    queryKey: ["model-profiles"],
    queryFn: ({ signal }) => listModelProfiles({ page_size: 100 }, signal),
  });
  const provider = providers.data?.items.find(
    (item) => item.key === providerKey
  );
  const model = useMemo(
    () =>
      modelKey
        ? models.data?.items.find((item) => item.key === modelKey)
        : suggestModelProfile(name, models.data?.items ?? []),
    [modelKey, models.data, name]
  );
  const parsedExtras = useMemo(
    () => (extrasValid ? parseRequestParameters(extras) : null),
    [extras, extrasValid]
  );

  const draft = useMemo<ModelProfileDraftRequest>(
    () => ({
      selection_mode: modelKey === "__other__" ? "manual" : "auto",
      provider_profile: provider
        ? { key: provider.key, revision: provider.revision }
        : null,
      model_profile: model
        ? { key: model.key, revision: model.revision }
        : null,
      provider_info: {
        ...initial?.provider_info,
        base_url: baseUrl.trim(),
        ssl_verify: sslVerify,
        timeout_seconds: timeout,
      },
      request_model_id: name.trim(),
      display_name: displayName.trim() || name.trim(),
      authentication_scheme: configuration
        ? (initial?.authentication_scheme ?? "no_auth_v1")
        : apiKey.trim()
          ? "bearer_token_v1"
          : "no_auth_v1",
      context_limits: limits,
      context_configuration: {
        output_reserve_tokens: reserve,
        tokenizer_family: tokenizer || null,
      },
      parameter_values: values,
      thinking_control: thinkingControl,
      thinking_mode:
        thinkingMode ?? (editing && resetParameters ? "default" : undefined),
      http_headers: Object.fromEntries(
        Object.entries(headers).filter(
          (entry): entry is [string, string] => entry[1] !== null
        )
      ),
      extra_api_parameters: parsedExtras ?? [],
    }),
    [
      thinkingControl,
      thinkingMode,
      editing,
      resetParameters,
      modelKey,
      provider,
      model,
      baseUrl,
      sslVerify,
      timeout,
      name,
      displayName,
      apiKey,
      configuration,
      initial?.authentication_scheme,
      values,
      limits,
      reserve,
      tokenizer,
      parsedExtras,
      headers,
      initial?.provider_info,
    ]
  );
  const makeEditPatch = (
    request: ModelProfileDraftRequest
  ): ModelOutletPatchRequest => ({
    expected_revision: editing!.config_revision,
    reset_parameters: resetParameters,
    display_name: request.display_name ?? request.request_model_id,
    connection: {
      base_url: request.provider_info.base_url,
      ssl_verify: request.provider_info.ssl_verify,
      timeout_seconds: request.provider_info.timeout_seconds,
      concurrency_limit: request.provider_info.concurrency_limit,
    },
    parameter_values: resetParameters
      ? (request.parameter_values ?? {})
      : outletSamplingValues(request.parameter_values ?? {}),
    delete_parameters: resetParameters
      ? []
      : Object.keys(editing!.profile.parameter_values).filter(
          (key) =>
            !Object.hasOwn(request.parameter_values ?? {}, key) &&
            !["temperature", "top_p"].includes(key)
        ),
    context_limits: request.context_limits,
    context_configuration: request.context_configuration,
    thinking_control: request.thinking_control,
    thinking_mode: request.thinking_mode,
    extra_api_parameters: request.extra_api_parameters,
    ...(keyEdited && !maskedKey ? { api_key: apiKey.trim() || null } : {}),
    ...(headersEdited ? { http_headers: headers } : {}),
    ...(selectionChanged
      ? {
          request_model_id: request.request_model_id,
          profile_selection: {
            catalog_revision:
              models.data?.catalog_revision ??
              providers.data?.catalog_revision ??
              "",
            model_profile: request.model_profile ?? null,
            provider_profile: request.provider_profile ?? null,
          },
        }
      : {}),
  });
  const [debounced, setDebounced] = useState(draft);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(draft), 300);
    return () => clearTimeout(timer);
  }, [draft]);
  const [catalogRefresh, setCatalogRefresh] = useState(0);
  const [refreshingCatalog, setRefreshingCatalog] = useState(false);
  const refreshCatalog = async () => {
    if (!modelKey && model) setModelKey(model.key);
    setRefreshingCatalog(true);
    try {
      const results = await Promise.all([
        providers.refetch(),
        models.refetch(),
      ]);
      if (results.every((result) => !result.isError)) {
        setCatalogRefresh((version) => version + 1);
      }
    } finally {
      setRefreshingCatalog(false);
    }
  };
  const previewIdentity = (request: ModelProfileDraftRequest) =>
    JSON.stringify([
      request.model_profile,
      request.provider_profile,
      request.request_model_id,
      request.provider_info.base_url,
    ]);
  const currentIdentity = previewIdentity(draft);
  const [lastPreview, setLastPreview] = useState<{
    identity: string;
    result: ModelProfileDraftResponse;
  }>();
  const preview = useQuery({
    queryKey: [
      "model-profile-preview",
      editing?.model_id,
      debounced,
      selectionChanged,
      resetParameters,
      catalogRefresh,
    ],
    queryFn: async ({ signal }) => {
      const result = editing
        ? await previewModelOutletPatch(
            editing.model_id,
            makeEditPatch(debounced),
            signal
          )
        : await previewModelProfile(debounced, signal);
      if (!signal.aborted)
        setLastPreview({ identity: previewIdentity(debounced), result });
      return result;
    },
    retry: false,
    enabled:
      !refreshingCatalog &&
      (!!editing ||
        !!debounced.request_model_id ||
        !!debounced.model_profile) &&
      parsedExtras !== null,
  });
  const previewCurrent = previewIdentity(debounced) === currentIdentity;
  const fullPreview = previewCurrent ? preview.data : undefined;
  const view =
    fullPreview ??
    (lastPreview?.identity === currentIdentity
      ? lastPreview.result
      : undefined) ??
    (editing
      ? {
          field_specs: editing.profile.parameter_rules,
          parameter_values: editing.profile.parameter_values,
          capabilities: editing.profile.capabilities,
        }
      : undefined);
  const appliedProvider = fullPreview
    ? fullPreview.selected.provider
    : editing && !selectionChanged
      ? initial?.provider_profile?.key
      : draft.provider_profile?.key;
  const previewConflict =
    previewCurrent &&
    preview.error instanceof ApiError &&
    (String(preview.error.code) === "409" ||
      preview.error.code === "MODEL_OUTLET_VERSION_CONFLICT");
  const previewDetails =
    preview.error instanceof ApiError ? preview.error.details : undefined;
  const validationMessages: Record<string, string> = {
    PARAMETER_UNKNOWN: "unknown",
    PARAMETER_VALUE_INVALID: "value",
    PARAMETER_VALUE_REQUIRED: "value",
    FIXED_PARAMETER: "fixed",
    PARAMETER_NOT_EDITABLE: "fixed",
    PARAMETER_DEPENDENCY: "dependency",
  };
  const category =
    typeof previewDetails?.category === "string" ? previewDetails.category : "";
  const invalidField =
    typeof previewDetails?.field === "string" ? previewDetails.field : "";
  const parameterName = invalidField.split("/").filter(Boolean).at(-1) ?? "";
  const previewDiagnostic = category
    ? validationMessages[category]
      ? t(`modelProfile.validation.${validationMessages[category]}`, {
          field: t(`modelProfile.parameterLabel.${parameterName}`, {
            defaultValue: parameterName,
          }),
        })
      : t("modelProfile.validation.source", {
          detail: [category, invalidField].filter(Boolean).join(" · "),
        })
    : undefined;
  const sampling = outletSamplingValues(values, view?.parameter_values);
  const samplingRules = outletSamplingRules(view?.field_specs ?? []);
  const ready =
    !invalidKey &&
    headersValid &&
    samplingComplete(sampling) &&
    (providerKey === "__custom__" ||
      !!provider ||
      (!!editing && !selectionChanged)) &&
    (!modelKey ||
      modelKey === "__other__" ||
      !!model ||
      (!!editing && !selectionChanged)) &&
    !!draft.request_model_id &&
    !!draft.provider_info.base_url.trim() &&
    !!preview.data &&
    JSON.stringify(debounced) === JSON.stringify(draft) &&
    !refreshingCatalog &&
    !preview.isFetching &&
    !preview.isError &&
    parsedExtras !== null;
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] =
    useState<
      Pick<ModelOutletValidationResponse, "ok" | "error" | "check_receipt">
    >();
  const checkGeneration = useRef(0);
  const checkController = useRef<AbortController | null>(null);
  const checkDraftIdentity = Object.fromEntries(
    Object.entries(draft).filter(([key]) => key !== "display_name")
  );
  const checkFingerprint = JSON.stringify([checkDraftIdentity, sampling]);
  useEffect(() => {
    checkGeneration.current += 1;
    checkController.current?.abort();
    return () => {
      checkController.current?.abort();
    };
  }, [checkFingerprint, apiKey]);
  const checkDraft = async () => {
    if (!ready || !preview.data || checking) return;
    const generation = checkGeneration.current;
    const controller = new AbortController();
    controller.signal.addEventListener(
      "abort",
      () => {
        setChecking(false);
        setCheckResult(undefined);
      },
      { once: true }
    );
    checkController.current = controller;
    setChecking(true);
    setCheckResult(undefined);
    try {
      const result = await validateModelOutlet(
        editing
          ? {
              outlet_id: editing.model_id,
              expected_revision: editing.config_revision,
              patch: makeEditPatch(draft),
            }
          : {
              draft: {
                ...draft,
                parameter_values: sampling,
                catalog_revision: preview.data.catalog_revision,
                api_key: apiKey.trim() || null,
              },
            },
        controller.signal
      );
      if (!controller.signal.aborted && generation === checkGeneration.current)
        setCheckResult({
          ok: result.ok,
          check_receipt: result.check_receipt,
          error: result.ok ? null : (result.error ?? modelCheckFailure(null)),
        });
    } catch (error) {
      if (!controller.signal.aborted && generation === checkGeneration.current)
        setCheckResult({ ok: false, error: modelCheckFailure(error) });
    } finally {
      if (!controller.signal.aborted && generation === checkGeneration.current)
        setChecking(false);
    }
  };
  const reviewFailed = useRef(false);
  const save = useMutation({
    onMutate: () => {
      reviewFailed.current = false;
      onPendingChange(true);
    },
    onSettled: () => onPendingChange(false),
    mutationFn: async () => {
      if (reviewOnly) {
        await confirmModelOutletMigration(
          editing!.model_id,
          editing!.config_revision
        );
        return editing;
      }
      if (!ready || !preview.data)
        throw new Error(t("modelProfile.previewRequired"));
      if (configuration) {
        configuration.onApply({
          ...draft,
          parameter_values: sampling,
          catalog_revision: preview.data.catalog_revision,
        });
        return null;
      }
      if (editing) {
        const saved = await updateModelOutlet(editing.model_id, {
          ...makeEditPatch(draft),
          check_receipt: checkResult?.check_receipt,
        });
        if (reviewMigration) {
          try {
            await confirmModelOutletMigration(
              saved.model_id,
              saved.config_revision
            );
          } catch {
            reviewFailed.current = true;
            message.warning(t("modelMigration.savedReviewFailed"));
          }
        }
        return saved;
      }
      const saved = await createModelOutlet({
        check_receipt: checkResult?.check_receipt,
        ...draft,
        parameter_values: sampling,
        catalog_revision: preview.data.catalog_revision,
        api_key: apiKey.trim() || null,
      });
      return saved;
    },
    onSuccess: () => {
      if (configuration) return;
      if (!reviewFailed.current)
        message.success(
          reviewOnly
            ? t("modelMigration.confirmed")
            : editing
              ? t("modelProfile.saved")
              : t("modelConfig.addDialog.batchSuccess", {
                  count: 1,
                  created: 1,
                })
        );
      onSuccess({ name: name.trim(), type: "llm" });
      onDone();
    },
    onError: (error) => {
      message.error(
        t(
          reviewOnly
            ? "modelMigration.confirmFailed"
            : error instanceof ApiError &&
                error.code === "MODEL_DISPLAY_NAME_CONFLICT"
              ? "modelProfile.displayNameConflict"
              : editing
                ? "modelProfile.editFailed"
                : "modelProfile.saveFailed"
        )
      );
    },
  });
  const changeValue = (key: string, value: unknown) =>
    setValues((previous) => ({ ...previous, [key]: value }));
  const resetValue = (key: string) =>
    setValues((previous) => {
      const next = { ...previous };
      delete next[key];
      return next;
    });
  const inheritedOutputLimit = profileOutputLimit(
    view?.capabilities.context,
    limits.combined_window
  );
  const field = (rule: ModelParameterRule) => (
    <ModelParameterField
      key={rule.key}
      rule={rule}
      values={values}
      fallbackValues={outletSamplingValues({}, view?.parameter_values)}
      pending={save.isPending}
      onChange={changeValue}
      onReset={resetValue}
    />
  );
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ModelOutletForm
        layout="vertical"
        disabled={save.isPending}
        className="min-h-0 flex-1 overflow-y-auto [&_.ant-form-item]:!mb-4 [&_.ant-form-item-label]:!pb-1"
      >
        <div className="grid min-h-0 grid-cols-1 lg:grid-cols-2">
          <div className="min-w-0 p-6">
            {editing && (
              <p className="mb-3 text-xs text-muted-foreground">
                {t("modelProfile.savedProfileVersionHint")}
              </p>
            )}
            <div className="grid grid-cols-2 items-start gap-x-3">
              <Form.Item
                label={t("modelConfig.addDialog.provider")}
                extra={t("modelProfile.appliedProvider", {
                  name:
                    providers.data?.items.find(
                      (item) => item.key === appliedProvider
                    )?.name ??
                    appliedProvider ??
                    t("modelProfile.customProvider"),
                })}
              >
                <Select
                  aria-label={t("modelProfile.provider")}
                  getPopupContainer={(trigger) => trigger.parentElement!}
                  showSearch
                  optionFilterProp="label"
                  value={
                    configuration
                      ? (fullPreview?.selected.provider ?? providerKey)
                      : providerKey
                  }
                  disabled={!!configuration || save.isPending}
                  loading={providers.isLoading}
                  options={[
                    ...(editing &&
                    providerKey !== "__custom__" &&
                    !providers.data?.items.some(
                      (item) => item.key === providerKey
                    )
                      ? [{ value: providerKey, label: providerKey }]
                      : []),
                    ...(providers.data?.items.map((item) => ({
                      value: item.key,
                      label: item.name,
                    })) ?? []),
                    {
                      value: "__custom__",
                      label: t("modelProfile.customProvider"),
                    },
                  ]}
                  onChange={(key) => {
                    setProviderKey(key);
                    setSelectionChanged(true);
                    setThinkingControl("profile_default");
                    setThinkingMode(undefined);
                    const selected = providers.data?.items.find(
                      (item) => item.key === key
                    );
                    if (!baseUrl.trim())
                      setBaseUrl(selected?.suggested_base_url ?? "");
                  }}
                />
              </Form.Item>
              <Form.Item
                label={t("modelConfig.addDialog.modelType")}
                htmlFor="outlet-model-type"
              >
                {typeControl ?? (
                  <Input
                    id="outlet-model-type"
                    disabled
                    value={t("model.type.llm")}
                  />
                )}
              </Form.Item>
            </div>
            <Form.Item required label={t("modelConfig.addDialog.baseUrl")}>
              <StandardInput
                aria-label={t("modelProfile.endpoint")}
                value={baseUrl}
                disabled={!!configuration || save.isPending}
                onChange={(event) => setBaseUrl(event.target.value)}
              />
            </Form.Item>
            <Form.Item
              label={t("modelProfile.apiKey")}
              extra={
                editing?.has_credential ? t("modelProfile.keepKey") : undefined
              }
            >
              <Input.Password
                aria-label={t("modelProfile.apiKey")}
                autoComplete="new-password"
                value={apiKey}
                disabled={!!configuration || save.isPending}
                placeholder={
                  configuration
                    ? t("modelProfile.sharedCredential")
                    : t("modelProfile.optionalApiKey")
                }
                visibilityToggle={{
                  visible:
                    !!apiKey.trim() && !maskedKey && !invalidKey && keyVisible,
                  onVisibleChange: setKeyVisible,
                }}
                styles={{
                  suffix: {
                    display:
                      !!apiKey.trim() && !maskedKey && !invalidKey
                        ? "inline-flex"
                        : "none",
                  },
                }}
                onFocus={(event) => {
                  if (maskedKey) event.target.select();
                }}
                onChange={(event) => {
                  const value = event.target.value;
                  if (
                    !value.trim() ||
                    /^\*+$/.test(value) ||
                    value.includes("********")
                  )
                    setKeyVisible(false);
                  setApiKey(value);
                  setKeyEdited(true);
                }}
              />
            </Form.Item>
            <Form.Item
              required
              label={
                <span>
                  {t("modelProfile.modelId")}{" "}
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    {t("modelConfig.addDialog.modelNameHint")}
                  </span>
                </span>
              }
            >
              <StandardInput
                aria-label={t("modelProfile.requestModel")}
                value={name}
                disabled={!!configuration || save.isPending}
                onChange={(event) => {
                  setName(event.target.value);
                  if (editing) setSelectionChanged(true);
                }}
              />
            </Form.Item>
            <Form.Item
              label={
                <span className="inline-flex flex-wrap items-baseline gap-x-2">
                  <span>{t("modelProfile.modelProfile")}</span>
                  {!modelKey && model && isApproximateProfile(name, model) && (
                    <span className="text-xs font-normal text-muted-foreground">
                      {t("modelProfile.approximateMatch")}
                    </span>
                  )}
                </span>
              }
            >
              <Select
                aria-label={t("modelProfile.modelProfile")}
                disabled={configuration?.profileLocked}
                getPopupContainer={(trigger) => trigger.parentElement!}
                allowClear
                showSearch
                filterOption={(input, option) => {
                  const item = models.data?.items.find(
                    (item) => item.key === option?.value
                  );
                  return item
                    ? matchesProfileKeywords(input, item)
                    : String(option?.label ?? "").includes(input);
                }}
                value={
                  modelKey ??
                  model?.key ??
                  fullPreview?.selected.model ??
                  undefined
                }
                placeholder={t("modelProfile.chooseProfile")}
                loading={models.isLoading}
                options={[
                  ...(editing &&
                  modelKey &&
                  modelKey !== "__other__" &&
                  !models.data?.items.some((item) => item.key === modelKey)
                    ? [{ value: modelKey, label: modelKey }]
                    : []),
                  ...(models.data?.items.map((item) => ({
                    value: item.key,
                    label: item.name,
                  })) ?? []),
                  { value: "__other__", label: t("modelProfile.otherProfile") },
                ]}
                onSelect={(key) => {
                  setModelKey(key);
                  setSelectionChanged(true);
                  setThinkingControl("profile_default");
                  setThinkingMode(undefined);
                  if (key === "__other__") {
                    setAdvanced(["advanced"]);
                  }
                }}
                onChange={(key) => {
                  setModelKey(key);
                  setSelectionChanged(true);
                  setThinkingControl("profile_default");
                  setThinkingMode(undefined);
                  if (key === "__other__") setAdvanced(["advanced"]);
                }}
              />
            </Form.Item>
            <Form.Item label={t("modelConfig.addDialog.displayName")}>
              <StandardInput
                aria-label={t("modelProfile.displayName")}
                value={displayName}
                placeholder={name}
                onChange={(event) => setDisplayName(event.target.value)}
              />
            </Form.Item>
            {preview.isFetching && (
              <p role="status">{t("modelProfile.previewLoading")}</p>
            )}
            {previewConflict && parsedExtras !== null ? (
              <div
                role="alert"
                className="mb-3 flex flex-wrap items-center gap-x-2 text-xs text-amber-700"
              >
                <span title={t("modelProfile.catalogChangedDetail")}>
                  {t("modelProfile.catalogChanged")}
                </span>
                <Button
                  type="link"
                  size="small"
                  className="!h-auto !p-0 !text-xs"
                  loading={refreshingCatalog}
                  onClick={refreshCatalog}
                >
                  {t("modelProfile.refreshCatalog")}
                </Button>
              </div>
            ) : (
              ((preview.isError && previewCurrent) ||
                parsedExtras === null) && (
                <Alert
                  type="error"
                  showIcon
                  description={previewDiagnostic}
                  action={
                    parsedExtras !== null ? (
                      <StandardButton
                        loading={preview.isFetching}
                        onClick={() => preview.refetch()}
                      >
                        {t("modelProfile.retryPreview")}
                      </StandardButton>
                    ) : undefined
                  }
                  title={t(
                    parsedExtras === null
                      ? "modelProfile.extrasInvalid"
                      : "modelProfile.previewFailed"
                  )}
                />
              )
            )}
            {(providers.isError || models.isError) && (
              <Alert
                type="warning"
                showIcon
                title={t("modelProfile.catalogFailed")}
              />
            )}

            <ModelRequestSettings
              showConnection={!configuration}
              headers={headers}
              onHeadersChange={(value) => {
                setHeaders(value);
                setHeadersEdited(true);
              }}
              onHeadersValidityChange={setHeadersValid}
              activeKey={advanced}
              onChange={(keys) =>
                setAdvanced(typeof keys === "string" ? [keys] : keys)
              }
              sslVerify={sslVerify}
              onSslVerifyChange={setSslVerify}
              timeout={timeout}
              onTimeoutChange={setTimeoutValue}
              extras={extras}
              onExtrasChange={setExtras}
              onValidityChange={setExtrasValid}
              pending={save.isPending}
            />
          </div>
          <ModelParameterPanel
            hasModel={!!name.trim() || !!model || modelKey === "__other__"}
            source={model?.name ?? initial?.model_profile?.key}
            pending={save.isPending}
            onReset={() => {
              setResetParameters(true);
              setValues({});
              setLimits({});
              setThinkingControl("profile_default");
              setThinkingMode(undefined);
            }}
            sampling={
              <div className="grid grid-cols-2 gap-x-3">
                {samplingRules.map(field)}
                {(view?.field_specs ?? [])
                  .filter(
                    (rule) =>
                      rule.visible &&
                      !["temperature", "top_p", "max_output_tokens"].includes(
                        rule.key
                      ) &&
                      rule.ui_group !== "reasoning"
                  )
                  .map(field)}
              </div>
            }
            thinking={
              <ModelThinkingSettings
                layout="panel"
                reasoningSupported={
                  (
                    view?.capabilities.reasoning as
                      { status?: string } | undefined
                  )?.status === "supported"
                }
                outputLimit={limits.output_limit ?? inheritedOutputLimit}
                prefillReady={
                  !!preview.data &&
                  !preview.isFetching &&
                  JSON.stringify(debounced) === JSON.stringify(draft)
                }
                rules={view?.field_specs ?? []}
                values={values}
                defaults={view?.parameter_values}
                mode={thinkingMode}
                pending={save.isPending}
                onToggle={(enabled) => {
                  if (
                    !(view?.field_specs ?? []).some(
                      (rule) => rule.key === "enable_thinking" && rule.visible
                    )
                  )
                    setThinkingControl(
                      thinkingControl === "profile_default"
                        ? "enable_thinking"
                        : thinkingControl
                    );
                  setValues((previous) => {
                    const next = {
                      ...previous,
                      enable_thinking: enabled,
                    };
                    if (!enabled)
                      thinkingDegreeKeys.forEach(
                        (key) => delete (next as Record<string, unknown>)[key]
                      );
                    return next;
                  });
                }}
                onModeChange={(mode) => {
                  setThinkingMode(mode);
                  setValues((previous) => {
                    const next = { ...previous };
                    thinkingDegreeKeys.forEach((key) => delete next[key]);
                    return next;
                  });
                }}
                onValueChange={(key, value) =>
                  value === undefined
                    ? resetValue(key)
                    : changeValue(key, value)
                }
              />
            }
            capacity={
              <ModelCapacityFields
                contextWindow={
                  limits.combined_window ??
                  (
                    view?.capabilities?.context as
                      { combined_window?: number } | undefined
                  )?.combined_window
                }
                outputLimit={
                  limits.output_limit ?? inheritedOutputLimit ?? null
                }
                onChange={(key, value) => {
                  const next = { ...limits };
                  if (value === null) delete next[key];
                  else next[key] = value;
                  setLimits(next);
                }}
              />
            }
          />
        </div>
      </ModelOutletForm>
      <div className="flex shrink-0 items-center justify-between gap-3 border-t px-6 py-4">
        <div className="flex flex-wrap items-center gap-3">
          {!configuration && (
            <>
              <StandardButton
                icon={<ShieldCheck className="h-4 w-4" />}
                loading={checking}
                disabled={!ready || save.isPending}
                onClick={() => void checkDraft()}
              >
                {t("modelConfig.editDialog.checkConnectivity")}
              </StandardButton>
              {checkResult?.ok && (
                <span role="status" className="text-xs text-emerald-600">
                  {t("model.status.available")}
                </span>
              )}
              <ModelCheckSummary
                issues={checkResult?.error ? { draft: checkResult.error } : {}}
                modelNames={{ draft: name.trim() }}
                onRetry={
                  !checking && ready ? () => void checkDraft() : undefined
                }
                onRetryShared={
                  !checking && ready ? () => void checkDraft() : undefined
                }
              />
            </>
          )}
        </div>
        <div className="flex gap-2">
          <StandardButton disabled={save.isPending} onClick={onDone}>
            {t("common.cancel")}
          </StandardButton>
          <StandardButton
            variant="primary"
            disabled={!ready && !reviewOnly}
            className="disabled:opacity-50"
            loading={save.isPending}
            onClick={() => save.mutate()}
          >
            {t(
              reviewOnly
                ? "modelMigration.confirm"
                : configuration || editing
                  ? reviewMigration
                    ? "modelMigration.saveAndConfirm"
                    : "common.save"
                  : "modelConfig.addDialog.submit"
            )}
          </StandardButton>
        </div>
      </div>
    </div>
  );
}
