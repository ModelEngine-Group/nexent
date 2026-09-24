"use client";

import { Button, Spin } from "antd";
import {
  Bot,
  CalendarDays,
  Download,
  Tag as TagIcon,
  UserRound,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import ResourceDetail from "@/components/resource/ResourceDetail";
import { mapSkillRepositoryDetail } from "@/lib/skillRepositoryDetail";
import type { SkillRepositoryListingDetail } from "@/types/skillRepository";

interface SkillDetailProps {
  open: boolean;
  detail: SkillRepositoryListingDetail | undefined;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  onClose: () => void;
  onRetry: () => void;
}

const statusStyles = {
  not_shared:
    "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300",
  pending_review:
    "border-amber-100 bg-amber-50 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300",
  rejected:
    "border-rose-100 bg-rose-50 text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300",
  shared:
    "border-blue-100 bg-blue-50 text-blue-700 dark:border-blue-500/20 dark:bg-blue-500/10 dark:text-blue-300",
} as const;

const statusLabelKeys = {
  not_shared: "repository.status.notListed",
  pending_review: "repository.status.reviewing",
  rejected: "repository.status.rejected",
  shared: "repository.status.listed",
} as const;

export function SkillDetail({
  open,
  detail,
  isLoading,
  isError,
  isFetching,
  onClose,
  onRetry,
}: SkillDetailProps) {
  const { t } = useTranslation("common");
  const view = detail ? mapSkillRepositoryDetail(detail) : null;

  return (
    <ResourceDetail
      open={open}
      onClose={onClose}
      width={560}
      className="skill-detail-modal [&_.ant-modal-close]:!z-20 [&_.ant-modal-content]:!overflow-hidden [&_.ant-modal-content]:!rounded-2xl [&_.ant-modal-content]:!p-0"
      bodyStyle={{ padding: 0 }}
    >
      <div className="flex max-h-[min(740px,calc(100dvh-3rem))] flex-col overflow-hidden">
        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4 pt-4 sm:px-4">
          {isLoading ? (
            <div className="flex min-h-64 items-center justify-center">
              <Spin size="large" />
            </div>
          ) : isError ? (
            <div className="flex min-h-64 flex-col items-center justify-center gap-3 text-center">
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {t("skillRepository.detail.loadError")}
              </p>
              <Button type="primary" onClick={onRetry} loading={isFetching}>
                {t("repository.common.retry")}
              </Button>
            </div>
          ) : view ? (
            <div className={isFetching ? "opacity-70" : undefined}>
              <div className="flex items-start gap-3 pr-6">
                <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Bot className="size-6" aria-hidden />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="break-words text-lg font-semibold leading-7 text-slate-900 dark:text-slate-100">
                    {view.title || t("skillRepository.common.untitled")}
                  </h2>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <span
                      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${statusStyles[view.status]}`}
                    >
                      <span
                        className="size-1.5 rounded-full bg-current"
                        aria-hidden
                      />
                      {t(statusLabelKeys[view.status])}
                    </span>
                  </div>
                </div>
              </div>

              <p className="mt-5 whitespace-pre-wrap text-sm leading-6 text-slate-600 dark:text-slate-300">
                {view.description || t("skillRepository.common.noDescription")}
              </p>

              <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
                <span className="inline-flex items-center gap-1">
                  <Download className="size-3.5" aria-hidden />
                  {t("skillRepository.detail.downloads")}
                  {view.downloads.toLocaleString()}
                </span>
                <span className="inline-flex items-center gap-1">
                  <CalendarDays className="size-3.5" aria-hidden />
                  {t("skillRepository.detail.updatedAt")}
                  {view.updatedAt}
                </span>
              </div>

              {view.author ? (
                <div className="mt-4 rounded-xl bg-slate-50 px-3 py-3 text-sm dark:bg-slate-800/60">
                  <div className="flex min-w-0 items-center gap-2 text-slate-500 dark:text-slate-400">
                    <UserRound className="size-4 shrink-0" aria-hidden />
                    <span className="shrink-0 whitespace-nowrap">
                      {t("skillRepository.detail.author")}
                    </span>
                    <span
                      className="ml-auto min-w-0 flex-1 truncate text-right font-medium text-slate-900 dark:text-slate-100"
                      title={view.author}
                    >
                      {view.author}
                    </span>
                  </div>
                </div>
              ) : null}

              <section className="mt-5 space-y-2">
                <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800 dark:text-slate-100">
                  <TagIcon
                    className="size-4 text-slate-500 dark:text-slate-400"
                    aria-hidden
                  />
                  {t("skillRepository.detail.tags")}
                  <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium leading-none text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                    {view.tags.length}
                  </span>
                </h3>
                {view.tags.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {view.tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded-md bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 dark:bg-blue-500/10 dark:text-blue-300"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-slate-400 dark:text-slate-500">
                    {t("skillRepository.detail.noTags")}
                  </p>
                )}
              </section>
            </div>
          ) : (
            <div className="flex min-h-64 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
              {t("skillRepository.detail.empty")}
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center justify-end gap-2 border-t border-slate-200 bg-slate-50/60 px-3 py-3 dark:border-slate-700 dark:bg-slate-900/60 sm:px-4">
          <Button onClick={onClose}>{t("common.close")}</Button>
        </div>
      </div>
    </ResourceDetail>
  );
}
