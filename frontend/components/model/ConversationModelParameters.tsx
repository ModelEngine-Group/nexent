// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  parameterIsActive,
  MODEL_TOKEN_LIMIT_KEYS,
} from "@/lib/modelParameterLayers";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Form, Spin } from "antd";
import { useTranslation } from "react-i18next";
import {
  ModelParameterPopover,
  ModelSamplingFields,
} from "@/components/chat/ModelParameterSettings";
import {
  detectThinkingMode,
  thinkingEnabled,
  thinkingDisplayState,
  enabledThinkingEffort,
  thinkingDegreePrefill,
} from "./ModelThinkingSettings";
import { ModelThinkingToggle } from "@/components/chat/ModelThinkingToggle";
import { StandardButton } from "@/components/common/StandardButton";
import {
  getModelOutlet,
  getConversationModelPreferences,
  patchConversationModelPreferences,
} from "@/services/modelProfileService";
import { patchModelDraft, readModelDraft } from "@/lib/conversationModelDrafts";
import type { ConversationModelPreferenceView } from "@/types/modelProfile";
import { ModelParameterField } from "./ModelParameterField";

function usePreferenceView({
  conversationId,
  draftScope,
  modelId,
}: {
  conversationId?: number;
  draftScope?: string;
  modelId: number;
}) {
  const queryKey = [
    "conversation-model-preferences",
    conversationId ?? draftScope,
    modelId,
  ];
  const query = useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      if (conversationId)
        return getConversationModelPreferences(conversationId, modelId, signal);
      const outlet = await getModelOutlet(modelId, signal);
      return {
        version: 0,
        config_revision: outlet.config_revision,
        parameter_values: readModelDraft(draftScope!, modelId),
        defaults: outlet.profile.parameter_values,
        field_specs: outlet.field_specs ?? outlet.profile.parameter_rules,
        issues: [],
        output_limit: outlet.profile.capabilities?.context?.output_limit,
        reasoning_status: outlet.profile.capabilities?.reasoning?.status,
      } satisfies ConversationModelPreferenceView;
    },
    enabled: Boolean(conversationId || draftScope),
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: 0,
  });
  return { query, queryKey };
}

function activeThinkingDegree(
  saved: ConversationModelPreferenceView,
  values: Record<string, unknown>
) {
  const rules = saved.field_specs.filter(
    (rule) =>
      ["reasoning_effort", "reasoning_budget_tokens"].includes(rule.key) &&
      rule.visible &&
      rule.allowed_scopes.includes("conversation") &&
      parameterIsActive(rule.condition, values)
  );
  return rules.find((rule) => Object.hasOwn(values, rule.key)) ?? rules[0];
}

/** The trigger summary observes the same query as the expanded controls. */
export function ConversationModelParameterSummary({
  conversationId,
  draftScope,
  modelId,
  agentDefaults = {},
}: {
  conversationId?: number;
  draftScope?: string;
  modelId: number;
  agentDefaults?: Record<string, unknown>;
}) {
  const { t } = useTranslation();
  const { query } = usePreferenceView({ conversationId, draftScope, modelId });
  if (!query.data || query.isError || query.data.issues.length) return null;
  const values = {
    ...query.data.defaults,
    ...agentDefaults,
    ...query.data.parameter_values,
  };
  if (
    !thinkingEnabled(
      query.data.field_specs,
      values,
      query.data.reasoning_status === "supported"
    )
  )
    return null;
  const degree = activeThinkingDegree(query.data, values);
  const effort =
    degree?.key === "reasoning_effort" ? values.reasoning_effort : undefined;
  const budget =
    degree?.key === "reasoning_budget_tokens"
      ? values.reasoning_budget_tokens
      : undefined;
  const text =
    typeof effort === "string"
      ? t(`modelProfile.thinkingLevel.${effort}`, { defaultValue: effort })
      : typeof budget === "number"
        ? `${budget} Token`
        : undefined;
  return text ? (
    <span className="shrink-0 text-muted-foreground">{text}</span>
  ) : null;
}

