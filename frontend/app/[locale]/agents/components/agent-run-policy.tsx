"use client";

import { useTranslation } from "react-i18next";
import { Form, InputNumber, Switch, Row, Col, Flex } from "antd";

import { useAgentStore } from "@/stores/agentStore";
import { DEFAULT_AGENT_VERIFICATION_CONFIG } from "@/types/agentConfig";

export default function AgentRunPolicy() {
  const { t } = useTranslation("common");
  const editedAgent = useAgentStore((state) => state.editedAgent!);
  const updateAgent = useAgentStore((state) => state.updateAgentConfig);

  return (
    <div className="w-full">
      <Row gutter={[16, 0]}>
        {/* Max Steps */}
        <Col xs={24}>
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
      </Row>

      {/* Self Validation */}
      <Row gutter={[16, 0]}>
        {/* Provide Run Summary */}
        <Col xs={24} sm={8}>
          <Form.Item
            label={t("agent.provideRunSummary")}
            className="mb-3"
          >
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
