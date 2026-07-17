"use client";

import { useEffect } from "react";
import { Form, Input, InputNumber, Modal, Select } from "antd";
import { useTranslation } from "react-i18next";

import type {
  AgentAutomationProposalData,
  UpdateAutomationProposalPayload,
} from "@/types/agentAutomation";
import {
  AutomationProposalFormValues,
  formValuesToProposalPatch,
  proposalToFormValues,
} from "../scheduleForm";

interface AutomationProposalEditorProps {
  proposal: AgentAutomationProposalData;
  open: boolean;
  saving: boolean;
  onCancel: () => void;
  onSave: (payload: UpdateAutomationProposalPayload) => Promise<void>;
}

export default function AutomationProposalEditor({
  proposal,
  open,
  saving,
  onCancel,
  onSave,
}: AutomationProposalEditorProps) {
  const { t } = useTranslation("common");
  const [form] = Form.useForm<AutomationProposalFormValues>();

  useEffect(() => {
    if (open && proposal.task?.schedule_trigger) {
      form.setFieldsValue(proposalToFormValues(proposal));
    }
  }, [form, open, proposal]);

  const handleSave = async () => {
    const values = await form.validateFields();
    const trigger = proposal.task?.schedule_trigger;
    if (!trigger) return;
    await onSave(formValuesToProposalPatch(values, trigger));
  };

  return (
    <Modal
      title={t("agentAutomation.proposal.editorTitle")}
      open={open}
      confirmLoading={saving}
      okText={t("agentAutomation.proposal.saveChanges")}
      cancelText={t("common.cancel")}
      onCancel={onCancel}
      onOk={handleSave}
      width={680}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" className="pt-2">
        <Form.Item
          name="title"
          label={t("agentAutomation.proposal.taskTitle")}
          rules={[{ required: true, whitespace: true }]}
        >
          <Input maxLength={100} />
        </Form.Item>
        <Form.Item
          name="instruction"
          label={t("agentAutomation.proposal.instruction")}
          rules={[{ required: true, whitespace: true }]}
        >
          <Input.TextArea rows={4} maxLength={2000} showCount />
        </Form.Item>
        <Form.Item
          name="mode"
          label={t("agentAutomation.proposal.scheduleMode")}
          rules={[{ required: true }]}
        >
          <Select
            options={[
              {
                label: t("agentAutomation.proposal.once"),
                value: "ONCE",
              },
              {
                label: t("agentAutomation.proposal.recurring"),
                value: "RECURRING",
              },
            ]}
          />
        </Form.Item>
        <Form.Item
          noStyle
          shouldUpdate={(previous, current) =>
            previous.mode !== current.mode ||
            previous.rule_type !== current.rule_type
          }
        >
          {({ getFieldValue }) => (
            <>
              <Form.Item
                name="start_at"
                label={t("agentAutomation.proposal.startAt")}
                rules={[{ required: true }]}
              >
                <Input type="datetime-local" />
              </Form.Item>
              <Form.Item
                name="timezone"
                label={t("agentAutomation.proposal.timezone")}
                rules={[{ required: true, whitespace: true }]}
              >
                <Input />
              </Form.Item>
              {getFieldValue("mode") === "RECURRING" && (
                <>
                  <Form.Item
                    name="rule_type"
                    label={t("agentAutomation.proposal.ruleType")}
                    rules={[{ required: true }]}
                  >
                    <Select
                      options={[
                        {
                          label: t("agentAutomation.proposal.cron"),
                          value: "CRON",
                        },
                        {
                          label: t("agentAutomation.proposal.interval"),
                          value: "INTERVAL",
                        },
                      ]}
                    />
                  </Form.Item>
                  {getFieldValue("rule_type") === "INTERVAL" ? (
                    <Form.Item
                      name="interval_seconds"
                      label={t("agentAutomation.proposal.intervalSeconds")}
                      rules={[{ required: true }]}
                    >
                      <InputNumber min={60} className="w-full" />
                    </Form.Item>
                  ) : (
                    <Form.Item
                      name="cron_expr"
                      label={t("agentAutomation.proposal.cronExpression")}
                      rules={[{ required: true, whitespace: true }]}
                    >
                      <Input placeholder="0 9 * * *" />
                    </Form.Item>
                  )}
                </>
              )}
            </>
          )}
        </Form.Item>
      </Form>
    </Modal>
  );
}
