// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useId, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { Tooltip } from "antd";
import { useTranslation } from "react-i18next";

interface McpResourceGroupProps {
  name: string;
  description?: string | null;
  tags?: string[];
  toolCount: number;
  searching: boolean;
  selection: ReactNode;
  status?: ReactNode;
  children: ReactNode | (() => ReactNode);
}

/** Shared service disclosure; selection remains owned by the caller. */
export function McpResourceGroup({
  name,
  description,
  tags,
  toolCount,
  searching,
  selection,
  status,
  children,
}: McpResourceGroupProps) {
  const { t } = useTranslation("common");
  const contentId = useId();
  const [expanded, setExpanded] = useState<boolean | null>(null);
  const isExpanded = expanded ?? searching;
  return (
    <section aria-label={name} className="py-2">
      <div className="flex items-start gap-3 px-3 py-2">
        <span className="pt-0.5">{selection}</span>
        <button
          type="button"
          aria-label={name}
          aria-expanded={isExpanded}
          aria-controls={contentId}
          onClick={() => setExpanded(!isExpanded)}
          className="min-w-0 flex-1 text-left focus-visible:outline-primary"
        >
          <span className="flex items-center gap-2">
            <span className="flex min-w-0 flex-1 items-center gap-2">
              <span
                className="min-w-0 truncate text-sm font-medium"
                title={name}
              >
                {name}
              </span>
              {tags?.slice(0, 2).map((tag) => (
                <span
                  key={tag}
                  className="rounded bg-muted px-1.5 text-xs text-muted-foreground"
                >
                  {tag}
                </span>
              ))}
              {status}
            </span>
            <span className="shrink-0 text-xs text-muted-foreground">
              {t("toolPool.mcpToolCount", { count: toolCount })}
            </span>
            <ChevronDown
              aria-hidden
              className={`size-3.5 shrink-0 text-muted-foreground ${isExpanded ? "rotate-180" : ""}`}
            />
          </span>
          {description && (
            <Tooltip title={description}>
              <span className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                {description}
              </span>
            </Tooltip>
          )}
        </button>
      </div>
      <div
        id={contentId}
        hidden={!isExpanded}
        className="ml-5 border-l border-primary/20 pl-2"
      >
        {isExpanded && (typeof children === "function" ? children() : children)}
      </div>
    </section>
  );
}
