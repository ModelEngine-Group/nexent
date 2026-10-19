// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { parameterIsActive } from "@/lib/modelParameterLayers";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Form, Modal, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { StandardButton } from "@/components/common/StandardButton";
import {
  getConversationModelPreferences,
  patchConversationModelPreferences,
} from "@/services/modelProfileService";
import type { ConversationModelPreferenceView } from "@/types/modelProfile";
import { ModelParameterField } from "./ModelParameterField";

export function ConversationModelParameters({
  conversationId,
  modelId,
  disabled,
  agentDefaults = {},
}: {
  conversationId?: number;
  modelId: number;
  disabled?: boolean;
  agentDefaults?: Record<string, unknown>;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: ["conversation-model-preferences", conversationId, modelId],
    queryFn: ({ signal }) =>
      getConversationModelPreferences(conversationId!, modelId, signal),
    enabled: open && Boolean(conversationId),
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: 0,
  });
  return (
    <>
      <StandardButton
        disabled={disabled || !conversationId}
        title={
          !conversationId ? t("modelProfile.preferencesAfterCreate") : undefined
        }
        onClick={() => setOpen(true)}
      >
        {t("modelProfile.parameters")}
      </StandardButton>
      <Modal
        centered
        open={open}
        onCancel={() => setOpen(false)}
        title={t("modelProfile.sessionParameters")}
        footer={null}
        destroyOnHidden
      >
        {query.isFetching ? (
          <Spin />
        ) : query.isError ? (
          <Alert type="error" title={t("modelProfile.loadFailed")} />
        ) : (
          query.data &&
          conversationId && (
            <PreferenceEditor
              key={`${conversationId}:${modelId}:${query.data.version}`}
              conversationId={conversationId}
              modelId={modelId}
              saved={{
                ...query.data,
                defaults: { ...query.data.defaults, ...agentDefaults },
              }}
              onDone={() => setOpen(false)}
            />
          )
        )}
      </Modal>
    </>
  );
}

function PreferenceEditor({
  conversationId,
  modelId,
  saved,
  onDone,
}: {
  conversationId: number;
  modelId: number;
  saved: ConversationModelPreferenceView;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const client = useQueryClient();
  const [values, setValues] = useState(saved.parameter_values);
  const [removed, setRemoved] = useState<string[]>([]);
  const save = useMutation({
    mutationFn: () =>
      patchConversationModelPreferences(conversationId, modelId, {
        expected_version: saved.version,
        parameter_values: values,
        delete_parameters: removed,
      }),
    onSuccess: async () => {
      await client.invalidateQueries({
        queryKey: ["conversation-model-preferences", conversationId],
      });
      onDone();
    },
    onError: () => {
      message.error(t("modelProfile.preferencesFailed"));
    },
  });
  return (
    <Form layout="vertical" onFinish={() => save.mutate()}>
      <Alert
        type={saved.issues.length ? "error" : "info"}
        className="mb-4"
        title={t(
          saved.issues.length
            ? "modelProfile.preferencesInvalid"
            : "modelProfile.preferencesScope"
        )}
      />
      <p className="text-xs text-gray-500 mb-4">
        {t("modelProfile.parameterPriority")}
      </p>
      {saved.field_specs
        .filter(
          (rule) =>
            rule.visible &&
            rule.allowed_scopes.includes("conversation") &&
            (parameterIsActive(rule.condition, {
              ...saved.defaults,
              ...values,
            }) ||
              Object.hasOwn(values, rule.key))
        )
        .map((rule) => (
          <ModelParameterField
            key={rule.key}
            rule={rule}
            values={values}
            fallbackValues={saved.defaults}
            resetLabel={t("modelProfile.useInheritedDefault")}
            scope="conversation"
            pending={save.isPending}
            onChange={(key, value) => {
              const next = { ...values, [key]: value };
              const inactive =
                key === "enable_thinking" && value === false
                  ? ["reasoning_effort", "reasoning_budget_tokens"]
                  : [];
              inactive.forEach((field) => delete next[field]);
              setValues(next);
              setRemoved(
                Array.from(
                  new Set([
                    ...removed.filter((entry) => entry !== key),
                    ...inactive,
                  ])
                )
              );
            }}
            onReset={(key) => {
              const next = { ...values };
              delete next[key];
              setValues(next);
              setRemoved(Array.from(new Set([...removed, key])));
            }}
          />
        ))}
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
              <StandardButton
                onClick={() => {
                  const next = { ...values };
                  delete next[key];
                  setValues(next);
                  setRemoved(Array.from(new Set([...removed, key])));
                }}
              >
                {t("common.delete")}
              </StandardButton>
            }
          />
        ))}
      {save.isError && (
        <Alert
          type="error"
          title={t("modelProfile.preferencesFailed")}
          className="my-4"
        />
      )}
      <StandardButton
        variant="primary"
        htmlType="submit"
        loading={save.isPending}
      >
        {t("common.save")}
      </StandardButton>
    </Form>
  );
}
