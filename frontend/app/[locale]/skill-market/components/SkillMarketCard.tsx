"use client";

import React from "react";
import { motion } from "framer-motion";
import { Download, Tag, Star } from "lucide-react";
import { SkillMarketItem } from "@/types/skillMarket";
import { useTranslation } from "react-i18next";

interface SkillMarketCardProps {
  skill: SkillMarketItem;
  onViewDetails: (skill: SkillMarketItem) => void;
  variant?: "featured" | "default";
}

/**
 * Skill market card component
 * Displays skill information in market view
 */
export function SkillMarketCard({
  skill,
  onViewDetails,
  variant = "default",
}: SkillMarketCardProps) {
  const { t, i18n } = useTranslation("common");
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";

  const handleCardClick = () => {
    onViewDetails(skill);
  };

  const categoryIcon = skill.category.icon;

  return (
    <motion.div
      whileHover={{
        y: -4,
        boxShadow: "0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05)",
      }}
      transition={{ type: "spring", stiffness: 300, damping: 25 }}
      onClick={handleCardClick}
      className="group z-10 hover:z-0 h-full min-h-[320px] rounded-lg border transition-all duration-300 overflow-visible flex flex-col cursor-pointer relative bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 hover:border-blue-300 dark:hover:border-blue-600 hover:shadow-lg"
    >
      {variant === "featured" && (
        <div
          aria-hidden
          className="absolute inset-0 rounded-lg pointer-events-none"
          style={{
            background: "linear-gradient(180deg, rgba(59,130,246,0.06), rgba(99,102,241,0.04))",
            zIndex: 0,
          }}
        />
      )}

      {/* Card header with category */}
      <div className="px-4 pt-4 pb-3 border-b border-slate-100 dark:border-slate-700">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-2xl">{categoryIcon}</span>
            <span className="text-xs font-medium text-blue-600 dark:text-blue-400">
              {isZh ? skill.category.display_name_zh : skill.category.display_name}
            </span>
          </div>
          <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
            <Download className="h-3.5 w-3.5" />
            <span>{skill.download_count}</span>
          </div>
        </div>

        <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-100 line-clamp-1 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
          {isZh ? skill.display_name_zh : skill.display_name}
        </h3>
        <div className="h-5 flex items-center">
          {skill.author ? (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t("skillMarket.by", { defaultValue: "By {{author}}", author: skill.author })}
            </p>
          ) : null}
        </div>
      </div>

      {/* Card body */}
      <div className="flex-1 px-4 py-3 flex flex-col gap-3 relative z-10 pb-20 min-h-[120px]">
        {/* Description */}
        <p className="text-sm text-slate-600 dark:text-slate-300 line-clamp-3 flex-1">
          {isZh ? skill.description_zh : skill.description}
        </p>

        {/* Tags - always show container for consistent height */}
        <div className="min-h-[24px]">
          {skill.tags && skill.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 max-h-6 overflow-hidden">
              {skill.tags.slice(0, 3).map((tag) => (
                <span
                  key={tag.id}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300"
                >
                  <Tag className="h-3 w-3" />
                  {tag.display_name}
                </span>
              ))}
              {skill.tags.length > 3 && (
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300">
                  +{skill.tags.length - 3}
                </span>
              )}
            </div>
          )}
        </div>

        {/* Source repo */}
        <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
          <Star className="h-3.5 w-3.5" />
          <span>{skill.source_repo}</span>
        </div>
      </div>

      {/* Card footer - pinned to bottom to keep all cards aligned */}
      <div className="absolute left-0 right-0 bottom-0 px-4 py-3 border-t border-slate-100 dark:border-slate-700 bg-transparent z-10">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onViewDetails(skill);
          }}
          className="w-full px-4 py-2 rounded-md bg-gradient-to-r from-blue-500 to-indigo-500 hover:from-blue-600 hover:to-indigo-600 text-white text-sm font-medium transition-all duration-300 flex items-center justify-center gap-2"
        >
          <Download className="h-4 w-4" />
          {t("skillMarket.viewDetails", "View Details")}
        </button>
      </div>
    </motion.div>
  );
}
