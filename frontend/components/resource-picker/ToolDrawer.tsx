// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Tooltip } from "antd";
import { Settings } from "lucide-react";
import i18n from "i18next";

import log from "@/lib/logger";
import { McpToolGroup } from "./McpToolGroup";
import { ResourceDrawer } from "./ResourceDrawer";
import { useToolList } from "@/hooks/agent/useToolList";
import { useScanToolList } from "@/hooks/agent/useScanToolList";
import { useMcpServerList } from "@/hooks/mcp/useMcpServerList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useAgentStore } from "@/stores/agentStore";
import { usePrefetchKnowledgeBases } from "@/hooks/useKnowledgeBaseSelector";
import { useConfig } from "@/hooks/useConfig";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { TOOL_SOURCE_TYPES } from "@/const/agentConfig";
import { cn } from "@/lib/utils";
import type { Tool, ToolParam } from "@/types/agentConfig";
import ToolConfigModal from "@/app/agents/components/capability/tool/ToolConfigModal";
import { useMergedToolParams } from "@/app/agents/[agentId]/components/capability/tool/useMergedToolParams";
import {
  TOOLS_REQUIRING_EMBEDDING,
  TOOLS_REQUIRING_IMAGE_UNDERSTANDING,
  TOOLS_REQUIRING_AUDIO_UNDERSTANDING,
  TOOLS_REQUIRING_VIDEO_UNDERSTANDING,
  getToolKbType,
  getToolLabels,
} from "@/app/agents/components/capability/tool/utils";

import { ResourceCollection, ResourceItem } from "./ResourceItem";

import { useResourceTagFilter } from "@/hooks/useResourceTagFilter";
import { useToolTagAssignments } from "@/hooks/useToolTagAssignments";
import { ResourceTagFilterControl } from "./ResourceTagFilterControl";
import { ResourceAssignedTags } from "./ResourceAssignedTags";

import styles from "./ResourcePickerDrawer.module.css";

// Stable fallback so the zustand selector returns a referentially-stable value
// when `editedAgent?.tools` is undefined (avoids a getSnapshot infinite loop).
const EMPTY_TOOLS: Tool[] = [];

function isToolDisabled(
  name: string,
  img: boolean,
  vid: boolean,
  emb: boolean,
  audio: boolean
): boolean {
  if (TOOLS_REQUIRING_IMAGE_UNDERSTANDING.includes(name) && !img) return true;
  if (TOOLS_REQUIRING_AUDIO_UNDERSTANDING.includes(name) && !audio) return true;
  if (TOOLS_REQUIRING_VIDEO_UNDERSTANDING.includes(name) && !vid) return true;
  if (TOOLS_REQUIRING_EMBEDDING.includes(name) && !emb) return true;
  return false;
}

function getToolDisabledTooltipKey(
  name: string,
  img: boolean,
  vid: boolean,
  emb: boolean,
  audio: boolean
): string | null {
  if (TOOLS_REQUIRING_IMAGE_UNDERSTANDING.includes(name) && !img) {
    return "toolPool.imageUnderstandingDisabledTooltip";
  }
  if (TOOLS_REQUIRING_AUDIO_UNDERSTANDING.includes(name) && !audio) {
    return "toolPool.audioUnderstandingDisabledTooltip";
  }
  if (TOOLS_REQUIRING_VIDEO_UNDERSTANDING.includes(name) && !vid) {
    return "toolPool.videoUnderstandingDisabledTooltip";
  }
  if (TOOLS_REQUIRING_EMBEDDING.includes(name) && !emb) {
    return "toolPool.embeddingDisabledTooltip";
  }
  return null;
}

function getToolDescription(tool: Tool): string {
  const locale = i18n.language || "en";
  if (locale === "zh" && tool.description_zh) {
    return tool.description_zh;
  }
  return tool.description || "";
}

const SOURCE_TABS: { key: string; labelKey: string; sourceValue: string }[] = [
  {
    key: "local",
    labelKey: "toolPool.group.local",
    sourceValue: TOOL_SOURCE_TYPES.LOCAL,
  },
  {
    key: "mcp",
    labelKey: "toolPool.group.mcp",
    sourceValue: TOOL_SOURCE_TYPES.MCP,
  },
  {
    key: "langchain",
    labelKey: "toolPool.group.langchain",
    sourceValue: TOOL_SOURCE_TYPES.LANGCHAIN,
  },
];

