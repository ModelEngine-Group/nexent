"use client";

import React from "react";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { OfficialBadge } from "./OfficialBadge";

export interface PresetAgentCardData {
  id: number;
  name: string;
  display_name: string;
  description: string;
  icon: string;
  prompt_template: string;
  source: "official" | "community";
}

interface PresetAgentCardProps {
  agent: PresetAgentCardData;
  onSelect?: (agent: PresetAgentCardData) => void;
  index?: number;
  variant?: "primary" | "secondary";
}

/**
 * PresetAgentCard - Zero-config entry point for preset agents
 * Shown on newchat landing page for quick start
 */
export function PresetAgentCard({
  agent,
  onSelect,
  index = 0,
  variant = "primary",
}: PresetAgentCardProps) {
  const { t, i18n } = useTranslation("common");
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";

  const handleClick = () => {
    onSelect?.(agent);
  };

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={{ duration: 0.3, delay: 0.05 * index }}
      whileHover={{
        y: -2,
        boxShadow: "0 6px 12px -4px rgba(0,0,0,0.08)",
      }}
      onClick={handleClick}
      className="rounded-lg border transition-all duration-300 overflow-hidden cursor-pointer relative bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 hover:border-purple-300 dark:hover:border-purple-600"
    >
      {/* Top color bar */}
      <div
        className={`h-[3px] bg-[#534AB7] ${variant === "secondary" ? "opacity-70" : ""}`}
      />

      {/* Header: badges + zap icon */}
      <div className="px-3 pt-2 pb-1 flex justify-between items-center">
        <OfficialBadge text={isZh ? "官方" : "Official"} />
        <div className="w-5 h-5 rounded-full bg-[#EEEDFE] dark:bg-purple-900/30 flex items-center justify-center text-[10px]">
          ⚡
        </div>
      </div>

      {/* Body: avatar + title + desc */}
      <div className="px-3 pb-2 flex items-center gap-2.5">
        <div className="w-9 h-9 rounded-full bg-[#EEEDFE] dark:bg-purple-900/30 border border-[#534AB7] flex items-center justify-center text-base flex-shrink-0">
          {agent.icon}
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-medium text-slate-800 dark:text-slate-100 truncate">
            {agent.display_name || agent.name}
          </h3>
          <p className="text-[11px] text-slate-400 dark:text-slate-500 line-clamp-2">
            {agent.description}
          </p>
        </div>
      </div>

      {/* Prompt preview */}
      <div
        className="mx-3 mb-3 px-3 py-2 rounded-lg bg-[#FAFAFB] dark:bg-slate-700/50 border border-[#CECBF6] dark:border-purple-800 text-[10px] text-[#534AB7] dark:text-purple-400 truncate"
      >
        {agent.prompt_template}
      </div>
    </motion.div>
  );
}

export default PresetAgentCard;
