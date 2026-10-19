// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { ModelOutletForm } from "@/components/model/ModelOutletForm";

import {
  ModelThinkingSettings,
  thinkingDegreeKeys,
} from "@/components/model/ModelThinkingSettings";
import { RequestParametersEditor } from "@/components/model/RequestParametersEditor";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Collapse,
  Form,
  Input,
  InputNumber,
  Modal,
  Spin,
  Switch,
} from "antd";
import { useTranslation } from "react-i18next";
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
      width={960}
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
  const [key, setKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [values, setValues] = useState(profile.parameter_values);
  const [deleted, setDeleted] = useState<string[]>([]);
  const originalThinking =
    (
      profile.provenance as
        | {
            provider_metadata?: {
              operator_thinking?: { preset?: ThinkingControlFormat };
            };
          }
        | undefined
    )?.provider_metadata?.operator_thinking?.preset ?? "profile_default";
  const [thinkingControl, setThinkingControl] =
    useState<ThinkingControlFormat>(originalThinking);
  const metadata = profile.provenance as
    | {
        provider_metadata?: {
          operator_thinking_degree?: { mode?: ThinkingDegreeMode };
        };
      }
    | undefined;
  const [thinkingMode, setThinkingMode] = useState<
    ThinkingDegreeMode | undefined
  >(metadata?.provider_metadata?.operator_thinking_degree?.mode);
  const [extrasValid, setExtrasValid] = useState(true);
  const [extras, setExtras] = useState(
    JSON.stringify(profile.extra_api_parameters, null, 2)
  );
  const [limits, setLimits] = useState(profile.capabilities.context);
  const [reserve] = useState(
    profile.context_configuration.output_reserve_tokens
  );
  const [tokenizer] = useState(
    profile.context_configuration.tokenizer_family ?? ""
  );
  const save = useMutation({
    mutationFn: async () => {
      if (!extrasValid) throw new Error("INVALID_API_PARAMETERS");
      const parsed: unknown = JSON.parse(extras);
      if (
        !Array.isArray(parsed) ||
        parsed.some(
          (entry) =>
            !entry ||
            typeof entry.path !== "string" ||
            !Object.hasOwn(entry, "value")
        )
      )
        throw new Error("INVALID_API_PARAMETERS");
      return updateModelOutlet(saved.model_id, {
        expected_revision: saved.config_revision,
        display_name: name,
        connection,
        thinking_control: thinkingControl,
        thinking_mode: thinkingMode,
        parameter_values: Object.fromEntries(
          Object.entries(values).filter(([entry]) => !deleted.includes(entry))
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
        ...(clearKey ? { api_key: null } : key ? { api_key: key } : {}),
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
      layout="vertical"
      disabled={save.isPending}
      onFinish={() => save.mutate()}
    >
      <Alert
        type="info"
        className="mb-4"
        title={t("modelProfile.parameterPriority")}
      />
      <Alert
        type="info"
        title={profile.identity.request_model_id}
        description={t("modelProfile.frozenRules")}
        className="mb-4"
      />
      <Form.Item label={t("modelProfile.displayName")}>
        <Input value={name} onChange={(event) => setName(event.target.value)} />
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
        help={t("modelProfile.keepKey")}
      >
        <Input.Password
          autoComplete="new-password"
          value={key}
          disabled={clearKey || save.isPending}
          onChange={(event) => setKey(event.target.value)}
        />
      </Form.Item>
      <Collapse
        className="[&_.ant-form-item]:!mb-3 [&_.ant-form-item-label]:!pb-1"
        items={[
          {
            key: "advanced",
            label: t("modelProfile.advanced"),
            children: (
              <>
                <section aria-label={t("modelProfile.modelParameters")}>
                  <h4 className="mb-4 font-semibold">
                    {t("modelProfile.modelParameters")}
                  </h4>
                  <div className="border-l pl-3">
                    <h5 className="mb-2 text-xs font-medium text-muted-foreground">
                      {t("modelProfile.samplingGroup")}
                    </h5>
                    <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2 lg:grid-cols-4">
                      {(saved.field_specs ?? profile.parameter_rules)
                        .filter(
                          (rule) =>
                            (rule.visible ||
                              (rule.key === "top_p" &&
                                rule.allowed_scopes.includes("outlet") &&
                                profile.capabilities.sampling?.top_p?.status !==
                                  "unsupported")) &&
                            rule.ui_group !== "reasoning" &&
                            rule.key !== "max_output_tokens"
                        )
                        .map((rule) => (
                          <ModelParameterField
                            key={rule.key}
                            rule={rule}
                            values={values}
                            resetLabel={t("modelProfile.omitParameter")}
                            pending={save.isPending}
                            onChange={(field, value) => {
                              setValues({ ...values, [field]: value });
                              setDeleted(
                                deleted.filter((entry) => entry !== field)
                              );
                            }}
                            onReset={(field) => {
                              const next = { ...values };
                              delete next[field];
                              setValues(next);
                              setDeleted(
                                Array.from(new Set([...deleted, field]))
                              );
                            }}
                          />
                        ))}
                    </div>
                    <h5 className="mb-2 mt-3 text-xs font-medium text-muted-foreground">
                      {t("modelProfile.thinkingGroup")}
                    </h5>
                    <ModelThinkingSettings
                      rules={profile.parameter_rules}
                      values={values}
                      mode={thinkingMode}
                      pending={save.isPending}
                      onToggle={(enabled) => {
                        if (
                          !profile.parameter_rules.some(
                            (rule) =>
                              rule.key === "enable_thinking" && rule.visible
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
                              ...deleted.filter(
                                (key) => key !== "enable_thinking"
                              ),
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
                        setDeleted(
                          Array.from(new Set([...deleted, ...removed]))
                        );
                      }}
                      onValueChange={(key, value) => {
                        const next = { ...values };
                        if (value === undefined) {
                          delete next[key];
                          setDeleted(Array.from(new Set([...deleted, key])));
                        } else {
                          next[key] = value;
                          setDeleted(deleted.filter((item) => item !== key));
                        }
                        setValues(next);
                      }}
                    />
                    <h5 className="mb-2 mt-3 text-xs font-medium text-muted-foreground">
                      {t("modelProfile.capacityGroup")}
                    </h5>
                    <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2 lg:grid-cols-4">
                      <Form.Item label={t("modelProfile.combined_window")}>
                        <InputNumber
                          className="!w-full"
                          min={1}
                          precision={0}
                          value={limits.combined_window}
                          onChange={(value) =>
                            setLimits({ ...limits, combined_window: value })
                          }
                        />
                      </Form.Item>
                      <Form.Item
                        label={t("modelProfile.maximumOutput")}
                        extra={t("modelProfile.inheritedOutputLimit")}
                      >
                        <InputNumber
                          aria-label={t("modelProfile.maximumOutput")}
                          className="!w-full"
                          min={1}
                          precision={0}
                          value={limits.output_limit ?? null}
                          onChange={(value) =>
                            setLimits({ ...limits, output_limit: value })
                          }
                        />
                      </Form.Item>
                    </div>
                  </div>
                </section>
                <section
                  aria-label={t("modelProfile.requestGroup")}
                  className="mt-4 border-t pt-4"
                >
                  <h4 className="mb-3 font-semibold">
                    {t("modelProfile.requestGroup")}
                  </h4>
                  <div className="border-l pl-3">
                    <h5 className="mb-2 text-xs font-medium text-muted-foreground">
                      {t("modelProfile.httpGroup")}
                    </h5>
                    <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2 lg:grid-cols-4">
                      <Form.Item label={t("modelProfile.clearKey")}>
                        <Switch checked={clearKey} onChange={setClearKey} />
                      </Form.Item>
                      <Form.Item label={t("modelProfile.sslVerify")}>
                        <Switch
                          checked={connection.ssl_verify}
                          onChange={(ssl_verify) =>
                            setConnection({ ...connection, ssl_verify })
                          }
                        />
                      </Form.Item>
                      <Form.Item label={t("modelProfile.timeout")}>
                        <InputNumber
                          className="!w-full"
                          min={1}
                          value={connection.timeout_seconds}
                          onChange={(value) =>
                            value &&
                            setConnection({
                              ...connection,
                              timeout_seconds: value,
                            })
                          }
                        />
                      </Form.Item>
                    </div>
                    <div className="mt-3">
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
                  </div>
                </section>
              </>
            ),
          },
        ]}
      />
      {save.isError && (
        <Alert
          className="mt-4"
          type="error"
          title={t("modelProfile.editFailed")}
        />
      )}
      <div className="mt-4 flex justify-end gap-2">
        <StandardButton disabled={save.isPending} onClick={onClose}>
          {t("common.cancel")}
        </StandardButton>
        <StandardButton
          variant="primary"
          htmlType="submit"
          disabled={!extrasValid}
          loading={save.isPending}
        >
          {t("common.save")}
        </StandardButton>
      </div>
    </ModelOutletForm>
  );
}
