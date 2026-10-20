// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useId, type ReactNode } from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export function ResourceSelectionRow({
  title,
  description,
  tags = [],
  selected = false,
  disabled = false,
  disabledReason,
  onClick,
  actions,
}: {
  title: string;
  description?: string;
  tags?: readonly string[];
  selected?: boolean;
  disabled?: boolean;
  disabledReason?: string;
  onClick: () => void;
  actions?: ReactNode;
}) {
  const reasonId = useId();
  return (
    <div
      className={cn(
        "flex min-w-0 items-center gap-3 border-b border-border",
        selected && "bg-primary/5"
      )}
    >
      <button
        type="button"
        role="option"
        aria-label={title}
        aria-selected={selected}
        aria-describedby={disabledReason ? reasonId : undefined}
        disabled={disabled}
        onClick={onClick}
        className="flex min-h-16 min-w-0 flex-1 items-center gap-3 px-3 py-2 text-left hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span className="min-w-0 flex-1 space-y-1">
          <span className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="truncate text-sm font-medium" title={title}>
              {title}
            </span>
            {[...new Set(tags)].map((tag) => (
              <span
                key={tag}
                className="shrink-0 rounded bg-muted px-1.5 text-xs text-muted-foreground"
              >
                {tag}
              </span>
            ))}
          </span>
          {description && (
            <span className="line-clamp-2 text-xs text-muted-foreground">
              {description}
            </span>
          )}
          {disabledReason && (
            <span id={reasonId} className="block text-xs text-destructive">
              {disabledReason}
            </span>
          )}
        </span>
        <span
          className={cn(
            "flex size-5 shrink-0 items-center justify-center rounded border",
            selected
              ? "border-primary bg-primary text-primary-foreground"
              : "border-border"
          )}
          aria-hidden
        >
          {selected && <Check className="size-3.5" />}
        </span>
      </button>
      {actions && <div className="shrink-0 pr-3">{actions}</div>}
    </div>
  );
}
