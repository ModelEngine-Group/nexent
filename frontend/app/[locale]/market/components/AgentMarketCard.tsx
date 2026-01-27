"use client";

import React from "react";
import { motion } from "framer-motion";
import { Download, Tag, Wrench } from "lucide-react";
import { MarketAgentListItem } from "@/types/market";
import { useTranslation } from "react-i18next";
import { getGenericLabel } from "@/lib/agentLabelMapper";
import { getCategoryIcon } from "@/const/marketConfig";

interface AgentMarketCardProps {
  agent: MarketAgentListItem;
  onDownload: (agent: MarketAgentListItem) => void;
  onViewDetails: (agent: MarketAgentListItem) => void;
}

/**
 * Market agent card component
 * Displays agent information in market view
 */
export function AgentMarketCard({
  agent,
  onDownload,
  onViewDetails,
}: AgentMarketCardProps) {
  const { t, i18n } = useTranslation("common");
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";

  const handleDownload = (e: React.MouseEvent) => {
    e.stopPropagation();
    onDownload(agent);
  };

  const handleCardClick = () => {
    onViewDetails(agent);
  };

  // Get category icon: prefer API icon, then fallback to default mapping by name
  const categoryIcon = agent.category
    ? agent.category.icon || getCategoryIcon(agent.category.name)
    : "📦";

  return (
    <motion.div
      whileHover={{ y: -4 }}
      onClick={handleCardClick}
      className="group h-full bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 hover:border-purple-300 dark:hover:border-purple-600 hover:shadow-lg transition-all duration-300 overflow-hidden flex flex-col cursor-pointer"
    >
      {/* Card header with category */}
      <div className="px-4 pt-4 pb-3 border-b border-slate-100 dark:border-slate-700">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-2xl">
              {categoryIcon}
            </span>
            <span className="text-xs font-medium text-purple-600 dark:text-purple-400">
              {agent.category
                ? isZh
                  ? agent.category.display_name_zh
                  : agent.category.display_name
                : t("market.category.other", "Other")}
            </span>
          </div>
          <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
            <Download className="h-3.5 w-3.5" />
            <span>{agent.download_count}</span>
          </div>
        </div>

        <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-100 line-clamp-1 group-hover:text-purple-600 dark:group-hover:text-purple-400 transition-colors">
          {agent.display_name}
        </h3>
        {agent.author ? (
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            {t("market.by", { defaultValue: "By {{author}}", author: agent.author })}
          </p>
        ) : (
          <div className="h-5" aria-hidden />
        )}
      </div>

      {/* Card body */}
      <div className="flex-1 px-4 py-3 flex flex-col gap-3">
        {/* Description */}
        <p className="text-sm text-slate-600 dark:text-slate-300 line-clamp-3 flex-1">
          {agent.description}
        </p>

        {/* Tags */}
        {agent.tags && agent.tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {agent.tags.slice(0, 3).map((tag) => (
              <span
                key={tag.id}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300"
              >
                <Tag className="h-3 w-3" />
                {getGenericLabel(tag.display_name, t)}
              </span>
            ))}
            {agent.tags.length > 3 && (
              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300">
                +{agent.tags.length - 3}
              </span>
            )}
          </div>
        )}

        {/* Tool count */}
        <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
          <Wrench className="h-3.5 w-3.5" />
          <span>
            {agent.tool_count} {t("market.tools", "tools")}
          </span>
        </div>
      </div>

      {/* Card footer */}
      <div className="px-4 py-3 border-t border-slate-100 dark:border-slate-700">
        <button
          onClick={handleDownload}
          className="w-full px-4 py-2 rounded-md bg-gradient-to-r from-purple-500 to-indigo-500 hover:from-purple-600 hover:to-indigo-600 text-white text-sm font-medium transition-all duration-300 flex items-center justify-center gap-2 group-hover:shadow-md"
        >
          <Download className="h-4 w-4" />
          {t("market.download", "Download")}
        </button>
      </div>
    </motion.div>
  );
}