export interface ToolDrawerProps {
  open: boolean;
  onClose: () => void;
  currentAgentId?: number;
}

export function ToolDrawer({ open, onClose, currentAgentId }: ToolDrawerProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { confirm } = useConfirmModal();

  const { selectableTools } = useToolList({ enabled: open });
  const scanTools = useScanToolList();
  const { user } = useAuthorizationContext();
  const tenantId = user?.tenantId || null;
  const { serverList: rawServers } = useMcpServerList({
    enabled: open,
    tenantId,
  });
  const mcpServersByName = useMemo(
    () => new Map(rawServers.map((server) => [server.service_name, server])),
    [rawServers]
  );
  const allMcpServerNames = useMemo(
    () => new Set(rawServers.map((s) => s.service_name)),
    [rawServers]
  );
  const visibleMcpNames = useMemo(
    () =>
      new Set(
        rawServers
          .filter(
            (s) =>
              !s.permission ||
              s.permission === "EDIT" ||
              s.permission === "READ_ONLY" ||
              s.group_ids
          )
          .map((s) => s.service_name)
      ),
    [rawServers]
  );
  const { prefetchKnowledgeBases } = usePrefetchKnowledgeBases();
  const {
    isImageUnderstandingAvailable,
    isVideoUnderstandingAvailable,
    isAudioUnderstandingAvailable,
    isEmbeddingAvailable,
  } = useConfig();

  const selectedTools = useAgentStore(
    (state) => state.editedAgent?.tools ?? EMPTY_TOOLS
  );
  const updateTools = useAgentStore((state) => state.updateTools);

  // Local draft of the selected tools. Changes are only committed to the
  // agent store when the confirm button is clicked.
  const [draftTools, setDraftTools] = useState<Tool[]>([]);

  useEffect(() => {
    if (!open) return;
    setDraftTools(selectedTools);
  }, [open, selectedTools]);

  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState("local");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  // ToolConfigModal — handles add/update to store internally on save
  const [configModalOpen, setConfigModalOpen] = useState(false);
  const [configTool, setConfigTool] = useState<Tool | null>(null);
  const [configParams, setConfigParams] = useState<ToolParam[]>([]);
  const [isSelectingAll, setIsSelectingAll] = useState(false);
  const selectionEpoch = useRef(0);
  const batchInFlight = useRef(false);

  useEffect(() => {
    return () => {
      selectionEpoch.current += 1;
      batchInFlight.current = false;
    };
  }, [open]);

  // Tools available in the active source tab (MCP tools filtered by visible server).
  const activeTabTools = useMemo(() => {
    const tab = SOURCE_TABS.find((item) => item.key === activeTab);
    if (!tab) return [];
    const sourceTools = selectableTools.filter(
      (tool: Tool) => tool.source === tab.sourceValue
    );
    if (tab.key === "mcp") {
      return sourceTools.filter(
        (tool: Tool) =>
          !tool.usage ||
          !allMcpServerNames.has(tool.usage) ||
          visibleMcpNames.has(tool.usage)
      );
    }
    return sourceTools;
  }, [activeTab, allMcpServerNames, selectableTools, visibleMcpNames]);

  const resourceTags = useResourceTagFilter(
    open,
    "tool",
    activeTabTools.map((tool) => String(tool.id))
  );
  // Combine text search with the unified tag service match set.
  const filteredTools = useMemo(() => {
    const kw = search.trim().toLowerCase();
    return activeTabTools
      .filter((tool: Tool) => {
        if (
          resourceTags.matchedIds &&
          !resourceTags.matchedIds.has(String(tool.id))
        )
          return false;
        if (kw) {
          const desc = getToolDescription(tool);
          const server =
            tool.source === TOOL_SOURCE_TYPES.MCP
              ? mcpServersByName.get(tool.usage || "")
              : undefined;
          const matchService =
            tool.source === TOOL_SOURCE_TYPES.MCP &&
            [tool.usage, server?.description, ...(server?.tags ?? [])].some(
              (value) => value?.toLowerCase().includes(kw)
            );
          const matchSearch =
            matchService ||
            tool.name.toLowerCase().includes(kw) ||
            (desc && desc.toLowerCase().includes(kw)) ||
            getToolLabels(tool).some((label: string) =>
              label.toLowerCase().includes(kw)
            );
          if (!matchSearch) return false;
        }
        return true;
      })
      .sort((a: Tool, b: Tool) => a.name.localeCompare(b.name));
  }, [activeTabTools, search, resourceTags.matchedIds, mcpServersByName]);

  const selectedToolIds = useMemo(
    () => new Set(draftTools.map((tool) => parseInt(tool.id))),
    [draftTools]
  );

  const mergeInstanceParams = useMergedToolParams(currentAgentId);

  // Check if tool has missing required params
  const hasMissingRequired = useCallback(
    (params: ToolParam[]): boolean =>
      params.some(
        (p: ToolParam) =>
          p.required &&
          (p.value === undefined || p.value === "" || p.value === null)
      ),
    []
  );

  // Selectable tools in the active tab (not disabled, no duplicate name, no missing required).
  const selectableToolsInActiveTab = useMemo(() => {
    return filteredTools.filter((tool: Tool) => {
      const toolId = parseInt(tool.id);
      const hasDuplicateName = draftTools.some(
        (selectedTool) =>
          parseInt(selectedTool.id) !== toolId &&
          selectedTool.name === tool.name
      );

      return (
        !hasDuplicateName &&
        !isToolDisabled(
          tool.name,
          isImageUnderstandingAvailable,
          isVideoUnderstandingAvailable,
          isEmbeddingAvailable,
          isAudioUnderstandingAvailable
        ) &&
        !hasMissingRequired(tool.initParams || [])
      );
    });
  }, [
    filteredTools,
    hasMissingRequired,
    isEmbeddingAvailable,
    isImageUnderstandingAvailable,
    isVideoUnderstandingAvailable,
    isAudioUnderstandingAvailable,
    draftTools,
  ]);

  const selectedChips = useMemo(
    () =>
      draftTools.map((tool) => ({
        id: String(tool.id),
        label: tool.name,
      })),
    [draftTools]
  );

  const mcpGroups = useMemo(() => {
    const groups = new Map<string, Tool[]>();
    if (activeTab === "mcp") {
      filteredTools.forEach((tool) => {
        const name = tool.usage || "";
        const children = groups.get(name) ?? [];
        children.push(tool);
        groups.set(name, children);
      });
    }
    return Array.from(groups, ([name, tools]) => ({ name, tools })).sort(
      (a, b) => a.name.localeCompare(b.name)
    );
  }, [activeTab, filteredTools]);
  const pagedGroups = useMemo(
    () => mcpGroups.slice((page - 1) * pageSize, page * pageSize),
    [mcpGroups, page, pageSize]
  );
  const total = activeTab === "mcp" ? mcpGroups.length : filteredTools.length;
  const pagedTools = useMemo(
    () =>
      activeTab === "mcp"
        ? pagedGroups.flatMap((group) => group.tools)
        : filteredTools.slice((page - 1) * pageSize, page * pageSize),
    [activeTab, pagedGroups, filteredTools, page, pageSize]
  );
  const selectionScope = activeTab === "mcp" ? pagedTools : filteredTools;
  const eligibleIds = useMemo(
    () => new Set(selectableToolsInActiveTab.map((tool) => parseInt(tool.id))),
    [selectableToolsInActiveTab]
  );
  const selectionTargets = selectionScope.filter(
    (tool) =>
      eligibleIds.has(parseInt(tool.id)) ||
      selectedToolIds.has(parseInt(tool.id))
  );
  const allVisibleToolsSelected =
    selectionTargets.length > 0 &&
    selectionTargets.every((tool) => selectedToolIds.has(parseInt(tool.id)));
  const partiallySelected =
    !allVisibleToolsSelected &&
    selectionTargets.some((tool) => selectedToolIds.has(parseInt(tool.id)));
  const toolAssignments = useToolTagAssignments(
    open,
    pagedTools.map((tool) => String(tool.id)),
    resourceTags.revision,
    tenantId
  );

  // Auto-switch to first available tab when the active tab has no tools.
  const tabItems = useMemo(
    () =>
      SOURCE_TABS.filter((tab) =>
        selectableTools.some(
          (tool: Tool) =>
            tool.source === tab.sourceValue &&
            (tab.key !== "mcp" ||
              !tool.usage ||
              !allMcpServerNames.has(tool.usage) ||
              visibleMcpNames.has(tool.usage))
        )
      ).map((tab) => ({ key: tab.key, label: t(tab.labelKey) })),
    [allMcpServerNames, selectableTools, t, visibleMcpNames]
  );

  useEffect(() => {
    if (tabItems.length > 0 && !tabItems.some((tab) => tab.key === activeTab)) {
      setActiveTab(tabItems[0].key);
    }
  }, [activeTab, tabItems]);

  useEffect(() => {
    setPage(1);
  }, [activeTab, search, resourceTags.matchedIds]);

  // Open ToolConfigModal (handles add/update internally on save)
  const openConfigModal = useCallback(
    async (tool: Tool) => {
      const numericId = parseInt(tool.id);
      const kbType = getToolKbType(tool.name);
      if (kbType) prefetchKnowledgeBases(kbType);

      const configuredTool = draftTools.find(
        (selectedTool) => parseInt(selectedTool.id) === numericId
      );
      const toolToUse = configuredTool
        ? { ...tool, ...configuredTool, initParams: configuredTool.initParams }
        : tool;

      const mergedParams = await mergeInstanceParams(toolToUse);
      if (!mergedParams) return;
      setConfigTool(toolToUse);
      setConfigParams(mergedParams);
      setConfigModalOpen(true);
    },
    [mergeInstanceParams, prefetchKnowledgeBases, draftTools]
  );

  const handleToolToggle = useCallback(
    async (tool: Tool) => {
      const numericId = parseInt(tool.id);
      const kbType = getToolKbType(tool.name);
      if (kbType) prefetchKnowledgeBases(kbType);

      const isCurrentlySelected = draftTools.some(
        (selectedTool) => parseInt(selectedTool.id) === numericId
      );

      if (isCurrentlySelected) {
        setDraftTools((prev) =>
          prev.filter((selectedTool) => parseInt(selectedTool.id) !== numericId)
        );
        return;
      }

      // Duplicate name check
      const dup = draftTools.find(
        (selectedTool) => selectedTool.name === tool.name
      );
      const doAdd = async () => {
        const mergedParams = await mergeInstanceParams(tool);
        if (!mergedParams) return;
        const toolToUse = { ...tool, initParams: mergedParams };
        if (hasMissingRequired(mergedParams)) {
          setConfigTool(toolToUse);
          setConfigParams(mergedParams);
          setConfigModalOpen(true);
        } else {
          setDraftTools((prev) => [...prev, toolToUse]);
        }
      };

      if (dup) {
        confirm({
          title: t("toolPool.duplicateToolName.title"),
          content: t("toolPool.duplicateToolName.content", {
            toolName: tool.name,
          }),
          okText: t("toolPool.duplicateToolName.confirm"),
          cancelText: t("toolPool.duplicateToolName.cancel"),
          danger: true,
          onOk: doAdd,
        });
      } else {
        await doAdd();
      }
    },
    [
      draftTools,
      prefetchKnowledgeBases,
      mergeInstanceParams,
      hasMissingRequired,
      confirm,
      t,
    ]
  );

  const selectTools = useCallback(
    async (scope: Tool[]) => {
      if (batchInFlight.current) return;

      const currentSelectedIds = new Set(
        draftTools.map((tool) => parseInt(tool.id))
      );
      const toolsToAdd = scope.filter(
        (tool: Tool) =>
          eligibleIds.has(parseInt(tool.id)) &&
          !currentSelectedIds.has(parseInt(tool.id))
      );
      if (toolsToAdd.length === 0) return;

      batchInFlight.current = true;
      const epoch = selectionEpoch.current;
      setIsSelectingAll(true);
      try {
        const toolsWithParams = await Promise.all(
          toolsToAdd.map(async (tool: Tool) => {
            const initParams = await mergeInstanceParams(tool);
            return initParams ? { ...tool, initParams } : null;
          })
        );
        if (
          epoch !== selectionEpoch.current ||
          toolsWithParams.some((tool) => !tool)
        )
          return;
        setDraftTools((prev) => {
          const latestIds = new Set(prev.map((tool) => parseInt(tool.id)));
          const names = new Set(prev.map((tool) => tool.name));
          const additions = toolsWithParams.filter((tool): tool is Tool => {
            if (!tool) return false;
            if (
              latestIds.has(parseInt(tool.id)) ||
              names.has(tool.name) ||
              hasMissingRequired(tool.initParams)
            ) {
              return false;
            }
            names.add(tool.name);
            return true;
          });

          if (additions.length === 0) return prev;
          return [...prev, ...additions];
        });
      } catch (error) {
        log.error("Failed to select tools:", error);
        if (epoch === selectionEpoch.current)
          message.error(t("toolPool.selectionFailed"));
      } finally {
        if (epoch === selectionEpoch.current) {
          batchInFlight.current = false;
          setIsSelectingAll(false);
        }
      }
    },
    [
      draftTools,
      hasMissingRequired,
      eligibleIds,
      mergeInstanceParams,
      message,
      t,
    ]
  );

  const selectScope = useCallback(
    (scope: Tool[], checked: boolean) => {
      if (batchInFlight.current) return;
      if (checked) {
        void selectTools(scope);
        return;
      }
      const ids = new Set(scope.map((tool) => parseInt(tool.id)));
      setDraftTools((prev) =>
        prev.filter((tool) => !ids.has(parseInt(tool.id)))
      );
    },
    [selectTools]
  );

  const removeTool = useCallback((id: string) => {
    setDraftTools((prev) => prev.filter((tool) => String(tool.id) !== id));
  }, []);

  const handleSelectAll = useCallback(
    (checked: boolean) => {
      selectScope(selectionScope, checked);
    },
    [selectScope, selectionScope]
  );

  const onCloseDialog = useCallback(() => {
    selectionEpoch.current += 1;
    batchInFlight.current = false;
    setIsSelectingAll(false);
    setSearch("");
    setActiveTab("local");
    setPage(1);
    onClose();
  }, [onClose]);

  // Commit a tool configured via ToolConfigModal into the local draft (add or
  // replace). The modal runs in localOnly mode here, so it does not write the
  // agent store directly.
  const saveToolConfig = useCallback((tool: Tool) => {
    setDraftTools((prev) => {
      const existingIndex = prev.findIndex(
        (item) => parseInt(item.id) === parseInt(tool.id)
      );
      if (existingIndex >= 0) {
        const next = [...prev];
        next[existingIndex] = tool;
        return next;
      }
      return [...prev, tool];
    });
  }, []);

  const handleConfirm = useCallback(() => {
    updateTools(draftTools);
    onCloseDialog();
  }, [draftTools, updateTools, onCloseDialog]);

  const renderTool = (tool: Tool) => {
    const isSelected = selectedToolIds.has(parseInt(tool.id));
    const description = getToolDescription(tool);
    const disabled = isToolDisabled(
      tool.name,
      isImageUnderstandingAvailable,
      isVideoUnderstandingAvailable,
      isEmbeddingAvailable,
      isAudioUnderstandingAvailable
    );
    const disabledTooltipKey = disabled
      ? getToolDisabledTooltipKey(
          tool.name,
          isImageUnderstandingAvailable,
          isVideoUnderstandingAvailable,
          isEmbeddingAvailable,
          isAudioUnderstandingAvailable
        )
      : null;

    const row = (
      <ResourceItem
        item={{
          key: String(tool.id),
          name: tool.name,
          description,
          tags: getToolLabels(tool),
          raw: tool,
        }}
        selected={isSelected}
        disabled={disabled}
        onToggle={() => void handleToolToggle(tool)}
        slots={{
          renderTags: () => (
            <ResourceAssignedTags
              resourceType="tool"
              resourceId={String(tool.id)}
              tags={getToolLabels(tool)}
              assignments={toolAssignments.data?.[String(tool.id)] ?? []}
              refreshKey={resourceTags.revision}
            />
          ),
          renderActions: () =>
            !disabled ? (
              <button
                type="button"
                onClick={() => void openConfigModal(tool)}
                aria-label={t("toolPool.configure")}
                title={t("toolPool.configure")}
                className="flex size-7 shrink-0 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
              >
                <Settings className="size-4" />
              </button>
            ) : null,
        }}
      />
    );

    return (
      <div key={tool.id}>
        {disabledTooltipKey ? (
          <Tooltip title={t(disabledTooltipKey)} mouseEnterDelay={0.2}>
            <div>{row}</div>
          </Tooltip>
        ) : (
          row
        )}
      </div>
    );
  };

  return (
    <>
      <ResourceDrawer
        width="min(768px, 100vw)"
        bodyClassName={cn(styles.drawer, styles.tool)}
        title={t("resourcePicker.addTool", "添加工具")}
        open={open}
        searchPlaceholder={t("toolPool.searchToolsPlaceholder")}
        tagFilter={
          <ResourceTagFilterControl
            filter={resourceTags}
            onChange={() => setPage(1)}
          />
        }
        confirmDisabled={
          isSelectingAll ||
          resourceTags.filtering ||
          !!(resourceTags.predicates.length && resourceTags.error)
        }
        selected={selectedChips}
        listTitle={t("resourcePicker.list.tool")}
        tabs={tabItems}
        activeTab={activeTab}
        total={total}
        page={page}
        onClose={onCloseDialog}
        onConfirm={handleConfirm}
        keyword={search}
        onSearch={setSearch}
        onTabChange={setActiveTab}
        onRemoveSelected={removeTool}
        onSelectAll={handleSelectAll}
        selectAllLabel={
          activeTab === "mcp" ? t("toolPool.mcpSelectPage") : undefined
        }
        allSelected={allVisibleToolsSelected}
        partiallySelected={partiallySelected}
        selectAllDisabled={isSelectingAll || selectionTargets.length === 0}
        refreshLoading={scanTools.isPending}
        onRefresh={() => {
          if (scanTools.isPending) return;
          scanTools.mutate(undefined, {
            onSuccess: () => {
              message.success(t("toolManagement.message.refreshSuccess"));
            },
            onError: () => {
              message.error(t("toolManagement.message.refreshFailedRetry"));
            },
          });
        }}
        onPageChange={setPage}
        pageSize={pageSize}
        onPageSizeChange={(size) => {
          setPageSize(size);
          setPage(1);
        }}
      >
        {total > 0 ? (
          <ResourceCollection>
            {activeTab === "mcp"
              ? pagedGroups.map((group) => (
                  <McpToolGroup
                    key={group.name}
                    name={group.name || t("toolPool.mcpUnknownService")}
                    server={mcpServersByName.get(group.name)}
                    tools={group.tools}
                    selectedIds={selectedToolIds}
                    eligibleIds={eligibleIds}
                    selecting={isSelectingAll}
                    searching={
                      Boolean(search.trim()) ||
                      resourceTags.predicates.length > 0
                    }
                    onSelect={selectScope}
                    renderTool={renderTool}
                  />
                ))
              : pagedTools.map(renderTool)}
          </ResourceCollection>
        ) : (
          <div className="flex flex-1 items-center justify-center text-sm text-gray-400">
            {t("toolPool.noSearchResults")}
          </div>
        )}
      </ResourceDrawer>

      <ToolConfigModal
        isOpen={configModalOpen}
        onCancel={() => {
          setConfigModalOpen(false);
          setConfigTool(null);
          setConfigParams([]);
        }}
        tool={configTool!}
        initialParams={configParams}
        selectedTool={configTool}
        currentAgentId={currentAgentId}
        localOnly
        onSaveTool={saveToolConfig}
      />
    </>
  );
}
