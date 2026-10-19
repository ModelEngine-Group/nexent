// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { profileOutputLimit } from "@/lib/modelProfileLimits";

import { ModelParameterPanel } from "@/components/model/ModelParameterPanel";
import { ShieldCheck, Settings2 } from "lucide-react";

import { ModelOutletForm } from "@/components/model/ModelOutletForm";

import {
  ModelThinkingSettings,
  thinkingDegreeKeys,
} from "@/components/model/ModelThinkingSettings";
import { RequestParametersEditor } from "@/components/model/RequestParametersEditor";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Collapse,
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
} from "antd";
import { useTranslation } from "react-i18next";

import { StandardButton } from "@/components/common/StandardButton";
import { StandardInput } from "@/components/common/StandardInput";
import { ModelParameterField } from "@/components/model/ModelParameterField";
import { ApiError } from "@/services/api";
import {
  createModelOutlet,
  listModelProfiles,
  listProviderProfiles,
  previewModelProfile,
  validateModelOutlet,
} from "@/services/modelProfileService";
import type {
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
  typeControl?: ReactNode;
  configuration?: {
    draft: ModelProfileDraftRequest;
    onApply: (draft: ModelProfileDraftRequest) => void;
  };
  onDone: () => void;
  onPendingChange: (pending: boolean) => void;
  onSuccess: (model: {
    name: string;
    type: "llm";
    connectionChecked?: boolean;
  }) => void;
}

