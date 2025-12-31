"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import ToolConfigModal from "./tool/ToolConfigModal";
import { ToolGroup, Tool } from "@/types/agentConfig";
import { Tabs, Collapse } from "antd";

import {
  LoaderCircle,
  Settings,
  RefreshCw,
  Lightbulb,
  Plug,
} from "lucide-react";

interface ToolManagementProps {
  toolGroups: ToolGroup[];
  selectedToolIds?: number[];
  onToolSelect?: (toolId: number) => void;
  editable?: boolean;
}

/**
 * ToolManagement - Component for displaying tools in tabs
 * Provides a tabbed interface for tool organization
 */
export default function ToolManagement({
  toolGroups,
  selectedToolIds = [],
  onToolSelect,
  editable = true,
}: ToolManagementProps) {
  const { t } = useTranslation("common");

  const [activeTabKey, setActiveTabKey] = useState<string>("");
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    new Set()
  );
  const [isToolModalOpen, setIsToolModalOpen] = useState<boolean>(false);
  const [selectedTool, setSelectedTool] = useState<Tool | null>(null);

  // Create selected tool ID set for efficient lookup
  const selectedToolIdsSet = new Set(
    selectedToolIds.map((id) => id.toString())
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
  };

  const handleToolModalSave = (tool: Tool) => {
    setIsToolModalOpen(false);
    setSelectedTool(null);
    // TODO: Handle tool save logic here
  };

  const handleToolSettingsClick = (tool: Tool) => {
    setSelectedTool(tool);
    setIsToolModalOpen(true);
  };

  const handleToolClick = (toolId: string) => {
    if (onToolSelect) {
      const numericId = parseInt(toolId, 10);
      onToolSelect(numericId);
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
      )}

      <ToolConfigModal
        isOpen={isToolModalOpen}
        onCancel={handleToolModalCancel}
        onSave={handleToolModalSave}
        tool={selectedTool}
      />
    </div>
  );
}
