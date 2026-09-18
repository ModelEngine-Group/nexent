"use client";

import { useId, type ReactNode, type Ref } from "react";

import { cn } from "@/lib/utils";

export interface ResourceCardProps {
  title: ReactNode;
  /** Secondary text displayed directly below the title. */
  subtitle?: ReactNode;
  description?: ReactNode;
  /** Maximum number of visible description lines before truncation. */
  descriptionLines?: number;
  icon?: ReactNode;
  /** Status or lifecycle content displayed beside the title. */
  badge?: ReactNode;
  /** Resource tags displayed below the description. */
  tags?: ReactNode;
  meta?: ReactNode;
  /** Display footer actions below metadata instead of beside it. */
  footerLayout?: "inline" | "stacked";
  /** Status icons displayed beside the title, left of actions. */
  headerActions?: ReactNode;
  /** Actions displayed at the top-right (e.g., "..." menu). */
  actions?: ReactNode;
  footer?: ReactNode;
  /** Use for legacy resource cards while their field mapping is migrated. */
  children?: ReactNode;
  onClick?: () => void;
  onDoubleClick?: () => void;
  selected?: boolean;
  className?: string;
  containerRef?: Ref<HTMLDivElement>;
}

export default function ResourceCard({
  title,
  subtitle,
  description,
  descriptionLines = 3,
  icon,
  badge,
  tags,
  meta,
  footerLayout = "stacked",
  headerActions,
  actions,
  footer,
  children,
  onClick,
  onDoubleClick,
  selected,
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
        "group relative flex min-h-[240px] flex-col rounded-xl border bg-white text-left transition",
        "p-5 shadow-sm hover:border-blue-300 hover:shadow-md dark:bg-slate-900",
        selected && "border-blue-400 ring-1 ring-blue-200 dark:ring-blue-900",
        !selected && "border-slate-200 dark:border-slate-700",
        className
      )}
      onDoubleClick={onDoubleClick}
    >
      {children ? (
        children
      ) : (
        <>
          {isInteractive ? (
            <button
              type="button"
              aria-labelledby={titleId}
              aria-pressed={selected}
              onClick={onClick}
              className="absolute inset-0 z-0 size-full cursor-pointer rounded-[inherit] border-0 bg-transparent p-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset"
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
                  className="truncate text-base font-semibold text-slate-900 dark:text-slate-100"
                >
                  {title}
                </h2>
                {subtitle ? (
                  <div className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">
                    {subtitle}
                  </div>
                ) : null}
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
                  onDoubleClick={(event) => event.stopPropagation()}
                >
                  {headerActions}
                  {actions}
                </div>
              ) : null}
            </div>
            <div className="flex flex-1 flex-col">
              {description ? (
                <div
                  className="mt-4 min-h-0 overflow-hidden text-sm leading-6 text-slate-600 dark:text-slate-300"
                  style={{
                    display: "-webkit-box",
                    WebkitBoxOrient: "vertical",
                    WebkitLineClamp: descriptionLines,
                  }}
                >
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
                {footerLayout === "stacked" ? (
                  <>
                    {meta ? (
                      <div className="flex min-h-7 items-center justify-between gap-3 border-t border-slate-100 pt-4 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
                        {meta}
                      </div>
                    ) : null}
                    {footer ? (
                      <div
                        data-resource-card-action
                        className={cn("mt-4", actionClassName)}
                        onDoubleClick={(event) => event.stopPropagation()}
                      >
                        {footer}
                      </div>
                    ) : null}
                  </>
                ) : meta || footer ? (
                  <div className="flex min-h-7 items-center justify-between gap-3 border-t border-slate-100 pt-4 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
                    <div className="min-w-0">{meta}</div>
                    {footer ? (
                      <div
                        data-resource-card-action
                        className={cn("shrink-0", actionClassName)}
                        onDoubleClick={(event) => event.stopPropagation()}
                      >
                        {footer}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
