"use client";

import React from "react";
import { motion } from "framer-motion";
import { Download, Tag, Wrench } from "lucide-react";
import { useTranslation } from "react-i18next";
import { OfficialBadge } from "./OfficialBadge";

export interface SkillMarketCardData {
  id: number;
  name: string;
  display_name: string;
  description: string;
  author: string;
  source: "official" | "community";
  category?: { name: string; display_name: string; display_name_zh: string };
  tags?: { id: string; display_name: string }[];
  usage_count: number;
  tool_count: number;
}

interface SkillMarketCardProps {
  skill: SkillMarketCardData;
  onDownload?: (skill: SkillMarketCardData) => void;
  onViewDetails?: (skill: SkillMarketCardData) => void;
  index?: number;
}

/**
 * SkillMarketCard - Skill card for unified market page
 * Uses Teal color encoding to distinguish from Agent cards
 */
export function SkillMarketCard({
  skill,
  onDownload,
  onViewDetails,
  index = 0,
}: SkillMarketCardProps) {
  const { t, i18n } = useTranslation("common");
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";

  const handleDownload = (e: React.MouseEvent) => {
    e.stopPropagation();
    onDownload?.(skill);
  };

  const handleCardClick = () => {
    onViewDetails?.(skill);
  };

  const categoryLabel = skill.category
    ? isZh
      ? skill.category.display_name_zh
      : skill.category.display_name
    : t("market.category.other", "Other");

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={{ duration: 0.3, delay: 0.05 * index }}
      whileHover={{
        y: -4,
        boxShadow: "0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05)",
      }}
      onClick={handleCardClick}
      className="group h-full min-h-[280px] rounded-lg border transition-all duration-300 overflow-hidden flex flex-col cursor-pointer relative bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 hover:border-teal-300 dark:hover:border-teal-600"
    >
      {/* Top color bar - Teal */}
      <div className="h-[3px] bg-teal-500 opacity-10" />

      {/* Header */}
      <div className="px-4 pt-4 pb-3 border-b border-slate-100 dark:border-slate-700">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-2xl">🔧</span>
            <span className="text-xs font-medium text-teal-600 dark:text-teal-400">
              {categoryLabel}
            </span>
          </div>
          <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
            <Download className="h-3.5 w-3.5" />
            <span>{skill.usage_count}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-100 line-clamp-1 group-hover:text-teal-600 dark:group-hover:text-teal-400 transition-colors">
            {skill.display_name || skill.name}
          </h3>
        </div>
        <div className="h-5 flex items-center gap-2">
          {skill.source === "official" ? (
            <OfficialBadge text={isZh ? "官方" : "Official"} />
          ) : (
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {t("market.by", { defaultValue: "By {{author}}", author: skill.author })}
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 px-4 py-3 flex flex-col gap-3 pb-20 min-h-[120px]">
        <p className="text-sm text-slate-600 dark:text-slate-300 line-clamp-3 flex-1">
          {skill.description}
        </p>
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
            </div>
          )}
        </div>
        <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
          <Wrench className="h-3.5 w-3.5" />
          <span>{skill.tool_count} {t("market.tools", "tools")}</span>
        </div>
      </div>

      {/* Footer */}
      <div className="absolute left-0 right-0 bottom-0 px-4 py-3 border-t border-slate-100 dark:border-slate-700 bg-transparent">
        <button
          onClick={handleDownload}
          className="w-full px-4 py-2 rounded-md bg-gradient-to-r from-teal-500 to-green-500 hover:from-teal-600 hover:to-green-600 text-white text-sm font-medium transition-all duration-300 flex items-center justify-center gap-2"
        >
          <Download className="h-4 w-4" />
          {t("market.download", "Download")}
        </button>
      </div>
    </motion.div>
  );
}

export default SkillMarketCard;
