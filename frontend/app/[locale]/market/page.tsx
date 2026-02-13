"use client";

import React, { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { ShoppingBag, Search, RefreshCw, ChevronLeft, ChevronRight } from "lucide-react";
import { Tabs, Input, Spin, Empty, Pagination, App } from "antd";
import log from "@/lib/logger";

import { useSetupFlow } from "@/hooks/useSetupFlow";
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
import "./MarketContent.css";

/**
 * MarketContent - Agent marketplace page
 * Browse and download pre-built agents from the marketplace
 */
export default function MarketContent() {
  const router = useRouter();
  const { t, i18n } = useTranslation("common");
  const { message } = App.useApp();
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";

  // Use custom hook for common setup flow logic
  const { pageVariants, pageTransition } = useSetupFlow();

  // State management
  const [categories, setCategories] = useState<MarketCategory[]>([]);
  const [agents, setAgents] = useState<MarketAgentListItem[]>([]);
  const [featuredItems, setFeaturedItems] = useState<MarketAgentListItem[]>([]);
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

  // Refs and state for featured card width calculation
  const contentRef = useRef<HTMLDivElement | null>(null);
  const featuredRowRef = useRef<HTMLDivElement | null>(null);
  const [featuredCardWidth, setFeaturedCardWidth] = useState<number | null>(null);

  // Calculate featured card width so it matches grid column width (accounting for gaps)
  useEffect(() => {
    const calc = () => {
      const container = contentRef.current;
      if (!container) return;
      const containerWidth = container.clientWidth;
      const w = window.innerWidth;
      let columns = 4;
      if (w < 768) columns = 1;
      else if (w < 1024) columns = 2;
      else if (w < 1280) columns = 3;
      else ;
      const gap = 16; // tailwind gap-4 == 16px
      const totalGap = gap * (columns - 1);
      const cardW = Math.floor((containerWidth - totalGap) / columns);
      setFeaturedCardWidth(cardW);
    };
    calc();
    window.addEventListener("resize", calc);
    return () => window.removeEventListener("resize", calc);
  }, [featuredItems]);

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
        lang: isZh ? "zh" : "en",
      };

      if (currentCategory !== "all") {
        params.category = currentCategory;
      }

      if (searchKeyword.trim()) {
        params.search = searchKeyword.trim();
      }

      // Backend returns all items in pagination, with is_featured flag
      const data = await marketService.fetchMarketAgentList(params);
      const allItems = data.items || [];

      // Separate featured and regular items
      const featured = allItems.filter((a) => a.is_featured);
      const items = allItems.filter((a) => !a.is_featured);

      setFeaturedItems(featured);
      setAgents(items);
      // Use pagination total as is - it represents total items across both featured and regular
      setTotalAgents(data.pagination?.total || 0);
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
      message.error(
        t("market.error.loadAgents", "Failed to load agent details")
      );
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
   * Handle install complete - Shows success message with navigation to agent space
   */
  const handleInstallComplete = () => {
    setInstallModalVisible(false);
    setInstallAgent(null);
    
    // Show success message with clickable link to agent space
    message.success({
      content: (
        <span>
          {t("market.install.success.viewSpace.prefix")}
          <button
            onClick={() => router.push("/space")}
            className="text-blue-600 dark:text-blue-400 font-bold hover:text-blue-700 dark:hover:text-blue-300 cursor-pointer transition-colors"
          >
            {t("market.install.success.viewSpace.link")}
          </button>
          {t("market.install.success.viewSpace.suffix")}
        </span>
      ),
      duration: 4,
    });
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
      <div className="w-full h-full">
        <motion.div
          initial="initial"
          animate="in"
          exit="out"
          variants={pageVariants}
          transition={pageTransition}
          className="w-full h-full overflow-auto"
        >
          <div className="w-full px-4 md:px-8 lg:px-16 py-8">
            <div ref={contentRef} className="max-w-7xl mx-auto">
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
                    ) : agents.length === 0 && featuredItems.length === 0 ? (
                      <Empty
                        description={t(
                          "market.noAgents",
                          "No agents found in this category"
                        )}
                        className="py-16"
                      />
                    ) : (
                      <>
                        {/* Featured row per category (show only if there are featured items) */}
                        {featuredItems.length > 0 && (
                          <div className="mb-6">
                            <div className="flex items-center justify-between mb-5">
                              <h2 className="text-2xl font-bold">
                                {t("market.featuredTitle")}
                              </h2>
                              <div className="hidden md:flex items-center gap-2">
                                <button
                                  aria-label="Prev featured"
                                  onClick={() => {
                                    const el = document.getElementById("featured-row");
                                    if (el) el.scrollBy({ left: -Math.floor(el.clientWidth * 0.9), behavior: "smooth" });
                                  }}
                                  className="px-2 py-1 hover:opacity-90"
                                  style={{ background: "transparent" }}
                                >
                                  <ChevronLeft className="w-6 h-6 text-slate-500" />
                                </button>
                                <button
                                  aria-label="Next featured"
                                  onClick={() => {
                                    const el = document.getElementById("featured-row");
                                    if (el) el.scrollBy({ left: Math.floor(el.clientWidth * 0.9), behavior: "smooth" });
                                  }}
                                  className="px-2 py-1 hover:opacity-90"
                                  style={{ background: "transparent" }}
                                >
                                  <ChevronRight className="w-6 h-6 text-slate-500" />
                                </button>
                              </div>
                            </div>
                            <div
                              id="featured-row"
                              ref={featuredRowRef}
                              className={`flex gap-4 overflow-x-auto noScrollbar pt-2 pb-2`}
                            >
                              {featuredItems.map((agent, index) => (
                                <div
                                  key={`featured-${agent.id}`}
                                  className="flex-shrink-0 h-full"
                                  style={featuredCardWidth ? { width: `${featuredCardWidth}px` } : undefined}
                                >
                                  <AgentMarketCard
                                    agent={agent}
                                    onDownload={handleDownload}
                                    onViewDetails={handleViewDetails}
                                    variant="featured"
                                  />
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Separator between featured and main list (only when both exist) */}
                        {featuredItems.length > 0 && agents.length > 0 && (
                          <div className="mt-4 mb-8">
                            <div className="w-full h-[0.5px] bg-slate-200 dark:bg-slate-700 rounded" />
                          </div>
                        )}

                        {agents.length > 0 && (
                          <>
                            <div className="mt-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 pb-8">
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
                    business_logic_model_id: installAgent.business_logic_model_id,
                    business_logic_model_name: installAgent.business_logic_model_name,
                  } as ImportAgentData)
                : null
            }
            onImportComplete={handleInstallComplete}
            title={undefined} // Use default title
            agentDisplayName={installAgent?.display_name}
            agentDescription={installAgent?.description}
          />
        </motion.div>
      </div>
    </>
  );
}
