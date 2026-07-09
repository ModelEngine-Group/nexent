"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Tabs, Input, Checkbox, Button, Select } from "antd";
import type { TabsProps } from "antd";
import { Search, Settings, Wrench, Tag } from "lucide-react";
import i18n from "i18next";

import { useToolList } from "@/hooks/agent/useToolList";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { usePrefetchKnowledgeBases } from "@/hooks/useKnowledgeBaseSelector";
import { useConfig } from "@/hooks/useConfig";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { TOOL_SOURCE_TYPES } from "@/const/agentConfig";
import type { Tool, ToolParam } from "@/types/agentConfig";
import ToolConfigModal from "./ToolConfigModal";
import {
  TOOLS_REQUIRING_KB_SELECTION,
  TOOLS_REQUIRING_EMBEDDING,
  TOOLS_REQUIRING_IMAGE_UNDERSTANDING,
  TOOLS_REQUIRING_VIDEO_UNDERSTANDING,
  getToolKbType,
  getToolLabels,
} from "./utils";
import log from "@/lib/logger";

function isToolDisabled(name: string, img: boolean, vid: boolean, emb: boolean): boolean {
  if (TOOLS_REQUIRING_IMAGE_UNDERSTANDING.includes(name) && !img) return true;
  if (TOOLS_REQUIRING_VIDEO_UNDERSTANDING.includes(name) && !vid) return true;
  if (TOOLS_REQUIRING_EMBEDDING.includes(name) && !emb) return true;
  return false;
}

function getToolDescription(tool: any): string {
  const locale = i18n.language || "en";
  if (locale === "zh" && tool.description_zh) {
    return tool.description_zh;
  }
  return tool.description || "";
}

const SOURCE_TABS: { key: string; labelKey: string; sourceValue: string }[] = [
  { key: "local", labelKey: "toolPool.group.local", sourceValue: TOOL_SOURCE_TYPES.LOCAL },
  { key: "mcp", labelKey: "toolPool.group.mcp", sourceValue: TOOL_SOURCE_TYPES.MCP },
  { key: "langchain", labelKey: "toolPool.group.langchain", sourceValue: TOOL_SOURCE_TYPES.LANGCHAIN },
];

interface SelectToolsDialogProps {
  open: boolean;
  onClose: () => void;
  onOpenManageLabels: () => void;
  isCreatingMode?: boolean;
  currentAgentId?: number;
}

