"use client";
import { useState } from "react";
import {
  GitBranch,
  GitCompare,
  Rocket,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  Card,
  Flex,
  Button,
  Tag,
  Typography,
  Empty,
  Spin,
  Modal,
  Form,
  Input,
  message,
} from "antd";
import { useAgentVersionList } from "@/hooks/agent/useAgentVersionList";
import { publishVersion } from "@/services/agentVersionService";
import { useAgentInfo } from "@/hooks/agent/useAgentInfo";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { VersionCardItem } from "./AgentVersionCard";
import log from "@/lib/logger";
import { useQueryClient } from "@tanstack/react-query";

const { TextArea } = Input;

export default function AgentVersionManage() {
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();

  const currentAgentId = useAgentConfigStore((state) => state.currentAgentId);

  const { agentVersionList, total, isLoading, invalidate: invalidateAgentVersionList } = useAgentVersionList(currentAgentId);
  const { agentInfo, invalidate: invalidateAgentInfo } = useAgentInfo(currentAgentId);


  const [isPublishModalOpen, setIsPublishModalOpen] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [publishForm] = Form.useForm();

  // Open publish modal
  const handlePublishClick = () => {
    setIsPublishModalOpen(true);
  };

  // Handle publish version
  const handlePublish = async (values: { version_name?: string; release_note?: string }) => {
    if (!currentAgentId) {
      message.error(t("agent.error.agentNotFound"));
      return;
    }

    // Prevent duplicate submissions
    if (isPublishing) {
      log.warn("Publish request already in progress, ignoring duplicate click");
      return;
    }

    try {
      setIsPublishing(true);
      await publishVersion(currentAgentId, values);
      message.success(t("agent.version.publishSuccess"));
      setIsPublishModalOpen(false);
      publishForm.resetFields();
      invalidateAgentVersionList();
      invalidateAgentInfo();
      queryClient.invalidateQueries({ queryKey: ["agents"] });
    } catch (error) {
      log.error("Failed to publish version:", error);
      message.error(t("agent.version.publishFailed"));
    } finally {
      setIsPublishing(false);
    }
  };

  const footer = [
    <Flex
      align="center"
      justify="space-between"
      gap={8}
      className="pl-4"
      key="actions"
    >
      <Tag color="blue">
        {t("agent.version.totalVersions", { count: total })}
      </Tag>
      <Button
        type="text"
        icon={<GitCompare size={16} />}
        onClick={() => {
          log.info("Version comparison");
        }}
      >
        {t("agent.version.compare")}
      </Button>
    </Flex>,
  ];

  return (
    <>
      <Card
        className="h-full min-h-0"
        style={{ minHeight: 400, height: "100%" }}
        title={
          <Flex align="center" gap={8}>
            <GitBranch size={16} />
            {t("agent.version.manage")}
          </Flex>
        }
        extra={
          <Button
            type="primary"
            icon={<Rocket size={16} />}
            onClick={handlePublishClick}
          >
            {t("agent.version.publish")}
          </Button>
        }
        actions={footer}
        styles={{
          body: {
            height: "calc(100% - 112px)",
            overflow: "auto",
          },
        }}
      >
        {/* Desktop: Timeline style version list */}
        <div className="w-full h-full">
          <Spin spinning={isLoading}>
            {agentVersionList.length === 0 ? (
              <Flex align="center" justify="center" className="h-full">
                <Empty />
              </Flex>
            ) : (
              <Flex vertical >
                {agentVersionList.map((version) => (
                  <VersionCardItem
                    key={version.version_no}
                    version={version}
                    agentId={currentAgentId || 0}
                    currentVersionNo={agentInfo?.current_version_no}
                  />
                ))}
              </Flex>
            )}
          </Spin>
        </div>
      </Card>

      {/* Publish Version Modal */}
      <Modal
        centered
        title={t("agent.version.publish")}
        open={isPublishModalOpen}
        onCancel={() => setIsPublishModalOpen(false)}
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
          <Form.Item className="mb-0 flex justify-end gap-2">
            <Button onClick={() => setIsPublishModalOpen(false)} disabled={isPublishing}>
              {t("common.cancel")}
            </Button>
            <Button type="primary" htmlType="submit" loading={isPublishing} disabled={isPublishing}>
              {t("common.confirm")}
            </Button>
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
