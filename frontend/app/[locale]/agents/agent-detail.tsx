"use client";

import { Button, Tag } from "antd";
import {
  Bot,
  BookOpen,
  Cpu,
  FileText,
  Pencil,
  Tag as TagIcon,
  User,
  Wrench,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";

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
  const skills = agent?.skills ?? [];
  const tags = (agent as (Agent & { tags?: string[] }) | null)?.tags ?? [];
  const knowledgeBases = Array.from(
    new Set(tools.flatMap((tool) => tool.display_names ?? []).filter(Boolean))
  );

  return (
    <ResourceDetail open={open} onClose={onClose} bodyStyle={{ padding: 0 }}>
      <div className="flex max-h-[calc(100vh-8rem)] flex-col overflow-hidden">
        <div className="min-h-0 flex-1 overflow-y-auto p-6">
          <div className="flex items-start gap-4">
            <span className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <Bot className="size-6" aria-hidden />
            </span>
            <div className="min-w-0">
              <h2 className="truncate text-xl font-semibold text-slate-900 dark:text-slate-100">
                {title}
              </h2>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <Tag color={agent?.current_version_no ? "green" : "orange"}>
                  {agent?.current_version_no
                    ? t("agentRepository.mine.lifecycle.published")
                    : t("agentRepository.mine.lifecycle.draft")}
                </Tag>
                <span className="text-sm text-slate-500">{version}</span>
              </div>
            </div>
          </div>
          {agent ? (
            <div className="mt-5 space-y-6">
              <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                {agent.description || t("agentRepository.card.noDescription")}
              </p>
              <div className="grid grid-cols-1 gap-x-6 gap-y-3 rounded-xl bg-slate-50 p-4 text-sm sm:grid-cols-2 dark:bg-slate-900/50">
                <span className="inline-flex items-center gap-2 text-slate-600 dark:text-slate-300">
                  <User className="size-4 text-slate-500" aria-hidden />
                  <span className="text-slate-500">
                    {t("agentRepository.review.column.submitter")}
                  </span>
                  <span className="ml-auto font-medium text-slate-900 dark:text-slate-100">
                    {agent.author || "-"}
                  </span>
                </span>
                <span className="inline-flex items-center gap-2 text-slate-600 dark:text-slate-300">
                  <Cpu className="size-4 text-slate-500" aria-hidden />
                  <span className="text-slate-500">
                    {t("agentRepository.copy.type.model")}
                  </span>
                  <span className="ml-auto truncate font-medium text-slate-900 dark:text-slate-100">
                    {agent.model_names?.join(", ") || "-"}
                  </span>
                </span>
                <Button
                  type="text"
                  className="h-auto justify-start gap-2 px-0 text-slate-600 dark:text-slate-300"
                  icon={
                    <FileText className="size-4 text-slate-500" aria-hidden />
                  }
                  onClick={onManageVersions}
                >
                  {t("agentRepository.mine.currentVersion", { version })}
                </Button>
              </div>
              <section className="space-y-2">
                <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">
                  <Wrench className="size-4 text-slate-500" aria-hidden />
                  {t("agentRepository.detail.tools")} ({tools.length})
                </h3>
                {tools.length > 0 ? (
                  <div className="space-y-2">
                    {tools.map((tool) => (
                      <div
                        key={tool.id}
                        className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-900/40"
                      >
                        <div className="font-mono text-slate-900 dark:text-slate-100">
                          {tool.origin_name || tool.name}
                        </div>
                        {tool.description ? (
                          <div className="mt-1 text-xs leading-5 text-slate-500">
                            {tool.description}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-slate-500">-</p>
                )}
              </section>
              <ResourceSection
                icon={<Wrench />}
                title={t("agentRepository.detail.tools")}
                items={skills.map((skill) => skill.name)}
              />
              <ResourceSection
                icon={<BookOpen />}
                title={t("agentRepository.detail.knowledgeBases", "关联知识库")}
                items={knowledgeBases}
              />
              <ResourceSection
                icon={<TagIcon />}
                title={t("resource.tags", "标签")}
                items={tags}
              />
            </div>
          ) : null}
        </div>
        <div className="flex shrink-0 justify-end gap-2 border-t border-slate-200 bg-white px-5 py-4 dark:border-slate-700 dark:bg-slate-950">
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
    </ResourceDetail>
  );
}

function ResourceSection({
  icon,
  title,
  items,
}: {
  icon: ReactNode;
  title: string;
  items: string[];
}) {
  if (items.length === 0) return null;
  return (
    <section className="space-y-2">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">
        {icon}
        {title} ({items.length})
      </h3>
      <div className="space-y-2">
        {items.map((item) => (
          <div
            key={item}
            className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-200"
          >
            {item}
          </div>
        ))}
      </div>
    </section>
  );
}
