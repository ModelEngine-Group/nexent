"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import ToolConfigModal from "./tool/ToolConfigModal";
import { ToolGroup, Tool, ToolParam } from "@/types/agentConfig";
import { Tabs, Collapse, message } from "antd";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useToolList } from "@/hooks/agent/useToolList";
import { usePrefetchKnowledgeBases } from "@/hooks/useKnowledgeBaseSelector";
import { updateToolConfig } from "@/services/agentConfigService";
import { useQueryClient } from "@tanstack/react-query";

import { Settings } from "lucide-react";

interface ToolManagementProps {
  toolGroups: ToolGroup[];
  isCreatingMode?: boolean;
  currentAgentId?: number | undefined;
}

// Tool types that require knowledge base selection
const TOOLS_REQUIRING_KB_SELECTION = [
  "knowledge_base_search",
  "dify_search",
  "datamate_search",
];

function getToolKbType(
  toolName: string
): "knowledge_base_search" | "dify_search" | "datamate_search" | null {
  if (!TOOLS_REQUIRING_KB_SELECTION.includes(toolName)) return null;
  if (toolName === "dify_search") return "dify_search";
  if (toolName === "datamate_search") return "datamate_search";
  return "knowledge_base_search";
}

/**
 * ToolManagement - Component for displaying tools in tabs
 * Provides a tabbed interface for tool organization
 */
