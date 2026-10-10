"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Tooltip } from "antd";
import { Settings, Wrench, Tag } from "lucide-react";
import i18n from "i18next";

import { AddResourceDrawer, CheckMark } from "./AddResourceDrawer";
import { useToolList } from "@/hooks/agent/useToolList";
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

const PAGE_SIZE = 10;

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

function getToolDescription(tool: any): string {
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

export interface AddToolDrawerProps {
  open: boolean;
  onClose: () => void;
  onOpenManageLabels?: () => void;
  currentAgentId?: number;
}

export function AddToolDrawer({
  open,
  onClose,
  onOpenManageLabels,
  currentAgentId,
}: AddToolDrawerProps) {
  const { t } = useTranslation("common");
  const { confirm } = useConfirmModal();

  const { selectableTools, invalidate } = useToolList({ enabled: open });
  const { user } = useAuthorizationContext();
  const tenantId = user?.tenantId || null;
  const { serverList: rawServers } = useMcpServerList({
    enabled: open,
    tenantId,
  });
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

  const [search, setSearch] = useState("");
  const [activeTag, setActiveTag] = useState("");
  const [activeTab, setActiveTab] = useState("local");
  const [page, setPage] = useState(1);

  // ToolConfigModal — handles add/update to store internally on save
  const [configModalOpen, setConfigModalOpen] = useState(false);
  const [configTool, setConfigTool] = useState<Tool | null>(null);
  const [configParams, setConfigParams] = useState<ToolParam[]>([]);
  const [isSelectingAll, setIsSelectingAll] = useState(false);

  // Collect all unique labels from available tools for the single tag dropdown
  const allLabels = useMemo(() => {
    const labelSet = new Set<string>();
    selectableTools.forEach((tool: any) => {
      getToolLabels(tool).forEach((label: string) => labelSet.add(label));
    });
    return Array.from(labelSet).sort((a, b) => a.localeCompare(b));
  }, [selectableTools]);

  const tagOptions = useMemo(
    () => allLabels.map((label) => ({ value: label, label })),
    [allLabels]
  );

  // Tools available in the active source tab (MCP tools filtered by visible server).
  const activeTabTools = useMemo(() => {
    const tab = SOURCE_TABS.find((item) => item.key === activeTab);
    if (!tab) return [];
    const sourceTools = selectableTools.filter(
      (tool: any) => tool.source === tab.sourceValue
    );
    if (tab.key === "mcp") {
      return sourceTools.filter(
        (tool: any) =>
          !allMcpServerNames.has(tool.usage) || visibleMcpNames.has(tool.usage)
      );
    }
    return sourceTools;
  }, [activeTab, allMcpServerNames, selectableTools, visibleMcpNames]);

  // Filter by search (name/description/labels) and single active tag (AND).
  const filteredTools = useMemo(() => {
    const kw = search.trim().toLowerCase();
    return activeTabTools
      .filter((tool: any) => {
        if (kw) {
          const desc = getToolDescription(tool);
          const matchSearch =
            tool.name.toLowerCase().includes(kw) ||
            (desc && desc.toLowerCase().includes(kw)) ||
            getToolLabels(tool).some((label: string) =>
              label.toLowerCase().includes(kw)
            );
          if (!matchSearch) return false;
        }
        if (activeTag && !getToolLabels(tool).includes(activeTag)) return false;
        return true;
      })
      .sort((a: any, b: any) => a.name.localeCompare(b.name));
  }, [activeTabTools, activeTag, search]);

  const selectedToolIds = useMemo(
    () => new Set(selectedTools.map((tool) => parseInt(tool.id))),
    [selectedTools]
  );

  const mergeInstanceParams = useMergedToolParams(currentAgentId);

  // Check if tool has missing required params
  const hasMissingRequired = useCallback(
    (params: ToolParam[]): boolean =>
      params.some(
        (p: any) =>
          p.required &&
          (p.value === undefined || p.value === "" || p.value === null)
      ),
    []
  );

  // Selectable tools in the active tab (not disabled, no duplicate name, no missing required).
  const selectableToolsInActiveTab = useMemo(() => {
    return filteredTools.filter((tool: any) => {
      const toolId = parseInt(tool.id);
      const hasDuplicateName = selectedTools.some(
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
    selectedTools,
  ]);

  const allVisibleToolsSelected = useMemo(
    () =>
      selectableToolsInActiveTab.length > 0 &&
      selectableToolsInActiveTab.every((tool: any) =>
        selectedToolIds.has(parseInt(tool.id))
      ),
    [selectableToolsInActiveTab, selectedToolIds]
  );

  const selectedChips = useMemo(
    () =>
      selectedTools.map((tool) => ({
        id: String(tool.id),
        label: tool.name,
      })),
    [selectedTools]
  );

  const total = filteredTools.length;
  const pagedTools = useMemo(
    () => filteredTools.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [filteredTools, page]
  );

  // Auto-switch to first available tab when the active tab has no tools.
  const tabItems = useMemo(
    () =>
      SOURCE_TABS.filter(
        (tab) =>
          selectableTools.some(
            (tool: any) =>
              tool.source === tab.sourceValue &&
              (tab.key !== "mcp" ||
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
  }, [activeTab, search, activeTag]);

  // Open ToolConfigModal (handles add/update internally on save)
  const openConfigModal = useCallback(
    async (tool: any) => {
      const numericId = parseInt(tool.id);
      const kbType = getToolKbType(tool.name);
      if (kbType) prefetchKnowledgeBases(kbType);

      const currentSelected = useAgentStore.getState().editedAgent?.tools ?? [];
      const configuredTool = currentSelected.find(
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
    [mergeInstanceParams, prefetchKnowledgeBases]
  );

  const handleToolToggle = useCallback(
    async (tool: any) => {
      const numericId = parseInt(tool.id);
      const kbType = getToolKbType(tool.name);
      if (kbType) prefetchKnowledgeBases(kbType);

      const currentSelected = useAgentStore.getState().editedAgent?.tools ?? [];
      const isCurrentlySelected = currentSelected.some(
        (selectedTool) => parseInt(selectedTool.id) === numericId
      );

      if (isCurrentlySelected) {
        updateTools(
          currentSelected.filter(
            (selectedTool) => parseInt(selectedTool.id) !== numericId
          )
        );
        return;
      }

      // Duplicate name check
      const dup = currentSelected.find(
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
          const latest = useAgentStore.getState().editedAgent?.tools ?? [];
          updateTools([...latest, toolToUse]);
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
      prefetchKnowledgeBases,
      mergeInstanceParams,
      hasMissingRequired,
      confirm,
      updateTools,
      t,
    ]
  );

  const selectAllVisibleTools = useCallback(async () => {
    if (isSelectingAll) return;

    const currentSelected = useAgentStore.getState().editedAgent?.tools ?? [];
    const currentSelectedIds = new Set(
      currentSelected.map((tool) => parseInt(tool.id))
    );
    const toolsToAdd = selectableToolsInActiveTab.filter(
      (tool: any) => !currentSelectedIds.has(parseInt(tool.id))
    );
    if (toolsToAdd.length === 0) return;

    setIsSelectingAll(true);
    try {
      const toolsWithParams = await Promise.all(
        toolsToAdd.map(async (tool: any) => {
          const initParams = await mergeInstanceParams(tool);
          return initParams ? { ...tool, initParams } : null;
        })
      );
      const latestSelected = useAgentStore.getState().editedAgent?.tools ?? [];
      const latestIds = new Set(
        latestSelected.map((tool) => parseInt(tool.id))
      );
      const names = new Set(latestSelected.map((tool) => tool.name));
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

      if (additions.length > 0) {
        updateTools([...latestSelected, ...additions]);
      }
    } finally {
      setIsSelectingAll(false);
    }
  }, [
    hasMissingRequired,
    isSelectingAll,
    mergeInstanceParams,
    selectableToolsInActiveTab,
    updateTools,
  ]);

  const deselectAllVisibleTools = useCallback(() => {
    const visibleToolIds = new Set(
      filteredTools.map((tool: any) => parseInt(tool.id))
    );
    const currentSelected = useAgentStore.getState().editedAgent?.tools ?? [];
    updateTools(
      currentSelected.filter(
        (tool) => !visibleToolIds.has(parseInt(tool.id))
      )
    );
  }, [filteredTools, updateTools]);

  const removeTool = useCallback(
    (id: string) => {
      const currentTools = useAgentStore.getState().editedAgent?.tools ?? [];
      updateTools(currentTools.filter((tool) => String(tool.id) !== id));
    },
    [updateTools]
  );

  const handleSelectAll = useCallback(
    (checked: boolean) => {
      if (checked) void selectAllVisibleTools();
      else deselectAllVisibleTools();
    },
    [deselectAllVisibleTools, selectAllVisibleTools]
  );

  const onCloseDialog = useCallback(() => {
    setSearch("");
    setActiveTag("");
    setActiveTab("local");
    setPage(1);
    onClose();
  }, [onClose]);

  return (
    <>
      <AddResourceDrawer
        title={
          <div className="flex items-center gap-2 pr-8">
            <Wrench className="size-4" />
            <span className="flex-1">{t("toolPool.selectTools")}</span>
            {onOpenManageLabels ? (
              <Button
                type="text"
                size="small"
                icon={<Tag size={13} />}
                onClick={onOpenManageLabels}
                className="!text-purple-500 hover:!text-purple-600 hover:!bg-purple-50 h-6 text-xs"
              >
                {t("toolPool.manageLabels")}
              </Button>
            ) : null}
          </div>
        }
        open={open}
        searchPlaceholder={t("toolPool.searchToolsPlaceholder")}
        tagOptions={tagOptions}
        selected={selectedChips}
        listTitle={t("resourcePicker.list.tool")}
        tabs={tabItems}
        activeTab={activeTab}
        total={total}
        page={page}
        showConfirm={false}
        onClose={onCloseDialog}
        onSearch={setSearch}
        onTagChange={(value) => setActiveTag(value ?? "")}
        onTabChange={setActiveTab}
        onRemoveSelected={removeTool}
        onSelectAll={handleSelectAll}
        allSelected={allVisibleToolsSelected}
        onRefresh={() => void invalidate()}
        onPageChange={setPage}
      >
        {total > 0 ? (
          <div className="flex flex-col gap-2">
            {pagedTools.map((tool: any) => {
              const isSelected = selectedToolIds.has(parseInt(tool.id));
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
                <div
                  role="button"
                  tabIndex={disabled ? -1 : 0}
                  className={cn(
                    "flex shrink-0 items-center gap-3 rounded-[2px] px-5 py-[9px] transition-colors",
                    isSelected ? "bg-[#E6F2FD]" : "bg-transparent",
                    disabled
                      ? "cursor-not-allowed opacity-50"
                      : "cursor-pointer hover:bg-gray-50"
                  )}
                  onClick={disabled ? undefined : () => handleToolToggle(tool)}
                  onKeyDown={(event) => {
                    if (
                      !disabled &&
                      (event.key === "Enter" || event.key === " ")
                    ) {
                      event.preventDefault();
                      handleToolToggle(tool);
                    }
                  }}
                >
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "truncate text-[14px] leading-[20px]",
                          isSelected
                            ? "font-medium text-[#0067D1]"
                            : "font-medium text-[#191919]"
                        )}
                      >
                        {tool.name}
                      </span>
                      {getToolLabels(tool)
                        .slice(0, 2)
                        .map((label: string) => (
                          <span
                            key={label}
                            className="h-5 shrink-0 rounded-[2px] bg-[#F5F5F5] px-2 text-[12px] leading-[20px] text-[#393939]"
                          >
                            {label}
                          </span>
                        ))}
                    </div>
                    {tool.description ? (
                      <p className="truncate text-[14px] leading-[20px] text-[#737373]">
                        {getToolDescription(tool)}
                      </p>
                    ) : null}
                  </div>
                  {!disabled && (
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        void openConfigModal(tool);
                      }}
                      aria-label={t("toolPool.configure")}
                      title={t("toolPool.configure")}
                      className="flex size-7 shrink-0 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
                    >
                      <Settings className="size-4" />
                    </button>
                  )}
                  <CheckMark checked={isSelected} />
                </div>
              );

              return (
                <div key={tool.id}>
                  {disabledTooltipKey ? (
                    <Tooltip title={t(disabledTooltipKey)} mouseEnterDelay={0.2}>
                      {row}
                    </Tooltip>
                  ) : (
                    row
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="flex flex-1 items-center justify-center text-sm text-gray-400">
            {t("toolPool.noSearchResults")}
          </div>
        )}
      </AddResourceDrawer>

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
      />
    </>
  );
}