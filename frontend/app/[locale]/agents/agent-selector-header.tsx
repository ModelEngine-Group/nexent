"use client";

import { useTranslation } from "react-i18next";
import { App, Flex, Button, Dropdown, Tooltip, Col, Row, Input } from "antd";
import {
  Plus,
  FileInput,
  ChevronDown,
  ChevronLeft,
  Bot,
  GitBranch,
  Search,
} from "lucide-react";
import { ExclamationCircleOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  useParams,
  usePathname,
  useRouter,
  useSearchParams,
} from "next/navigation";
import {
  searchAgentInfo,
  clearAgentNewMark,
} from "@/services/agentConfigService";

import { Agent } from "@/types/agentConfig";
import { useAgentStore } from "@/stores/agentStore";
import { useQueryClient } from "@tanstack/react-query";
import AgentImportWizard from "@/components/agent/AgentImportWizard";
import CreateAgentModal from "@/components/agent/CreateAgentModal";
import {
  ImportAgentData,
  openImportWizardWithFile,
} from "@/lib/agentImportUtils";
import log from "@/lib/logger";
import { useAgentList } from "@/hooks/agent/useAgentList";
import AgentConfigActions from "./components/agent-config-actions";

interface AgentSelectorHeaderProps {
  onToggleVersionManage: () => void;
  isVersionManageVisible: boolean;
  onAgentCreated: () => void;
}

