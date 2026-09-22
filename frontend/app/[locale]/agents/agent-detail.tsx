"use client";

import { Button, Descriptions, Modal, Tag } from "antd";
import { Bot, Pencil } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Agent } from "@/types/agentConfig";

interface AgentDetailProps {
  agent: Agent | null;
  open: boolean;
  onClose: () => void;
  onEdit: () => void;
  actions?: React.ReactNode;
  onManageVersions: () => void;
}

export default function AgentDetail({
  agent,
  open,
  onClose,
  onEdit,
  actions,
  onManageVersions,
}: AgentDetailProps) {
  const { t } = useTranslation("common");
  const title =
    agent?.display_name || agent?.name || t("agentRepository.card.untitled");
  const version =
    agent?.version_name ||
    (agent?.current_version_no
      ? `V${agent.current_version_no}`
      : t("agentRepository.mine.lifecycle.draft"));

  return (
    <Modal
      centered
      width={720}
      open={open}
      title={
        <span className="flex items-center gap-2">
          <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Bot className="size-5" aria-hidden />
          </span>
          <span className="truncate">{title}</span>
        </span>
      }
      onCancel={onClose}
      footer={
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-1">{actions}</div>
          <div className="flex gap-2">
            <Button onClick={onClose}>{t("common.cancel")}</Button>
            <Button
              type="primary"
              icon={<Pencil className="size-4" />}
              onClick={onEdit}
            >
              {t("agentRepository.mine.edit")}
            </Button>
          </div>
        </div>
      }
    >
      {agent ? (
        <div className="space-y-5 py-2">
          <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
            {agent.description || t("agentRepository.card.noDescription")}
          </p>
          <Descriptions column={{ xs: 1, sm: 2 }} size="small">
            <Descriptions.Item label={t("agentRepository.mine.currentVersion")}>
              <Tag color="cyan">{version}</Tag>
            </Descriptions.Item>
            <Descriptions.Item
              label={t("agentRepository.mine.lifecycle.published")}
            >
              <Tag color={agent.current_version_no ? "green" : "orange"}>
                {agent.current_version_no
                  ? t("agentRepository.mine.lifecycle.published")
                  : t("agentRepository.mine.lifecycle.draft")}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label={t("agentConfig.form.author")}>
              {agent.author || "-"}
            </Descriptions.Item>
            <Descriptions.Item label={t("agent.version.current")}>
              <Button type="link" className="px-0" onClick={onManageVersions}>
                {t("agent.version.manage")}
              </Button>
            </Descriptions.Item>
          </Descriptions>
        </div>
      ) : null}
    </Modal>
  );
}
