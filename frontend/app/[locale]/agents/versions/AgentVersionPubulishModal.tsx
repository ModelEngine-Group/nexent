"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Form, Input, Button, message } from "antd";
import { useQueryClient } from "@tanstack/react-query";

import { publishVersion, updateVersion } from "@/services/agentVersionService";
import { useAgentVersionList } from "@/hooks/agent/useAgentVersionList";
import log from "@/lib/logger";

const { TextArea } = Input;

export interface AgentVersionPubulishModalProps {
  open: boolean;
  onClose: () => void;
  agentId?: number | null;
  versionNo?: number | null;
  isEdit?: boolean;
  initialValues?: {
    version_name?: string;
    release_note?: string;
  };
  onPublished?: () => void;
  onUpdated?: () => void;
}

export default function AgentVersionPubulishModal({
  open,
  onClose,
  agentId,
  versionNo,
  isEdit = false,
  initialValues,
  onPublished,
  onUpdated,
}: AgentVersionPubulishModalProps) {
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();

  // Get version list for duplicate name validation
  const { agentVersionList } = useAgentVersionList(agentId ?? null);

  const [isLoading, setIsLoading] = useState(false);
  const [publishForm] = Form.useForm();

  // Reset form when modal opens or initialValues changes
  useEffect(() => {
    if (open) {
      if (isEdit && initialValues) {
        publishForm.setFieldsValue(initialValues);
      } else if (!isEdit) {
        publishForm.resetFields();
      }
    }
  }, [open, isEdit, initialValues, publishForm]);

  // Custom validator for duplicate version name
  const validateVersionName = {
    validator(_: unknown, value: string) {
      if (!value) {
        return Promise.resolve();
      }

      // Find duplicate version name (exclude current version if editing)
      const duplicate = (agentVersionList || []).find(
        (v) =>
          v.version_name?.toLowerCase() === value.toLowerCase() &&
          (!isEdit || v.version_no !== versionNo)
      );

      if (duplicate) {
        return Promise.reject(new Error(t("agent.version.versionNameDuplicate")));
      }

      return Promise.resolve();
    },
  };

  const handleSubmit = async (values: { version_name?: string; release_note?: string }) => {
    if (isEdit) {
      await handleUpdate(values);
    } else {
      await handlePublish(values);
    }
  };

  const handlePublish = async (values: { version_name?: string; release_note?: string }) => {
    if (!agentId) {
      message.error(t("agent.error.agentNotFound"));
      return;
    }

    if (isLoading) {
      log.warn("Publish request already in progress, ignoring duplicate click");
      return;
    }

    try {
      setIsLoading(true);
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
      setIsLoading(false);
    }
  };

  const handleUpdate = async (values: { version_name?: string; release_note?: string }) => {
    if (!agentId || !versionNo) {
      message.error(t("agent.error.agentNotFound"));
      return;
    }

    if (isLoading) {
      log.warn("Update request already in progress, ignoring duplicate click");
      return;
    }

    try {
      setIsLoading(true);
      const result = await updateVersion(agentId, versionNo, values);
      if (result.success) {
        message.success(t("agent.version.updateSuccess"));
        onClose();
        publishForm.resetFields();
        onUpdated?.();
        queryClient.invalidateQueries({ queryKey: ["agents"] });
        queryClient.invalidateQueries({ queryKey: ["publishedAgentsList"] });
      } else {
        message.error(result.message || t("agent.version.updateFailed"));
      }
    } catch (error) {
      log.error("Failed to update version:", error);
      message.error(t("agent.version.updateFailed"));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Modal
      centered
      title={isEdit ? t("common.edit") : t("agent.version.publish")}
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
    >
      <Form
        form={publishForm}
        layout="vertical"
        onFinish={handleSubmit}
      >
        <Form.Item
          label={t("agent.version.versionName")}
          name="version_name"
          rules={[
            { required: true, message: t("agent.version.versionNameRequired") },
            validateVersionName,
          ]}
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
            <Button onClick={onClose} disabled={isLoading}>
              {t("common.cancel")}
            </Button>
            <Button
              type="primary"
              htmlType="submit"
              loading={isLoading}
              disabled={isLoading}
            >
              {isEdit ? t("common.confirm") : t("agent.version.publish")}
            </Button>
          </div>
        </Form.Item>
      </Form>
    </Modal>
  );
}
