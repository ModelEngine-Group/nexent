// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { CheckMark } from "./ResourceDrawer";
import { McpResourceGroup } from "./McpResourceGroup";
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
  const targets = tools.filter(
    (tool) =>
      selectedIds.has(parseInt(tool.id)) || eligibleIds.has(parseInt(tool.id))
  );
  const count = targets.filter((tool) =>
    selectedIds.has(parseInt(tool.id))
  ).length;
  const checked = targets.length > 0 && count === targets.length;
  return (
    <McpResourceGroup
      name={name}
      description={server?.description}
      tags={server?.tags}
      toolCount={tools.length}
      searching={searching}
      selection={
        <CheckMark
          checked={checked}
          indeterminate={count > 0 && !checked}
          disabled={selecting || targets.length === 0}
          ariaLabel={t("toolPool.mcpSelectService", { name })}
          onToggle={() => onSelect(tools, !checked)}
        />
      }
    >
      {() => tools.map(renderTool)}
    </McpResourceGroup>
  );
}
