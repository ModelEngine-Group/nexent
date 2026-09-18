"use client";

import { useId, type ReactNode, type Ref } from "react";

import { cn } from "@/lib/utils";

export interface ResourceCardProps {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  /** Status or lifecycle content displayed beside the title. */
  badge?: ReactNode;
  /** Resource tags displayed below the description. */
  tags?: ReactNode;
  meta?: ReactNode;
  /** Status icons displayed beside the title, left of actions. */
  headerActions?: ReactNode;
  /** Actions displayed at the top-right (e.g., "..." menu). */
  actions?: ReactNode;
  footer?: ReactNode;
  onClick?: () => void;
  selected?: boolean;
  disabled?: boolean;
  selectionRole?: "option";
  describedBy?: string;
  className?: string;
  containerRef?: Ref<HTMLDivElement>;
}

export default function ResourceCard({
  title,
  description,
  icon,
  badge,
  tags,
  meta,
  headerActions,
  actions,
  footer,
  onClick,
  selected,
  disabled = false,
  selectionRole,
  describedBy,
  className,
  containerRef,
}: ResourceCardProps) {
  const titleId = `resource-card-title-${useId()}`;
  const isInteractive = onClick !== undefined;
  const actionClassName = isInteractive
    ? "pointer-events-auto relative z-10"
    : undefined;

  return (
    <div
      ref={containerRef}
      className={cn(
        "group relative flex min-h-[240px] flex-col rounded-lg border bg-white text-left transition",
        "p-5 shadow-sm hover:border-blue-300 hover:shadow-md",
        selected && "border-blue-400 ring-1 ring-blue-200",
        !selected && "border-slate-200",
        disabled &&
          "cursor-not-allowed opacity-50 hover:border-slate-200 hover:shadow-sm",
        className
      )}
    >
      {isInteractive ? (
        <button
          type="button"
          aria-labelledby={titleId}
          role={selectionRole}
          aria-pressed={selectionRole ? undefined : selected}
          aria-selected={selectionRole ? selected : undefined}
          aria-describedby={describedBy}
          disabled={disabled}
          onClick={onClick}
          className="absolute inset-0 z-0 size-full cursor-pointer rounded-[inherit] border-0 bg-transparent p-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset disabled:cursor-not-allowed"
        />
      ) : null}
      <div
        className={cn(
          "flex min-h-0 flex-1 flex-col",
          isInteractive && "pointer-events-none relative z-[1]"
        )}
      >
        <div className="flex items-start gap-3">
          {icon ? <span className="shrink-0">{icon}</span> : null}
          <div className="min-w-0 flex-1">
            <h2
              id={titleId}
              className="truncate text-base font-semibold text-slate-900"
            >
              {title}
            </h2>
            {badge ? (
              <div className="mt-1 flex flex-wrap gap-2">{badge}</div>
            ) : null}
          </div>
          {headerActions || actions ? (
            <div
              data-resource-card-action
              className={cn(
                "flex shrink-0 items-center gap-1",
                actionClassName
              )}
            >
              {headerActions}
              {actions}
            </div>
          ) : null}
        </div>
        <div className="flex flex-1 flex-col">
          {description ? (
            <div className="mt-4 line-clamp-3 text-sm leading-6 text-slate-600">
              {description}
            </div>
          ) : null}
          {tags ? (
            <div
              className={cn(
                "flex flex-wrap gap-2 pb-2 text-xs",
                description ? "mt-3" : "mt-4"
              )}
            >
              {tags}
            </div>
          ) : null}
          <div className="mt-auto">
            {meta || footer ? (
              <div className="flex items-center justify-between gap-3 border-t border-slate-100 pt-4">
                <div className="min-w-0">{meta}</div>
                {footer ? (
                  <div data-resource-card-action className={actionClassName}>
                    {footer}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