export default function ToolManagement({
  toolGroups,
  isCreatingMode,
  currentAgentId,
}: ToolManagementProps) {
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();

  const editable = currentAgentId || isCreatingMode;

  // Get state from store
  const originalSelectedTools = useAgentConfigStore(
    (state) => state.editedAgent.tools
  );
  const originalSelectedToolIdsSet = new Set(
    originalSelectedTools.map((tool) => tool.id)
  );

  const updateTools = useAgentConfigStore((state) => state.updateTools);

  // Use tool list hook for data management
  const { availableTools } = useToolList();

  // Prefetch knowledge bases for KB tools
  const { prefetchKnowledgeBases } = usePrefetchKnowledgeBases();

  const [activeTabKey, setActiveTabKey] = useState<string>("");
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    new Set()
  );
  const [isToolModalOpen, setIsToolModalOpen] = useState<boolean>(false);
  const [selectedTool, setSelectedTool] = useState<Tool | null>(null);
  const [toolParams, setToolParams] = useState<ToolParam[]>([]);

  // Helper function to merge tool parameters with instance parameters
  const mergeToolParamsWithInstance = async (
    tool: Tool,
    defaultTool: Tool,
    agentId?: number
  ): Promise<ToolParam[]> => {
    if (agentId) {
      try {
        const { searchToolConfig } =
          await import("@/services/agentConfigService");
        const tooInstance = await searchToolConfig(parseInt(tool.id), agentId);

        if (tooInstance.success && tooInstance.data) {
          // Merge instance params with default params
          const mergedParams =
            defaultTool.initParams?.map((param: ToolParam) => {
              const instanceValue = tooInstance.data?.params?.[param.name];
              return {
                ...param,
                value:
                  instanceValue !== undefined ? instanceValue : param.value,
              };
            }) ||
            defaultTool.initParams ||
            [];
          return mergedParams;
        } else {
          return defaultTool.initParams || [];
        }
      } catch (error) {
        console.error("Failed to fetch tool instance params:", error);
        return defaultTool.initParams || [];
      }
    } else {
      return defaultTool.initParams || [];
    }
  };

  // Set default active tab
  useEffect(() => {
    if (toolGroups.length > 0 && !activeTabKey) {
      setActiveTabKey(toolGroups[0].key);
    }
  }, [toolGroups, activeTabKey]);

  const handleToolSettingsClick = async (tool: Tool) => {
    // Prefetch knowledge bases for KB tools
    const kbType = getToolKbType(tool.name);
    if (kbType) {
      prefetchKnowledgeBases(kbType);
    }

    // Get latest tools directly from store to avoid stale closure issues
    const currentTools = useAgentConfigStore.getState().editedAgent.tools;
    const configuredTool = currentTools.find(
      (t) => parseInt(t.id) === parseInt(tool.id)
    );
    // Merge configured tool with original tool to ensure all fields are present
    const toolToUse = configuredTool
      ? { ...tool, ...configuredTool, initParams: configuredTool.initParams }
      : tool;

    // Get merged parameters (for editing mode, merge with instance params)
    const mergedParams = await mergeToolParamsWithInstance(
      tool,
      toolToUse,
      isCreatingMode ? undefined : currentAgentId
    );

    setSelectedTool(toolToUse);
    setToolParams(mergedParams);
    setIsToolModalOpen(true);
  };

  const handleToolClick = async (toolId: string) => {
    const numericId = parseInt(toolId, 10);
    const tool = availableTools.find((t) => parseInt(t.id) === numericId);

    if (!tool) return;

    // Prefetch knowledge bases for KB tools
    const kbType = getToolKbType(tool.name);
    if (kbType) {
      prefetchKnowledgeBases(kbType);
    }

    // Get latest tools directly from store to avoid stale closure issues
    const currentSelectdTools =
      useAgentConfigStore.getState().editedAgent.tools;
    const isCurrentlySelected = currentSelectdTools.some(
      (t) => parseInt(t.id) === numericId
    );

    if (isCurrentlySelected) {
      // If already selected, deselect it
      const newSelectedTools = currentSelectdTools.filter(
        (t) => parseInt(t.id) !== numericId
      );
      updateTools(newSelectedTools);
    } else {
      // If not selected, determine tool params and check if modal is needed
      const configuredTool = currentSelectdTools.find(
        (t) => parseInt(t.id) === numericId
      );
      // Merge configured tool with original tool to ensure all fields are present
      const toolToUse = configuredTool
        ? { ...tool, ...configuredTool, initParams: configuredTool.initParams }
        : tool;

      // Get merged parameters (for editing mode, merge with instance params)
      const mergedParams = await mergeToolParamsWithInstance(
        tool,
        toolToUse,
        isCreatingMode ? undefined : currentAgentId!
      );

      // Check if there are empty required params
      const hasEmptyRequiredParams = mergedParams.some(
        (param: ToolParam) =>
          param.required &&
          (param.value === undefined ||
            param.value === "" ||
            param.value === null)
      );

      if (hasEmptyRequiredParams) {
        // Need to configure, open modal
        setSelectedTool(toolToUse);
        setToolParams(mergedParams);
        setIsToolModalOpen(true);
      } else {
        // No required params missing, add directly
        const newSelectedTools = [
          ...currentSelectdTools,
          {
            ...toolToUse,
            initParams: mergedParams,
          },
        ];
        updateTools(newSelectedTools);

        // In non-creating mode, immediately save tool config to backend
        if (!isCreatingMode && currentAgentId) {
          try {
            // Convert params to backend format
            const paramsObj = mergedParams.reduce(
              (acc, param) => {
                acc[param.name] = param.value;
                return acc;
              },
              {} as Record<string, any>
            );

            const isEnabled = true; // New tool is enabled by default
            const result = await updateToolConfig(
              numericId,
              currentAgentId,
              paramsObj,
              isEnabled
            );

            if (result.success) {
              // Invalidate queries to refresh tool info
              queryClient.invalidateQueries({
                queryKey: ["toolInfo", numericId, currentAgentId],
              });
            } else {
              message.error(
                result.message || t("toolConfig.message.saveError")
              );
            }
          } catch (error) {
            console.error("Failed to save tool config:", error);
            message.error(t("toolConfig.message.saveError"));
          }
        }
      }
    }
  };

  // Generate Tabs configuration
  const tabItems = toolGroups.map((group) => {
    // Limit tab display to maximum 7 characters
    const displayLabel =
      t(group.label).length > 7
        ? `${t(group.label).substring(0, 7)}...`
        : t(group.label);

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
                        {subGroup.tools.map((tool) => {
                          const isSelected = originalSelectedToolIdsSet.has(
                            tool.id
                          );
                          return (
                            <div
                              key={tool.id}
                              className={`border-2 rounded-md p-2 flex items-center justify-between transition-all duration-300 ease-in-out min-h-[52px] shadow-sm ${
                                isSelected
                                  ? "bg-blue-100 border-blue-400 shadow-md"
                                  : "border-gray-200 hover:border-blue-300 hover:shadow-md"
                              } ${editable ? "cursor-pointer" : "cursor-not-allowed opacity-60"}`}
                              onClick={
                                editable
                                  ? () => handleToolClick(tool.id)
                                  : undefined
                              }
                            >
                              <span>{tool.name}</span>
                              <Settings
                                size={16}
                                className={`${editable ? "cursor-pointer text-gray-500 hover:text-gray-700" : "cursor-not-allowed text-gray-400"} transition-colors`}
                                onClick={
                                  editable
                                    ? (e) => {
                                        e.stopPropagation();
                                        handleToolSettingsClick(tool);
                                      }
                                    : undefined
                                }
                              />
                            </div>
                          );
                        })}
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
              {group.tools.map((tool) => {
                const isSelected = originalSelectedToolIdsSet.has(tool.id);
                return (
                  <div
                    key={tool.id}
                    className={`border-2 rounded-md p-2 flex items-center justify-between transition-all duration-300 ease-in-out min-h-[52px] shadow-sm ${
                      isSelected
                        ? "bg-blue-100 border-blue-400 shadow-md"
                        : "border-gray-200 hover:border-blue-300 hover:shadow-md"
                    } ${editable ? "cursor-pointer" : "cursor-not-allowed opacity-60"}`}
                    onClick={
                      editable ? () => handleToolClick(tool.id) : undefined
                    }
                  >
                    <span>{tool.name}</span>
                    <Settings
                      size={16}
                      className={`${editable ? "cursor-pointer text-gray-500 hover:text-gray-700" : "cursor-not-allowed text-gray-400"} transition-colors`}
                      onClick={
                        editable
                          ? (e) => {
                              e.stopPropagation();
                              handleToolSettingsClick(tool);
                            }
                          : undefined
                      }
                    />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ),
    };
  });

  return (
    <div className="h-full">
      {toolGroups.length === 0 ? (
        <div className="flex items-center justify-center h-full">
          <span className="text-gray-500">{t("toolPool.noTools")}</span>
        </div>
      ) : (
        <Tabs
          tabPlacement="start"
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
      )}

      {isToolModalOpen && (
        <ToolConfigModal
          isOpen={isToolModalOpen}
          onCancel={() => {
            setIsToolModalOpen(false);
            setSelectedTool(null);
            setToolParams([]);
          }}
          tool={selectedTool!}
          initialParams={toolParams}
          selectedTool={selectedTool}
          isCreatingMode={isCreatingMode}
          currentAgentId={currentAgentId}
        />
      )}
    </div>
  );
}