export function ConversationModelParameters({
  conversationId,
  draftScope,
  modelId,
  disabled,
  agentDefaults = {},
}: {
  conversationId?: number;
  draftScope?: string;
  modelId: number;
  disabled?: boolean;
  agentDefaults?: Record<string, unknown>;
}) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const client = useQueryClient();
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const { query, queryKey } = usePreferenceView({
    conversationId,
    draftScope,
    modelId,
  });
  const savePreferences = async (request: {
    expected_version: number;
    parameter_values: Record<string, unknown>;
    delete_parameters: string[];
  }) => {
    if (conversationId)
      await patchConversationModelPreferences(conversationId, modelId, request);
    else if (draftScope)
      patchModelDraft(
        draftScope,
        modelId,
        request.parameter_values,
        request.delete_parameters
      );
    else throw new Error("MODEL_PREFERENCE_SCOPE_MISSING");
    await client.invalidateQueries({
      queryKey: conversationId
        ? ["conversation-model-preferences", conversationId]
        : queryKey,
    });
  };
  const quick = useMutation({
    mutationFn: ({
      key,
      value,
      reset = false,
    }: {
      key: string;
      value?: unknown;
      reset?: boolean;
    }) => {
      const removed =
        key === "enable_thinking" && value === false
          ? query
              .data!.field_specs.filter(
                (rule) =>
                  ["reasoning_effort", "reasoning_budget_tokens"].includes(
                    rule.key
                  ) &&
                  rule.editable &&
                  rule.allowed_scopes.includes("conversation")
              )
              .map((rule) => rule.key)
          : [];
      const values: Record<string, unknown> = reset ? {} : { [key]: value };
      if (key === "enable_thinking" && value === true) {
        const effective = {
          ...query.data!.defaults,
          ...agentDefaults,
          ...query.data!.parameter_values,
        };
        const mode = detectThinkingMode(query.data!.field_specs, effective);
        const degreeKey =
          mode === "effort" ? "reasoning_effort" : "reasoning_budget_tokens";
        const rule = query.data!.field_specs.find(
          (item) =>
            item.key === degreeKey &&
            item.editable &&
            item.allowed_scopes.includes("conversation")
        );
        const prefill =
          effective[degreeKey] ??
          thinkingDegreePrefill(rule, mode, query.data!.output_limit);
        if (rule && effective[degreeKey] === undefined && prefill !== undefined)
          values[degreeKey] = prefill;
      }
      return savePreferences({
        expected_version: query.data!.version,
        parameter_values: values,
        delete_parameters: reset ? [key] : removed,
      });
    },
    onError: () => message.error(t("modelProfile.preferencesFailed")),
  });
  const saved = query.data;
  const defaults = { ...saved?.defaults, ...agentDefaults };
  const effective = { ...defaults, ...saved?.parameter_values };
  const state = thinkingDisplayState(
    saved?.field_specs ?? [],
    effective,
    saved?.reasoning_status === "supported"
  );
  const thinkingRule = saved?.field_specs.find(
    (rule) =>
      rule.key === "enable_thinking" &&
      rule.visible &&
      rule.editable &&
      rule.allowed_scopes.includes("conversation")
  );
  const effortRule =
    state.offEffort?.editable &&
    state.offEffort.allowed_scopes.includes("conversation")
      ? state.offEffort
      : undefined;
  const degree = saved ? activeThinkingDegree(saved, effective) : undefined;
  const pending = disabled || quick.isPending || query.isFetching;
  const enabled = state.enabled;
  return (
    <div
      onKeyDown={(event) => {
        if (event.key === "Enter") event.stopPropagation();
      }}
    >
      <div
        data-slot="model-selector-effort"
        className="px-3 pt-1 pb-0"
        title={
          !conversationId && !draftScope
            ? t("modelProfile.loadFailed")
            : undefined
        }
      >
        <ModelThinkingToggle
          checked={enabled}
          disabled={
            state.alwaysOn ||
            pending ||
            advancedOpen ||
            (!conversationId && !draftScope) ||
            (!thinkingRule && !effortRule) ||
            !!saved?.issues.length
          }
          onChange={(enabled) => {
            if (effortRule) {
              const value = enabled
                ? enabledThinkingEffort(effortRule, defaults)
                : "none";
              if (value !== undefined)
                quick.mutate({ key: "reasoning_effort", value });
            } else quick.mutate({ key: "enable_thinking", value: enabled });
          }}
        />
        {(enabled || !!state.offEffort) && degree && (
          <Form
            layout="horizontal"
            colon={false}
            className="[&_.ant-form-item]:!mb-1 [&_.ant-form-item-row]:!flex-nowrap [&_.ant-form-item-row]:!items-center [&_.ant-form-item-label]:!flex-none [&_.ant-form-item-label]:!pb-0 [&_.ant-form-item-label]:!text-left [&_.ant-form-item-control]:!min-w-0 [&_.ant-form-item-control]:!flex-1"
          >
            <ModelParameterField
              rule={degree}
              label={
                degree.key === "reasoning_effort"
                  ? t("chat.modelSelector.reasoningEffort")
                  : undefined
              }
              values={saved?.parameter_values ?? {}}
              fallbackValues={defaults}
              scope="conversation"
              inModelSelector
              pending={pending || advancedOpen}
              onChange={(key, value) => quick.mutate({ key, value })}
              resetLabel={t("modelProfile.useInheritedDefault")}
              onReset={(key) => quick.mutate({ key, reset: true })}
            />
          </Form>
        )}
      </div>
      <ModelParameterPopover
        disabled={pending || (!conversationId && !draftScope)}
        onOpenChange={setAdvancedOpen}
      >
        {() =>
          query.isPending ? (
            <Spin />
          ) : query.isError ? (
            <Alert type="error" title={t("modelProfile.loadFailed")} />
          ) : (
            saved && (
              <PreferenceEditor
                key={`${conversationId}:${modelId}:${saved.version}`}
                onSave={savePreferences}
                saved={{ ...saved, defaults }}
              />
            )
          )
        }
      </ModelParameterPopover>
    </div>
  );
}

