"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Button } from "antd";
import { Download } from "lucide-react";

export interface WebMcpCardItem {
  name: string;
  description?: string;
  source?: string;
  url?: string;
  transport?: string;
  score?: number;
  reason?: string;
}

export interface WebMcpCardProps {
  /** The draft agent_id (used for the install callback context, though MCP
   * install is handled by opening the existing AddMcpServiceModal). */
  agentId: number;
  item: WebMcpCardItem;
  /** Optional callback to open the existing AddMcpServiceModal prefilled. */
  onInstall?: (item: WebMcpCardItem) => void;
}

/**
 * Renders a single web MCP server recommendation with an "Install" button.
 * Clicking Install opens the existing AddMcpServiceModal prefilled with the
 * card's url/server_name. No new install logic is implemented here — the
 * modal handles POST /mcp/add.
 *
 * Rendered from a ```nl2agent-web-mcp fenced JSON block.
 */
export const WebMcpCard: React.FC<WebMcpCardProps> = ({ item, onInstall }) => {
  const { t } = useTranslation("common");

  return (
    <div className="my-2 border border-sky-200 rounded-lg p-3 bg-sky-50/40">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm">{item.name}</span>
            {item.source && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-50 text-sky-700 border border-sky-200">
                {item.source}
              </span>
            )}
            {item.transport && (
              <span className="text-[10px] text-gray-500">{item.transport}</span>
            )}
            {typeof item.score === "number" && (
              <span className="text-[10px] text-gray-500">score: {item.score}</span>
            )}
          </div>
          {item.description && (
            <div className="text-xs text-gray-600 mt-1">{item.description}</div>
          )}
          {item.reason && (
            <div className="text-xs text-gray-400 mt-1 italic">{item.reason}</div>
          )}
          {item.url && (
            <div className="text-[11px] text-gray-400 mt-1 truncate">{item.url}</div>
          )}
        </div>
        <Button
          size="small"
          icon={<Download className="h-3.5 w-3.5" />}
          onClick={() => onInstall?.(item)}
        >
          {t("nl2agent.webMcp.install", "Install")}
        </Button>
      </div>
    </div>
  );
};
