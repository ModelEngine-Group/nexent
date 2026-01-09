"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import ToolConfigModal from "./tool/ToolConfigModal";
import { ToolGroup, Tool, ToolParam } from "@/types/agentConfig";
import { Tabs, Collapse } from "antd";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useToolList } from "@/hooks/agent/useToolList";
import { updateToolConfig } from "@/services/agentConfigService";
import { useToolInfo } from "@/hooks/tool/useToolInfo";
import { message } from "antd";
import { useQueryClient } from "@tanstack/react-query";

import { Settings } from "lucide-react";

interface ToolManagementProps {
  toolGroups: ToolGroup[];
  isCreatingMode?: boolean;
  currentAgentId?: number | undefined;
}

/**
 * ToolManagement - Component for displaying tools in tabs
 * Provides a tabbed interface for tool organization
 */
export default function ToolManagement({
  toolGroups,
  isCreatingMode = true,
  currentAgentId,
}: ToolManagementProps) {
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();

  const editable = currentAgentId !== null || isCreatingMode;
  // Get state from store
  const usedTools = useAgentConfigStore((state) => state.editedAgent.tools);
  const updateTools = useAgentConfigStore((state) => state.updateTools);

  // Use tool list hook for data management
  const { availableTools } = useToolList();

  const [activeTabKey, setActiveTabKey] = useState<string>("");
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    new Set()
  );
  const [isToolModalOpen, setIsToolModalOpen] = useState<boolean>(false);
  const [isClickSetting, setIsClickSetting] = useState<boolean>(false);
  const [selectedTool, setSelectedTool] = useState<Tool | null>(null);
  const [toolParams, setToolParams] = useState<ToolParam[]>([]);

  // Get tool info for selected tool (when checking if config is needed)
  const { data: selectedToolInfo, isLoading: isToolInfoLoading } = useToolInfo(
    (selectedTool) ? parseInt(selectedTool.id) : null,
    currentAgentId ?? null
  );

  // Effect to handle tool selection when tool info is loaded
  useEffect(() => {
    let mergedParams: ToolParam[];

    if (isCreatingMode && selectedTool) {
      mergedParams = selectedTool.initParams || [];
    } else if (selectedTool && selectedToolInfo) {
      mergedParams = selectedTool.initParams?.map((param: ToolParam) => {
        const instanceValue = selectedToolInfo?.params?.[param.name];
        return {
          ...param,
          value: instanceValue !== undefined ? instanceValue : param.value,
        };
      }) || [];
    } else {
      return;
    }
    setToolParams(mergedParams);
    const hasEmptyRequiredParams = mergedParams.some(
      (param: ToolParam) => param.required &&
        (param.value === undefined || param.value === '' || param.value === null)
    );
    if (isClickSetting || hasEmptyRequiredParams) {
      // Open modal for configuration with pre-calculated params
      setIsToolModalOpen(true);
      setIsClickSetting(false)
    } else {
      // Add tool directly
      const newSelectedTools = [...usedTools, {
        ...selectedTool,
        initParams: mergedParams
      }];
      updateTools(newSelectedTools);
      setSelectedTool(null); // Clear selected tool
      setIsClickSetting(false)
    }

    
  }, [selectedTool, isToolInfoLoading]); 

  // Create selected tool ID set for efficient lookup
  const selectedToolIdsSet = new Set(
    usedTools.map((tool) => tool.id)
  );

  // Set default active tab
  useEffect(() => {
    if (toolGroups.length > 0 && !activeTabKey) {
      setActiveTabKey(toolGroups[0].key);
    }
  }, [toolGroups, activeTabKey]);

  const handleToolModalCancel = () => {
    setIsToolModalOpen(false);
    setSelectedTool(null);
    setToolParams([]);
    setIsClickSetting(false)
  };

  const handleToolModalSave = async (params: ToolParam[]) => {
    if (!selectedTool) return;

      // Convert params to backend format
      const paramsObj = params.reduce((acc, param) => {
        acc[param.name] = param.value;
        return acc;
      }, {} as Record<string, any>);

      if (isCreatingMode) {
        saveToolConfig(params);
      } else if (currentAgentId) {

        try {
          const isEnabled = true; // New tool is enabled by default
          const result = await updateToolConfig(
            parseInt(selectedTool.id),
            currentAgentId,
            paramsObj,
            isEnabled
          );

          if (result.success) {
            saveToolConfig(params);
            queryClient.invalidateQueries({ 
              queryKey: ["toolInfo", parseInt(selectedTool.id), currentAgentId] 
            });
          } else {
            message.error(result.message || t("toolConfig.message.saveError"));
          }
        } catch (error) {
          message.error(t("toolConfig.message.saveError"));
        }
      }
  };


  const saveToolConfig = async (params: ToolParam[]) => {
    // Add tool to selected tools with updated params
    const updatedTool = { ...selectedTool!, initParams: params };
    const newSelectedTools = [...usedTools, updatedTool];
    updateTools(newSelectedTools);

    message.success(t("toolConfig.message.saveSuccess"));

    setIsToolModalOpen(false);
    setSelectedTool(null);
    setToolParams([]);
    setIsClickSetting(false)
  }
  const handleToolSettingsClick = (tool: Tool) => {
    setIsClickSetting(true)
    setSelectedTool(tool); 
  };

  const handleToolSelect = (toolId: number) => {
    // Find the tool from available tools
    const tool = availableTools.find((t) => parseInt(t.id) === toolId);
    if (!tool) return;

    const isCurrentlySelected = usedTools.some(
      (t) => parseInt(t.id) === toolId
    );
    if (isCurrentlySelected) {
      const newSelectedTools = usedTools.filter((t) => parseInt(t.id) !== toolId);
      updateTools(newSelectedTools);   
    } else {
      setSelectedTool(tool);
    }
  }

  const handleToolClick = (toolId: string) => {
    const numericId = parseInt(toolId, 10);
    handleToolSelect(numericId);
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
                          const isSelected = selectedToolIdsSet.has(tool.id);
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
                const isSelected = selectedToolIdsSet.has(tool.id);
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

      <ToolConfigModal
        isOpen={isToolModalOpen}
        onCancel={handleToolModalCancel}
        onSave={handleToolModalSave}
        tool={selectedTool ?? undefined}
        initialParams={toolParams}
      />
    </div>
  );
}