export default function AgentSelectorHeader({
  onToggleVersionManage,
  isVersionManageVisible,
  onAgentCreated,
}: AgentSelectorHeaderProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const params = useParams<{ locale: string }>();
  const locale = params.locale || "en";
  const showBackFromRepository = true;
  const queryClient = useQueryClient();
  const waitForAutosave = useAgentStore((state) => state.waitForIdle);

  // Resolve tenant from auth (matches AgentManageComp / published_list; keeps ASSET_OWNER merge)
  const { agents, isSuccess: hasLoadedAgents } = useAgentList("");

  // Store state
  const currentAgentId = useAgentStore((state) => state.currentAgentId);
  const initialize = useAgentStore((state) => state.initialize);
  const reset = useAgentStore((state) => state.reset);

  // Dropdown open state
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [agentSearch, setAgentSearch] = useState("");
  const requestedAgentIdRef = useRef<number | null>(null);

  // Import wizard state
  const [importWizardVisible, setImportWizardVisible] = useState(false);
  const [importWizardData, setImportWizardData] =
    useState<ImportAgentData | null>(null);
  const [createAgentModalVisible, setCreateAgentModalVisible] = useState(false);

  // Get current selected agent
  const currentAgent = agents.find(
    (agent: Agent) =>
      currentAgentId !== null && String(agent.id) === String(currentAgentId)
  );

  // Handle import agent
  const handleImportAgent = async () => {
    await openImportWizardWithFile({
      onSuccess: (agentData) => {
        setImportWizardData(agentData);
        setImportWizardVisible(true);
      },
      message: message,
      t: t,
      log: log,
    });
  };

  // Handle select agent from dropdown
  const handleSelectAgent = useCallback(
    async (agentId: number | null) => {
      if (agentId === null) return;

      const agent = agents.find((a: Agent) => String(a.id) === String(agentId));
      if (!agent || currentAgentId === Number(agent.id)) return;

      const selectedAgentId = Number(agent.id);
      requestedAgentIdRef.current = selectedAgentId;

      const nextSearchParams = new URLSearchParams(searchParams.toString());
      nextSearchParams.set("agent_id", String(selectedAgentId));
      router.replace(`${pathname}?${nextSearchParams.toString()}`);

      // Clear NEW mark when agent is selected for editing
      if (agent.is_new === true) {
        try {
          const res = await clearAgentNewMark(agent.id);
          if (!res?.success) {
            log.warn("Failed to clear NEW mark on select:", res);
            queryClient.invalidateQueries({ queryKey: ["agents"] });
          }
        } catch (err) {
          log.error("Failed to clear NEW mark on select:", err);
        }
      }

      if (currentAgentId !== null) {
        await waitForAutosave();
      }

      // Load and set agent
      try {
        const result = await searchAgentInfo(selectedAgentId);
        if (requestedAgentIdRef.current !== selectedAgentId) {
          return;
        }
        if (result.success && result.data) {
          initialize(result.data);
        } else {
          message.error(
            result.message || t("agentConfig.agents.detailsLoadFailed")
          );
        }
      } catch (error) {
        log.error("Failed to load agent detail:", error);
        message.error(t("agentConfig.agents.detailsLoadFailed"));
      }
    },
    [
      agents,
      clearAgentNewMark,
      currentAgentId,
      initialize,
      log,
      message,
      pathname,
      queryClient,
      router,
      searchParams,
      t,
      waitForAutosave,
    ]
  );

  useEffect(() => {
    const rawAgentId = searchParams.get("agent_id");
    const parsedAgentId = rawAgentId ? Number(rawAgentId) : null;

    // Keep the selected Agent in sync with the URL and the current user's list.
    // This also prevents an Agent loaded under a previous account from remaining
    // in the store after the account switch clears or invalidates agent_id.
    if (parsedAgentId === null) {
      requestedAgentIdRef.current = null;
      if (currentAgentId !== null) reset();
      return;
    }

    if (!Number.isInteger(parsedAgentId) || parsedAgentId <= 0) {
      requestedAgentIdRef.current = null;
      if (currentAgentId !== null) reset();

      const nextSearchParams = new URLSearchParams(searchParams.toString());
      nextSearchParams.delete("agent_id");
      router.replace(
        nextSearchParams.size > 0
          ? `${pathname}?${nextSearchParams.toString()}`
          : pathname
      );
      return;
    }

    // An empty list is also the query's loading state, so wait for a successful
    // response before treating an Agent as unavailable to the current user.
    if (!hasLoadedAgents) return;

    if (!agents.some((agent: Agent) => Number(agent.id) === parsedAgentId)) {
      requestedAgentIdRef.current = null;
      if (currentAgentId !== null) reset();

      const nextSearchParams = new URLSearchParams(searchParams.toString());
      nextSearchParams.delete("agent_id");
      router.replace(
        nextSearchParams.size > 0
          ? `${pathname}?${nextSearchParams.toString()}`
          : pathname
      );
      return;
    }

    if (requestedAgentIdRef.current === parsedAgentId) {
      return;
    }

    requestedAgentIdRef.current = parsedAgentId;
    if (currentAgentId !== parsedAgentId) {
      void handleSelectAgent(parsedAgentId);
    }
  }, [
    agents,
    currentAgentId,
    handleSelectAgent,
    hasLoadedAgents,
    pathname,
    reset,
    router,
    searchParams,
  ]);

  const filteredAgents = useMemo(() => {
    const query = agentSearch.trim().toLowerCase();
    if (!query) return agents;

    return agents.filter((agent: Agent) =>
      [agent.display_name, agent.name, agent.description].some((value) =>
        String(value || "")
          .toLowerCase()
          .includes(query)
      )
    );
  }, [agentSearch, agents]);

  // Dropdown menu items (only agents)
  const agentMenuItems = filteredAgents.flatMap(
    (agent: Agent, index: number) => {
      const isAvailable = agent.is_available !== false;
      const displayName = agent.display_name || "";
      const name = agent.name || "";

      const agentItem = {
        key: `agent-${agent.id}`,
        label: (
          <div className="py-2">
            <Flex vertical gap={8}>
              {/* Row 1: Name + Status */}
              <div
                className={`font-medium text-base truncate min-w-0 ${!isAvailable ? "text-gray-500" : ""}`}
              >
                <div className="flex justify-between" style={{ gap: 6 }}>
                  <Flex gap={4} align="center">
                    {!isAvailable && (
                      <Tooltip
                        title={(() => {
                          const reasons = agent.unavailable_reasons || [];
                          if (reasons.includes("agent_not_found")) {
                            return t("subAgentPool.tooltip.unavailableAgent");
                          } else if (reasons.includes("tool_unavailable")) {
                            return t("toolPool.tooltip.unavailableTool");
                          } else if (reasons.includes("duplicate_name")) {
                            return t("agent.error.nameExists", { name });
                          } else if (
                            reasons.includes("duplicate_display_name")
                          ) {
                            return t("agent.error.displayNameExists", {
                              displayName,
                            });
                          } else if (reasons.includes("model_unavailable")) {
                            return t("agent.error.modelUnavailable");
                          }
                          return t("subAgentPool.tooltip.unavailableAgent");
                        })()}
                      >
                        <ExclamationCircleOutlined className="text-amber-500 text-sm flex-shrink-0 cursor-pointer" />
                      </Tooltip>
                    )}
                    {agent.is_new && (
                      <Tooltip title={t("space.new", "New imported agent")}>
                        <span className="inline-flex items-center px-1 h-5 bg-amber-50 text-amber-700 rounded-full text-[11px] font-medium border border-amber-200 flex-shrink-0 leading-none">
                          <span className="px-0.5">
                            {t("space.new", "NEW")}
                          </span>
                        </span>
                      </Tooltip>
                    )}
                    {displayName && (
                      <span className="truncate text-sm">{displayName}</span>
                    )}
                  </Flex>
                  <div></div>
                </div>
              </div>
              {/* Row 2: Description */}
              <div
                className={`text-xs truncate min-w-0 ${!isAvailable ? "text-gray-400" : "text-gray-500"}`}
              >
                {agent.description}
              </div>
            </Flex>
          </div>
        ),
        onClick: () => handleSelectAgent(Number(agent.id)),
      };

      // Add divider after each item except the last one
      const divider =
        index < filteredAgents.length - 1
          ? { key: `divider-${agent.id}`, type: "divider" as const }
          : null;

      return divider ? [agentItem, divider] : [agentItem];
    }
  );

  const handleBackToRepository = async () => {
    await waitForAutosave();
    router.push(`/${locale}/agent-space?tab=mine`);
  };

  const handleCreateAgent = async () => {
    await waitForAutosave();
    setCreateAgentModalVisible(true);
  };

  const handleImportComplete = async (agentId: number) => {
    setImportWizardVisible(false);
    setImportWizardData(null);
    await queryClient.invalidateQueries({ queryKey: ["agents"] });

    const result = await searchAgentInfo(agentId);
    if (!result.success || !result.data) {
      message.error(result.message || t("agent.error.fetchAgentList"));
      return;
    }

    initialize({ ...result.data, permission: "EDIT" });
    const nextSearchParams = new URLSearchParams(searchParams.toString());
    nextSearchParams.set("agent_id", String(agentId));
    router.replace(`${pathname}?${nextSearchParams.toString()}`);
  };

  const handleAgentCreated = async ({ agentId }: { agentId: number }) => {
    setCreateAgentModalVisible(false);
    queryClient.invalidateQueries({ queryKey: ["agents"] });
    const result = await searchAgentInfo(agentId);
    if (!result.success || !result.data) {
      message.error(result.message || t("agent.error.fetchAgentList"));
      return;
    }
    initialize({ ...result.data, permission: "EDIT" });
    router.replace(`${pathname}?agent_id=${agentId}`);
    message.success(t("subAgentPool.button.create"));
    onAgentCreated();
  };

  return (
    <>
      <div
        className="w-full h-full px-6 py-2"
        style={{ borderBottom: "1px solid #f0f0f0" }}
      >
        <Row className="h-full" align="middle">
          {/* Left column: Agent Config */}
          <Col xs={12} sm={12} md={12} lg={8} className="flex min-w-0 lg:pr-4">
            <Flex align="center" className="min-w-0 w-full" gap={4}>
              {showBackFromRepository ? (
                <Tooltip title={t("agentRepository.mine.backToRepository")}>
                  <Button
                    type="text"
                    aria-label={t("agentRepository.mine.backToRepository")}
                    className="flex shrink-0 items-center px-2 text-gray-600"
                    icon={<ChevronLeft className="size-4" aria-hidden />}
                    onClick={handleBackToRepository}
                  />
                </Tooltip>
              ) : null}
              <Dropdown
                trigger={["click"]}
                placement="bottomLeft"
                open={dropdownOpen}
                onOpenChange={(open) => {
                  setDropdownOpen(open);
                  if (!open) setAgentSearch("");
                }}
                menu={{
                  items: agentMenuItems,
                }}
                popupRender={(menu) => (
                  <div className="overflow-hidden rounded-lg bg-white shadow-lg">
                    <div className="border-b border-gray-100 py-2">
                      <div className="relative">
                        <Search className="absolute left-2 top-1/2 size-4 -translate-y-1/2 text-gray-400" />
                        <Input
                          autoFocus
                          value={agentSearch}
                          onClick={(event) => event.stopPropagation()}
                          onKeyDown={(event) => event.stopPropagation()}
                          onChange={(event) =>
                            setAgentSearch(event.target.value)
                          }
                          placeholder={t("agentSelector.searchPlaceholder")}
                          allowClear
                          className="pl-7"
                        />
                      </div>
                    </div>
                    <div className="max-h-[420px] overflow-y-auto">
                      {filteredAgents.length > 0 ? (
                        menu
                      ) : (
                        <div className="px-3 py-8 text-center text-sm text-gray-400">
                          {t("agentSelector.noSearchResults")}
                        </div>
                      )}
                    </div>
                  </div>
                )}
                getPopupContainer={(triggerNode) =>
                  triggerNode.parentNode as HTMLElement
                }
                classNames={{ root: "agent-selector-dropdown" }}
                className="min-w-0 flex-1"
                styles={{
                  root: {
                    width: showBackFromRepository
                      ? "calc(100% - 68px)"
                      : "calc(100% - 32px)",
                  },
                }}
              >
                <div className="flex items-center gap-2 py-2 pr-2 cursor-pointer hover:bg-gray-50 rounded-md transition-colors w-full overflow-hidden">
                  <div className="relative w-12 h-12 rounded-lg bg-blue-100 flex items-center justify-center flex-shrink-0">
                    <Bot className="w-8 h-8 text-blue-600" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-lg font-medium text-gray-900 leading-tight mb-2">
                      {currentAgent?.display_name ||
                        currentAgent?.name ||
                        t("agentConfig.agents.selectAgent")}
                    </div>
                    <div className="text-sm text-gray-500 leading-tight truncate">
                      {currentAgent?.description ||
                        t("agentConfig.agents.noAgentSelected")}
                    </div>
                  </div>
                  <ChevronDown className="w-4 h-4 text-gray-400 flex-shrink-0" />
                </div>
              </Dropdown>
            </Flex>
          </Col>
          {/* Right column: Agent Info */}
          <Col
            xs={12}
            sm={12}
            md={12}
            lg={16}
            className="flex justify-end lg:pl-4"
          >
            <Flex
              align="center"
              gap={12}
              wrap="wrap"
              justify="flex-end"
              className="w-full mr-6"
            >
              <Flex align="center" gap={12} wrap="wrap">
                <AgentConfigActions />
                <Flex align="center" gap={8} wrap="wrap" className="ml-4">
                  <Button
                    size="middle"
                    onClick={handleCreateAgent}
                    className="flex items-center gap-1"
                  >
                    <Plus className="w-4 h-4" />
                    <span>{t("agentConfig.button.new")}</span>
                  </Button>
                  <Button
                    size="middle"
                    onClick={handleImportAgent}
                    className="flex items-center gap-1"
                  >
                    <FileInput className="w-4 h-4" />
                    <span>{t("agentConfig.button.import")}</span>
                  </Button>
                </Flex>

                <Button
                  icon={<GitBranch size={16} />}
                  onClick={onToggleVersionManage}
                  type={isVersionManageVisible ? "primary" : "default"}
                >
                  {t("agent.version.manage")}
                </Button>
              </Flex>
            </Flex>
          </Col>
        </Row>
      </div>

      <CreateAgentModal
        open={createAgentModalVisible}
        onCancel={() => setCreateAgentModalVisible(false)}
        onCreated={handleAgentCreated}
      />

      {/* Import Wizard Modal */}
      <AgentImportWizard
        visible={importWizardVisible}
        onCancel={() => {
          setImportWizardVisible(false);
          setImportWizardData(null);
        }}
        initialData={importWizardData}
        onImportComplete={handleImportComplete}
      />
    </>
  );
}
