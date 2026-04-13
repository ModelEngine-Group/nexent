"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Form, Input, Button, Switch, message } from "antd";
import { useQueryClient } from "@tanstack/react-query";

const { TextArea } = Input;

import { publishVersion, updateVersion } from "@/services/agentVersionService";
import { useAgentVersionList } from "@/hooks/agent/useAgentVersionList";
import A2AServerSettingsPanel from "../components/a2a/A2AServerSettingsPanel";
import log from "@/lib/logger";

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
  const [isA2AAgent, setIsA2AAgent] = useState(false);
  const [showA2ASettings, setShowA2ASettings] = useState(false);
  const [publishedAgentName, setPublishedAgentName] = useState("");
  const [a2aAgentInfo, setA2aAgentInfo] = useState<{
    endpoint_id: string;
    agent_id: number;
  } | null>(null);
  const [a2aAgentCard, setA2aAgentCard] = useState<{
    endpoint_id: string;
    name: string;
    description?: string;
    version?: string;
    streaming?: boolean;
    agent_card_url: string | null;
    rest_endpoints: {
      message_send: string;
      message_stream: string;
      tasks_get: string;
    };
    jsonrpc_url: string;
    jsonrpc_methods: string[];
  } | undefined>(undefined);

  // Reset form when modal opens or initialValues changes
  useEffect(() => {
    if (open) {
      if (isEdit && initialValues) {
        publishForm.setFieldsValue(initialValues);
      } else if (!isEdit) {
        publishForm.resetFields();
      }
      setIsA2AAgent(false);
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
      const publishParams = {
        ...values,
        publish_as_a2a: isA2AAgent,
      };
      const result = await publishVersion(agentId, publishParams);
      if (result.success) {
        message.success(t("agent.version.publishSuccess"));
        setPublishedAgentName(values.version_name || "");
        if (isA2AAgent && result.data?.a2a_agent) {
          setA2aAgentInfo({
            endpoint_id: result.data.a2a_agent.endpoint_id,
            agent_id: result.data.a2a_agent.agent_id,
          });
          // Set Agent Card data from backend response
          if (result.data?.a2a_agent_card) {
            setA2aAgentCard(result.data.a2a_agent_card);
          }
          onClose();
          publishForm.resetFields();
          onPublished?.();
          queryClient.invalidateQueries({ queryKey: ["agents"] });
          queryClient.invalidateQueries({ queryKey: ["publishedAgentsList"] });
          setShowA2ASettings(true);
        } else {
          onClose();
          publishForm.resetFields();
          onPublished?.();
          queryClient.invalidateQueries({ queryKey: ["agents"] });
          queryClient.invalidateQueries({ queryKey: ["publishedAgentsList"] });
        }
      } else {
        message.error(result.message || t("agent.version.publishFailed"));
      }
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
    <>
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

          <Form.Item
            label={t("agent.version.publishAsA2AAgent")}
            name="publish_as_a2a"
            valuePropName="checked"
          >
            <Switch
              checked={isA2AAgent}
              onChange={(checked) => setIsA2AAgent(checked)}
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

      <Modal
        centered
        width={640}
        title={t("a2a.server.previewTitle")}
        open={showA2ASettings}
        onCancel={() => setShowA2ASettings(false)}
        footer={null}
        destroyOnHidden
      >
        {showA2ASettings && agentId && (
          <A2AServerSettingsPanel
            agentId={agentId}
            agentName={publishedAgentName}
            endpointId={a2aAgentInfo?.endpoint_id}
            a2aAgentCard={a2aAgentCard ?? undefined}
          />
        )}
      </Modal>
    </>
  );
}
