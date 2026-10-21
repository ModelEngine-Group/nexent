// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Form, Modal, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { getModelOutlet } from "@/services/modelProfileService";
import {
  agentParameterValues,
  AGENT_PARAMETER_KEYS,
  parameterIsActive,
  withAgentParameterValues,
} from "@/lib/modelParameterLayers";
import {
  ModelThinkingSettings,
  thinkingDegreeKeys,
} from "./ModelThinkingSettings";
import type {
  ModelOutletResponse,
  ThinkingDegreeMode,
} from "@/types/modelProfile";
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
  const [edited, setEdited] = useState(false);
  const [thinkingMode, setThinkingMode] = useState<ThinkingDegreeMode>();
  const defaults = outlet.profile.parameter_values;
  const thinkingKeys = ["enable_thinking", ...thinkingDegreeKeys];
  const rules = outlet.profile.parameter_rules.filter(
    (rule) =>
      rule.visible &&
      rule.allowed_scopes.includes("conversation") &&
      AGENT_PARAMETER_KEYS.includes(rule.key)
  );
  const change = (patch: Record<string, unknown>, removed: string[] = []) => {
    setEdited(true);
    setParameters((previous) => {
      const next = { ...previous, ...patch };
      removed.forEach((key) => delete next[key]);
      return next;
    });
  };
  const effective = { ...defaults, ...parameters };
  return (
    <Form
      layout="vertical"
      onFinish={() => {
        const next = edited
          ? withAgentParameterValues(value, parameters)
          : { ...value };
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
            !thinkingKeys.includes(rule.key) &&
            (parameterIsActive(rule.condition, effective) ||
              Object.hasOwn(parameters, rule.key))
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
            onChange={(key, next) => change({ [key]: next })}
            onReset={(key) => change({}, [key])}
          />
        ))}
      {rules.some((rule) => thinkingKeys.includes(rule.key)) && (
        <ModelThinkingSettings
          declaredControlsOnly
          rules={rules}
          values={parameters}
          defaults={defaults}
          mode={thinkingMode}
          outputLimit={outlet.profile.capabilities.context.output_limit}
          pending={disabled}
          onToggle={(enabled) =>
            change(
              { enable_thinking: enabled },
              enabled ? [] : thinkingDegreeKeys
            )
          }
          onModeChange={(mode) => {
            setThinkingMode(mode);
            change({}, thinkingDegreeKeys);
          }}
          onValueChange={(key, next) =>
            next === undefined ? change({}, [key]) : change({ [key]: next })
          }
        />
      )}
      {!disabled &&
        thinkingKeys.some((key) => Object.hasOwn(parameters, key)) && (
          <StandardButton
            onClick={() => {
              setThinkingMode(undefined);
              change({}, thinkingKeys);
            }}
          >
            {t("modelProfile.useOutletDefault")}
          </StandardButton>
        )}
      <StandardButton variant="primary" htmlType="submit" disabled={disabled}>
        {t("common.confirm")}
      </StandardButton>
    </Form>
  );
}
