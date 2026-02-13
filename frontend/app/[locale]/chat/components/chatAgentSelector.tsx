"use client";

import React, { useState, useEffect, useRef, useMemo } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { ChevronDown, MousePointerClick, AlertCircle } from "lucide-react";

import { getUrlParam } from "@/lib/utils";
import log from "@/lib/logger";
import { ChatAgentSelectorProps } from "@/types/chat";
import { Agent } from "@/types/agentConfig";
import { clearAgentNewMark } from "@/services/agentConfigService";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";

export function ChatAgentSelector({
  selectedAgentId,
  onAgentSelect,
  disabled = false,
  isInitialMode = false,
}: ChatAgentSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [dropdownPosition, setDropdownPosition] = useState({
    top: 0,
    left: 0,
    direction: "down",
  });
  const [isPositionCalculated, setIsPositionCalculated] = useState(false);
  const [isAutoSelectInit, setIsAutoSelectInit] = useState(false);
  const { t } = useTranslation("common");
  const buttonRef = useRef<HTMLDivElement>(null);
  const { agents, invalidate, isLoading } = usePublishedAgentList();

  const selectedAgent = agents.find(
    (agent: Agent) => agent.id === String(selectedAgentId)
  );

  // Detect duplicate agent names and mark later-added agents as disabled
  // For agents with the same name, keep the first one (smallest ID) enabled, disable the rest
  const duplicateAgentInfo = useMemo(() => {
    // Create a map to track agents by name
    const nameToAgents = new Map<string, Agent[]>();

    agents.forEach((agent: Agent) => {
      const agentName = agent.name;
      if (!nameToAgents.has(agentName)) {
        nameToAgents.set(agentName, []);
      }
      nameToAgents.get(agentName)!.push(agent);
    });

    // For each group of agents with the same name, sort by ID (smallest first)
    // Mark all except the first one as disabled
    const disabledAgentIds = new Set<string>();

    nameToAgents.forEach((agents, name) => {
      if (agents.length > 1) {
        // Sort by id (smallest first)
        const sortedAgents = [...agents].sort((a, b) => Number(a.id) - Number(b.id));

        // Mark all except the first one as disabled
        for (let i = 1; i < sortedAgents.length; i++) {
          disabledAgentIds.add(sortedAgents[i].id);
        }
      }
    });

    return { disabledAgentIds, nameToAgents };
  }, [agents]);

  /**
   * Handle URL parameter auto-selection logic for Agent
   */
  const handleAutoSelectAgent = () => {
    if (agents.length === 0 || isAutoSelectInit) return;

    // Get agent_id parameter from URL
    const agentId = getUrlParam("agent_id", null as string | null, (str) =>
      str ? str : null
    );
    if (agentId === null) return;

    // Check if agentId is a valid and effectively available agent
    const agent = agents.find((a: Agent) => a.id === agentId);
    if (agent) {
      const isAvailableTool = agent.is_available !== false;
      const isDuplicateDisabled = duplicateAgentInfo.disabledAgentIds.has(agent.id);
      const isEffectivelyAvailable = isAvailableTool && !isDuplicateDisabled;

      if (isEffectivelyAvailable) {
        handleAgentSelect(agent.id);
        setIsAutoSelectInit(true);
      }
    }
  };

  // Execute auto-selection logic when agents are loaded
  useEffect(() => {
    handleAutoSelectAgent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents, duplicateAgentInfo]);

  // Calculate dropdown position
  useEffect(() => {
    if (isOpen && buttonRef.current) {
      const buttonRect = buttonRef.current.getBoundingClientRect();
      const viewportHeight = window.innerHeight;
      const dropdownHeight = 320; // Estimated dropdown height (max-h-80), can be adjusted based on agent count

      // Check if there's enough space to display below
      const hasSpaceBelow =
        buttonRect.bottom + dropdownHeight + 10 < viewportHeight;
      // Check if there's enough space to display above
      const hasSpaceAbove = buttonRect.top - dropdownHeight - 10 > 0;

      let direction = "down";
      let top = buttonRect.bottom + 4;

      // Decide direction: prioritize suggested direction, but adjust if space is insufficient
      if (isInitialMode) {
        // Initial mode prioritizes downward
        if (!hasSpaceBelow && hasSpaceAbove) {
          direction = "up";
          top = buttonRect.top - 4;
        }
      } else {
        // Non-initial mode prioritizes upward
        direction = "up";
        top = buttonRect.top - 4;
        if (!hasSpaceAbove && hasSpaceBelow) {
          direction = "down";
          top = buttonRect.bottom + 4;
        }
      }

      setDropdownPosition({
        top,
        left: buttonRect.left,
        direction,
      });
      setIsPositionCalculated(true);
    } else if (!isOpen) {
      setIsPositionCalculated(false);
    }
  }, [isOpen, isInitialMode]);

  // Listen for window scroll and resize events, close dropdown
  useEffect(() => {
    if (!isOpen) return;

    const handleScroll = (e: Event) => {
      // If scrolling occurs inside the dropdown, don't close it
      const target = e.target as Node;
      const dropdownElement = document.querySelector(
        ".agent-selector-dropdown"
      );
      if (
        dropdownElement &&
        (dropdownElement === target || dropdownElement.contains(target))
      ) {
        return;
      }

      // If it's page scrolling or other container scrolling, close the dropdown
      setIsOpen(false);
    };

    const handleResize = () => {
      setIsOpen(false);
    };

    // Use event capture phase
    window.addEventListener("scroll", handleScroll, true);
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("scroll", handleScroll, true);
      window.removeEventListener("resize", handleResize);
    };
  }, [isOpen]);

  const handleAgentSelect = async (agentId: string | null) => {
    // Only effectively available agents can be selected
    if (agentId !== null) {
      const agent = agents.find((a: Agent) => a.id === agentId);
      if (agent) {
        const isAvailableTool = agent.is_available !== false;
        const isDuplicateDisabled = duplicateAgentInfo.disabledAgentIds.has(agent.id);
        const isEffectivelyAvailable = isAvailableTool && !isDuplicateDisabled;

        if (!isEffectivelyAvailable) {
          return; // Unavailable agents cannot be selected
        }

        // Clear NEW mark when agent is selected for chat (only if marked as new)
        if (agent.is_new === true) {
          try {
            const res = await clearAgentNewMark(Number(agentId));
            if (res?.success) {
              // Invalidate the query to refresh agents list
              invalidate();
            } else {
              log.warn("Failed to clear NEW mark on select:", res);
            }
          } catch (e) {
            log.error("Failed to clear NEW mark on select:", e);
          }
        }
      }
    }

    onAgentSelect(agentId);
    setIsOpen(false);

    // If it's an iframe embedded page, send postMessage to the parent page
    if (window.self !== window.top) {
      try {
        const selectedAgent = agents.find(
          (agent: Agent) => agent.id === agentId
        );
        const message = {
          type: "agent_selected",
          agent_id: agentId,
          agent_name: selectedAgent?.name || null,
          timestamp: Date.now(),
          source: "agent_selector",
        };

        // Send postMessage to the parent page
        window.parent.postMessage(message, "*");
      } catch (error) {
        log.error("Failed to send postMessage:", error);
      }
    }
  };

  // Show all agents, including unavailable ones
  const allAgents = agents;

  return (
    <div className="relative">
      <div
        ref={buttonRef}
        className={`
          relative h-8 min-w-[150px] max-w-[250px] px-2
          rounded-lg border border-slate-200
          bg-white hover:bg-slate-50
          flex items-center justify-between
          cursor-pointer select-none
          transition-colors duration-150
          ${disabled || isLoading ? "opacity-50 cursor-not-allowed" : ""}
          ${
            isOpen
              ? "border-blue-400 ring-2 ring-blue-100"
              : "hover:border-slate-300"
          }
        `}
        onClick={() => !disabled && !isLoading && setIsOpen(!isOpen)}
      >
        <div className="flex items-center gap-2 truncate">
          {selectedAgent && (
            <MousePointerClick className="w-4 h-4 text-blue-500 flex-shrink-0" />
          )}
          <span
            className={`truncate text-sm ${
              selectedAgent ? "font-medium text-slate-700" : "text-slate-500"
            }`}
          >
            {isLoading ? (
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 border-2 border-slate-300 border-t-slate-500 rounded-full animate-spin" />
                <span>{t("agentSelector.loading")}</span>
              </div>
            ) : selectedAgent ? (
              selectedAgent.display_name
            ) : (
              t("agentSelector.selectAgent")
            )}
          </span>
        </div>
        <ChevronDown
          className={`h-4 w-4 text-slate-400 transition-transform duration-200 ${
            isOpen ? "rotate-180" : ""
          }`}
        />
      </div>

      {/* Portal renders dropdown to body to avoid being blocked by parent container */}
      {isOpen &&
        isPositionCalculated &&
        typeof window !== "undefined" &&
        createPortal(
          <>
            {/* Overlay */}
            <div
              className="fixed inset-0 z-[9998]"
              onClick={() => setIsOpen(false)}
              onWheel={(e) => {
                // If scrolling occurs inside the dropdown, don't close it
                const target = e.target as Node;
                const dropdownElement = document.querySelector(
                  ".agent-selector-dropdown"
                );
                if (
                  dropdownElement &&
                  (dropdownElement === target ||
                    dropdownElement.contains(target))
                ) {
                  return;
                }
                setIsOpen(false);
              }}
            />

            {/* Dropdown */}
            <div
              className="agent-selector-dropdown fixed bg-white border border-slate-200 rounded-md shadow-lg z-[9999] max-h-80 overflow-y-auto"
              style={{
                top:
                  dropdownPosition.direction === "up"
                    ? `${dropdownPosition.top}px`
                    : `${dropdownPosition.top}px`,
                left: `${dropdownPosition.left}px`,
                width: `550px`,
                transform:
                  dropdownPosition.direction === "up"
                    ? "translateY(-100%)"
                    : "none",
              }}
              onWheel={(e) => {
                // Prevent scroll event bubbling, but allow normal scrolling
                e.stopPropagation();
              }}
            >
              <div className="py-1">
                {allAgents.length === 0 ? (
                  <div className="px-3 py-2.5 text-sm text-slate-500 text-center">
                    {isLoading ? (
                      <div className="flex items-center justify-center gap-2">
                        <div className="w-4 h-4 border-2 border-slate-300 border-t-slate-500 rounded-full animate-spin" />
                        <span>{t("agentSelector.loading")}</span>
                      </div>
                    ) : (
                      t("agentSelector.noAvailableAgents")
                    )}
                  </div>
                ) : (
                  allAgents.map((agent: Agent, idx: number) => {
                    const isAvailableTool = agent.is_available !== false;
                    const isDuplicateDisabled = duplicateAgentInfo.disabledAgentIds.has(agent.id);
                    const isEffectivelyAvailable = isAvailableTool && !isDuplicateDisabled;

                    // Determine the reason for unavailability
                    let unavailableReason: string | null = null;
                    if (!isEffectivelyAvailable) {
                      if (isDuplicateDisabled) {
                        unavailableReason = t("subAgentPool.tooltip.duplicateNameDisabled");
                      } else if (!isAvailableTool) {
                        unavailableReason = t("subAgentPool.tooltip.hasUnavailableTools");
                      }
                    }

                    return (
                      <div
                        key={agent.id}
                        className={`
                        flex items-start gap-3 px-3.5 py-2.5 text-sm
                        transition-all duration-150 ease-in-out
                        ${
                          isEffectivelyAvailable
                            ? `hover:bg-slate-50 cursor-pointer ${
                                selectedAgentId === agent.id
                                  ? "bg-blue-50/70 text-blue-600 hover:bg-blue-50/70"
                                  : ""
                              }`
                            : "opacity-60 cursor-not-allowed bg-slate-50/50"
                        }
                        ${
                          selectedAgentId === agent.id
                            ? "shadow-[inset_2px_0_0_0] shadow-blue-500"
                            : ""
                        }
                        ${idx !== 0 ? "border-t border-slate-100" : ""}
                      `}
                        onClick={() =>
                          isEffectivelyAvailable && handleAgentSelect(agent.id)
                        }
                      >
                        {/* Agent Icon */}
                        <div className="flex-shrink-0 mt-0.5">
                          {isEffectivelyAvailable ? (
                            <MousePointerClick
                              className={`h-4 w-4 ${
                                selectedAgentId === agent.id
                                  ? "text-blue-500"
                                  : "text-slate-500"
                              }`}
                            />
                          ) : (
                            <AlertCircle className="h-4 w-4 text-amber-500" />
                          )}
                        </div>

                        {/* Agent Info */}
                        <div className="flex-1 min-w-0">
                          <div
                            className={`font-medium truncate ${
                              isEffectivelyAvailable
                                ? selectedAgentId === agent.id
                                  ? "text-blue-600"
                                  : "text-slate-700 hover:text-slate-900"
                                : "text-slate-400"
                            }`}
                          >
                            <div className="flex items-center gap-1.5">
                              {/* NEW badge - placed before display_name */}
                              {(agent as any).is_new && agent.display_name && (
                                <span className="inline-flex items-center px-1 h-5 bg-amber-50 dark:bg-amber-900/10 text-amber-700 dark:text-amber-300 rounded-full text-[11px] font-medium border border-amber-200 flex-shrink-0 leading-none mr-0.5">
                                  <span className="px-0.5">{t("space.new", "NEW")}</span>
                                </span>
                              )}
                              {agent.display_name && (
                                <span className="text-sm leading-none">
                                  {agent.display_name}
                                </span>
                              )}
                              <span
                                className={`text-sm leading-none align-baseline ${
                                  agent.display_name ? "ml-2" : "text-sm"
                                }`}
                              >
                                {agent.name}
                              </span>
                            </div>
                          </div>
                          <div
                            className={`text-xs mt-1 leading-relaxed ${
                              isEffectivelyAvailable
                                ? selectedAgentId === agent.id
                                  ? "text-blue-500"
                                  : "text-slate-500"
                                : "text-slate-400"
                            }`}
                          >
                            {agent.description}
                            {unavailableReason && (
                              <span className="block mt-1.5 text-amber-600 font-medium">
                                {unavailableReason}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </>,
          document.body
        )}
    </div>
  );
}
