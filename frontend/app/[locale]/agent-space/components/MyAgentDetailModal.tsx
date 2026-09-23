"use client";

import { Button, Spin } from "antd";
import {
  BookOpen,
  Bot,
  Cpu,
  Pencil,
  Sparkles,
  Tag as TagIcon,
  UserRound,
  Wrench,
} from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import ResourceDetail from "@/components/resource/ResourceDetail";
import type { MyAgentDetailView } from "@/lib/myAgentDetail";
import type { AgentRepositoryListingStatus } from "@/types/agentRepository";

interface MyAgentDetailModalProps {
  open: boolean;
  onClose: () => void;
  onEdit?: () => void;
  detail: MyAgentDetailView | null | undefined;
  published: boolean;
  status?: AgentRepositoryListingStatus;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  onRetry: () => void;
}

function DetailSection({
  icon,
  title,
  items,
  tone = "neutral",
}: {
  icon: ReactNode;
  title: string;
  items: string[];
  tone?: "neutral" | "blue";
}) {
  if (items.length === 0) return null;

  return (
    <section className="space-y-2">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800 dark:text-slate-100">
        <span className="text-slate-500 dark:text-slate-400">{icon}</span>
        {title}
        <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium leading-none text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          {items.length}
        </span>
      </h3>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span
            key={item}
            className={
              tone === "blue"
                ? "rounded-md bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 dark:bg-blue-500/10 dark:text-blue-300"
                : "max-w-full break-all rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
            }
          >
            {item}
          </span>
        ))}
      </div>
    </section>
  );
}

export function MyAgentDetailModal({
  open,
  onClose,
  onEdit,
  detail,
  published,
  status,
  isLoading,
  isError,
  isFetching,
  onRetry,
}: MyAgentDetailModalProps) {
  const { t } = useTranslation("common");

  return (
    <ResourceDetail
      open={open}
      onClose={onClose}
      width={560}
      className="my-agent-detail-modal [&_.ant-modal-close]:!z-20 [&_.ant-modal-content]:!overflow-hidden [&_.ant-modal-content]:!rounded-2xl [&_.ant-modal-content]:!p-0"
      bodyStyle={{ padding: 0 }}
    >
      <div className="flex max-h-[min(740px,calc(100dvh-3rem))] flex-col overflow-hidden">
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-5 pt-6 sm:px-7">
          {isLoading ? (
            <div className="flex min-h-64 items-center justify-center">
              <Spin size="large" />
            </div>
          ) : isError ? (
            <div className="flex min-h-64 flex-col items-center justify-center gap-3 text-center">
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {t("agentRepository.detail.loadError")}
              </p>
              <Button type="primary" onClick={onRetry} loading={isFetching}>
                {t("repository.common.retry")}
              </Button>
            </div>
          ) : detail ? (
            <>
              <div className="flex items-start gap-3 pr-6">
                <div className="flex size-12 shrink-0 items-center justify-center rounded-xl border border-rose-100 bg-rose-50 text-rose-600 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300">
                  <Bot className="size-6" aria-hidden />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="break-words text-lg font-semibold leading-7 text-slate-900 dark:text-slate-100">
                    {detail.title || t("agentRepository.card.untitled")}
                  </h2>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <span
                      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${
                        published
                          ? "border-emerald-100 bg-emerald-50 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300"
                          : "border-amber-100 bg-amber-50 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300"
                      }`}
                    >
                      <span
                        className="size-1.5 rounded-full bg-current"
                        aria-hidden
                      />
                      {t(
                        published
                          ? "agentRepository.mine.lifecycle.published"
                          : "agentRepository.mine.lifecycle.draft"
                      )}
                      {published && detail.versionLabel
                        ? ` · ${detail.versionLabel}`
                        : null}
                    </span>
                    {status && status !== "not_shared" ? (
                      <span
                        className={`rounded-full border px-2 py-0.5 text-xs font-medium ${
                          status === "rejected"
                            ? "border-rose-100 bg-rose-50 text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300"
                            : status === "pending_review"
                              ? "border-amber-100 bg-amber-50 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300"
                              : "border-blue-100 bg-blue-50 text-blue-700 dark:border-blue-500/20 dark:bg-blue-500/10 dark:text-blue-300"
                        }`}
                      >
                        {status === "shared"
                          ? t("agentRepository.mine.listed")
                          : t(`agentRepository.detail.status.${status}`)}
                      </span>
                    ) : null}
                  </div>
                </div>
              </div>

              <p className="mt-5 whitespace-pre-wrap text-sm leading-6 text-slate-600 dark:text-slate-300">
                {detail.description || t("agentRepository.card.noDescription")}
              </p>

              {detail.author || detail.modelName ? (
                <div className="mt-4 space-y-2 rounded-xl bg-slate-50 px-3 py-3 text-sm dark:bg-slate-800/60">
                  {detail.author ? (
                    <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400">
                      <UserRound className="size-4 shrink-0" aria-hidden />
                      <span>{t("agentRepository.mine.detail.author")}</span>
                      <span className="ml-auto min-w-0 truncate font-medium text-slate-900 dark:text-slate-100">
                        {detail.author}
                      </span>
                    </div>
                  ) : null}
                  {detail.modelName ? (
                    <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400">
                      <Cpu className="size-4 shrink-0" aria-hidden />
                      <span>{t("agentRepository.mine.detail.model")}</span>
                      <span className="ml-auto min-w-0 truncate font-medium text-slate-900 dark:text-slate-100">
                        {detail.modelName}
                      </span>
                    </div>
                  ) : null}
                </div>
              ) : null}

              <div className="mt-5 space-y-5">
                <DetailSection
                  icon={<Wrench className="size-4" aria-hidden />}
                  title={t("agentRepository.mine.detail.tools")}
                  items={detail.tools}
                />
                <DetailSection
                  icon={<Sparkles className="size-4" aria-hidden />}
                  title={t("agentRepository.mine.detail.skills")}
                  items={detail.skills}
                />
                <DetailSection
                  icon={<BookOpen className="size-4" aria-hidden />}
                  title={t("agentRepository.mine.detail.knowledgeBases")}
                  items={detail.knowledgeBases}
                />
                <DetailSection
                  icon={<Bot className="size-4" aria-hidden />}
                  title={t("agentRepository.mine.detail.subAgents")}
                  items={detail.subAgents}
                />
                <DetailSection
                  icon={<TagIcon className="size-4" aria-hidden />}
                  title={t("agentRepository.mine.detail.tags")}
                  items={detail.tags}
                  tone="blue"
                />
              </div>
            </>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center justify-end gap-2 border-t border-slate-200 bg-slate-50/60 px-6 py-4 dark:border-slate-700 dark:bg-slate-900/60 sm:px-7">
          <Button onClick={onClose}>{t("common.close")}</Button>
          {onEdit && detail && !isError ? (
            <Button
              type="primary"
              icon={<Pencil className="size-4" />}
              onClick={onEdit}
            >
              {t("agentRepository.mine.edit")}
            </Button>
          ) : null}
        </div>
      </div>
    </ResourceDetail>
  );
}
