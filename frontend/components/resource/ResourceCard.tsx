"use client";

import type { ReactNode, Ref } from "react";

import ResourceCardShell from "./ResourceCardShell";

export interface ResourceCardProps {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  badge?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  onClick?: () => void;
  selected?: boolean;
  className?: string;
  containerRef?: Ref<HTMLDivElement>;
}

export default function ResourceCard({
  title,
  description,
  icon,
  badge,
  meta,
  actions,
  footer,
  onClick,
  selected,
  className,
  containerRef,
}: ResourceCardProps) {
  return (
    <ResourceCardShell
      onClick={onClick}
      selected={selected}
      className={className}
      containerRef={containerRef}
    >
      <div className="flex items-start gap-3">
        {icon ? <span className="shrink-0">{icon}</span> : null}
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-base font-semibold text-slate-900">
            {title}
          </h2>
          {badge ? (
            <div className="mt-1 flex flex-wrap gap-2">{badge}</div>
          ) : null}
        </div>
        {actions ? (
          <div onClick={(event) => event.stopPropagation()}>{actions}</div>
        ) : null}
      </div>
      <div className="flex flex-1 flex-col">
        {description ? (
          <div className="mt-4 line-clamp-3 text-sm leading-6 text-slate-600">
            {description}
          </div>
        ) : null}
        <div className="mt-auto">
          {meta || footer ? (
            <div className="flex items-center justify-between gap-3 border-t border-slate-100 pt-4">
              <div className="min-w-0">{meta}</div>
              <div className="shrink-0">{footer}</div>
            </div>
          ) : null}
        </div>
      </div>
    </ResourceCardShell>
  );
}
