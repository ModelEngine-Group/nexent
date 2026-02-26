"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Form, Input, Button, message } from "antd";
import { useQueryClient } from "@tanstack/react-query";

import { publishVersion } from "@/services/agentVersionService";
import log from "@/lib/logger";

const { TextArea } = Input;

export interface AgentVersionPubulishModalProps {
  open: boolean;
  onClose: () => void;
  agentId?: number | null;
  onPublished?: () => void;
}

export default function AgentVersionPubulishModal({
  open,
  onClose,
  agentId,
  onPublished,
}: AgentVersionPubulishModalProps) {
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();

  const [isPublishing, setIsPublishing] = useState(false);
  const [publishForm] = Form.useForm();

  const handlePublish = async (values: { version_name?: string; release_note?: string }) => {
    if (!agentId) {
      message.error(t("agent.error.agentNotFound"));
      return;
    }

    if (isPublishing) {
      log.warn("Publish request already in progress, ignoring duplicate click");
      return;
    }

    try {
      setIsPublishing(true);
      await publishVersion(agentId, values);
      message.success(t("agent.version.publishSuccess"));
      onClose();
      publishForm.resetFields();
      onPublished?.();
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      queryClient.invalidateQueries({ queryKey: ["publishedAgentsList"] });
    } catch (error) {
      log.error("Failed to publish version:", error);
      message.error(t("agent.version.publishFailed"));
    } finally {
      setIsPublishing(false);
    }
  };

  return (
    <Modal
      centered
      title={t("agent.version.publish")}
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
    >
      <Form
        form={publishForm}
        layout="vertical"
        onFinish={handlePublish}
      >
        <Form.Item
          label={t("agent.version.versionName")}
          name="version_name"
          rules={[{ required: true, message: t("agent.version.versionNameRequired") }]}
        >
          <Input placeholder={t("agent.version.versionNamePlaceholder")} />
        </Form.Item>
        <Form.Item
          label={t("agent.version.releaseNote")}
          name="release_note"
        >
          <TextArea
            rows={4}
            placeholder={t("agent.version.releaseNotePlaceholder")}
          />
        </Form.Item>
        <Form.Item className="mb-0">
          <div className="flex justify-end gap-2">
            <Button onClick={onClose} disabled={isPublishing}>
              {t("common.cancel")}
            </Button>
            <Button
              type="primary"
              htmlType="submit"
              loading={isPublishing}
              disabled={isPublishing}
            >
              {t("common.confirm")}
            </Button>
          </div>
        </Form.Item>
      </Form>
    </Modal>
  );
}

