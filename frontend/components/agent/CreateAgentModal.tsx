"use client";

import { useEffect } from "react";
import { App, Form, Input, Modal } from "antd";
import { useTranslation } from "react-i18next";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { updateAgentInfo } from "@/services/agentConfigService";

export interface CreatedAgentResult {
  agentId: number;
  name: string;
  displayName: string;
}

interface CreateAgentModalProps {
  open: boolean;
  onCancel: () => void;
  onCreated: (agent: CreatedAgentResult) => void | Promise<void>;
}

interface CreateAgentFormValues {
  displayName: string;
  name: string;
}

export default function CreateAgentModal({
  open,
  onCancel,
  onCreated,
}: CreateAgentModalProps) {
  const { t } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const { message } = App.useApp();
  const [form] = Form.useForm<CreateAgentFormValues>();

  useEffect(() => {
    if (open) {
      form.resetFields();
    }
  }, [form, open]);

  const handleSubmit = async () => {
    const values = await form.validateFields();
    const result = await updateAgentInfo({
      name: values.name.trim(),
      display_name: values.displayName.trim(),
      description: "",
      author: user?.email || "",
      max_steps: 15,
      is_main_agent: true,
      provide_run_summary: false,
      enabled: true,
    });

    if (!result.success || !result.data?.agent_id) {
      message.error(result.message || t("businessLogic.config.error.saveFailed"));
      return;
    }

    await onCreated({
      agentId: Number(result.data.agent_id),
      name: values.name.trim(),
      displayName: values.displayName.trim(),
    });
  };

  return (
    <Modal
      open={open}
      centered
      title={t("chat.agentLanding.createAgent")}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      onCancel={onCancel}
      onOk={() => void handleSubmit()}
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item
          name="displayName"
          label={t("agent.displayName")}
          rules={[{ required: true, whitespace: true, message: t("agent.info.name.error.empty") }]}
        >
          <Input autoFocus maxLength={100} placeholder={t("agent.displayNamePlaceholder")} />
        </Form.Item>
        <Form.Item
          name="name"
          label={t("agent.name")}
          rules={[
            { required: true, whitespace: true, message: t("agent.info.name.error.empty") },
            {
              pattern: /^[A-Za-z_][A-Za-z0-9_]*$/,
              message: t("agent.info.name.error.format"),
            },
          ]}
        >
          <Input maxLength={100} placeholder={t("agent.namePlaceholder")} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
