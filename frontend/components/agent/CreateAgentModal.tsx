"use client";

import { useEffect } from "react";
import { App, Form, Input, Modal } from "antd";
import { useTranslation } from "react-i18next";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import {
  AGENT_NAME_MAX_LENGTH,
  createAgentNameConflictValidator,
  isValidAgentDisplayName,
  isValidAgentName,
} from "@/hooks/agent/useSaveGuard";
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
          validateTrigger={["onChange", "onBlur"]}
          rules={[
            {
              required: true,
              whitespace: true,
              message: t("agent.validation.displayNameRequired"),
            },
            {
              validator: (_, value: string) =>
                !value || isValidAgentDisplayName(value)
                  ? Promise.resolve()
                  : Promise.reject(
                      new Error(
                        t("agent.validation.displayNameMaxLength", {
                          max: AGENT_NAME_MAX_LENGTH,
                        })
                      )
                    ),
            },
            {
              ...createAgentNameConflictValidator(t, "display_name"),
              validateTrigger: "onBlur",
            },
          ]}
        >
          <Input
            autoFocus
            maxLength={AGENT_NAME_MAX_LENGTH}
            showCount
            placeholder={t("agent.displayNamePlaceholder")}
          />
        </Form.Item>
        <Form.Item
          name="name"
          label={t("agent.name")}
          validateTrigger={["onChange", "onBlur"]}
          rules={[
            {
              required: true,
              whitespace: true,
              message: t("agent.validation.nameRequired"),
            },
            {
              validator: (_, value: string) =>
                !value || isValidAgentName(value)
                  ? Promise.resolve()
                  : Promise.reject(new Error(t("agent.validation.namePattern"))),
            },
            {
              ...createAgentNameConflictValidator(t, "name"),
              validateTrigger: "onBlur",
            },
          ]}
        >
          <Input
            maxLength={AGENT_NAME_MAX_LENGTH}
            showCount
            placeholder={t("agent.namePlaceholder")}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