export function ModelOutletAddForm({
  onDone,
  onSuccess,
  onPendingChange,
  configuration,
  typeControl,
}: ModelOutletAddFormProps) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const initial = configuration?.draft;
  const [baseUrl, setBaseUrl] = useState(initial?.provider_info.base_url ?? "");
  const [name, setName] = useState(initial?.request_model_id ?? "");
  const [displayName, setDisplayName] = useState(initial?.display_name ?? "");
  const [apiKey, setApiKey] = useState("");
  const [providerKey, setProviderKey] = useState<string>(
    initial?.provider_profile?.key ?? "__custom__"
  );
  const [modelKey, setModelKey] = useState<string | undefined>(
    initial?.model_profile?.key ??
      (initial?.selection_mode === "manual" ? "__other__" : undefined)
  );
  const [advanced, setAdvanced] = useState<string[]>(
    initial?.selection_mode === "manual" && !initial.model_profile
      ? ["advanced"]
      : []
  );
  const [sslVerify, setSslVerify] = useState(
    initial?.provider_info.ssl_verify ?? true
  );
  const [timeout, setTimeoutValue] = useState(
    initial?.provider_info.timeout_seconds ?? 120
  );
  const [noAuth, setNoAuth] = useState(
    initial?.authentication_scheme === "no_auth_v1"
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
  const parsedExtras = useMemo(() => {
    if (!extrasValid) return null;
    try {
      const parsed: unknown = JSON.parse(extras);
      if (
        !Array.isArray(parsed) ||
        parsed.some(
          (entry) =>
            !entry ||
            typeof entry !== "object" ||
            typeof entry.path !== "string" ||
            !Object.hasOwn(entry, "value")
        )
      )
        return null;
      return parsed as Array<{ path: string; value: unknown }>;
    } catch {
      return null;
    }
  }, [extras, extrasValid]);
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
      authentication_scheme: noAuth ? "no_auth_v1" : "bearer_token_v1",
      context_limits: limits,
      context_configuration: {
        output_reserve_tokens: reserve,
        tokenizer_family: tokenizer || null,
      },
      parameter_values: values,
      thinking_control: thinkingControl,
      thinking_mode: thinkingMode,
      extra_api_parameters: parsedExtras ?? [],
    }),
    [
      thinkingControl,
      thinkingMode,
      modelKey,
      provider,
      model,
      baseUrl,
      sslVerify,
      timeout,
      name,
      displayName,
      noAuth,
      values,
      limits,
      reserve,
      tokenizer,
      parsedExtras,
      initial?.provider_info,
    ]
  );
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
    queryKey: ["model-profile-preview", debounced, catalogRefresh],
    queryFn: async ({ signal }) => {
      const result = await previewModelProfile(debounced, signal);
      if (!signal.aborted)
        setLastPreview({ identity: previewIdentity(debounced), result });
      return result;
    },
    retry: false,
    enabled:
      !refreshingCatalog &&
      !!debounced.request_model_id &&
      !!debounced.provider_info.base_url &&
      parsedExtras !== null,
  });
  const previewCurrent = previewIdentity(debounced) === currentIdentity;
  const fullPreview = previewCurrent ? preview.data : undefined;
  const view =
    fullPreview ??
    (lastPreview?.identity === currentIdentity
      ? lastPreview.result
      : undefined) ??
    model?.configuration;
  const previewConflict =
    previewCurrent &&
    preview.error instanceof ApiError &&
    (String(preview.error.code) === "409" ||
      preview.error.code === "MODEL_OUTLET_VERSION_CONFLICT");
  const previewDiagnostic =
    preview.error instanceof ApiError
      ? [preview.error.details?.category, preview.error.details?.field]
          .filter((value): value is string => typeof value === "string")
          .join(" · ")
      : undefined;
  const ready =
    (providerKey === "__custom__" || !!provider) &&
    (!modelKey || modelKey === "__other__" || !!model) &&
    !!draft.provider_info.base_url.trim() &&
    !!preview.data &&
    JSON.stringify(debounced) === JSON.stringify(draft) &&
    !refreshingCatalog &&
    !preview.isFetching &&
    !preview.isError &&
    parsedExtras !== null;
  const save = useMutation({
    onMutate: () => onPendingChange(true),
    onSettled: () => onPendingChange(false),
    mutationFn: async () => {
      if (!ready || !preview.data)
        throw new Error(t("modelProfile.previewRequired"));
      if (configuration) {
        configuration.onApply({
          ...draft,
          catalog_revision: preview.data.catalog_revision,
        });
        return null;
      }
      const saved = await createModelOutlet({
        ...draft,
        catalog_revision: preview.data.catalog_revision,
        api_key: noAuth ? null : apiKey.trim() || null,
      });
      try {
        const result = await validateModelOutlet({
          outlet_id: saved.model_id,
          expected_revision: saved.config_revision,
        });
        if (!result.ok) message.warning(t("modelProfile.savedUnavailable"));
        else message.success(t("modelProfile.savedAvailable"));
      } catch {
        message.warning(t("modelProfile.savedCheckFailed"));
      }
      return saved;
    },
    onSuccess: () => {
      if (configuration) return;
      onSuccess({ name: name.trim(), type: "llm", connectionChecked: true });
      onDone();
    },
    onError: () => {
      message.error(t("modelProfile.saveFailed"));
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
      fallbackValues={view?.parameter_values}
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
            <div className="grid grid-cols-2 items-start gap-x-3">
              <Form.Item label={t("modelConfig.addDialog.provider")}>
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
                    const selected = providers.data?.items.find(
                      (item) => item.key === key
                    );
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
            <Form.Item
              required
              label={
                <span>
                  {t("modelConfig.addDialog.modelName")}{" "}
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
                onChange={(event) => setName(event.target.value)}
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
                  (fullPreview ? "__other__" : undefined)
                }
                placeholder={t("modelProfile.autoProfile")}
                loading={models.isLoading}
                options={[
                  ...(models.data?.items.map((item) => ({
                    value: item.key,
                    label: item.name,
                  })) ?? []),
                  { value: "__other__", label: t("modelProfile.otherProfile") },
                ]}
                onSelect={(key) => {
                  setModelKey(key);
                  if (key === "__other__") {
                    setAdvanced(["advanced"]);
                  }
                }}
                onChange={(key) => {
                  setModelKey(key);
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
            <Form.Item required label={t("modelConfig.addDialog.baseUrl")}>
              <StandardInput
                aria-label={t("modelProfile.endpoint")}
                value={baseUrl}
                disabled={!!configuration || save.isPending}
                onChange={(event) => setBaseUrl(event.target.value)}
              />
            </Form.Item>
            <Form.Item label={t("modelProfile.apiKey")}>
              <Input.Password
                aria-label={t("modelProfile.apiKey")}
                autoComplete="new-password"
                value={apiKey}
                disabled={!!configuration || noAuth || save.isPending}
                placeholder={
                  configuration ? t("modelProfile.sharedCredential") : undefined
                }
                onChange={(event) => setApiKey(event.target.value)}
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

            <Collapse
              ghost
              activeKey={advanced}
              onChange={(keys) =>
                setAdvanced(typeof keys === "string" ? [keys] : keys)
              }
              className="border-t [&_.ant-collapse-header]:!bg-transparent [&_.ant-collapse-header]:!px-0 [&_.ant-collapse-header]:!shadow-none [&_.ant-collapse-body]:!px-0"
              expandIconPlacement="end"
              items={[
                {
                  key: "advanced",
                  label: (
                    <span className="flex items-center gap-2 text-xs">
                      <Settings2 size={14} />
                      {t("modelProfile.advanced")}
                      <span className="text-muted-foreground">
                        {t("modelProfile.layout.advancedHint")}
                      </span>
                    </span>
                  ),
                  children: (
                    <section
                      aria-label={t("modelProfile.requestGroup")}
                      className="pt-1"
                    >
                      <div className="space-y-3">
                        <h5 className="mb-2 text-xs font-medium text-muted-foreground">
                          {t("modelProfile.httpGroup")}
                        </h5>
                        <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2 lg:grid-cols-2">
                          <Form.Item label={t("modelProfile.sslVerify")}>
                            <Switch
                              checked={sslVerify}
                              onChange={setSslVerify}
                            />
                          </Form.Item>
                          <Form.Item label={t("modelProfile.timeout")}>
                            <InputNumber
                              className="!w-full"
                              value={timeout}
                              min={1}
                              max={2147483646}
                              precision={0}
                              onChange={(value) => {
                                if (value !== null) setTimeoutValue(value);
                              }}
                            />
                          </Form.Item>
                          <Form.Item label={t("modelProfile.noAuth")}>
                            <Switch checked={noAuth} onChange={setNoAuth} />
                          </Form.Item>
                        </div>
                        <h5 className="mb-2 mt-3 text-xs font-medium text-muted-foreground">
                          {t("modelProfile.extraParameters")}
                        </h5>
                        <Form.Item>
                          <RequestParametersEditor
                            value={extras}
                            onChange={setExtras}
                            onValidityChange={setExtrasValid}
                            disabled={save.isPending}
                          />
                        </Form.Item>
                      </div>
                    </section>
                  ),
                },
              ]}
            />
          </div>
          <ModelParameterPanel
            hasModel={!!name.trim()}
            source={model?.name}
            pending={save.isPending}
            onReset={() => {
              setValues({});
              setLimits({});
              setThinkingControl("profile_default");
              setThinkingMode(undefined);
            }}
            sampling={
              <div className="grid grid-cols-2 gap-x-3">
                {(view?.field_specs ?? [])
                  .filter(
                    (rule) =>
                      rule.visible &&
                      rule.ui_group !== "reasoning" &&
                      rule.key !== "max_output_tokens"
                  )
                  .map(field)}
                {!(view?.field_specs ?? []).some(
                  (rule) =>
                    rule.visible &&
                    rule.ui_group !== "reasoning" &&
                    rule.key !== "max_output_tokens"
                ) && (
                  <p className="col-span-2 text-xs text-muted-foreground">
                    {t("modelProfile.layout.awaitingProfile")}
                  </p>
                )}
              </div>
            }
            thinking={
              <ModelThinkingSettings
                layout="panel"
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
              <div className="grid grid-cols-2 gap-x-3">
                <Form.Item label={t("modelProfile.combined_window")}>
                  <InputNumber
                    className="!w-full"
                    aria-label={t("modelProfile.combined_window")}
                    min={1}
                    precision={0}
                    value={
                      limits.combined_window ??
                      (
                        view?.capabilities?.context as
                          { combined_window?: number } | undefined
                      )?.combined_window
                    }
                    onChange={(value) => {
                      const next = { ...limits };
                      if (value === null) delete next.combined_window;
                      else next.combined_window = value;
                      setLimits(next);
                    }}
                  />
                </Form.Item>
                <Form.Item
                  label={t("modelProfile.maximumOutput")}
                  tooltip={t("modelProfile.inheritedOutputLimit")}
                >
                  <InputNumber
                    className="!w-full"
                    aria-label={t("modelProfile.maximumOutput")}
                    min={1}
                    precision={0}
                    value={limits.output_limit ?? inheritedOutputLimit ?? null}
                    onChange={(value) => {
                      const next = { ...limits };
                      if (value === null) delete next.output_limit;
                      else next.output_limit = value;
                      setLimits(next);
                    }}
                  />
                </Form.Item>
              </div>
            }
          />
        </div>
      </ModelOutletForm>
      <div className="flex shrink-0 items-center justify-between gap-3 border-t px-6 py-4">
        {!configuration ? (
          <span className="flex items-center gap-2 text-xs text-muted-foreground">
            <ShieldCheck size={14} />
            {t("modelProfile.layout.checkAfterSave")}
          </span>
        ) : (
          <span />
        )}
        <div className="flex gap-2">
          <StandardButton disabled={save.isPending} onClick={onDone}>
            {t("common.cancel")}
          </StandardButton>
          <StandardButton
            variant="primary"
            disabled={!ready}
            className="disabled:opacity-50"
            loading={save.isPending}
            onClick={() => save.mutate()}
          >
            {t(configuration ? "common.save" : "modelConfig.addDialog.submit")}
          </StandardButton>
        </div>
      </div>
    </div>
  );
}
