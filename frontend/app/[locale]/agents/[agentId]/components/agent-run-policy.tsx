"use client";

import { useTranslation } from "react-i18next";
import { Checkbox, Form, InputNumber, Switch, Row, Col, Tooltip } from "antd";

import { useAgentStore } from "@/stores/agentStore";
import { useAgentReadOnly } from "@/hooks/agent/useAgentReadOnly";
import { DEFAULT_AGENT_VERIFICATION_CONFIG } from "@/types/agentConfig";
import { AgentDeploymentOptions } from "./agent-deployment";

interface AgentRunPolicyProps {
  highFidelity?: boolean;
}

export function AgentProtocolRepairOption() {
  const { t } = useTranslation("common");
  const editedAgent = useAgentStore((state) => state.editedAgent!);
  const updateAgent = useAgentStore((state) => state.updateAgentConfig);
  const isReadOnly = useAgentReadOnly();

  return (
    <Form.Item
      label={t("agent.runPolicy.protocolRepairRetry")}
      tooltip={t("agent.runPolicy.protocolRepairRetryHint")}
      className="!mb-0"
    >
      <Switch
        checked={editedAgent.enable_protocol_repair_retry ?? false}
        disabled={isReadOnly}
        onChange={(checked) =>
          updateAgent({ enable_protocol_repair_retry: checked })
        }
      />
    </Form.Item>
  );
}

