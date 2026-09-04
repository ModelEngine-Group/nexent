"use client";

import type { KeyboardEvent, ReactNode, Ref } from "react";

import { cn } from "@/lib/utils";

export interface ResourceCardShellProps {
  children: ReactNode;
  header?: ReactNode;
  footer?: ReactNode;
  onClick?: () => void;
  selected?: boolean;
  variant?: "default" | "create";
  className?: string;
  containerRef?: Ref<HTMLDivElement>;
}

export default function ResourceCardShell({
  children,
  header,
  footer,
  onClick,
  selected = false,
  variant = "default",
  className,
  containerRef,
}: ResourceCardShellProps) {
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget || !onClick) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onClick();
    }
  };

  return (
    <div
      ref={containerRef}
      onClick={onClick}
      onKeyDown={handleKeyDown}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      className={cn(
        "group flex min-h-[240px] flex-col rounded-lg border bg-white text-left transition",
        variant === "create"
          ? "items-center justify-center border-2 border-dashed border-slate-300 p-6 text-center hover:border-blue-400 hover:bg-slate-50/50"
          : "p-5 shadow-sm hover:border-blue-300 hover:shadow-md",
        selected && "border-blue-400 ring-1 ring-blue-200",
        !selected && variant === "default" && "border-slate-200",
        className
      )}
    >
      {header}
      <div
        className={cn(
          "flex min-h-0 flex-1 flex-col",
          variant === "create" && "items-center justify-center"
        )}
      >
        {children}
      </div>
      {footer}
    </div>
  );
}
