"use client";

import { Button, Tag } from "antd";
import {
  Bot,
  BookOpen,
  Cpu,
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
    <ResourceDetail open={open} onClose={onClose}>
      <div className="border-b border-slate-200 bg-slate-50 p-6 dark:border-slate-700 dark:bg-slate-900/40">
        <div className="flex items-start gap-4">
          <span className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary">
            <Bot className="size-7" aria-hidden />
          </span>
          <div className="min-w-0">
            <h2 className="truncate text-xl font-semibold text-slate-900 dark:text-slate-100">
              {title}
            </h2>
            <div className="mt-1 flex items-center gap-2">
              <Tag color={agent?.current_version_no ? "green" : "orange"}>
                {agent?.current_version_no
                  ? t("agentRepository.mine.lifecycle.published")
                  : t("agentRepository.mine.lifecycle.draft")}
              </Tag>
              <span className="text-sm text-slate-500">
                {t("agentRepository.mine.currentVersion", { version })}
              </span>
            </div>
          </div>
        </div>
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
          <div className="space-y-6 py-2">
            <section className="space-y-2">
              <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                {t("agentRepository.detail.intro")}
              </h3>
              <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                {agent.description || t("agentRepository.card.noDescription")}
              </p>
            </section>
            <div className="grid grid-cols-1 gap-3 rounded-xl bg-slate-50 p-4 text-sm sm:grid-cols-2 dark:bg-slate-900/50">
              <span className="inline-flex items-center gap-2 text-slate-600 dark:text-slate-300">
                <User className="size-4" />
                {agent.author || "-"}
              </span>
              <span className="inline-flex items-center gap-2 text-slate-600 dark:text-slate-300">
                <Cpu className="size-4" />
                {agent.model_names?.join(", ") || "-"}
              </span>
              <Button
                type="link"
                className="justify-start px-0"
                onClick={onManageVersions}
              >
                {t("agent.version.manage")}
              </Button>
            </div>
            <section className="space-y-2">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">
                <Wrench className="size-4 text-primary" aria-hidden />
                {t("agentRepository.detail.tools")} ({tools.length})
              </h3>
              {tools.length > 0 ? (
                <div className="space-y-2">
                  {tools.map((tool) => (
                    <div
                      key={tool.id}
                      className="rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-700"
                    >
                      <div className="font-mono">
                        {tool.origin_name || tool.name}
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        {tool.description}
                      </div>
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
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <Tag key={item} className="m-0">
            {item}
          </Tag>
        ))}
      </div>
    </section>
  );
}
