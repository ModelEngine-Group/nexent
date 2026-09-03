"use client";

import { useTranslation } from "react-i18next";
import { Form, InputNumber, Switch, Row, Col, Flex, Alert } from "antd";
import { Info } from "lucide-react";

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
            label={t("agent.field.maxStep")}
            className="mb-3"
          >
            <InputNumber
              min={1}
              max={1000}
              className="w-full"
              value={editedAgent.max_step || 10}
              onChange={(val) => updateAgent({ max_step: val ?? 10 })}
              addonAfter={t("agent.field.maxStepUnit")}
            />
          </Form.Item>
        </Col>
      </Row>

      {/* Self Validation */}
      <Row gutter={[16, 0]}>
        {/* Provide Run Summary */}
        <Col xs={24} sm={12}>
          <Form.Item
            label={t("agent.field.provideRunSummary")}
            className="mb-3"
          >
            <Flex align="center" gap={8}>
              <Switch
                checked={editedAgent.provide_run_summary}
                onChange={(checked) =>
                  updateAgent({ provide_run_summary: checked })
                }
              />
              <span className="text-xs text-gray-500">
                {editedAgent.provide_run_summary
                  ? t("common.enabled")
                  : t("common.disabled")}
              </span>
            </Flex>
          </Form.Item>
        </Col>
        <Col xs={24} sm={12}>
          <Form.Item label={t("agent.field.selfValidate")} className="mb-2">
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
          {editedAgent.verification_config?.enabled && (
            <Alert
              type="info"
              icon={<Info size={14} />}
              message={t("agent.field.selfValidateHint")}
              className="mt-1"
            />
          )}
        </Col>
      </Row>
    </div>
  );
}
