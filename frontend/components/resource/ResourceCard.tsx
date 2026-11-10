// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useId, type ReactNode, type Ref } from "react";

import { cn } from "@/lib/utils";
import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";

export interface ResourceCardProps {
  title: ReactNode;
  /** Reuse the same guarded actions in the repository table. */
  actionsOnly?: boolean;
  /** Secondary text displayed directly below the title. */
  subtitle?: ReactNode;
  description?: ReactNode;
  descriptionLabel?: ReactNode;
  /** Maximum number of visible description lines before truncation. */
  descriptionLines?: number;
  icon?: ReactNode;
  /** Status or lifecycle content displayed beside the title. */
  badge?: ReactNode;
  /** Status content displayed across the card above the description. */
  statusRow?: ReactNode;
  /** Resource tags displayed below the description. */
  tags?: ReactNode;
  tagsPlacement?: "header" | "body";
  meta?: ReactNode;
  /** Display footer actions below metadata instead of beside it. */
  footerLayout?: "inline" | "stacked";
  /** Status icons displayed beside the title, left of actions. */
  headerActions?: ReactNode;
  /** Keep header positions stable while centering the icon vertically. */
  fixedHeaderLayout?: boolean;
  /** Actions displayed at the top-right (e.g., "..." menu). */
  actions?: ReactNode;
  footer?: ReactNode;
  /** Use for legacy resource cards while their field mapping is migrated. */
  children?: ReactNode;
  onClick?: () => void;
  onDoubleClick?: () => void;
  selected?: boolean;
  disabled?: boolean;
  selectionRole?: "option";
  describedBy?: string;
  className?: string;
  containerRef?: Ref<HTMLDivElement>;
}

