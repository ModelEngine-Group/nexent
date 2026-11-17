// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useId, useRef, useState } from "react";
import { App, Button, Checkbox, Input, theme, Tooltip } from "antd";
import { AlertTriangle, ChevronDown, Search, Settings } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SelectedResourceRow } from "@/components/common/SelectedResourceRow";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import log from "@/lib/logger";
import { useAgentStore } from "@/stores/agentStore";
import type { Tool, ToolParam } from "@/types/agentConfig";
import { SelectedToolIcon } from "./SelectedToolIcon";
import { useMergedToolParams } from "./useMergedToolParams";

interface SelectedMcpToolGroupProps {
  name: string;
  tools: Tool[];
  selectedTools: Tool[];
  catalogIds: ReadonlySet<string>;
  agentId?: number;
  isReadOnly: boolean;
  getUnavailableReason: (tool: Tool) => string | undefined;
  onConfigure: (tool: Tool, params?: ToolParam[]) => void;
}

function needsConfiguration(params: ToolParam[]) {
  return params.some(
    ({ required, value }) =>
      required && (value === undefined || value === "" || value === null)
  );
}

export function SelectedMcpToolGroup({
  name,
  tools,
  selectedTools,
  catalogIds,
  agentId,
  isReadOnly,
  getUnavailableReason,
  onConfigure,
}: SelectedMcpToolGroupProps) {
  const { t, i18n } = useTranslation("common");
  const { message } = App.useApp();
  const { token } = theme.useToken();
  const mergeParams = useMergedToolParams(agentId);
  const countId = useId();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);
  const selectedIds = new Set(selectedTools.map((tool) => String(tool.id)));
  const selectedNames = new Set(selectedTools.map((tool) => tool.name));
  const count = tools.filter((tool) => selectedIds.has(String(tool.id))).length;
  const title = t("toolPool.mcpSelectService", { name });
  const searchLabel = t("toolPool.mcpSearchTools");
  const editable = !isReadOnly && agentId !== undefined;
  const canCommit = useRef(editable);
  useEffect(() => {
    canCommit.current = editable;
    return () => {
      canCommit.current = false;
    };
  }, [editable]);
  const keyword = search.trim().toLowerCase();
  const entries = tools.map((tool) => ({
    tool,
    description:
      (i18n.language?.startsWith("zh") && tool.description_zh) ||
      tool.description,
    checked: selectedIds.has(String(tool.id)),
    warning: getUnavailableReason(tool),
  }));
  const selectedWarning = entries.find(
    ({ checked, warning }) => checked && warning
  )?.warning;
  const matches = entries
    .filter(({ tool, description }) =>
      [tool.name, description].some((value) =>
        value?.toLowerCase().includes(keyword)
      )
    )
    .map((entry) => ({
      ...entry,
      canAdd:
        catalogIds.has(String(entry.tool.id)) &&
        !entry.warning &&
        !selectedNames.has(entry.tool.name),
    }));
  const bulkTargets = matches.filter(
    ({ tool, checked, canAdd }) =>
      checked || (canAdd && !needsConfiguration(tool.initParams ?? []))
  );
  const allSelected =
    bulkTargets.length > 0 && bulkTargets.every(({ checked }) => checked);

  function changeOpen(next: boolean) {
    setOpen(next);
    if (!next) setSearch("");
  }

  function removeTools(scope: Tool[]) {
    const state = useAgentStore.getState();
    if (!editable || inFlight.current || state.agentId !== agentId) return;
    const ids = new Set(scope.map((tool) => String(tool.id)));
    state.updateTools(
      (state.editedAgent?.tools ?? []).filter(
        (tool) => !ids.has(String(tool.id))
      )
    );
  }

  async function addTools(scope: Tool[], configureIndividually = false) {
    if (!editable || inFlight.current || scope.length === 0) return;
    inFlight.current = true;
    setPending(true);
    try {
      const additions = await Promise.all(
        scope.map(async (tool) => {
          const initParams = await mergeParams(tool);
          return initParams ? { ...tool, initParams } : null;
        })
      );
      const state = useAgentStore.getState();
      if (!canCommit.current || state.agentId !== agentId || state.isReadOnly)
        return;
      const current = state.editedAgent?.tools ?? [];
      const names = new Set(current.map((tool) => tool.name));
      const ids = new Set(current.map((tool) => String(tool.id)));
      const nextTools = [...current];
      for (const tool of additions) {
        if (!tool) return;
        if (ids.has(String(tool.id)) || names.has(tool.name)) continue;
        if (needsConfiguration(tool.initParams)) {
          if (configureIndividually) {
            changeOpen(false);
            onConfigure(tool, tool.initParams);
          }
          continue;
        }
        names.add(tool.name);
        ids.add(String(tool.id));
        nextTools.push(tool);
      }
      if (nextTools.length !== current.length) state.updateTools(nextTools);
    } catch (error) {
      log.error("Failed to select MCP tools:", error);
      if (useAgentStore.getState().agentId === agentId) {
        message.error(t("toolPool.selectionFailed"));
      }
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }

  return (
    <SelectedResourceRow
      name={name}
      data-testid={`agent-selected-mcp-service-${name}`}
      className="shadow-none"
      icon={<SelectedToolIcon service />}
      actions={
        <Popover open={open} onOpenChange={changeOpen}>
          {selectedWarning && (
            <Tooltip title={t(selectedWarning)}>
              <AlertTriangle
                size={14}
                aria-label={t(selectedWarning)}
                className="shrink-0"
                style={{ color: token.colorWarning }}
              />
            </Tooltip>
          )}
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-label={title}
              aria-describedby={countId}
              className="inline-flex items-center gap-1 rounded bg-[var(--color-select)] px-2 py-0.5 text-xs text-[var(--color-brand)] hover:text-[var(--color-brand-hover)] focus-visible:outline-primary"
            >
              <span id={countId}>
                {t("toolPool.mcpSelectedToolCount", {
                  selected: count,
                  total: tools.length,
                })}
              </span>
              <ChevronDown size={12} aria-hidden />
            </button>
          </PopoverTrigger>
          <PopoverContent
            align="start"
            side="top"
            aria-label={title}
            className="flex max-h-[min(25rem,var(--radix-popover-content-available-height))] w-[min(20rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-xl border-border p-0 shadow-lg"
          >
            <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-border px-3">
              <span className="truncate text-sm">
                {t("toolPool.mcpToolsTitle", { name })}
              </span>
              {editable && (
                <Button
                  type="link"
                  size="small"
                  className="!px-0 !text-xs"
                  loading={pending}
                  disabled={!bulkTargets.length}
                  onClick={() =>
                    allSelected
                      ? removeTools(bulkTargets.map(({ tool }) => tool))
                      : void addTools(
                          bulkTargets
                            .filter(({ checked }) => !checked)
                            .map(({ tool }) => tool)
                        )
                  }
                >
                  {t(allSelected ? "common.deselectAll" : "common.selectAll")}
                </Button>
              )}
            </div>
            <div className="flex h-9 shrink-0 items-center border-b border-border px-3 focus-within:bg-muted">
              <Input
                allowClear
                size="small"
                variant="borderless"
                styles={{ root: { paddingInline: 0 } }}
                prefix={
                  <Search
                    size={14}
                    aria-hidden
                    className="mr-1 text-muted-foreground"
                  />
                }
                aria-label={searchLabel}
                placeholder={searchLabel}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
            <div className="min-h-0 overflow-y-auto py-1 [scrollbar-width:thin]">
              {matches.length === 0 && (
                <p className="px-3 py-3 text-center text-xs text-muted-foreground">
                  {t("toolPool.noSearchResults")}
                </p>
              )}
              {matches.map(
                ({ tool, description, warning, checked, canAdd }) => (
                  <div
                    key={tool.id}
                    className="flex items-start gap-1 px-3 py-1.5 hover:bg-muted/70"
                  >
                    <Checkbox
                      aria-label={tool.name}
                      checked={checked}
                      disabled={!editable || pending || (!checked && !canAdd)}
                      className="min-w-0 flex-1"
                      styles={{
                        root: { alignItems: "flex-start" },
                        icon: { alignSelf: "flex-start", marginTop: 1 },
                        label: { minWidth: 0, paddingInlineEnd: 0 },
                      }}
                      onChange={({ target }) =>
                        target.checked
                          ? void addTools([tool], true)
                          : removeTools([tool])
                      }
                    >
                      <span className="block break-all font-mono text-xs leading-4">
                        {tool.name}
                      </span>
                      {description && (
                        <span
                          className="line-clamp-2 wrap-break-word text-xs leading-4 text-muted-foreground"
                          title={description}
                        >
                          {description}
                        </span>
                      )}
                    </Checkbox>
                    {warning && (
                      <Tooltip title={t(warning)}>
                        <AlertTriangle
                          size={14}
                          aria-label={t(warning)}
                          className="mt-1 shrink-0"
                          style={{ color: token.colorWarning }}
                        />
                      </Tooltip>
                    )}
                    {checked && editable && (
                      <Button
                        type="text"
                        size="small"
                        icon={<Settings size={14} />}
                        aria-label={`${t("toolPool.configure")} ${tool.name}`}
                        className="!size-5 !shrink-0 !text-muted-foreground"
                        disabled={pending}
                        onClick={() => {
                          changeOpen(false);
                          onConfigure(tool);
                        }}
                      />
                    )}
                  </div>
                )
              )}
            </div>
            <div
              aria-live="polite"
              className="flex shrink-0 flex-wrap items-center gap-x-2 border-t border-border bg-muted/70 px-3 py-2 text-xs text-muted-foreground"
            >
              <span>
                {t("toolPool.mcpSelectedToolSummary", {
                  selected: count,
                  total: tools.length,
                })}
              </span>
              {editable && <span>{t("toolPool.mcpAutosaveHint")}</span>}
            </div>
          </PopoverContent>
        </Popover>
      }
    />
  );
}
