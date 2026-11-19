// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { ReactNode } from "react";
import { Button, Empty, Spin } from "antd";
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
        <Button onClick={onRetry}>{t("repository.common.retry")}</Button>
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
