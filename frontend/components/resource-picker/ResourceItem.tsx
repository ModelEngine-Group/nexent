// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useId, type HTMLAttributes } from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  ResourceItemContext,
  ResourceItemData,
  ResourceItemSlots,
  ResourceViewMode,
} from "@/types/resourcePicker";

export interface ResourceItemProps<T> {
  item: ResourceItemData<T>;
  selected?: boolean;
  disabled?: boolean;
  disabledReason?: string;
  viewMode?: ResourceViewMode;
  onToggle: () => void;
  slots?: ResourceItemSlots<T>;
}

/** Selection and interactive metadata/actions remain separate keyboard targets. */
export function ResourceItem<T>({
  item,
  selected = false,
  disabled = false,
  disabledReason,
  viewMode = "list",
  onToggle,
  slots,
}: ResourceItemProps<T>) {
  const reasonId = useId();
  const context: ResourceItemContext = { selected, disabled, viewMode };
  const metadata = slots?.renderMetadata
    ? slots.renderMetadata(item, context)
    : item.metadata?.map((field) => (
        <span key={field.key}>
          {field.value} {field.label}
        </span>
      ));
  const actions = slots?.renderActions?.(item, context);
  const titleTrailing = slots?.renderTitleTrailing?.(item, context);

  return (
    <div
      data-resource-view={viewMode}
      className={cn(
        "flex min-w-0 gap-3 transition-colors",
        viewMode === "card"
          ? "flex-col rounded-lg border border-border p-3"
          : "items-center",
        selected && "bg-primary/5",
        !disabled &&
          (selected
            ? "hover:bg-primary/10 focus-within:bg-primary/10"
            : "hover:bg-muted/50 focus-within:bg-muted/50")
      )}
    >
      <div className="min-w-0 flex-1">
        <button
          type="button"
          role="option"
          aria-label={item.name}
          aria-selected={selected}
          aria-describedby={disabledReason ? reasonId : undefined}
          disabled={disabled}
          onClick={onToggle}
          className={cn(
            "flex w-full min-w-0 items-start gap-3 px-3 py-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50",
            item.description || slots?.renderContent ? "min-h-16" : "min-h-10"
          )}
        >
          <span
            data-resource-checkbox
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
          <span className="min-w-0 flex-1 space-y-1">
            {slots?.renderContent ? (
              slots.renderContent(item, context)
            ) : (
              <>
                <span className="flex min-w-0 items-start justify-between gap-3">
                  <span className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                    <span
                      className={cn(
                        "truncate text-sm font-medium",
                        selected && "text-primary"
                      )}
                      title={item.name}
                    >
                      {item.name}
                    </span>
                    {[...new Set(item.badges ?? [])].map((badge) => (
                      <span
                        key={badge}
                        className="rounded bg-blue-50 px-1.5 text-xs text-primary"
                      >
                        {badge}
                      </span>
                    ))}
                    {slots?.renderTags
                      ? slots.renderTags(item, context)
                      : [...new Set(item.tags ?? [])].map((tag) => (
                          <span
                            key={tag}
                            className="shrink-0 rounded bg-muted px-1.5 text-xs text-muted-foreground"
                          >
                            {tag}
                          </span>
                        ))}
                  </span>
                  {titleTrailing && (
                    <span className="flex max-w-[40%] shrink-0 items-center">
                      {titleTrailing}
                    </span>
                  )}
                </span>
                {(item.description || slots?.renderDescription) && (
                  <span className="line-clamp-2 text-xs text-muted-foreground">
                    {slots?.renderDescription
                      ? slots.renderDescription(item, context)
                      : item.description}
                  </span>
                )}
              </>
            )}
            {disabledReason && (
              <span id={reasonId} className="block text-xs text-destructive">
                {disabledReason}
              </span>
            )}
          </span>
        </button>
        {metadata && (
          <div className="flex flex-wrap gap-3 pb-2 pl-11 pr-3 text-xs text-muted-foreground">
            {metadata}
          </div>
        )}
      </div>
      {actions && <div className="shrink-0 px-3">{actions}</div>}
    </div>
  );
}

export function ResourceCollection({
  viewMode = "list",
  className,
  ...props
}: HTMLAttributes<HTMLDivElement> & { viewMode?: ResourceViewMode }) {
  return (
    <div
      role="listbox"
      aria-multiselectable="true"
      {...props}
      className={cn(
        viewMode === "card"
          ? "grid grid-cols-[repeat(auto-fit,minmax(min(100%,240px),1fr))] gap-4"
          : "flex flex-col divide-y divide-border",
        className
      )}
    />
  );
}
