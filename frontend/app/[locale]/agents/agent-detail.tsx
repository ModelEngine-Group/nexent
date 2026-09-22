"use client";

import { Button, Descriptions, Tag } from "antd";
import { Bot, Pencil, Wrench } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Agent } from "@/types/agentConfig";
import ResourceDetail from "@/components/resource/ResourceDetail";

interface AgentDetailProps {
  agent: Agent | null;
  open: boolean;
  onClose: () => void;
  onEdit: () => void;
  onManageVersions: () => void;
}

export default function AgentDetail({
  agent,
  open,
  onClose,
  onEdit,
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
  const tools = agent?.tools ?? [];

  return (
    <ResourceDetail open={open} onClose={onClose}>
      <div className="border-b border-slate-200 p-5 dark:border-slate-700">
        <span className="flex items-center gap-2">
          <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Bot className="size-5" aria-hidden />
          </span>
          <span className="truncate">{title}</span>
        </span>
      </div>
      <div className="p-5">
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            type="primary"
            icon={<Pencil className="size-4" />}
            onClick={onEdit}
          >
            {t("agentRepository.mine.edit")}
          </Button>
        </div>
        {agent ? (
          <div className="space-y-5 py-2">
            <section className="space-y-2">
              <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                {t("agentRepository.detail.intro")}
              </h3>
              <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                {agent.description || t("agentRepository.card.noDescription")}
              </p>
            </section>
            <Descriptions column={{ xs: 1, sm: 2 }} size="small">
              <Descriptions.Item
                label={t("agentRepository.mine.currentVersion")}
              >
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
            <section className="space-y-2">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">
                <Wrench className="size-4 text-primary" aria-hidden />
                {t("agentRepository.detail.tools")} ({tools.length})
              </h3>
              {tools.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {tools.map((tool) => (
                    <Tag key={tool.id} className="m-0 font-mono text-xs">
                      {tool.origin_name || tool.name}
                    </Tag>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-500">-</p>
              )}
            </section>
          </div>
        ) : null}
      </div>
    </ResourceDetail>
  );
}