export default function SelectToolsDialog({
  open,
  onClose,
  onOpenManageLabels,
  isCreatingMode,
  currentAgentId,
}: SelectToolsDialogProps) {
  const { t } = useTranslation("common");
  const { confirm } = useConfirmModal();

  const { availableTools } = useToolList({ enabled: open });
  const { prefetchKnowledgeBases } = usePrefetchKnowledgeBases();
  const { isImageUnderstandingAvailable, isVideoUnderstandingAvailable, isEmbeddingAvailable } = useConfig();

  const selectedTools = useAgentConfigStore((state) => state.editedAgent.tools);
  const updateTools = useAgentConfigStore((state) => state.updateTools);

  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState("local");
  const [activeCategory, setActiveCategory] = useState("");

  // Collect all unique labels from available tools for filter dropdown
  const allLabels = useMemo(() => {
    const labelSet = new Set<string>();
    availableTools.forEach((tool: any) => {
      const labels = getToolLabels(tool);
      labels.forEach((l: string) => labelSet.add(l));
    });
    return Array.from(labelSet).sort((a, b) => a.localeCompare(b));
  }, [availableTools]);

  const [activeLabels, setActiveLabels] = useState<string[]>([]);

  // ToolConfigModal — handles add/update to store internally on save
  const [configModalOpen, setConfigModalOpen] = useState(false);
  const [configTool, setConfigTool] = useState<Tool | null>(null);
  const [configParams, setConfigParams] = useState<ToolParam[]>([]);

  // --- Group tools by source & category ---
  const sourceGroups = useMemo(() => {
    const result: Record<string, { category: string; tools: any[] }[]> = {};
    for (const tab of SOURCE_TABS) {
      const sourceTools = availableTools.filter(
        (t: any) => t.source === tab.sourceValue
      );
      const catMap = new Map<string, any[]>();
      for (const tool of sourceTools) {
        // MCP tools are grouped by server name (usage); local/langchain by category
        const cat =
          tab.key === "mcp"
            ? tool.usage?.trim() || "toolPool.category.other"
            : tool.category?.trim() || "toolPool.category.other";
        if (!catMap.has(cat)) catMap.set(cat, []);
        catMap.get(cat)!.push(tool);
      }
      result[tab.key] = Array.from(catMap.entries())
        .map(([cat, tools]) => ({
          category: cat,
          tools: tools.sort((a: any, b: any) => a.name.localeCompare(b.name)),
        }))
        .sort((a, b) => {
          if (a.category === "toolPool.category.other") return 1;
          if (b.category === "toolPool.category.other") return -1;
          return a.category.localeCompare(b.category);
        });
    }
    return result;
  }, [availableTools]);

  // --- Filtered current tab data by search + labels (AND) ---
  const currentGroups = useMemo(() => {
    const groups = sourceGroups[activeTab] || [];
    const kw = search.trim().toLowerCase();
    const hasSearch = kw !== "";
    const hasLabels = activeLabels.length > 0;

    if (!hasSearch && !hasLabels) return groups;

    const filterOne = (tool: any): boolean => {
      // Search filter (OR across name/desc/desc_zh/tags)
      if (hasSearch) {
        const toolDesc = getToolDescription(tool);
        const matchSearch =
          tool.name.toLowerCase().includes(kw) ||
          (toolDesc && toolDesc.toLowerCase().includes(kw)) ||
          getToolLabels(tool).some((l: string) => l.toLowerCase().includes(kw));
        if (!matchSearch) return false;
      }
      // Label filter (OR — tool must have at least one selected label)
      if (hasLabels) {
        const toolLabels = getToolLabels(tool);
        if (!toolLabels.some((l: string) => activeLabels.includes(l))) return false;
      }
      return true;
    };

    return groups
      .map((g) => ({ ...g, tools: g.tools.filter(filterOne) }))
      .filter((g) => g.tools.length > 0);
  }, [sourceGroups, activeTab, search, activeLabels]);

  const visibleCategories = useMemo(() => currentGroups.map((g) => g.category), [currentGroups]);

  // Auto-select first visible category
  if (visibleCategories.length > 0 && (!activeCategory || !visibleCategories.includes(activeCategory))) {
    setTimeout(() => setActiveCategory(visibleCategories[0]), 0);
  }

  const selectedToolIds = useMemo(
    () => new Set(selectedTools.map((t) => parseInt(t.id))),
    [selectedTools]
  );

  // --- Merge instance params for a tool ---
  const mergeInstanceParams = useCallback(
    async (tool: any, forceFetch?: boolean): Promise<ToolParam[]> => {
      const params = tool.initParams || [];
      // If tool already has stored params with non-empty values, the user's
      // unsaved modifications are already reflected in those params — skip the
      // API call to avoid overwriting them with stale server data.
      const hasStoredParams = params.some((p: ToolParam) => p.value !== undefined && p.value !== null && p.value !== "");
      if (!forceFetch && hasStoredParams) {
        return params;
      }
      if (!currentAgentId) return params;
      try {
        const { searchToolConfig } = await import("@/services/agentConfigService");
        const instance = await searchToolConfig(parseInt(tool.id), currentAgentId);
        if (instance.success && instance.data) {
          return params.map((p: ToolParam) => ({
            ...p,
            value:
              instance.data?.params?.[p.name] !== undefined
                ? instance.data.params[p.name]
                : p.value,
          }));
        }
      } catch (err) {
        log.error("Failed to fetch tool instance params:", err);
      }
      return params;
    },
    [currentAgentId]
  );

  // --- Check if tool has missing required params ---
  const hasMissingRequired = useCallback(
    (params: ToolParam[]): boolean =>
      params.some(
        (p: any) =>
          p.required &&
          (p.value === undefined || p.value === "" || p.value === null)
      ),
    []
  );

  // --- Open ToolConfigModal (which handles add/update internally) ---
  const openConfigModal = useCallback(
    async (tool: any) => {
      const numericId = parseInt(tool.id);
      const kbType = getToolKbType(tool.name);
      if (kbType) prefetchKnowledgeBases(kbType);

      const currentSelected = useAgentConfigStore.getState().editedAgent.tools;
      const configuredTool = currentSelected.find((t) => parseInt(t.id) === numericId);
      const toolToUse = configuredTool
        ? { ...tool, ...configuredTool, initParams: configuredTool.initParams }
        : tool;

      const mergedParams = await mergeInstanceParams(toolToUse);
      setConfigTool(toolToUse);
      setConfigParams(mergedParams);
      setConfigModalOpen(true);
    },
    [mergeInstanceParams, prefetchKnowledgeBases]
  );

  // --- Checkbox toggle ---
  const handleToolToggle = useCallback(
    async (tool: any) => {
      const numericId = parseInt(tool.id);
      const kbType = getToolKbType(tool.name);
      if (kbType) prefetchKnowledgeBases(kbType);

      const currentSelected = useAgentConfigStore.getState().editedAgent.tools;
      const isCurrentlySelected = currentSelected.some(
        (t) => parseInt(t.id) === numericId
      );

      if (isCurrentlySelected) {
        updateTools(currentSelected.filter((t) => parseInt(t.id) !== numericId));
        return;
      }

      // Duplicate name check
      const dup = currentSelected.find((s) => s.name === tool.name);
      const doAdd = async () => {
        const mergedParams = await mergeInstanceParams(tool);
        const toolToUse = { ...tool, initParams: mergedParams };
        if (hasMissingRequired(mergedParams)) {
          setConfigTool(toolToUse);
          setConfigParams(mergedParams);
          setConfigModalOpen(true);
        } else {
          const latest = useAgentConfigStore.getState().editedAgent.tools;
          updateTools([...latest, toolToUse]);
        }
      };

      if (dup) {
        confirm({
          title: t("toolPool.duplicateToolName.title"),
          content: t("toolPool.duplicateToolName.content", { toolName: tool.name }),
          okText: t("toolPool.duplicateToolName.confirm"),
          cancelText: t("toolPool.duplicateToolName.cancel"),
          danger: true,
          onOk: doAdd,
        });
      } else {
        await doAdd();
      }
    },
    [prefetchKnowledgeBases, mergeInstanceParams, hasMissingRequired, confirm, updateTools, t]
  );

  const tabItems: TabsProps["items"] = SOURCE_TABS
    .filter((tab) => (sourceGroups[tab.key] || []).length > 0)
    .map((tab) => ({
      key: tab.key,
      label: t(tab.labelKey),
    }));

  // Auto-switch to first available tab when active tab becomes hidden
  useEffect(() => {
    if (tabItems.length > 0 && !tabItems.find((t) => t.key === activeTab)) {
      setActiveTab(tabItems[0].key!);
    }
  }, [tabItems, activeTab]);

  const onCloseDialog = useCallback(() => {
    setSearch("");
    setActiveTab("local");
    setActiveCategory("");
    onClose();
  }, [onClose]);

  return (
    <>
      <Modal
        title={
          <div className="flex items-center gap-2 pr-8">
            <Wrench className="size-4" />
            <span className="flex-1">{t("toolPool.selectTools")}</span>
            <Button
              type="text"
              size="small"
              icon={<Tag size={13} />}
              onClick={onOpenManageLabels}
              className="!text-purple-500 hover:!text-purple-600 hover:!bg-purple-50 h-6 text-xs"
            >
              {t("toolPool.manageLabels")}
            </Button>
          </div>
        }
        open={open}
        onCancel={onCloseDialog}
        footer={null}
        width={1100}
        zIndex={1000}
        mask={{ closable: true }}
        destroyOnHidden
      >
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />

        <div className="flex items-center gap-2 mb-3">
          <div className="relative flex-1">
            <Search className="absolute left-2 top-1/2 size-4 -translate-y-1/2 text-gray-400" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("toolPool.searchToolsPlaceholder")}
              className="pl-7"
              allowClear
            />
          </div>
          <Select
            mode="multiple"
            placeholder={t("toolPool.filterByLabel")}
            value={activeLabels}
            onChange={setActiveLabels}
            className="min-w-[160px]"
            options={allLabels.map((l: string) => {
              // Count tools matching this label in the current source tab
              const count = (sourceGroups[activeTab] || []).reduce(
                (sum, g) => sum + g.tools.filter((t: any) => getToolLabels(t).includes(l)).length, 0
              );
              return { label: `${l} (${count})`, value: l };
            })}
            allowClear
            maxTagCount={1}
            notFoundContent={allLabels.length === 0 ? t("toolPool.noLabelsAssigned") : undefined}
          />
        </div>

        <div className="flex max-h-[55vh] min-h-[340px] gap-3">
          {/* Category sidebar */}
          <nav className="flex w-36 shrink-0 flex-col gap-1 overflow-y-auto">
            {currentGroups.map((g) => {
              const count = g.tools.length;
              const selCount = g.tools.filter((t: any) =>
                selectedToolIds.has(parseInt(t.id))
              ).length;
              return (
                <button
                  key={g.category}
                  onClick={() => setActiveCategory(g.category)}
                  className={`truncate border-l-2 py-2 pl-3 text-left text-sm transition-colors ${
                    activeCategory === g.category
                      ? "border-blue-500 font-medium text-blue-600"
                      : "border-transparent text-gray-500 hover:text-gray-700"
                  }`}
                >
                  {t(g.category)}
                  <span className="ml-1 text-xs text-gray-400">
                    ({selCount > 0 ? `${selCount}/` : ""}{count})
                  </span>
                </button>
              );
            })}
            {currentGroups.length === 0 && (
              <div className="py-2 pl-3 text-sm text-gray-400">{t("toolPool.noTools")}</div>
            )}
          </nav>

          {/* Tool list */}
          <div className="flex-1 space-y-2 overflow-y-auto pr-1">
            {currentGroups
              .filter((g) => g.category === activeCategory)
              .map((g) => (
                <div key={g.category}>
                  <div className="mb-1 px-1 text-xs font-medium text-gray-400">
                    {t(g.category)}
                  </div>
                  <ul className="space-y-1">
                    {g.tools.map((tool: any) => {
                      const isSelected = selectedToolIds.has(parseInt(tool.id));
                      const disabled = isToolDisabled(
                        tool.name,
                        isImageUnderstandingAvailable,
                        isVideoUnderstandingAvailable,
                        isEmbeddingAvailable
                      );

                      return (
                        <li key={tool.id}>
                          <div
                            role="button"
                            tabIndex={disabled ? -1 : 0}
                            className={`group flex items-center gap-2 rounded-md px-2 py-1.5 transition-colors ${
                              disabled
                                ? "cursor-not-allowed opacity-50"
                                : "cursor-pointer hover:bg-gray-50"
                            }`}
                            onClick={disabled ? undefined : () => handleToolToggle(tool)}
                            onKeyDown={(e) => {
                              if (!disabled && (e.key === 'Enter' || e.key === ' ')) {
                                e.preventDefault();
                                handleToolToggle(tool);
                              }
                            }}
                          >
                            <Checkbox checked={isSelected} disabled={disabled} />
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="truncate font-mono text-xs font-medium text-gray-800">
                                  {tool.name}
                                </span>
                                {getToolLabels(tool)
                                  .slice(0, 2)
                                  .map((label: string) => (
                                    <span
                                      key={label}
                                      className="shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-600"
                                    >
                                      {label}
                                    </span>
                                  ))}
                              </div>
                              {tool.description && (
                                <p className="truncate text-xs text-gray-400">
                                  {getToolDescription(tool)}
                                </p>
                              )}
                            </div>
                            {!disabled && (
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  openConfigModal(tool);
                                }}
                                className="flex size-7 shrink-0 items-center justify-center rounded-md text-gray-400 opacity-0 transition-opacity hover:bg-gray-100 hover:text-gray-600 group-hover:opacity-100"
                              >
                                <Settings className="size-4" />
                              </button>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
            {currentGroups.filter((g) => g.category === activeCategory).length === 0 &&
              search.trim() !== "" && (
                <div className="flex items-center justify-center py-8 text-sm text-gray-400">
                  {t("toolPool.noSearchResults")}
                </div>
              )}
          </div>
        </div>
      </Modal>

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
        isCreatingMode={isCreatingMode}
        currentAgentId={currentAgentId}
      />
    </>
  );
}