function PreferenceEditor({
  onSave,
  saved,
}: {
  onSave: (request: {
    expected_version: number;
    parameter_values: Record<string, unknown>;
    delete_parameters: string[];
  }) => Promise<void>;
  saved: ConversationModelPreferenceView;
}) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const values = saved.parameter_values;
  const save = useMutation({
    mutationFn: (patch: {
      parameter_values: Record<string, unknown>;
      delete_parameters: string[];
    }) => onSave({ expected_version: saved.version, ...patch }),
    onError: () => message.error(t("modelProfile.preferencesFailed")),
  });
  const update = (key: string, value?: unknown) =>
    save.mutate({
      parameter_values: value === undefined ? {} : { [key]: value },
      delete_parameters: value === undefined ? [key] : [],
    });
  const samplingKeys = ["temperature", "top_p"];
  const sampling = Object.fromEntries(
    samplingKeys
      .filter((key) => Object.hasOwn(values, key))
      .map((key) => [key, values[key]])
  );
  const rules = saved.field_specs.filter(
    (rule) =>
      ![
        ...samplingKeys,
        "enable_thinking",
        "reasoning_effort",
        "reasoning_budget_tokens",
        ...MODEL_TOKEN_LIMIT_KEYS,
      ].includes(rule.key) &&
      rule.visible &&
      rule.allowed_scopes.includes("conversation") &&
      (parameterIsActive(rule.condition, { ...saved.defaults, ...values }) ||
        Object.hasOwn(values, rule.key))
  );
  return (
    <div className="space-y-3">
      {!!saved.issues.length && (
        <Alert type="error" title={t("modelProfile.preferencesInvalid")} />
      )}
      <ModelSamplingFields
        value={sampling}
        inheritedValue={saved.defaults}
        defaultValue={{}}
        disabled={save.isPending}
        disabledFields={samplingKeys.filter((key) => {
          const rule = saved.field_specs.find((field) => field.key === key);
          return (
            !rule?.editable || !rule.allowed_scopes.includes("conversation")
          );
        })}
        bounds={Object.fromEntries(
          saved.field_specs
            .filter((rule) => samplingKeys.includes(rule.key))
            .map((rule) => [
              rule.key,
              {
                min:
                  typeof rule.schema.minimum === "number"
                    ? rule.schema.minimum
                    : undefined,
                max:
                  typeof rule.schema.maximum === "number"
                    ? rule.schema.maximum
                    : undefined,
              },
            ])
        )}
        onChange={(next) =>
          save.mutate({
            parameter_values: { ...next },
            delete_parameters: samplingKeys.filter(
              (key) => Object.hasOwn(values, key) && !Object.hasOwn(next, key)
            ),
          })
        }
      />
      {!!rules.length && (
        <Form
          layout="vertical"
          className="[&_.ant-form-item]:!mb-2 [&_.ant-form-item-label]:!pb-1"
        >
          {rules.map((rule) => (
            <ModelParameterField
              key={rule.key}
              rule={rule}
              values={values}
              fallbackValues={saved.defaults}
              scope="conversation"
              inModelSelector
              pending={save.isPending}
              resetLabel={t("modelProfile.useInheritedDefault")}
              onChange={update}
              onReset={(key) => update(key)}
            />
          ))}
        </Form>
      )}
      {Object.keys(values)
        .filter(
          (key) =>
            !saved.field_specs.some(
              (rule) =>
                rule.key === key &&
                rule.visible &&
                rule.allowed_scopes.includes("conversation")
            )
        )
        .map((key) => (
          <Alert
            key={key}
            type="error"
            title={key}
            action={
              <StandardButton onClick={() => update(key)}>
                {t("common.delete")}
              </StandardButton>
            }
          />
        ))}
      {save.isError && (
        <Alert type="error" title={t("modelProfile.preferencesFailed")} />
      )}
    </div>
  );
}
