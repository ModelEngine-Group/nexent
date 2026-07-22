"use client";

import type { ReactNode } from "react";
import { Button, Empty, Modal, Spin } from "antd";
import { Bot, CalendarDays, Download, UserRound } from "lucide-react";
import { useTranslation } from "react-i18next";

import { StatusTag } from "./SkillRepositoryCard";
import { formatRepositoryDate } from "./skillRepositoryShared";
import { cn } from "@/lib/utils";
import type { SkillRepositoryListingDetail } from "@/types/skillRepository";

export function SkillRepositoryDetailModal({
  open,
  detail,
  isLoading,
  isError,
  isFetching,
  onClose,
  onRetry,
}: {
  open: boolean;
  detail: SkillRepositoryListingDetail | undefined;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  onClose: () => void;
  onRetry: () => void;
}) {
  const { t } = useTranslation("common");
  const author =
    detail?.submitted_by?.trim() || t("skillRepository.detail.unknownAuthor");
  const updatedAt =
    formatRepositoryDate(detail?.updated_at) ||
    formatRepositoryDate(detail?.created_at) ||
    "-";
  const tags = detail?.tags?.filter((tag) => tag.trim()) ?? [];

  return (
    <Modal
      open={open}
      onCancel={onClose}
      centered
      destroyOnHidden
      width={520}
      title={null}
      footer={null}
      closeIcon={<span className="text-lg leading-none">×</span>}
      className="skill-repository-detail-modal"
    >
      {isLoading ? (
        <div className="flex min-h-[260px] items-center justify-center">
          <Spin />
        </div>
      ) : isError ? (
        <div className="flex min-h-[260px] flex-col items-center justify-center gap-3">
          <Empty description={t("skillRepository.detail.loadError")} />
          <Button type="primary" onClick={onRetry}>
            {t("skillRepository.common.retry")}
          </Button>
        </div>
      ) : detail ? (
        <div className={cn("space-y-6 pt-1", isFetching && "opacity-70")}>
          <header className="flex items-start gap-4 pr-8">
            <div className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <Bot className="size-7" aria-hidden />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="min-w-0 truncate text-xl font-semibold text-slate-900 dark:text-slate-100">
                  {detail.name || t("skillRepository.common.untitled")}
                </h2>
                <StatusTag status={detail.status} />
              </div>
              <p className="mt-1 flex min-w-0 items-center gap-1.5 text-sm text-slate-500 dark:text-slate-400">
                <UserRound className="size-3.5 shrink-0" aria-hidden />
                <span className="truncate">{author}</span>
              </p>
            </div>
          </header>

          <p className="whitespace-pre-wrap text-sm leading-7 text-slate-600 dark:text-slate-300">
            {detail.description || t("skillRepository.common.noDescription")}
          </p>

          <section className="space-y-2">
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              {t("skillRepository.detail.tags")}
            </h3>
            {tags.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-400">
                {t("skillRepository.detail.noTags")}
              </p>
            )}
          </section>

          <div className="grid grid-cols-2 divide-x divide-slate-200 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-5 dark:divide-slate-700 dark:border-slate-700 dark:bg-slate-800/50">
            <StatItem
              icon={<Download className="size-4" aria-hidden />}
              label={t("skillRepository.detail.downloads")}
              value={(detail.downloads ?? 0).toLocaleString()}
            />
            <StatItem
              icon={<CalendarDays className="size-4" aria-hidden />}
              label={t("skillRepository.detail.updatedAt")}
              value={updatedAt}
            />
          </div>
        </div>
      ) : (
        <Empty description={t("skillRepository.detail.empty")} />
      )}
    </Modal>
  );
}

function StatItem({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col items-center justify-center px-3 text-center">
      <div className="text-xs font-medium text-slate-400 dark:text-slate-500">
        {label}
      </div>
      <div className="mt-2 flex max-w-full items-center justify-center gap-1.5 truncate text-base font-semibold text-slate-800 dark:text-slate-100">
        <span className="shrink-0 text-slate-500 dark:text-slate-400">
          {icon}
        </span>
        {value}
      </div>
    </div>
  );
}
