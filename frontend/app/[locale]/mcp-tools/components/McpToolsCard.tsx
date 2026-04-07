"use client";

import React from "react";
import { motion } from "framer-motion";
import { Info, Tag, Star } from "lucide-react";
import { McpToolsItem } from "@/types/mcpTools";
import { useTranslation } from "react-i18next";

interface McpToolsCardProps {
  tool: McpToolsItem;
  onViewDetails: (tool: McpToolsItem) => void;
  variant?: "featured" | "default";
}

/**
 * MCP Tools card component
 * Displays tool information in market view
 */
export function McpToolsCard({
  tool,
  onViewDetails,
  variant = "default",
}: McpToolsCardProps) {
  const { t, i18n } = useTranslation("common");
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";

  const handleCardClick = () => {
    onViewDetails(tool);
  };

  const categoryIcon = tool.category.icon;

  return (
    <motion.div
      whileHover={{
        y: -4,
        boxShadow: "0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05)",
      }}
      transition={{ type: "spring", stiffness: 300, damping: 25 }}
      onClick={handleCardClick}
      className="group z-10 hover:z-0 h-full min-h-[320px] rounded-lg border transition-all duration-300 overflow-visible flex flex-col cursor-pointer relative bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 hover:border-amber-300 dark:hover:border-amber-600 hover:shadow-lg"
    >
      {variant === "featured" && (
        <div
          aria-hidden
          className="absolute inset-0 rounded-lg pointer-events-none"
          style={{
            background: "linear-gradient(180deg, rgba(245,158,11,0.06), rgba(249,115,22,0.04))",
            zIndex: 0,
          }}
        />
      )}

      {/* Card header with category */}
      <div className="px-4 pt-4 pb-3 border-b border-slate-100 dark:border-slate-700">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-2xl">{categoryIcon}</span>
            <span className="text-xs font-medium text-amber-600 dark:text-amber-400">
              {isZh ? tool.category.display_name_zh : tool.category.display_name}
            </span>
          </div>
          <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
            <Star className="h-3.5 w-3.5 text-amber-500" />
            <span>{tool.github_stars.toLocaleString()}</span>
          </div>
        </div>

        <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-100 line-clamp-1 group-hover:text-amber-600 dark:group-hover:text-amber-400 transition-colors">
          {tool.display_name}
        </h3>
        <div className="h-5 flex items-center">
          {tool.author ? (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t("mcpTools.by", { defaultValue: "By {{author}}", author: tool.author })}
            </p>
          ) : null}
        </div>
      </div>

      {/* Card body */}
      <div className="flex-1 px-4 py-3 flex flex-col gap-3 relative z-10 pb-20 min-h-[120px]">
        {/* Description */}
        <p className="text-sm text-slate-600 dark:text-slate-300 line-clamp-3 flex-1">
          {isZh ? tool.description_zh : tool.description}
        </p>

        {/* Tags - always show container for consistent height */}
        <div className="min-h-[24px]">
          {tool.tags && tool.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 max-h-6 overflow-hidden">
              {tool.tags.slice(0, 3).map((tag) => (
                <span
                  key={tag.id}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300"
                >
                  <Tag className="h-3 w-3" />
                  {tag.display_name}
                </span>
              ))}
              {tool.tags.length > 3 && (
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300">
                  +{tool.tags.length - 3}
                </span>
              )}
            </div>
          )}
        </div>

        {/* Source repo */}
        <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
          <Star className="h-3.5 w-3.5" />
          <span>{tool.source_repo}</span>
        </div>
      </div>

      {/* Card footer - pinned to bottom to keep all cards aligned */}
      <div className="absolute left-0 right-0 bottom-0 px-4 py-3 border-t border-slate-100 dark:border-slate-700 bg-transparent z-10">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onViewDetails(tool);
          }}
          className="w-full px-4 py-2 rounded-md bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white text-sm font-medium transition-all duration-300 flex items-center justify-center gap-2"
        >
          <Info className="h-4 w-4" />
          {t("mcpTools.viewDetails", "View Details")}
        </button>
      </div>
    </motion.div>
  );
}
