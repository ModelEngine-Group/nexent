"use client";

import React, { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { ShoppingBag, Search, RefreshCw } from "lucide-react";
import { Tabs, Input, Spin, Empty, Pagination, App } from "antd";
import log from "@/lib/logger";

import { useSetupFlow } from "@/hooks/useSetupFlow";
import { ConnectionStatus } from "@/const/modelConfig";
import {
  MarketAgentListItem,
  MarketCategory,
  MarketAgentListParams,
  MarketAgentDetail,
} from "@/types/market";
import marketService, { MarketApiError } from "@/services/marketService";
import { AgentMarketCard } from "./components/AgentMarketCard";
import MarketAgentDetailModal from "./components/MarketAgentDetailModal";
import AgentImportWizard from "@/components/agent/AgentImportWizard";
import { ImportAgentData } from "@/hooks/useAgentImport";
import MarketErrorState from "./components/MarketErrorState";

interface MarketContentProps {
  /** Connection status */
  connectionStatus?: ConnectionStatus;
  /** Is checking connection */
  isCheckingConnection?: boolean;
  /** Check connection callback */
  onCheckConnection?: () => void;
  /** Callback to expose connection status */
  onConnectionStatusChange?: (status: ConnectionStatus) => void;
}

/**
 * MarketContent - Agent marketplace page
 * Browse and download pre-built agents from the marketplace
 */
export default function MarketContent({
  connectionStatus: externalConnectionStatus,
  isCheckingConnection: externalIsCheckingConnection,
  onCheckConnection: externalOnCheckConnection,
  onConnectionStatusChange,
}: MarketContentProps) {
  const { t, i18n } = useTranslation("common");
  const { message } = App.useApp();
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";

  // Use custom hook for common setup flow logic
  const { canAccessProtectedData, pageVariants, pageTransition } = useSetupFlow(
    {
    requireAdmin: false, // Market accessible to all users
    externalConnectionStatus,
    externalIsCheckingConnection,
    onCheckConnection: externalOnCheckConnection,
    onConnectionStatusChange,
    }
  );

  // State management
  const [categories, setCategories] = useState<MarketCategory[]>([]);
  const [agents, setAgents] = useState<MarketAgentListItem[]>([]);
  const [isLoadingCategories, setIsLoadingCategories] = useState(true);
  const [isLoadingAgents, setIsLoadingAgents] = useState(false);
  const [currentCategory, setCurrentCategory] = useState<string>("all");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize] = useState(20);
  const [totalAgents, setTotalAgents] = useState(0);
  const [errorType, setErrorType] = useState<
    "timeout" | "network" | "server" | "unknown" | null
  >(null);

  // Detail modal state
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<MarketAgentDetail | null>(
    null
  );
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);

  // Install modal state
  const [installModalVisible, setInstallModalVisible] = useState(false);
  const [installAgent, setInstallAgent] = useState<MarketAgentDetail | null>(
    null
  );

  // Load categories and initial agents on mount
  useEffect(() => {
    loadCategories();
    loadAgents(); // Auto-refresh on page load
  }, []);

  // Load agents when category, page, or search changes (but not on initial mount)
  useEffect(() => {
    loadAgents();
  }, [currentCategory, currentPage, searchKeyword]);

  /**
   * Load categories from market
   */
  const loadCategories = async () => {
    setIsLoadingCategories(true);
    setErrorType(null);
    try {
      const data = await marketService.fetchMarketCategories();
      setCategories(data);
    } catch (error) {
      log.error("Failed to load market categories:", error);
      
      if (error instanceof MarketApiError) {
        setErrorType(error.type);
      } else {
        setErrorType("unknown");
      }
    } finally {
      setIsLoadingCategories(false);
    }
  };

  /**
   * Load agents from market
   */
  const loadAgents = async () => {
    setIsLoadingAgents(true);
    setErrorType(null);
    try {
      const params: MarketAgentListParams = {
        page: currentPage,
        page_size: pageSize,
      };

      if (currentCategory !== "all") {
        params.category = currentCategory;
      }

      if (searchKeyword.trim()) {
        params.search = searchKeyword.trim();
      }

      const data = await marketService.fetchMarketAgentList(params);
      setAgents(data.items);
      setTotalAgents(data.pagination.total);
    } catch (error) {
      log.error("Failed to load market agents:", error);
      
      if (error instanceof MarketApiError) {
        setErrorType(error.type);
      } else {
        setErrorType("unknown");
      }
      
      setAgents([]);
      setTotalAgents(0);
    } finally {
      setIsLoadingAgents(false);
    }
  };

  /**
   * Handle category tab change
   */
  const handleCategoryChange = (key: string) => {
    setCurrentCategory(key);
    setCurrentPage(1);
  };

  /**
   * Handle search
   */
  const handleSearch = (value: string) => {
    setSearchKeyword(value);
    setCurrentPage(1);
  };

  /**
   * Handle page change
   */
  const handlePageChange = (page: number) => {
    setCurrentPage(page);
  };

  /**
   * Handle view agent details
   */
  const handleViewDetails = async (agent: MarketAgentListItem) => {
    setDetailModalVisible(true);
    setIsLoadingDetail(true);
    setSelectedAgent(null);

    try {
      const agentDetail = await marketService.fetchMarketAgentDetail(
        agent.agent_id
      );
      setSelectedAgent(agentDetail);
    } catch (error) {
      log.error("Failed to load agent detail:", error);
      message.error(t("market.error.loadAgents", "Failed to load agent details"));
      setDetailModalVisible(false);
    } finally {
      setIsLoadingDetail(false);
    }
  };

  /**
   * Handle close detail modal
   */
  const handleCloseDetail = () => {
    setDetailModalVisible(false);
    setSelectedAgent(null);
  };

  /**
   * Handle agent download - Opens install wizard
   */
  const handleDownload = async (agent: MarketAgentListItem) => {
    try {
      setIsLoadingDetail(true);
      // Fetch full agent details for installation
      const agentDetail = await marketService.fetchMarketAgentDetail(
        agent.agent_id
      );
      setInstallAgent(agentDetail);
      setInstallModalVisible(true);
    } catch (error) {
      log.error("Failed to load agent details for installation:", error);
      message.error(
        t("market.error.fetchDetailFailed", "Failed to load agent details")
      );
    } finally {
      setIsLoadingDetail(false);
    }
  };

  /**
   * Handle install complete
   */
  const handleInstallComplete = () => {
    setInstallModalVisible(false);
    setInstallAgent(null);
    // Optionally reload agents or show success message
    message.success(
      t("market.install.success", "Agent installed successfully!")
    );
  };

  /**
   * Handle install cancel
   */
  const handleInstallCancel = () => {
    setInstallModalVisible(false);
    setInstallAgent(null);
  };

  /**
   * Render tab items
   */
  const tabItems = [
    {
      key: "all",
      label: t("market.category.all", "All"),
    },
    ...categories.map((cat) => ({
      key: cat.name,
      label: isZh ? cat.display_name_zh : cat.display_name,
    })),
  ];

  return (
    <>
      {canAccessProtectedData ? (
        <motion.div
          initial="initial"
          animate="in"
          exit="out"
          variants={pageVariants}
          transition={pageTransition}
          className="w-full h-full overflow-auto"
        >
          <div className="w-full px-4 md:px-8 lg:px-16 py-8">
            <div className="max-w-7xl mx-auto">
              {/* Page header */}
              <div className="flex items-center justify-between mb-6">
            <motion.div
                  initial={{ opacity: 0, y: -20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5 }}
                >
                  <div className="flex items-center gap-3">
                    <div className="w-12 h-12 rounded-full bg-gradient-to-br from-purple-500 to-indigo-500 flex items-center justify-center">
                      <ShoppingBag className="h-6 w-6 text-white" />
                    </div>
                    <div>
                      <h1 className="text-3xl font-bold text-purple-600 dark:text-purple-500">
                        {t("market.title", "Agent Market")}
                      </h1>
                      <p className="text-slate-600 dark:text-slate-300 mt-1">
                        {t(
                          "market.description",
                          "Discover and download pre-built intelligent agents"
                        )}
                      </p>
                    </div>
                  </div>
            </motion.div>

                {/* Refresh button */}
                <motion.div
                  initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5, delay: 0.1 }}
                >
                  <button
                    onClick={loadAgents}
                    disabled={isLoadingAgents}
                    className="p-2 rounded-md hover:bg-purple-50 dark:hover:bg-purple-900/20 text-slate-600 dark:text-slate-300 hover:text-purple-600 dark:hover:text-purple-400 transition-colors disabled:opacity-50"
                    title={t("common.refresh", "Refresh")}
                  >
                    <RefreshCw
                      className={`h-5 w-5 ${isLoadingAgents ? "animate-spin" : ""}`}
                    />
                  </button>
                </motion.div>
              </div>

              {/* Only show search and content if no error */}
              {!errorType ? (
                <>
                  {/* Search bar */}
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.5, delay: 0.2 }}
                    className="mb-6"
                  >
                    <Input
                      size="large"
                      placeholder={t(
                        "market.searchPlaceholder",
                        "Search agents by name or description..."
                      )}
                      prefix={<Search className="h-4 w-4 text-slate-400" />}
                      value={searchKeyword}
                      onChange={(e) => handleSearch(e.target.value)}
                      allowClear
                      className="max-w-md"
                    />
                  </motion.div>
                  {/* Category tabs */}
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.5, delay: 0.3 }}
                    className="mb-6"
                  >
                    {isLoadingCategories ? (
                      <div className="flex justify-center py-8">
                        <Spin size="large" />
                      </div>
                    ) : (
                      <Tabs
                        activeKey={currentCategory}
                        items={tabItems}
                        onChange={handleCategoryChange}
                        size="large"
                      />
                    )}
                  </motion.div>

                  {/* Agents grid */}
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.5, delay: 0.4 }}
                  >
                    {isLoadingAgents ? (
                      <div className="flex justify-center py-16">
                        <Spin size="large" />
                      </div>
                    ) : agents.length === 0 ? (
                      <Empty
                        description={t(
                          "market.noAgents",
                          "No agents found in this category"
                        )}
                        className="py-16"
                      />
                    ) : (
                      <>
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 pb-8">
                          {agents.map((agent, index) => (
                            <motion.div
                              key={agent.id}
                              initial={{ opacity: 0, scale: 0.9 }}
                              animate={{ opacity: 1, scale: 1 }}
                              transition={{
                                duration: 0.3,
                                delay: 0.05 * index,
                              }}
                              className="h-full"
                            >
                              <AgentMarketCard
                                agent={agent}
                                onDownload={handleDownload}
                                onViewDetails={handleViewDetails}
                              />
                            </motion.div>
                          ))}
                        </div>

                        {/* Pagination */}
                        {totalAgents > pageSize && (
                          <div className="flex justify-center mt-8">
                            <Pagination
                              current={currentPage}
                              total={totalAgents}
                              pageSize={pageSize}
                              onChange={handlePageChange}
                              showSizeChanger={false}
                              showTotal={(total) =>
                                t("market.totalAgents", {
                                  defaultValue: "Total {{total}} agents",
                                  total,
                                })
                              }
                            />
                          </div>
                        )}
                      </>
                    )}
                  </motion.div>
                </>
              ) : (
                /* Error state - only show when there's an error */
                !isLoadingAgents &&
                !isLoadingCategories && <MarketErrorState type={errorType} />
              )}
            </div>
          </div>

          {/* Agent Detail Modal */}
          <MarketAgentDetailModal
            visible={detailModalVisible}
            onClose={handleCloseDetail}
            agentDetails={selectedAgent}
            loading={isLoadingDetail}
          />

          {/* Agent Install Modal */}
          <AgentImportWizard
            visible={installModalVisible}
            onCancel={handleInstallCancel}
            initialData={
              installAgent?.agent_json
                ? ({
                    agent_id: installAgent.agent_id,
                    agent_info: installAgent.agent_json.agent_info,
                    mcp_info: installAgent.agent_json.mcp_info,
                  } as ImportAgentData)
                : null
            }
            onImportComplete={handleInstallComplete}
            title={undefined} // Use default title
            agentDisplayName={installAgent?.display_name}
            agentDescription={installAgent?.description}
          />
        </motion.div>
      ) : null}
    </>
  );
}