export default function ResourceCard({
  title,
  actionsOnly = false,
  subtitle,
  description,
  descriptionLabel,
  descriptionLines = 3,
  icon,
  badge,
  statusRow,
  tags,
  tagsPlacement = "body",
  meta,
  footerLayout = "stacked",
  headerActions,
  fixedHeaderLayout = false,
  actions,
  footer,
  children,
  onClick,
  onDoubleClick,
  selected,
  disabled = false,
  selectionRole,
  describedBy,
  className,
  containerRef,
}: ResourceCardProps) {
  const presentation = useRepositoryPresentation();
  const compact = presentation !== null;
  const repositoryView = presentation?.query?.get("view") !== "mine";
  const measuredAgent =
    repositoryView && presentation?.resourceType === "agent";
  const measuredMcp = repositoryView && presentation?.resourceType === "mcp";
  const measuredMineMcp =
    presentation?.resourceType === "mcp" && !repositoryView;
  const footerInHeader = compact && !measuredMineMcp;
  const measuredSkill =
    repositoryView && presentation?.resourceType === "skill";
  const titleId = `resource-card-title-${useId()}`;
  const isInteractive = onClick !== undefined;
  const actionClassName = isInteractive
    ? "pointer-events-auto relative z-10"
    : undefined;

  if (actionsOnly)
    return (
      <div className="flex items-center gap-2">
        {measuredAgent ? footer : null}
        {headerActions}
        {actions}
        {!measuredAgent ? footer : null}
      </div>
    );

  return (
    <div
      ref={containerRef}
      className={cn(
        "group relative flex min-w-0 min-h-[240px] flex-col rounded-xl border bg-white text-left transition",
        "p-5 shadow-sm hover:border-blue-300 hover:shadow-md dark:bg-slate-900",
        compact && "min-h-0 rounded-lg p-4 shadow-none",
        selected && "border-blue-400 ring-1 ring-blue-200 dark:ring-blue-900",
        !selected && "border-slate-200 dark:border-slate-700",
        disabled && "cursor-not-allowed opacity-50",
        className,
        measuredAgent &&
          "self-start rounded-xl border-[rgba(201,201,201,0.4)] px-[24px] py-[16px]",
        measuredMcp &&
          "min-h-[140px] rounded-xl border-0 px-6 py-4 outline outline-1 -outline-offset-1 outline-[#C9C9C9]/40 hover:outline-blue-300",
        measuredMineMcp &&
          "min-h-[142px] rounded-xl border-[rgba(201,201,201,0.4)] bg-white px-6 py-4",
        measuredSkill &&
          "min-h-[154px] rounded-xl border-[rgba(201,201,201,0.4)] px-6 py-4"
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
              title={typeof title === "string" ? title : undefined}
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
            <div
              className={cn(
                "flex shrink-0 gap-3",
                fixedHeaderLayout ? "min-h-[60px] items-center" : "items-start",
                (measuredMcp || measuredMineMcp) && "min-h-12 items-center",
                measuredAgent && "min-h-14"
              )}
            >
              {icon ? <span className="shrink-0">{icon}</span> : null}
              <div
                className={cn(
                  "min-w-0 flex-1",
                  measuredAgent && "self-end",
                  fixedHeaderLayout &&
                    "flex min-h-11 flex-col justify-between self-center"
                )}
              >
                <h2
                  id={titleId}
                  title={typeof title === "string" ? title : undefined}
                  className={cn(
                    "truncate text-base font-semibold text-slate-900 dark:text-slate-100",
                    (measuredAgent ||
                      measuredMcp ||
                      measuredMineMcp ||
                      measuredSkill) &&
                      "font-['HarmonyOS_Sans_SC',sans-serif] font-medium leading-6 tracking-normal text-[#191919]"
                  )}
                >
                  {title}
                </h2>
                {subtitle ? (
                  <div
                    className={cn(
                      "mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400",
                      measuredAgent &&
                        "mt-2 font-['HarmonyHeiTi',sans-serif] font-normal leading-[18px] tracking-normal text-[rgba(25,25,25,0.7)]"
                    )}
                  >
                    {subtitle}
                  </div>
                ) : null}
                {badge ? (
                  <div className="mt-1 flex flex-wrap gap-2">{badge}</div>
                ) : null}
                {tags && tagsPlacement === "header" ? (
                  <div
                    className={cn(
                      "mt-1 flex flex-wrap gap-1 text-xs",
                      (measuredMcp || measuredMineMcp) && "mt-0",
                      measuredSkill && "gap-2"
                    )}
                  >
                    {tags}
                  </div>
                ) : null}
              </div>
              {headerActions || actions || (footerInHeader && footer) ? (
                <div
                  data-resource-card-action
                  className={cn(
                    "flex shrink-0 items-start gap-1",
                    fixedHeaderLayout && "self-center",
                    measuredAgent &&
                      (subtitle ? "mb-[22px] self-end" : "-mb-1 self-end"),
                    actionClassName
                  )}
                  onDoubleClick={(event) => event.stopPropagation()}
                >
                  {headerActions}
                  {actions}
                  {footerInHeader ? footer : null}
                </div>
              ) : null}
            </div>
            <div
              className={cn(
                "flex flex-1 flex-col",
                measuredAgent && "gap-2 pt-2"
              )}
            >
              {statusRow ? (
                <div className={cn("min-w-0", !measuredAgent && "mt-1")}>
                  {statusRow}
                </div>
              ) : null}
              {description ? (
                <div
                  className={
                    descriptionLabel ? "flex items-start gap-2" : "contents"
                  }
                >
                  {descriptionLabel && (
                    <span className="shrink-0 text-xs leading-5 text-[#191919]/70">
                      {descriptionLabel}
                    </span>
                  )}
                  <div
                    className={cn(
                      "min-h-0 overflow-hidden [overflow-wrap:anywhere] text-sm leading-6 text-slate-600 dark:text-slate-300",
                      !measuredAgent &&
                        (compact
                          ? "mt-2.5 leading-5"
                          : statusRow
                            ? "mt-3"
                            : "mt-4"),
                      (measuredAgent || measuredMcp || measuredMineMcp) &&
                        "font-['HarmonyOS_Sans_SC',sans-serif] text-xs font-normal leading-5 tracking-normal text-[rgba(25,25,25,0.7)]",
                      measuredSkill &&
                        "font-['HarmonyHeiTi',sans-serif] text-xs font-normal leading-[18px] tracking-normal text-[#777777]"
                    )}
                    style={{
                      display: "-webkit-box",
                      WebkitBoxOrient: "vertical",
                      WebkitLineClamp: compact
                        ? Math.min(2, descriptionLines)
                        : descriptionLines,
                    }}
                  >
                    {description}
                  </div>
                </div>
              ) : null}
              {tags && tagsPlacement === "body" ? (
                <div
                  className={cn(
                    "flex flex-wrap gap-2 text-xs [&>*]:max-w-full [&>*]:[overflow-wrap:anywhere]",
                    !measuredAgent && "pb-2",
                    !measuredAgent &&
                      (compact ? "mt-2.5" : description ? "mt-3" : "mt-4")
                  )}
                >
                  {tags}
                </div>
              ) : null}
              <div className={cn("shrink-0", !measuredAgent && "mt-auto")}>
                {footerLayout === "stacked" ? (
                  <>
                    {meta ? (
                      <div
                        className={cn(
                          "flex min-h-7 items-center justify-between gap-3 border-t border-slate-100 pt-4 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400",
                          compact && "min-h-0 border-0 pt-2.5"
                        )}
                      >
                        {meta}
                      </div>
                    ) : null}
                    {!footerInHeader && footer ? (
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
                  <div
                    className={cn(
                      "flex min-h-7 items-center justify-between gap-3 border-t border-slate-100 pt-4 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400",
                      compact && "min-h-0 border-0 pt-2.5",
                      (measuredMcp || measuredMineMcp) &&
                        "leading-5 text-[#777777]",
                      measuredAgent && "pt-0"
                    )}
                  >
                    <div
                      className={cn(
                        "min-w-0",
                        compact &&
                          "flex flex-1 flex-wrap items-center gap-x-3 gap-y-1"
                      )}
                    >
                      {meta}
                    </div>
                    {!footerInHeader && footer ? (
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
