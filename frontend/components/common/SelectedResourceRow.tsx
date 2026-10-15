"use client";

import { Tooltip } from "antd";
import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface SelectedResourceRowProps extends HTMLAttributes<HTMLDivElement> {
  icon: ReactNode;
  name: string;
  nameTooltip?: ReactNode;
  metadata?: ReactNode;
  actions?: ReactNode;
}

export function SelectedResourceRow({
  icon,
  name,
  nameTooltip,
  metadata,
  actions,
  className,
  ...props
}: SelectedResourceRowProps) {
  return (
    <div
      {...props}
      className={cn(
        "flex h-12 min-w-0 items-center rounded-[4px] border border-solid border-[#dfdfdf] bg-white px-3 py-2 shadow-[0_2px_8px_rgba(0,0,0,0.08)]",
        className
      )}
    >
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <span className="flex shrink-0 items-center justify-center">
          {icon}
        </span>
        <Tooltip title={nameTooltip ?? name}>
          <span
            data-slot="selected-resource-name"
            className="min-w-0 truncate text-sm font-normal leading-[22px] tracking-[0px] text-[#191919]"
          >
            {name}
          </span>
        </Tooltip>
        {metadata && (
          <span className="flex min-w-0 shrink items-center gap-2 overflow-hidden">
            {metadata}
          </span>
        )}
      </div>
      {actions && (
        <div className="ml-2 flex shrink-0 items-center">{actions}</div>
      )}
    </div>
  );
}

export interface SelectedResourceTagProps extends HTMLAttributes<HTMLSpanElement> {
  children: ReactNode;
}

export function SelectedResourceTag({
  children,
  className,
  ...props
}: SelectedResourceTagProps) {
  return (
    <span
      {...props}
      data-slot="selected-resource-tag"
      className={cn(
        "truncate rounded-[4px] bg-[#f3f3f3] px-2 text-xs font-normal leading-[18px] tracking-[0px] text-[#777777]",
        className
      )}
    >
      {children}
    </span>
  );
}
