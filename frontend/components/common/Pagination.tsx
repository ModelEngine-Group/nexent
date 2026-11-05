// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState, type ComponentProps } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/common/Button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  Pagination as PaginationRoot,
  PaginationContent,
  PaginationItem,
} from "@/components/ui/pagination";

export interface PaginationProps extends Omit<
  ComponentProps<"nav">,
  "onChange"
> {
  current: number;
  pageSize: number;
  total: number;
  onPageChange?: (page: number, pageSize: number) => void;
  onPageSizeChange?: (pageSize: number) => void;
  pageSizeOptions?: number[];
  showTotal?: boolean;
  showSizeChanger?: boolean;
  showQuickJumper?: boolean;
  disabled?: boolean;
  compact?: boolean;
}

function pagesNear(
  current: number,
  count: number
): (number | "start" | "end")[] {
  const sorted = [...new Set([1, count, current - 1, current, current + 1])]
    .filter((page) => page >= 1 && page <= count)
    .sort((a, b) => a - b);
  const result: (number | "start" | "end")[] = [];
  sorted.forEach((page, index) => {
    if (index && page - sorted[index - 1] > 1) {
      if (page - sorted[index - 1] === 2) result.push(sorted[index - 1] + 1);
      else result.push(index === 1 ? "start" : "end");
    }
    result.push(page);
  });
  return result;
}

/** Controlled pagination never fetches data or silently rewrites a caller's page. */
export function Pagination({
  current,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = [10, 20, 50, 100],
  showTotal = false,
  showSizeChanger = false,
  showQuickJumper = false,
  disabled = false,
  compact = false,
  className,
  ...props
}: PaginationProps) {
  const { t } = useTranslation("common");
  const [jump, setJump] = useState("");
  const size = Math.max(1, Math.floor(pageSize) || 1);
  const count = Math.max(1, Math.ceil(Math.max(0, total) / size));
  const page = Math.min(count, Math.max(1, Math.floor(current) || 1));
  const sizes = [...new Set([...pageSizeOptions, size])]
    .filter((value) => Number.isInteger(value) && value > 0)
    .sort((a, b) => a - b);
  const change = (value: number) => {
    if (!disabled && value !== page && value >= 1 && value <= count)
      onPageChange?.(value, size);
  };
  const navigateToJump = () => {
    if (/^\d+$/.test(jump)) change(Number(jump));
    setJump("");
  };
  return (
    <PaginationRoot
      aria-label={t("pagination.navigation")}
      className={cn(
        "mx-0 w-auto max-w-full flex-wrap items-center gap-3 md:flex-nowrap",
        showTotal && "w-full justify-between",
        className
      )}
      {...props}
    >
      {showTotal && (
        <span className="shrink-0 whitespace-nowrap text-sm text-muted-foreground">
          {t("pagination.total", { count: Math.max(0, total) })}
        </span>
      )}
      <div className="flex min-w-0 flex-wrap items-center justify-end gap-2 md:flex-nowrap">
        {showSizeChanger && (
          <select
            className="h-8 shrink-0 rounded-md border border-input bg-background px-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={t("pagination.pageSize")}
            value={size}
            disabled={disabled}
            onChange={(event) => {
              if (disabled) return;
              const next = Number(event.target.value);
              setJump("");
              onPageSizeChange?.(next);
              onPageChange?.(1, next);
            }}
          >
            {sizes.map((value) => (
              <option key={value} value={value}>
                {t("pagination.perPage", { count: value })}
              </option>
            ))}
          </select>
        )}
        <PaginationContent className="shrink-0">
          <PaginationItem>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              disabled={disabled || page <= 1}
              aria-label={t("pagination.previous")}
              onClick={() => change(page - 1)}
            >
              <ChevronLeft aria-hidden="true" />
            </Button>
          </PaginationItem>
          {pagesNear(page, count).map((value) => (
            <PaginationItem key={value}>
              {typeof value === "number" ? (
                <Button
                  type="button"
                  size={compact ? "sm" : "icon"}
                  variant={value === page ? "default" : "ghost"}
                  aria-current={value === page ? "page" : undefined}
                  title={String(value)}
                  aria-label={t("pagination.page", { page: value })}
                  disabled={disabled || total <= 0}
                  onClick={() => change(value)}
                >
                  {value}
                </Button>
              ) : (
                <span className="px-2 text-muted-foreground" aria-hidden="true">
                  …
                </span>
              )}
            </PaginationItem>
          ))}
          <PaginationItem>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              disabled={disabled || page >= count}
              aria-label={t("pagination.next")}
              onClick={() => change(page + 1)}
            >
              <ChevronRight aria-hidden="true" />
            </Button>
          </PaginationItem>
        </PaginationContent>
        {showQuickJumper && (
          <div
            className="flex shrink-0 items-center gap-2 whitespace-nowrap text-sm text-muted-foreground"
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget))
                navigateToJump();
            }}
          >
            <label className="flex items-center gap-2">
              {t("pagination.jumpTo")}
              <Input
                className="h-8 w-16"
                inputMode="numeric"
                value={jump}
                disabled={disabled}
                aria-label={t("pagination.jumpTo")}
                onChange={(event) => setJump(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    navigateToJump();
                  }
                }}
              />
            </label>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={disabled || total <= 0}
              onClick={navigateToJump}
            >
              {t("pagination.jump")}
            </Button>
          </div>
        )}
      </div>
    </PaginationRoot>
  );
}
