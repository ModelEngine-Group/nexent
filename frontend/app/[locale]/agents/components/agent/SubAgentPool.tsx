"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "antd";
import { ExclamationCircleOutlined } from "@ant-design/icons";
import { FileOutput, Network, FileInput, Trash2, Plus, X } from "lucide-react";

import { ScrollArea } from "@/components/ui/scrollArea";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Agent, SubAgentPoolProps } from "@/types/agentConfig";

import AgentCallRelationshipModal from "@/components/ui/AgentCallRelationshipModal";

/**
 * Sub Agent Pool Component
 */
type ExtendedSubAgentPoolProps = SubAgentPoolProps & {
  /** Agent id that currently has unsaved changes to show blue indicator */
  unsavedAgentId?: number | null;
};

export default function SubAgentPool({
  onEditAgent,
  onCreateNewAgent,
  onImportAgent,
  onExitEditMode,
  subAgentList = [],
  loadingAgents = false,
  isImporting = false,
  isGeneratingAgent = false,
  editingAgent = null,
  isCreatingNewAgent = false,
  onExportAgent,
  onDeleteAgent,
  unsavedAgentId = null,
}: ExtendedSubAgentPoolProps) {
  const { t } = useTranslation("common");

  // Call relationship related state
  const [callRelationshipModalVisible, setCallRelationshipModalVisible] =
    useState(false);
  const [selectedAgentForRelationship, setSelectedAgentForRelationship] =
    useState<Agent | null>(null);

  // Open call relationship modal
  const handleViewCallRelationship = (agent: Agent) => {
    setSelectedAgentForRelationship(agent);
    setCallRelationshipModalVisible(true);
  };

  // Close call relationship modal
  const handleCloseCallRelationshipModal = () => {
    setCallRelationshipModalVisible(false);
    setSelectedAgentForRelationship(null);
  };

  return (
    <TooltipProvider>
      <style jsx global>{`
        /* Agent action button base styles */
        .agent-action-button {
          transition: all 0.2s ease-in-out !important;
          border-radius: 6px !important;
          padding: 4px 8px !important;
        }

        /* Blue action button */
        .agent-action-button-blue {
          color: #3b82f6 !important; /* blue-500 */
        }

        .agent-action-button-blue:hover:not(:disabled) {
          color: #2563eb !important; /* blue-600 */
          background-color: #eff6ff !important; /* blue-50 */
          transform: scale(1.05);
        }

        .agent-action-button-blue:disabled {
          color: #9ca3af !important; /* gray-400 */
          opacity: 0.5;
          cursor: not-allowed !important;
        }

        /* Green action button */
        .agent-action-button-green {
          color: #22c55e !important; /* green-500 */
        }

        .agent-action-button-green:hover:not(:disabled) {
          color: #16a34a !important; /* green-600 */
          background-color: #f0fdf4 !important; /* green-50 */
          transform: scale(1.05);
        }

        .agent-action-button-green:disabled {
          color: #9ca3af !important; /* gray-400 */
          opacity: 0.5;
          cursor: not-allowed !important;
        }

        /* Red action button */
        .agent-action-button-red {
          color: #ef4444 !important; /* red-500 */
        }

        .agent-action-button-red:hover:not(:disabled) {
          color: #dc2626 !important; /* red-600 */
          background-color: #fef2f2 !important; /* red-50 */
          transform: scale(1.05);
        }

        .agent-action-button-red:disabled {
          color: #9ca3af !important; /* gray-400 */
          opacity: 0.5;
          cursor: not-allowed !important;
        }

        /* Agent description clamps to 1 line on small screens */
        .agent-description {
          display: -webkit-box;
          -webkit-box-orient: vertical;
          overflow: hidden;
          text-overflow: ellipsis;
          line-height: 1.25;
          -webkit-line-clamp: 1;
          max-height: 1.25rem;
        }

        @media (min-width: 640px) {
          .agent-description {
            -webkit-line-clamp: 2;
            max-height: 2.5rem;
          }
        }
      `}</style>
      <div className="flex flex-col h-full min-h-[300px] lg:min-h-0 overflow-hidden">
        <div className="flex justify-between items-center mb-2">
          <div className="flex items-center">
            <div className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-500 text-white text-sm font-medium mr-2">
              1
            </div>
            <h2 className="text-lg font-medium">
              {t("subAgentPool.management")}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            {loadingAgents && (
              <span className="text-sm text-gray-500">
                {t("subAgentPool.loading")}
              </span>
            )}
          </div>
        </div>
        <ScrollArea className="flex-1 min-h-0 border-t pt-2 pb-2">
          <div className="flex flex-col pr-2">
            {/* Function operation block */}
            <div className="mb-4">
              <div className="flex gap-3">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div
                      className={`flex-1 rounded-md p-2 flex items-center cursor-pointer transition-all duration-200 min-h-[70px] ${
                        isCreatingNewAgent
                          ? "bg-blue-100 border border-blue-200 shadow-sm" // Highlight in creation mode
                          : "bg-white hover:bg-blue-50 hover:shadow-sm"
                      }`}
                      onClick={() => {
                        if (isCreatingNewAgent) {
                          // If currently in creation mode, click to exit creation mode
                          onExitEditMode?.();
                        } else {
                          // Otherwise enter creation mode
                          onCreateNewAgent();
                        }
                      }}
                    >
                      <div
                        className={`flex items-center w-full ${
                          isCreatingNewAgent ? "text-blue-700" : "text-blue-600"
                        }`}
                      >
                        <div className="flex items-center justify-center w-8 h-8 rounded-full bg-blue-100 mr-3 flex-shrink-0 relative overflow-hidden">
                          {/* Smoothly cross-fade and scale between Plus and X */}
                          <Plus
                            className={`absolute transition-all duration-200 ease-in-out ${
                              isCreatingNewAgent
                                ? "opacity-0 scale-90"
                                : "opacity-100 scale-100"
                            } w-4 h-4`}
                            aria-hidden="true"
                          />
                          <X
                            className={`absolute transition-all duration-200 ease-in-out ${
                              isCreatingNewAgent
                                ? "opacity-100 scale-100"
                                : "opacity-0 scale-90"
                            } w-4 h-4`}
                            aria-hidden="true"
                          />
                        </div>
                        <div className="flex-1">
                          <div className="font-medium text-sm">
                            {isCreatingNewAgent
                              ? t("subAgentPool.button.exitCreate")
                              : t("subAgentPool.button.create")}
                          </div>
                          <div className="text-xs text-gray-500 mt-0.5">
                            {isCreatingNewAgent
                              ? t("subAgentPool.description.exitCreate")
                              : t("subAgentPool.description.createAgent")}
                          </div>
                        </div>
                      </div>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>
                    {isCreatingNewAgent
                      ? t("subAgentPool.tooltip.exitCreateMode")
                      : t("subAgentPool.tooltip.createNewAgent")}
                  </TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <div
                      className={`flex-1 rounded-md p-2 flex items-center transition-all duration-200 min-h-[70px] ${
                        isImporting
                          ? "bg-gray-100 cursor-not-allowed" // Importing: disabled state
                          : "bg-white cursor-pointer hover:bg-green-50 hover:shadow-sm" // Normal state: clickable
                      }`}
                      onClick={isImporting ? undefined : onImportAgent}
                    >
                      <div
                        className={`flex items-center w-full ${
                          isImporting ? "text-gray-400" : "text-green-600" // Use gray when importing
                        }`}
                      >
                        <div
                          className={`flex items-center justify-center w-8 h-8 rounded-full mr-3 flex-shrink-0 ${
                            isImporting ? "bg-gray-100" : "bg-green-100"
                          }`}
                        >
                          <FileOutput
                            className={`w-4 h-4 ${
                              isImporting ? "text-gray-400" : "text-green-600"
                            }`}
                          />
                        </div>
                        <div className="flex-1">
                          <div className="font-medium text-sm">
                            {isImporting
                              ? t("subAgentPool.button.importing")
                              : t("subAgentPool.button.import")}
                          </div>
                          <div className="text-xs text-gray-500 mt-0.5">
                            {isImporting
                              ? t("subAgentPool.description.importing")
                              : t("subAgentPool.description.importAgent")}
                          </div>
                        </div>
                      </div>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>
                    {isImporting
                      ? t("subAgentPool.description.importing")
                      : t("subAgentPool.description.importAgent")}
                  </TooltipContent>
                </Tooltip>
              </div>
            </div>

            {/* Agent list block */}
            <div>
              <div className="text-sm font-medium text-gray-600 mb-2 px-1">
                {t("subAgentPool.section.agentList")} ({subAgentList.length})
              </div>
              <div className="space-y-0">
                {subAgentList.map((agent) => {
                  const isAvailable = agent.is_available !== false; // Default is true, only unavailable when explicitly false
                  const isCurrentlyEditing =
                    editingAgent &&
                    String(editingAgent.id) === String(agent.id); // Ensure type matching
                  const displayName = agent.display_name || agent.name;

                  const agentItem = (
                    <div
                      className={`py-3 px-2 flex flex-col justify-center transition-colors border-t border-gray-200 h-[80px] ${
                        isCurrentlyEditing
                          ? "bg-blue-50 border-l-4 border-l-blue-500" // Highlight editing agent, add left vertical line
                          : isAvailable
                          ? "hover:bg-gray-50 cursor-pointer"
                          : "opacity-60 cursor-pointer" // All unavailable agents can be clicked to edit
                      }`}
                      onClick={async (e) => {
                        // Prevent event bubbling
                        e.preventDefault();
                        e.stopPropagation();

                        if (!isGeneratingAgent) {
                          // Allow all unavailable agents to enter edit mode for configuration
                          if (isCurrentlyEditing) {
                            // If currently editing this Agent, click to exit edit mode
                            onExitEditMode?.();
                          } else {
                            // Enter edit mode (all agents can be edited)
                            onEditAgent(agent);
                          }
                        }
                      }}
                    >
                      <div className="flex items-center h-full">
                        <div className="flex-1 overflow-hidden min-w-0">
                          <div
                            className={`font-medium text-base truncate transition-colors duration-300 ${
                              !isAvailable ? "text-gray-500" : ""
                            }`}
                          >
                            <div className="flex items-center gap-1.5 max-w-full pr-1">
                              {!isAvailable && (
                                <ExclamationCircleOutlined className="text-amber-500 text-sm flex-shrink-0" />
                              )}
                              {displayName && (
                                <span className="text-base leading-normal max-w-[220px] truncate break-all">
                                  {displayName}
                                </span>
                              )}
                              {unsavedAgentId !== null &&
                                String(unsavedAgentId) === String(agent.id) && (
                                  <span
                                    aria-label="unsaved-indicator"
                                    title="Unsaved changes"
                                    className="ml-2 inline-block w-2.5 h-2.5 rounded-full bg-blue-500"
                                  />
                                )}
                            </div>
                          </div>
                          <div
                            className={`text-xs transition-colors duration-300 leading-[1.25] agent-description break-words ${
                              !isAvailable ? "text-gray-400" : "text-gray-500"
                            }`}
                          >
                            {agent.description}
                          </div>
                        </div>

                        {/* Operation button area */}
                        <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                          {/* View call relationship button */}
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                type="text"
                                size="small"
                                icon={<Network className="w-4 h-4" />}
                                onClick={(e) => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  handleViewCallRelationship(agent);
                                }}
                                className="agent-action-button agent-action-button-blue"
                              />
                            </TooltipTrigger>
                            <TooltipContent>
                              {t("agent.action.viewCallRelationship")}
                            </TooltipContent>
                          </Tooltip>
                          {/* Export button */}
                          {onExportAgent && (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  type="text"
                                  size="small"
                                  icon={<FileInput className="w-4 h-4" />}
                                  onClick={(e) => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    onExportAgent(agent);
                                  }}
                                  className="agent-action-button agent-action-button-green"
                                />
                              </TooltipTrigger>
                              <TooltipContent>
                                {t("agent.contextMenu.export")}
                              </TooltipContent>
                            </Tooltip>
                          )}
                          {/* Delete button */}
                          {onDeleteAgent && (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  type="text"
                                  size="small"
                                  icon={<Trash2 className="w-4 h-4" />}
                                  onClick={(e) => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    onDeleteAgent(agent);
                                  }}
                                  className="agent-action-button agent-action-button-red"
                                />
                              </TooltipTrigger>
                              <TooltipContent>
                                {t("agent.contextMenu.delete")}
                              </TooltipContent>
                            </Tooltip>
                          )}
                        </div>
                      </div>
                    </div>
                  );

                  return <div key={agent.id}>{agentItem}</div>;
                })}
              </div>
            </div>
          </div>
        </ScrollArea>

        {/* Agent call relationship modal */}
        {selectedAgentForRelationship && (
          <AgentCallRelationshipModal
            visible={callRelationshipModalVisible}
            onClose={handleCloseCallRelationshipModal}
            agentId={Number(selectedAgentForRelationship.id)}
            agentName={
              selectedAgentForRelationship.display_name ||
              selectedAgentForRelationship.name
            }
          />
        )}
      </div>
    </TooltipProvider>
  );
}
