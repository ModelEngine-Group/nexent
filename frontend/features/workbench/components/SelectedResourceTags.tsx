// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function SelectedResourceTags({
  items,
  onRemove,
  compact = false,
  disabled = false,
}: {
  items: { id: string; name: string; icon?: ReactNode }[];
  onRemove: (id: string) => void;
  compact?: boolean;
  disabled?: boolean;
}) {
  const { t } = useTranslation("common");
  if (!items.length) return null;
  return (
    <div
      data-slot={compact ? "composer-resources" : undefined}
      className={cn(
        "flex min-w-0 flex-wrap gap-1.5",
        compact && "max-h-24 overflow-y-auto"
      )}
    >
      {items.map(({ id, name, icon }) => (
        <span
          key={id}
          className={cn(
            "inline-flex min-w-0 items-center",
            compact
              ? "h-7 max-w-full shrink-0 gap-1.5 rounded-lg border border-[var(--color-border-separator)] bg-muted/40 px-2 text-xs font-normal text-foreground sm:max-w-56"
              : "max-w-48 rounded bg-blue-100 px-2 py-0.5 text-sm font-medium text-blue-800"
          )}
        >
          {icon && (
            <span
              className="inline-flex shrink-0 text-primary"
              aria-hidden="true"
            >
              {icon}
            </span>
          )}
          <span className="truncate" title={name}>
            {name}
          </span>
          <button
            type="button"
            disabled={disabled}
            className={cn(
              "shrink-0",
              compact
                ? "inline-flex size-4 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-40"
                : "ml-1.5 text-blue-600 hover:text-blue-800"
            )}
            aria-label={t("ui.localization.removeResource", { name })}
            onClick={() => onRemove(id)}
          >
            {compact ? <X className="size-3" aria-hidden="true" /> : "×"}
          </button>
        </span>
      ))}
    </div>
  );
}
