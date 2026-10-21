// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { ModelCapacityFields } from "@/components/model/ModelCapacityFields";
import { ModelParameterPanel } from "@/components/model/ModelParameterPanel";
import { ModelOutletForm } from "@/components/model/ModelOutletForm";
import {
  ModelThinkingSettings,
  thinkingDegreeKeys,
} from "@/components/model/ModelThinkingSettings";
import { parseRequestParameters } from "@/components/model/RequestParametersEditor";
import { ModelRequestSettings } from "@/components/model/ModelRequestSettings";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, App, Form, Input, Modal, Spin } from "antd";
import { useTranslation } from "react-i18next";
import {
  outletSamplingRules,
  outletSamplingValues,
  samplingComplete,
} from "@/lib/modelSamplingParameters";
import { ModelParameterField } from "@/components/model/ModelParameterField";
import { StandardButton } from "@/components/common/StandardButton";
import {
  getModelOutlet,
  updateModelOutlet,
} from "@/services/modelProfileService";
import type {
  ModelOutletResponse,
  ThinkingControlFormat,
  ThinkingDegreeMode,
} from "@/types/modelProfile";

interface EditProps {
  modelId: number;
  onClose: () => void;
  onSuccess: () => void;
}

export function ModelOutletEditDialog({
  modelId,
  onClose,
  onSuccess,
}: EditProps) {
  const { t } = useTranslation();
  const outlet = useQuery({
    queryKey: ["model-outlet-edit", modelId],
    queryFn: ({ signal }) => getModelOutlet(modelId, signal),
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  return (
    <Modal
      open
      centered
      title={t("modelProfile.edit")}
      footer={null}
      onCancel={onClose}
      destroyOnHidden
      width={1040}
      styles={{
        body: { padding: 0 },
        container: { padding: 0 },
        header: {
          margin: 0,
          padding: "20px 24px",
          borderBottom: "1px solid var(--border)",
        },
      }}
    >
      {outlet.isFetching ? (
        <Spin />
      ) : outlet.isError ? (
        <Alert
          type="error"
          title={t("modelProfile.loadFailed")}
          action={
            <StandardButton onClick={() => void outlet.refetch()}>
              {t("common.retry")}
            </StandardButton>
          }
        />
      ) : (
        outlet.data && (
          <OutletEditor
            key={`${modelId}:${outlet.data.config_revision}`}
            saved={outlet.data}
            onClose={onClose}
            onSuccess={onSuccess}
          />
        )
      )}
    </Modal>
  );
}

function OutletEditor({
  saved,
  onClose,
  onSuccess,
}: {
  saved: ModelOutletResponse;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const profile = saved.profile;
  const [name, setName] = useState(profile.identity.display_name);
  const [connection, setConnection] = useState(() => ({
    base_url: profile.connection.base_url,
    ssl_verify: profile.connection.ssl_verify,
    timeout_seconds: profile.connection.timeout_seconds,
    concurrency_limit: profile.connection.concurrency_limit,
  }));
  // A fixed UI sentinel reveals neither the secret nor its length.
  const [key, setKey] = useState(saved.has_credential ? "********" : "");
  const [keyEdited, setKeyEdited] = useState(false);
  const [keyVisible, setKeyVisible] = useState(false);
  const maskedKey = saved.has_credential && /^\*+$/.test(key);
  const invalidKey = !maskedKey && key.includes("********");
  const canRevealKey = !!key.trim() && !maskedKey && !invalidKey;
  const [values, setValues] = useState(profile.parameter_values);
  const [deleted, setDeleted] = useState<string[]>([]);
  const metadata = profile.provenance?.provider_metadata;
  const [thinkingControl, setThinkingControl] = useState<ThinkingControlFormat>(
    metadata?.operator_thinking?.preset ?? "profile_default"
  );
  const [thinkingMode, setThinkingMode] = useState<
    ThinkingDegreeMode | undefined
  >(metadata?.operator_thinking_degree?.mode);
  const [extrasValid, setExtrasValid] = useState(true);
  const [extras, setExtras] = useState(
    JSON.stringify(profile.extra_api_parameters, null, 2)
  );
  const updateParameter = (field: string, value?: unknown) => {
    setValues((previous) => {
      const next = { ...previous };
      if (value === undefined) delete next[field];
      else next[field] = value;
      return next;
    });
    setDeleted((previous) =>
      value === undefined
        ? Array.from(new Set([...previous, field]))
        : previous.filter((key) => key !== field)
    );
  };
  const [limits, setLimits] = useState(profile.capabilities.context);
  const reserve = profile.context_configuration.output_reserve_tokens;
  const tokenizer = profile.context_configuration.tokenizer_family ?? "";
  const sampling = outletSamplingValues(values);
  const save = useMutation({
    mutationFn: async () => {
      if (!samplingComplete(sampling)) throw new Error("SAMPLING_REQUIRED");
      if (!extrasValid) throw new Error("INVALID_API_PARAMETERS");
      if (invalidKey) throw new Error("INVALID_CREDENTIAL_PLACEHOLDER");
      const parsed = parseRequestParameters(extras);
      if (parsed === null) throw new Error("INVALID_API_PARAMETERS");
      return updateModelOutlet(saved.model_id, {
        expected_revision: saved.config_revision,
        display_name: name,
        connection,
        thinking_control: thinkingControl,
        thinking_mode: thinkingMode,
        parameter_values: Object.fromEntries(
          Object.entries(sampling).filter(([entry]) => !deleted.includes(entry))
        ),
        delete_parameters: deleted,
        extra_api_parameters: parsed,
        context_limits: {
          combined_window: limits.combined_window,
          output_limit: limits.output_limit,
        },
        context_configuration: {
          output_reserve_tokens: reserve,
          tokenizer_family: tokenizer || null,
        },
        ...(keyEdited && !maskedKey ? { api_key: key.trim() || null } : {}),
      });
    },
    onSuccess: () => {
      message.success(t("modelProfile.saved"));
      onSuccess();
    },
    onError: () => {
      message.error(t("modelProfile.editFailed"));
    },
  });
  return (
    <ModelOutletForm
      className="[&_.ant-form-item]:!mb-3 [&_.ant-form-item-label]:!pb-1"
      layout="vertical"
      disabled={save.isPending}
      onFinish={() => save.mutate()}
    >
      <div className="max-h-[min(72vh,800px)] overflow-y-auto">
        <div className="grid grid-cols-1 lg:grid-cols-2">
          <div className="min-w-0 space-y-3 p-6">
            <div className="border-b pb-3">
              <div className="break-words text-sm font-medium">
                {profile.identity.request_model_id}
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("modelProfile.frozenRules")}
              </p>
            </div>
            <Form.Item label={t("modelProfile.displayName")}>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </Form.Item>
            <Form.Item label={t("modelProfile.endpoint")}>
              <Input
                value={connection.base_url}
                onChange={(event) =>
                  setConnection({ ...connection, base_url: event.target.value })
                }
              />
            </Form.Item>
            <Form.Item
              label={t("modelProfile.apiKey")}
              help={t(
                invalidKey
                  ? "modelProfile.replaceWholeKey"
                  : "modelProfile.keepKey"
              )}
              validateStatus={invalidKey ? "error" : undefined}
            >
              <Input.Password
                autoComplete="new-password"
                visibilityToggle={{
                  visible: canRevealKey && keyVisible,
                  onVisibleChange: setKeyVisible,
                }}
                styles={{
                  suffix: { display: canRevealKey ? "inline-flex" : "none" },
                }}
                value={key}
                disabled={save.isPending}
                aria-label={t("modelProfile.apiKey")}
                onFocus={(event) => {
                  if (maskedKey) event.target.select();
                }}
                onChange={(event) => {
                  const next = event.target.value;
                  if (
                    !next.trim() ||
                    /^\*+$/.test(next) ||
                    next.includes("********")
                  ) {
                    setKeyVisible(false);
                  }
                  setKeyEdited(true);
                  setKey(next);
                }}
              />
            </Form.Item>
            <ModelRequestSettings
              sslVerify={connection.ssl_verify}
              onSslVerifyChange={(ssl_verify) =>
                setConnection({ ...connection, ssl_verify })
              }
              timeout={connection.timeout_seconds}
              onTimeoutChange={(timeout_seconds) =>
                setConnection({ ...connection, timeout_seconds })
              }
              extras={extras}
              onExtrasChange={setExtras}
              onValidityChange={setExtrasValid}
              pending={save.isPending}
            />
          </div>
          <ModelParameterPanel
            hasModel
            source={profile.identity.request_model_id}
            pending={save.isPending}
            sampling={
              <div className="grid grid-cols-2 gap-x-3">
                {[
                  ...outletSamplingRules(
                    saved.field_specs ?? profile.parameter_rules
                  ),
                  ...(saved.field_specs ?? profile.parameter_rules).filter(
                    (rule) =>
                      rule.visible &&
                      !["temperature", "top_p", "max_output_tokens"].includes(
                        rule.key
                      ) &&
                      rule.ui_group !== "reasoning"
                  ),
                ].map((rule) => (
                  <ModelParameterField
                    key={rule.key}
                    rule={rule}
                    values={values}
                    fallbackValues={outletSamplingValues({})}
                    resetLabel={t("modelProfile.omitParameter")}
                    pending={save.isPending}
                    onChange={updateParameter}
                    onReset={(field) => updateParameter(field)}
                  />
                ))}
              </div>
            }
            thinking={
              <ModelThinkingSettings
                layout="panel"
                outputLimit={limits.output_limit}
                rules={profile.parameter_rules}
                values={values}
                mode={thinkingMode}
                pending={save.isPending}
                onToggle={(enabled) => {
                  if (
                    !profile.parameter_rules.some(
                      (rule) => rule.key === "enable_thinking" && rule.visible
                    )
                  )
                    setThinkingControl(
                      thinkingControl === "profile_default"
                        ? "enable_thinking"
                        : thinkingControl
                    );
                  const next: Record<string, unknown> = {
                    ...values,
                    enable_thinking: enabled,
                  };
                  const removed = enabled
                    ? []
                    : thinkingDegreeKeys.filter((key) =>
                        Object.hasOwn(values, key)
                      );
                  removed.forEach((key) => delete next[key]);
                  setValues(next);
                  setDeleted(
                    Array.from(
                      new Set([
                        ...deleted.filter((key) => key !== "enable_thinking"),
                        ...removed,
                      ])
                    )
                  );
                }}
                onModeChange={(mode) => {
                  setThinkingMode(mode);
                  const next = { ...values };
                  const removed = thinkingDegreeKeys.filter((key) =>
                    Object.hasOwn(values, key)
                  );
                  removed.forEach((key) => delete next[key]);
                  setValues(next);
                  setDeleted(Array.from(new Set([...deleted, ...removed])));
                }}
                onValueChange={updateParameter}
              />
            }
            capacity={
              <ModelCapacityFields
                contextWindow={limits.combined_window}
                outputLimit={limits.output_limit ?? null}
                onChange={(key, value) =>
                  setLimits({ ...limits, [key]: value })
                }
              />
            }
          />
        </div>
      </div>
      {save.isError && (
        <Alert
          className="mx-6 mb-3"
          type="error"
          title={t("modelProfile.editFailed")}
        />
      )}
      <div className="flex flex-wrap items-center justify-end gap-3 border-t px-6 py-4">
        <span className="mr-auto text-xs text-muted-foreground">
          {t("modelProfile.parameterPriority")}
        </span>
        <StandardButton disabled={save.isPending} onClick={onClose}>
          {t("common.cancel")}
        </StandardButton>
        <StandardButton
          variant="primary"
          htmlType="submit"
          disabled={invalidKey || !extrasValid || !samplingComplete(sampling)}
          loading={save.isPending}
        >
          {t("common.save")}
        </StandardButton>
      </div>
    </ModelOutletForm>
  );
}