export default function AgentRunPolicy({
  highFidelity = false,
}: AgentRunPolicyProps = {}) {
  const { t } = useTranslation("common");
  const editedAgent = useAgentStore((state) => state.editedAgent!);
  const updateAgent = useAgentStore((state) => state.updateAgentConfig);
  const isReadOnly = useAgentReadOnly();

  if (highFidelity) {
    return (
      <div className="flex w-[296px] max-w-full flex-col gap-4 text-sm leading-[22px] tracking-[0px] text-[#191919] [&_.ant-checkbox-wrapper]:!m-0 [&_.ant-checkbox-wrapper]:!h-[22px] [&_.ant-checkbox-wrapper]:!text-sm [&_.ant-checkbox-wrapper]:!leading-[22px] [&_.ant-checkbox-wrapper]:!text-[#191919] [&_.ant-checkbox-label]:!pl-2 [&_.ant-checkbox-label]:!pr-0">
        <div className="flex flex-col gap-2">
          <label htmlFor="agent-max-step">
            {t("agentConfig.layout.maxRunSteps")}
          </label>
          <InputNumber
            id="agent-max-step"
            min={1}
            max={1000}
            disabled={isReadOnly}
            controls={false}
            suffix={t("agent.runPolicy.maxStepUnit")}
            className="!h-8 !w-full !rounded-[4px] !border-[#c9c9c9] [&_.ant-input-number-input]:!h-[30px] [&_.ant-input-number-suffix]:!ml-[10px]"
            value={editedAgent.max_step || 10}
            onChange={(val) => updateAgent({ max_step: val ?? 10 })}
          />
        </div>
        <div className="flex flex-col gap-2">
          <label htmlFor="agent-requested-output-tokens">
            {t("agentConfig.layout.outputReserve")}
          </label>
          <InputNumber
            id="agent-requested-output-tokens"
            min={128}
            max={32768}
            step={128}
            disabled={isReadOnly}
            controls={false}
            suffix="tokens"
            className="!h-8 !w-full !rounded-[4px] !border-[#c9c9c9] [&_.ant-input-number-input]:!h-[30px] [&_.ant-input-number-suffix]:!ml-[10px]"
            value={editedAgent.requested_output_tokens ?? 4096}
            onChange={(val) =>
              updateAgent({ requested_output_tokens: val ?? 4096 })
            }
          />
        </div>
        <Checkbox
          checked={editedAgent.provide_run_summary}
          disabled={isReadOnly}
          onChange={(event) =>
            updateAgent({ provide_run_summary: event.target.checked })
          }
        >
          {t("agent.highFidelity.runSummary")}
        </Checkbox>
        <Tooltip title={t("agent.allowChatMetadata.tooltip")}>
          <Checkbox
            checked={editedAgent.allow_chat_metadata ?? false}
            disabled={isReadOnly}
            onChange={(event) =>
              updateAgent({ allow_chat_metadata: event.target.checked })
            }
          >
            {t("agent.highFidelity.chatMetadata")}
          </Checkbox>
        </Tooltip>
        <Tooltip title={t("agent.runPolicy.selfValidateHint")}>
          <Checkbox
            checked={editedAgent.verification_config?.enabled ?? false}
            disabled={isReadOnly}
            onChange={(event) =>
              updateAgent({
                verification_config: {
                  ...DEFAULT_AGENT_VERIFICATION_CONFIG,
                  ...(editedAgent.verification_config ?? {}),
                  enabled: event.target.checked,
                },
              })
            }
          >
            {t("agent.highFidelity.selfValidate")}
          </Checkbox>
        </Tooltip>
        <AgentDeploymentOptions highFidelity />
      </div>
    );
  }

  return (
    <div className="w-full">
      <Row gutter={[16, 0]}>
        {/* Max Steps */}
        <Col xs={24} sm={12}>
          <Form.Item
            name="max_step"
            label={t("agent.runPolicy.maxStep")}
            className="mb-3"
          >
            <InputNumber
              min={1}
              max={1000}
              className="flex-1"
              value={editedAgent.max_step || 10}
              onChange={(val) => updateAgent({ max_step: val ?? 10 })}
            />
            <span className="ant-form-text pl-2">
              {t("agent.runPolicy.maxStepUnit")}
            </span>
          </Form.Item>
        </Col>

        {/* Output Reserve */}
        <Col xs={24} sm={12}>
          <Form.Item
            name="requested_output_tokens"
            label={t("agent.requestedOutputTokens")}
            className="mb-3"
          >
            <InputNumber
              min={128}
              max={32768}
              step={128}
              className="w-full"
              value={editedAgent.requested_output_tokens ?? 4096}
              onChange={(val) =>
                updateAgent({ requested_output_tokens: val ?? 4096 })
              }
            />
            <span className="ant-form-tex pl-2">tokens</span>
          </Form.Item>
        </Col>
      </Row>

      {/* Self Validation */}
      <Row gutter={[16, 0]}>
        {/* Provide Run Summary */}
        <Col xs={24} sm={8}>
          <Form.Item label={t("agent.provideRunSummary")} className="mb-3">
            <Switch
              checked={editedAgent.provide_run_summary}
              onChange={(checked) =>
                updateAgent({ provide_run_summary: checked })
              }
            />
          </Form.Item>
        </Col>
        {/* Allow Chat Metadata */}
        <Col xs={24} sm={8}>
          <Form.Item
            label={t("agent.allowChatMetadata")}
            tooltip={t("agent.allowChatMetadata.tooltip")}
            className="mb-3"
          >
            <Switch
              checked={editedAgent.allow_chat_metadata ?? false}
              onChange={(checked) =>
                updateAgent({ allow_chat_metadata: checked })
              }
            />
          </Form.Item>
        </Col>
        <Col xs={24} sm={8}>
          <Form.Item
            label={t("agent.runPolicy.protocolRepairRetry")}
            tooltip={t("agent.runPolicy.protocolRepairRetryHint")}
            className="mb-3"
          >
            <Switch
              checked={editedAgent.enable_protocol_repair_retry ?? false}
              disabled={isReadOnly}
              onChange={(checked) =>
                updateAgent({ enable_protocol_repair_retry: checked })
              }
            />
          </Form.Item>
        </Col>
        <Col xs={24} sm={8}>
          <Form.Item
            label={t("agent.field.selfValidate")}
            tooltip={t("agent.runPolicy.selfValidateHint")}
            className="mb-2"
          >
            <Switch
              checked={editedAgent.verification_config?.enabled ?? false}
              onChange={(checked) =>
                updateAgent({
                  verification_config: {
                    ...DEFAULT_AGENT_VERIFICATION_CONFIG,
                    ...(editedAgent.verification_config ?? {}),
                    enabled: checked,
                  },
                })
              }
            />
          </Form.Item>
        </Col>
      </Row>
    </div>
  );
}
