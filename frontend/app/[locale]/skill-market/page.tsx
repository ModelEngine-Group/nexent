"use client";

import React, { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { ShoppingBag, Search, ChevronLeft, ChevronRight } from "lucide-react";
import { Tabs, Input, Empty } from "antd";
import log from "@/lib/logger";

import { useSetupFlow } from "@/hooks/useSetupFlow";
import { SkillMarketItem, SkillMarketDetail } from "@/types/skillMarket";
import {
  SKILL_CATEGORIES,
  STATIC_SKILL_MARKET_DATA,
  getSkillsByCategory,
  searchSkills,
} from "@/data/skillMarketData";
import { SkillMarketCard } from "./components/SkillMarketCard";
import SkillMarketDetailModal from "./components/SkillMarketDetailModal";
import "./SkillMarketContent.css";

/**
 * SkillMarketContent - Skill marketplace page
 * Browse and view pre-built skills from the marketplace
 */
export default function SkillMarketContent() {
  const { t, i18n } = useTranslation("common");
  const { pageVariants, pageTransition } = useSetupFlow();
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";

  // State management
  const [skills, setSkills] = useState<SkillMarketItem[]>([]);
  const [featuredItems, setFeaturedItems] = useState<SkillMarketItem[]>([]);
  const [currentCategory, setCurrentCategory] = useState<string>("all");
  const [searchKeyword, setSearchKeyword] = useState("");

  // Detail modal state
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedSkill, setSelectedSkill] = useState<SkillMarketDetail | null>(
    null
  );

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
      const gap = 16;
      const totalGap = gap * (columns - 1);
      const cardW = Math.floor((containerWidth - totalGap) / columns);
      setFeaturedCardWidth(cardW);
    };
    calc();
    window.addEventListener("resize", calc);
    return () => window.removeEventListener("resize", calc);
  }, [featuredItems]);

  // Load skills when category or search changes
  useEffect(() => {
    loadSkills();
  }, [currentCategory, searchKeyword]);

  /**
   * Load skills based on current category and search
   */
  const loadSkills = () => {
    try {
      let items: SkillMarketItem[];

      if (searchKeyword.trim()) {
        items = searchSkills(searchKeyword.trim());
      } else {
        items = getSkillsByCategory(currentCategory);
      }

      // Separate featured and regular items
      // Sort: medical featured first, then by download count
      const featured = items.filter((s) => s.is_featured).sort((a, b) => {
        const aIsMedical = a.category.name === "medical";
        const bIsMedical = b.category.name === "medical";
        if (aIsMedical && !bIsMedical) return -1;
        if (!aIsMedical && bIsMedical) return 1;
        return b.download_count - a.download_count;
      });
      const regular = items.filter((s) => !s.is_featured);

      setFeaturedItems(featured);
      setSkills(regular);
    } catch (error) {
      log.error("Failed to load skills:", error);
      setSkills([]);
      setFeaturedItems([]);
    }
  };

  /**
   * Handle category tab change
   */
  const handleCategoryChange = (key: string) => {
    setCurrentCategory(key);
    setSearchKeyword("");
  };

  /**
   * Handle search
   */
  const handleSearch = (value: string) => {
    setSearchKeyword(value);
  };

  /**
   * Handle view skill details
   */
  const handleViewDetails = (skill: SkillMarketItem) => {
    setSelectedSkill(skill as SkillMarketDetail);
    setDetailModalVisible(true);
  };

  /**
   * Handle close detail modal
   */
  const handleCloseDetail = () => {
    setDetailModalVisible(false);
    setSelectedSkill(null);
  };

  /**
   * Render tab items
   */
  const tabItems = [
    {
      key: "all",
      label: t("skillMarket.category.all", "All"),
    },
    ...SKILL_CATEGORIES.map((cat) => ({
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
                    <div className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-500 to-indigo-500 flex items-center justify-center">
                      <ShoppingBag className="h-6 w-6 text-white" />
                    </div>
                    <div>
                      <h1 className="text-3xl font-bold text-blue-600 dark:text-blue-500">
                        {t("skillMarket.title", "Skill Market")}
                      </h1>
                      <p className="text-slate-600 dark:text-slate-300 mt-1">
                        {t(
                          "skillMarket.description",
                          "Discover and learn from pre-built intelligent skills"
                        )}
                      </p>
                    </div>
                  </div>
                </motion.div>
              </div>

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
                    "skillMarket.searchPlaceholder",
                    "Search skills by name or description..."
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
                <Tabs
                  activeKey={currentCategory}
                  items={tabItems}
                  onChange={handleCategoryChange}
                  size="large"
                />
              </motion.div>

              {/* Skills grid */}
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.5, delay: 0.4 }}
              >
                {skills.length === 0 && featuredItems.length === 0 ? (
                  <Empty
                    description={t(
                      "skillMarket.noSkills",
                      "No skills found in this category"
                    )}
                    className="py-16"
                  />
                ) : (
                  <>
                    {/* Featured row */}
                    {featuredItems.length > 0 && (
                      <div className="mb-6">
                        <div className="flex items-center justify-between mb-5">
                          <h2 className="text-2xl font-bold">
                            {t("skillMarket.featuredTitle", "Featured Skills")}
                          </h2>
                          <div className="hidden md:flex items-center gap-2">
                            <button
                              aria-label="Prev featured"
                              onClick={() => {
                                const el = document.getElementById("skill-featured-row");
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
                                const el = document.getElementById("skill-featured-row");
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
                          id="skill-featured-row"
                          ref={featuredRowRef}
                          className="flex gap-4 overflow-x-auto skill-market-noScrollbar pt-2 pb-2"
                        >
                          {featuredItems.map((skill) => (
                            <div
                              key={`featured-${skill.id}`}
                              className="flex-shrink-0 h-full"
                              style={featuredCardWidth ? { width: `${featuredCardWidth}px` } : undefined}
                            >
                              <SkillMarketCard
                                skill={skill}
                                onViewDetails={handleViewDetails}
                                variant="featured"
                              />
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Separator between featured and main list */}
                    {featuredItems.length > 0 && skills.length > 0 && (
                      <div className="mt-4 mb-8">
                        <div className="w-full h-[0.5px] bg-slate-200 dark:bg-slate-700 rounded" />
                      </div>
                    )}

                    {skills.length > 0 && (
                      <div className="mt-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 pb-8">
                        {skills.map((skill, index) => (
                          <motion.div
                            key={skill.id}
                            initial={{ opacity: 0, scale: 0.9 }}
                            animate={{ opacity: 1, scale: 1 }}
                            transition={{
                              duration: 0.3,
                              delay: 0.05 * index,
                            }}
                            className="h-full"
                          >
                            <SkillMarketCard
                              skill={skill}
                              onViewDetails={handleViewDetails}
                            />
                          </motion.div>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </motion.div>
            </div>
          </div>

          {/* Skill Detail Modal */}
          <SkillMarketDetailModal
            visible={detailModalVisible}
            onClose={handleCloseDetail}
            skillDetails={selectedSkill}
          />
        </motion.div>
      </div>
    </>
  );
}
