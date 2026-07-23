"use client";

import type { ReactNode } from "react";
import { Button, Empty, Spin } from "antd";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

export function AsyncContent({
  isLoading,
  isError,
  isFetching,
  isEmpty,
  onRetry,
  emptyDescription,
  children,
}: {
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  isEmpty: boolean;
  onRetry: () => void;
  emptyDescription: string;
  children: ReactNode;
}) {
  const { t } = useTranslation("common");
  if (isLoading) {
    return (
      <div className="flex min-h-[320px] items-center justify-center rounded-xl border border-dashed border-border bg-background/60">
        <Spin />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-background/60">
        <Empty description={t("skillRepository.common.loadError")} />
        <Button onClick={onRetry}>{t("skillRepository.common.retry")}</Button>
      </div>
    );
  }

  if (isEmpty) {
    return (
      <div className="flex min-h-[320px] items-center justify-center rounded-xl border border-dashed border-border bg-background/60">
        <Empty description={emptyDescription} />
      </div>
    );
  }

  return (
    <div className={cn("relative", isFetching && "opacity-70")}>{children}</div>
  );
}

export function PaginationBar({
  page,
  pageSize,
  total,
  onPageChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}) {
  const { t } = useTranslation("common");
  const totalPages = total > 0 ? Math.ceil(total / pageSize) : 0;
  if (totalPages <= 1) return null;

  return (
    <div className="flex items-center justify-center gap-1.5 pt-2">
      <Button
        type="default"
        className="flex size-9 items-center justify-center rounded-lg p-0"
        aria-label={t("skillRepository.pagination.prev")}
        disabled={page <= 1}
        onClick={() => onPageChange(Math.max(1, page - 1))}
      >
        <ChevronLeft className="size-4" aria-hidden />
      </Button>
      {Array.from({ length: totalPages }, (_, index) => index + 1).map(
        (pageNumber) => (
          <Button
            key={pageNumber}
            type={pageNumber === page ? "primary" : "default"}
            className="flex size-9 items-center justify-center rounded-lg p-0"
            onClick={() => onPageChange(pageNumber)}
            aria-label={t("skillRepository.pagination.page", {
              page: pageNumber,
            })}
            aria-current={pageNumber === page ? "page" : undefined}
          >
            {pageNumber}
          </Button>
        )
      )}
      <Button
        type="default"
        className="flex size-9 items-center justify-center rounded-lg p-0"
        aria-label={t("skillRepository.pagination.next")}
        disabled={page >= totalPages}
        onClick={() => onPageChange(Math.min(totalPages, page + 1))}
      >
        <ChevronRight className="size-4" aria-hidden />
      </Button>
    </div>
  );
}

export function FilterButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors",
        active
          ? "bg-primary text-white"
          : "bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
      )}
    >
      {children}
    </button>
  );
}

export function CountBadge({
  count,
  strong = false,
}: {
  count: number;
  strong?: boolean;
}) {
  if (!strong) {
    return (
      <span className="ml-1 rounded-md bg-background/70 px-1.5 text-xs text-muted-foreground">
        {count}
      </span>
    );
  }

  if (count <= 0) return null;

  return (
    <span className="ml-1 inline-flex size-5 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
      {count}
    </span>
  );
}
