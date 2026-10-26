// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useId, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import { CheckMark } from "./ResourceDrawer";
import type { McpServer, Tool } from "@/types/agentConfig";

interface McpToolGroupProps {
  name: string;
  server?: McpServer;
  tools: Tool[];
  selectedIds: Set<number>;
  eligibleIds: Set<number>;
  selecting: boolean;
  searching: boolean;
  onSelect: (tools: Tool[], checked: boolean) => void;
  renderTool: (tool: Tool) => ReactNode;
}

/** The checkbox edits tool IDs; expanding a service never changes selection. */
export function McpToolGroup({
  name,
  server,
  tools,
  selectedIds,
  eligibleIds,
  selecting,
  searching,
  onSelect,
  renderTool,
}: McpToolGroupProps) {
  const { t } = useTranslation("common");
  const contentId = useId();
  const [expanded, setExpanded] = useState<boolean | null>(null);
  const isExpanded = expanded ?? searching;
  const targets = tools.filter(
    (tool) =>
      selectedIds.has(parseInt(tool.id)) || eligibleIds.has(parseInt(tool.id))
  );
  const count = targets.filter((tool) =>
    selectedIds.has(parseInt(tool.id))
  ).length;
  const checked = targets.length > 0 && count === targets.length;

  return (
    <section aria-label={name} className="py-2">
      <div className="flex items-start gap-3 px-3 py-2">
        <span className="pt-0.5">
          <CheckMark
            checked={checked}
            indeterminate={count > 0 && !checked}
            disabled={selecting || targets.length === 0}
            ariaLabel={t("toolPool.mcpSelectService", { name })}
            onToggle={() => onSelect(tools, !checked)}
          />
        </span>
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
              {server?.tags?.slice(0, 2).map((tag) => (
                <span
                  key={tag}
                  className="rounded bg-muted px-1.5 text-xs text-muted-foreground"
                >
                  {tag}
                </span>
              ))}
            </span>
            <span className="shrink-0 text-xs text-muted-foreground">
              {t("toolPool.mcpToolCount", { count: tools.length })}
            </span>
            <ChevronDown
              aria-hidden
              className={`size-3.5 shrink-0 text-muted-foreground ${isExpanded ? "rotate-180" : ""}`}
            />
          </span>
          {server?.description && (
            <Tooltip title={server.description}>
              <span className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                {server.description}
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
        {isExpanded && tools.map(renderTool)}
      </div>
    </section>
  );
}
