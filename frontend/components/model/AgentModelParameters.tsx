// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Form, InputNumber, Modal, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { getModelOutlet } from "@/services/modelProfileService";
import {
  agentParameterValues,
  parameterIsActive,
  withAgentParameterValues,
} from "@/lib/modelParameterLayers";
import type { ModelOutletResponse } from "@/types/modelProfile";
import { StandardButton } from "@/components/common/StandardButton";
import { ModelParameterField } from "./ModelParameterField";

interface Props {
  modelId: number;
  name: string;
  value: Record<string, unknown>;
  disabled?: boolean;
  onApply: (entry: Record<string, unknown>) => void;
  onClose: () => void;
}

/** The Agent page owns saving/publishing; this editor only applies a local draft. */
export function AgentModelParameters(props: Props) {
  const { t } = useTranslation();
  const query = useQuery({
    queryKey: ["model-outlet", props.modelId],
    queryFn: ({ signal }) => getModelOutlet(props.modelId, signal),
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  return (
    <Modal
      open
      centered
      title={`${props.name} · ${t("modelProfile.agentParameters")}`}
      onCancel={props.onClose}
      footer={null}
      destroyOnHidden
    >
      {query.isFetching ? (
        <Spin />
      ) : query.isError ? (
        <Alert type="error" title={t("modelProfile.loadFailed")} />
      ) : (
        query.data && (
          <Editor
            key={`${props.modelId}:${query.data.config_revision}`}
            {...props}
            outlet={query.data}
          />
        )
      )}
    </Modal>
  );
}

function Editor({
  value,
  disabled,
  onApply,
  onClose,
  outlet,
}: Props & { outlet: ModelOutletResponse }) {
  const { t } = useTranslation();
  const [parameters, setParameters] = useState(() =>
    agentParameterValues(value)
  );
  const [window, setWindow] = useState<number | undefined>(() =>
    typeof value.context_window_tokens === "number"
      ? value.context_window_tokens
      : undefined
  );
  const [edited, setEdited] = useState(false);
  const defaults = outlet.profile.parameter_values;
  const rules = outlet.profile.parameter_rules.filter(
    (rule) =>
      rule.visible &&
      rule.editable &&
      rule.allowed_scopes.includes("conversation") &&
      Object.hasOwn(agentParameterValues({ [rule.key]: true }), rule.key)
  );
  const contextDefault = outlet.profile.capabilities.context.combined_window;
  const effective = { ...defaults, ...parameters };
  return (
    <Form
      layout="vertical"
      onFinish={() => {
        const next = edited
          ? withAgentParameterValues(value, parameters)
          : { ...value };
        if (window === undefined) delete next.context_window_tokens;
        else next.context_window_tokens = window;
        onApply(next);
        onClose();
      }}
    >
      <Alert
        type="info"
        className="mb-4"
        title={t("modelProfile.parameterPriority")}
        description={t("modelProfile.agentParametersScope")}
      />
      {rules
        .filter(
          (rule) =>
            parameterIsActive(rule.condition, effective) ||
            Object.hasOwn(parameters, rule.key)
        )
        .map((rule) => (
          <ModelParameterField
            key={rule.key}
            rule={rule}
            values={parameters}
            fallbackValues={defaults}
            scope="conversation"
            pending={disabled}
            resetLabel={t("modelProfile.useOutletDefault")}
            onChange={(key, next) => {
              setEdited(true);
              const changed = { ...parameters, [key]: next };
              if (key === "enable_thinking" && next === false) {
                delete changed.reasoning_effort;
                delete changed.reasoning_budget_tokens;
              }
              setParameters(changed);
            }}
            onReset={(key) => {
              setEdited(true);
              const next = { ...parameters };
              delete next[key];
              setParameters(next);
            }}
          />
        ))}
      <Form.Item label={t("modelProfile.agentContextWindow")}>
        <div className="flex items-center gap-2">
          <InputNumber
            aria-label="context_window_tokens"
            min={1}
            precision={0}
            value={window ?? contextDefault}
            disabled={disabled}
            onChange={(next) => setWindow(next ?? undefined)}
          />
          {window !== undefined && (
            <StandardButton
              disabled={disabled}
              onClick={() => setWindow(undefined)}
            >
              {t("modelProfile.useOutletDefault")}
            </StandardButton>
          )}
        </div>
      </Form.Item>
      <StandardButton variant="primary" htmlType="submit" disabled={disabled}>
        {t("common.confirm")}
      </StandardButton>
    </Form>
  );
}
