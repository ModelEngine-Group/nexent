"use client";

import { useState, useEffect, useMemo, useCallback, memo } from "react";
import { useTranslation } from "react-i18next";

import { Button, App, Tabs, Collapse, Tooltip } from "antd";
import {
  SettingOutlined,
  LoadingOutlined,
  ApiOutlined,
  ReloadOutlined,
  BulbOutlined,
} from "@ant-design/icons";

import { TOOL_SOURCE_TYPES } from "@/const/agentConfig";
import log from "@/lib/logger";
import {
  Tool,
  ToolPoolProps,
  ToolGroup,
  ToolSubGroup,
} from "@/types/agentConfig";
import { fetchTools } from "@/services/agentConfigService";
import { updateToolList } from "@/services/mcpService";

import ToolConfigModal from "./ToolConfigModal";
import McpConfigModal from "../McpConfigModal";

/**
 * Tool Pool Component
 */
function ToolPool({
  selectedTools,
  onSelectTool,
  onToolConfigSave,
  tools = [],
  loadingTools = false,
  mainAgentId,
  localIsGenerating = false,
  onToolsRefresh,
  isEditingMode = false, // New: Default not in editing mode
  isGeneratingAgent = false, // New: Default not in generating state
  isEmbeddingConfigured = true,
  agentUnavailableReasons = [],
  toolConfigDrafts = {},
}: ToolPoolProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  const [isToolModalOpen, setIsToolModalOpen] = useState(false);
  const [currentTool, setCurrentTool] = useState<Tool | null>(null);
  const [pendingToolSelection, setPendingToolSelection] = useState<{
    tool: Tool;
    isSelected: boolean;
  } | null>(null);
  const [isMcpModalOpen, setIsMcpModalOpen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [activeTabKey, setActiveTabKey] = useState<string>("");
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    new Set()
  );

  const normalizedAgentId =
    typeof mainAgentId === "string"
      ? parseInt(mainAgentId, 10)
      : typeof mainAgentId === "number"
      ? mainAgentId
      : null;
  const shouldCacheLocally =
    !normalizedAgentId ||
    Number.isNaN(normalizedAgentId) ||
    normalizedAgentId <= 0;

  const applyDraftParams = useCallback(
    (tool: Tool): Tool => {
      if (!shouldCacheLocally) {
        return tool;
      }
      const draft = toolConfigDrafts?.[tool.id];
      if (!draft || draft.length === 0) {
        return tool;
      }
      return {
        ...tool,
        initParams: draft.map((param) => ({ ...param })),
      };
    },
    [shouldCacheLocally, toolConfigDrafts]
  );

  // Use useMemo to cache the selected tool ID set to improve lookup efficiency
  const selectedToolIds = useMemo(() => {
    return new Set(selectedTools.map((tool) => tool.id));
  }, [selectedTools]);

  // Use useMemo to cache tool grouping
  const toolGroups = useMemo(() => {
    const groups: ToolGroup[] = [];
    const groupMap = new Map<string, Tool[]>();

    // Filter out unavailable tools (hide tools when MCP server is deleted)
    const availableTools = tools.filter((tool) => {
      // Keep tools that are available or selected (to show selected unavailable tools)
      return tool.is_available !== false || selectedToolIds.has(tool.id);
    });

    // Group by source and usage
    availableTools.forEach((tool) => {
      let groupKey: string;

      if (tool.source === TOOL_SOURCE_TYPES.MCP) {
        // MCP tools grouped by usage
        const usage = tool.usage || TOOL_SOURCE_TYPES.OTHER;
        groupKey = `mcp-${usage}`;
      } else if (tool.source === TOOL_SOURCE_TYPES.LOCAL) {
        groupKey = TOOL_SOURCE_TYPES.LOCAL;
      } else if (tool.source === TOOL_SOURCE_TYPES.LANGCHAIN) {
        groupKey = TOOL_SOURCE_TYPES.LANGCHAIN;
      } else {
        // Other types
        groupKey = tool.source || TOOL_SOURCE_TYPES.OTHER;
      }

      if (!groupMap.has(groupKey)) {
        groupMap.set(groupKey, []);
      }
      groupMap.get(groupKey)!.push(tool);
    });

    // Convert to array and sort
    groupMap.forEach((tools, key) => {
      const sortedTools = tools.sort((a, b) => {
        // Sort by creation time
        if (!a.create_time && !b.create_time) return 0;
        if (!a.create_time) return 1;
        if (!b.create_time) return -1;
        return a.create_time.localeCompare(b.create_time);
      });

      // Create secondary grouping for local tools
      let subGroups: ToolSubGroup[] | undefined;
      if (key === TOOL_SOURCE_TYPES.LOCAL) {
        const categoryMap = new Map<string, Tool[]>();

        sortedTools.forEach((tool) => {
          const category =
            tool.category && tool.category.trim() !== ""
              ? tool.category
              : t("toolPool.category.other");
          if (!categoryMap.has(category)) {
            categoryMap.set(category, []);
          }
          categoryMap.get(category)!.push(tool);
        });

        subGroups = Array.from(categoryMap.entries())
          .map(([category, categoryTools]) => ({
            key: category,
            label: category,
            tools: categoryTools.sort((a, b) => a.name.localeCompare(b.name)), // Sort by name alphabetically
          }))
          .sort((a, b) => {
            // Put "Other" category at the end
            const otherKey = t("toolPool.category.other");
            if (a.key === otherKey) return 1;
            if (b.key === otherKey) return -1;
            return a.label.localeCompare(b.label); // Sort other categories alphabetically
          });
      }

      groups.push({
        key,
        label: key.startsWith("mcp-")
          ? key.replace("mcp-", "")
          : key === TOOL_SOURCE_TYPES.LOCAL
          ? t("toolPool.group.local")
          : key === TOOL_SOURCE_TYPES.LANGCHAIN
          ? t("toolPool.group.langchain")
          : key,
        tools: sortedTools,
        subGroups,
      });
    });

    // Sort by priority: local > langchain > mcp groups
    return groups.sort((a, b) => {
      const getPriority = (key: string) => {
        if (key === TOOL_SOURCE_TYPES.LOCAL) return 1;
        if (key === TOOL_SOURCE_TYPES.LANGCHAIN) return 2;
        if (key.startsWith("mcp-")) return 3;
        return 4;
      };
      return getPriority(a.key) - getPriority(b.key);
    });
  }, [tools, t, selectedToolIds]);

  // Set default active tab
  useEffect(() => {
    if (toolGroups.length > 0 && !activeTabKey) {
      setActiveTabKey(toolGroups[0].key);
    }
  }, [toolGroups, activeTabKey]);

  // Use useCallback to cache the tool selection processing function
  const handleToolSelect = useCallback(
    async (tool: Tool, isSelected: boolean, e: React.MouseEvent) => {
      e.stopPropagation();

      // Disable tool selection during generation
      if (isGeneratingAgent) {
        return;
      }

      // Block knowledge_base_search when embedding model is not configured
      const embeddingBlocked =
        tool.name === "knowledge_base_search" && !isEmbeddingConfigured;
      if (embeddingBlocked) {
        message.warning(t("embedding.agentToolDisableTooltip.content"));
        return;
      }

      // Only block the action when attempting to select an unavailable tool.
      if (tool.is_available === false && isSelected) {
        message.error(t("tool.message.unavailable"));
        return;
      }

      try {
        const preparedTool = applyDraftParams(tool);
        // step 1: if enabling the tool, check required fields using current or default values
        let params: Record<string, any> = (
          preparedTool.initParams || []
        ).reduce((acc, param) => {
          if (param && param.name) {
            acc[param.name] = param.value;
          }
          return acc;
        }, {} as Record<string, any>);

        if (
          isSelected &&
          preparedTool.initParams &&
          preparedTool.initParams.length > 0
        ) {
          const missingRequiredFields = preparedTool.initParams
            .filter(
              (param) =>
                param &&
                param.required &&
                (params[param.name] === undefined ||
                  params[param.name] === "" ||
                  params[param.name] === null)
            )
            .map((param) => param.name);

          if (missingRequiredFields.length > 0) {
            setCurrentTool({
              ...preparedTool,
              initParams: preparedTool.initParams.map((param) => ({
                ...param,
                value: params[param.name] || param.value,
              })),
            });
            setPendingToolSelection({ tool: preparedTool, isSelected });
            setIsToolModalOpen(true);
            return;
          }
        }

        // step 2: if all checks pass, update local selection only; persistence happens on Save
        onSelectTool(preparedTool, isSelected);
      } catch (error) {
        message.error(t("tool.error.updateRetry"));
      }
    },
    [
      onSelectTool,
      t,
      isGeneratingAgent,
      message,
      isEmbeddingConfigured,
      applyDraftParams,
    ]
  );

  // Use useCallback to cache the tool configuration click processing function
  const handleConfigClick = useCallback(
    (tool: Tool, e: React.MouseEvent) => {
      e.stopPropagation();

      // Disable tool configuration during generation
      if (isGeneratingAgent) {
        return;
      }

      const preparedTool = applyDraftParams(tool);
      setCurrentTool(preparedTool);
      setIsToolModalOpen(true);
    },
    [isGeneratingAgent, applyDraftParams]
  );

  // Use useCallback to cache the tool save processing function
  const handleToolSave = useCallback(
    (updatedTool: Tool) => {
      if (shouldCacheLocally) {
        onToolConfigSave?.(updatedTool);
      }
      if (pendingToolSelection) {
        const { tool, isSelected } = pendingToolSelection;
        const missingRequiredFields = updatedTool.initParams
          .filter(
            (param) =>
              param.required &&
              (param.value === undefined ||
                param.value === "" ||
                param.value === null)
          )
          .map((param) => param.name);

        if (missingRequiredFields.length > 0) {
          message.error(
            t("toolPool.error.requiredFields", {
              fields: missingRequiredFields.join(", "),
            })
          );
          return;
        }

        // Apply selection locally after saving config
        onSelectTool(updatedTool, isSelected);
      }

      setIsToolModalOpen(false);
      setPendingToolSelection(null);
    },
    [
      pendingToolSelection,
      onSelectTool,
      t,
      onToolConfigSave,
      shouldCacheLocally,
    ]
  );

  // Use useCallback to cache the modal close processing function
  const handleModalClose = useCallback(() => {
    setIsToolModalOpen(false);
    setPendingToolSelection(null);
  }, []);

  // Tool list refresh handler function
  const handleRefreshTools = useCallback(async () => {
    if (isRefreshing || localIsGenerating) return;

    setIsRefreshing(true);
    try {
      // Step 1: Update backend tool status, rescan MCP and local tools
      const updateResult = await updateToolList();
      if (!updateResult.success) {
        message.warning(t("toolManagement.message.updateStatusFailed"));
      }

      // Step 2: Get the latest tool list
      const fetchResult = await fetchTools();
      if (fetchResult.success) {
        // Call parent component's refresh callback to update tool list state
        if (onToolsRefresh) {
          onToolsRefresh();
        }
      } else {
        message.error(
          fetchResult.message || t("toolManagement.message.refreshFailed")
        );
      }
    } catch (error) {
      log.error(t("agentConfig.tools.refreshFailedDebug"), error);
      message.error(t("toolManagement.message.refreshFailedRetry"));
    } finally {
      setIsRefreshing(false);
    }
  }, [isRefreshing, localIsGenerating, onToolsRefresh, t]);

  // Listen for tool update events
  useEffect(() => {
    const handleToolsUpdate = async () => {
      try {
        // Re-fetch the latest tool list to ensure newly added MCP tools are included
        const fetchResult = await fetchTools();
        if (fetchResult.success) {
          // Call parent component's refresh callback to update tool list state
          // Pass false to prevent showing success message (MCP modal will show its own message)
          if (onToolsRefresh) {
            onToolsRefresh(false);
          }
        } else {
          log.error(
            "Auto refresh tool list failed after MCP configuration:",
            fetchResult.message
          );
        }
      } catch (error) {
        log.error(
          "Error during auto refresh tool list after MCP configuration:",
          error
        );
      }
    };

    window.addEventListener("toolsUpdated", handleToolsUpdate);
    return () => {
      window.removeEventListener("toolsUpdated", handleToolsUpdate);
    };
  }, [onToolsRefresh]);

  const showUnavailableToolAlert =
    agentUnavailableReasons.includes("tool_unavailable");

  // Use memo to optimize the rendering of tool items
  const ToolItem = memo(({ tool }: { tool: Tool }) => {
    const isSelected = selectedToolIds.has(tool.id);
    const isAvailable = tool.is_available !== false; // Default to true, only unavailable when explicitly false
    const isEmbeddingBlocked =
      tool.name === "knowledge_base_search" && !isEmbeddingConfigured;
    const isEffectivelyAvailable = isAvailable && !isEmbeddingBlocked;
    const isDisabled = localIsGenerating || !isEditingMode || isGeneratingAgent; // Disable only during generation or view-only

    const item = (
      <div
        className={`border-2 rounded-md p-2 flex items-center transition-all duration-300 ease-in-out min-h-[52px] shadow-sm ${
          !isEffectivelyAvailable
            ? isSelected
              ? "bg-blue-100 border-blue-400 opacity-60"
              : "bg-gray-50 border-gray-200 opacity-60 cursor-not-allowed"
            : isSelected
            ? "bg-blue-100 border-blue-400 shadow-md"
            : "border-gray-200 hover:border-blue-300 hover:shadow-md"
        } ${
          isDisabled
            ? "opacity-50 cursor-not-allowed"
            : !isEffectivelyAvailable
            ? "cursor-not-allowed"
            : "cursor-pointer"
        }`}
        onClick={(e) => {
          if (isDisabled) {
            if (!isEditingMode) {
              message.warning(t("toolPool.message.viewOnlyMode"));
            }
            return;
          }
          // Prevent selecting unavailable tools
          if (!isEffectivelyAvailable && !isSelected) {
            message.warning(
              isEmbeddingBlocked
                ? t("embedding.agentToolDisableTooltip.content")
                : t("toolPool.message.unavailable")
            );
            return;
          }
          // Prevent deselecting unavailable tools that are already selected
          if (!isEffectivelyAvailable && isSelected) {
            message.warning(
              isEmbeddingBlocked
                ? t("embedding.agentToolDisableTooltip.content")
                : t("toolPool.message.unavailable")
            );
            return;
          }
          handleToolSelect(tool, !isSelected, e);
        }}
      >
        {/* Tool name left */}
        <div className="flex-1 overflow-hidden">
          <div
            className={`font-medium text-sm truncate transition-colors duration-300 ${
              !isEffectivelyAvailable && !isSelected ? "text-gray-400" : ""
            }`}
            style={{
              maxWidth: "300px",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              display: "inline-block",
              verticalAlign: "middle",
            }}
          >
            {tool.name}
          </div>
        </div>
        {/* Settings button right - Tag removed */}
        <div className="flex items-center gap-2 ml-2">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation(); // Prevent triggering parent element click event
              if (localIsGenerating || isGeneratingAgent) return;
              if (!isEffectivelyAvailable) {
                if (isSelected && isEditingMode) {
                  handleToolSelect(tool, false, e);
                } else if (!isEditingMode) {
                  message.warning(t("toolPool.message.viewOnlyMode"));
                  return;
                } else {
                  message.warning(
                    isEmbeddingBlocked
                      ? t("embedding.agentToolDisableTooltip.content")
                      : t("toolPool.message.unavailable")
                  );
                }
                return;
              }
              handleConfigClick(tool, e);
            }}
            disabled={localIsGenerating || isGeneratingAgent}
            aria-label={t("toolPool.button.settings", {
              defaultValue: "Settings",
            })}
            title={t("toolPool.button.settings", { defaultValue: "Settings" })}
            className={`flex-shrink-0 flex items-center justify-center bg-transparent ${
              localIsGenerating || isGeneratingAgent
                ? "text-gray-300 cursor-not-allowed"
                : "text-gray-500 hover:text-blue-500"
            }`}
            style={{ border: "none", padding: "4px" }}
          >
            <SettingOutlined style={{ fontSize: "16px" }} />
          </button>
        </div>
      </div>
    );

    return item;
  });

  // Generate Tabs configuration
  const tabItems = toolGroups.map((group) => {
    // Limit tab display to maximum 7 characters
    const displayLabel =
      group.label.length > 7
        ? `${group.label.substring(0, 7)}...`
        : group.label;

    return {
      key: group.key,
      label: (
        <span
          style={{
            display: "block",
            maxWidth: "70px",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {displayLabel}
        </span>
      ),
      children: (
        <div
          className="flex h-full flex-col sm:flex-row"
          style={{
            height: "100%",
            overflow: "hidden",
          }}
        >
          {group.subGroups ? (
            <>
              {/* Collapsible categories using Ant Design Collapse */}
              <div className="flex-1 overflow-y-auto p-1">
                <Collapse
                  activeKey={Array.from(expandedCategories)}
                  onChange={(keys) => {
                    const newSet = new Set(
                      typeof keys === "string" ? [keys] : keys
                    );
                    setExpandedCategories(newSet);
                  }}
                  ghost
                  size="small"
                  className="tool-categories-collapse mt-1"
                  items={group.subGroups.map((subGroup, index) => ({
                    key: subGroup.key,
                    label: (
                      <span
                        className="text-gray-700 font-medium"
                        style={{
                          paddingTop: "8px",
                          paddingBottom: "8px",
                          display: "block",
                          minHeight: "36px",
                          lineHeight: "20px",
                        }}
                      >
                        {subGroup.label}
                      </span>
                    ),
                    className: `tool-category-panel ${
                      index === 0 ? "mt-1" : "mt-3"
                    }`,
                    children: (
                      <div className="space-y-3 pt-3">
                        {subGroup.tools.map((tool) => (
                          <ToolItem key={tool.id} tool={tool} />
                        ))}
                      </div>
                    ),
                  }))}
                />
              </div>
            </>
          ) : (
            // Regular layout for non-local tools
            <div
              className="flex flex-col gap-3 pr-2 flex-1"
              style={{
                height: "100%",
                overflowY: "auto",
                padding: "8px 0",
                maxHeight: "100%",
              }}
            >
              {group.tools.map((tool) => (
                <ToolItem key={tool.id} tool={tool} />
              ))}
            </div>
          )}
        </div>
      ),
    };
  });

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      <div className="flex justify-between items-center mb-2 flex-shrink-0">
        <div className="flex items-center">
          <h4 className="text-md font-medium text-gray-700">
            {t("toolPool.title")}
          </h4>
          <Tooltip
            title={
              <div style={{ whiteSpace: "pre-line" }}>
                {t("toolPool.tooltip.functionGuide")}
              </div>
            }
            color="#ffffff"
            styles={{
              body: {
                backgroundColor: "#ffffff",
                color: "#374151",
                border: "1px solid #e5e7eb",
                borderRadius: "6px",
                boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)",
                padding: "12px",
                maxWidth: "800px",
                minWidth: "700px",
                width: "fit-content",
              },
            }}
          >
            <BulbOutlined className="ml-2 text-yellow-500" />
          </Tooltip>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="text"
            size="small"
            icon={isRefreshing ? <LoadingOutlined /> : <ReloadOutlined />}
            onClick={handleRefreshTools}
            disabled={localIsGenerating || isRefreshing || isGeneratingAgent}
            className="text-green-500 hover:text-green-600 hover:bg-green-50"
            title={t("toolManagement.refresh.title")}
          >
            {isRefreshing
              ? t("toolManagement.refresh.button.refreshing")
              : t("toolManagement.refresh.button.refresh")}
          </Button>
          <Button
            type="text"
            size="small"
            icon={<ApiOutlined />}
            onClick={() => setIsMcpModalOpen(true)}
            disabled={localIsGenerating || isGeneratingAgent}
            className="text-blue-500 hover:text-blue-600 hover:bg-blue-50"
            title={t("toolManagement.mcp.title")}
          >
            {t("toolManagement.mcp.button")}
          </Button>
          {loadingTools && (
            <span className="text-sm text-gray-500">
              {t("toolPool.loading")}
            </span>
          )}
        </div>
      </div>
      {showUnavailableToolAlert && (
        <div className="mb-2 text-sm text-red-600" role="alert">
          {t("toolPool.error.unavailableSelected")}
        </div>
      )}
      <div className="flex-1 min-h-0 border-t pt-2 pb-2">
        {loadingTools ? (
          <div className="flex items-center justify-center h-full">
            <span className="text-gray-500">{t("toolPool.loadingTools")}</span>
          </div>
        ) : toolGroups.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <span className="text-gray-500">{t("toolPool.noTools")}</span>
          </div>
        ) : (
          <div style={{ height: "100%" }}>
            <Tabs
              tabPosition="left"
              activeKey={activeTabKey}
              onChange={setActiveTabKey}
              items={tabItems}
              className="h-full tool-pool-tabs"
              style={{
                height: "100%",
              }}
              tabBarStyle={{
                minWidth: "80px",
                maxWidth: "100px",
                padding: "4px 0",
                margin: 0,
              }}
            />
          </div>
        )}
      </div>

      <ToolConfigModal
        isOpen={isToolModalOpen}
        onCancel={handleModalClose}
        onSave={handleToolSave}
        tool={currentTool}
        mainAgentId={normalizedAgentId}
        selectedTools={selectedTools}
        isEditingMode={isEditingMode}
      />

      <McpConfigModal
        visible={isMcpModalOpen}
        onCancel={() => setIsMcpModalOpen(false)}
      />
    </div>
  );
}

// Use memo to optimize the rendering of ToolPool component
export const MemoizedToolPool = memo(ToolPool);
