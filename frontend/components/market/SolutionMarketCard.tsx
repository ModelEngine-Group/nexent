"use client";

import React from "react";
import { motion } from "framer-motion";
import {
  MessageCircle,
  Tag,
  Layers,
  Users,
  ShieldCheck,
  Settings,
  BookOpen,
  Headphones,
  BarChart3,
  PenLine,
  Search,
  TrendingUp,
  Code2,
  FileText,
  Mail,
  Image as ImageIcon,
  Package,
  Download,
  Loader2,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { OfficialBadge } from "./OfficialBadge";

export type SolutionType = "single" | "team";

export interface SolutionMember {
  role_name: string;
  role_name_zh: string;
  is_lead?: boolean;
}

export interface SolutionCardData {
  id: number;
  name: string;
  display_name: string;
  description: string;
  version?: string;
  author: string;
  source: "official" | "community";
  solution_type: SolutionType;
  category?: { name: string; display_name: string; display_name_zh: string };
  tags?: { id: string; display_name: string }[];
  download_count: number;
  agent_count?: number;
  skill_count?: number;
  mcp_count?: number;
  icon_name?: string;
  agent_id?: number;
  tool_keywords?: string[];
  resolved?: boolean;
  is_available?: boolean;
  unavailable_reasons?: string[];
  members?: SolutionMember[];
  has_guardrails?: boolean;
  guardrails_label?: string;
}

const ICON_MAP: Record<string, LucideIcon> = {
  BookOpen,
  Headphones,
  BarChart3,
  PenLine,
  Search,
  TrendingUp,
  Code2,
  FileText,
  Mail,
  Image: ImageIcon,
  Users,
  Package,
};

function getSolutionIcon(solution: SolutionCardData): LucideIcon {
  const name = solution.icon_name || solution.category?.name || "";
  return ICON_MAP[name] || Package;
}

interface SolutionCardProps {
  solution: SolutionCardData;
  onChat?: (solution: SolutionCardData) => void;
  onInstall?: (solution: SolutionCardData) => void;
  onConfig?: (solution: SolutionCardData) => void;
  onViewDetails?: (solution: SolutionCardData) => void;
  installing?: boolean;
  index?: number;
}

export function SolutionMarketCard({
  solution,
  onChat,
  onInstall,
  onConfig,
  onViewDetails,
  installing = false,
  index = 0,
}: SolutionCardProps) {
  const { t, i18n } = useTranslation("common");
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";

  const isTeam = solution.solution_type === "team";
  const isResolved = solution.resolved || !!solution.agent_id;
  const isAvailable = solution.is_available !== false;
  const reasons = solution.unavailable_reasons || [];

  const handleInstall = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isResolved && isAvailable && onChat) {
      onChat(solution);
    } else if (isResolved && !isAvailable && onConfig) {
      onConfig(solution);
    } else if (onInstall) {
      onInstall(solution);
    }
  };

  const handleCardClick = () => {
    if (isResolved) {
      onViewDetails?.(solution);
    }
  };

  const categoryLabel = solution.category
    ? isZh
      ? solution.category.display_name_zh
      : solution.category.display_name
    : t("market.category.other", "Other");

  const Icon = getSolutionIcon(solution);

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={{ duration: 0.3, delay: 0.05 * index }}
      whileHover={{ y: -4 }}
      onClick={handleCardClick}
      className="group h-full min-h-[320px] rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:border-slate-300 dark:hover:border-slate-600 hover:shadow-sm transition-all duration-300 overflow-hidden flex flex-col cursor-pointer relative"
    >
      {/* Header */}
      <div className="px-4 pt-4 pb-3 border-b border-slate-100 dark:border-slate-700">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Icon className="h-4 w-4 text-slate-500 dark:text-slate-400" />
            <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
              {categoryLabel}
            </span>
          </div>
          <div className="flex items-center gap-1 text-xs text-slate-400 dark:text-slate-500">
            <MessageCircle className="h-3.5 w-3.5" />
            <span>{solution.download_count}</span>
          </div>
        </div>
        <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100 line-clamp-1 group-hover:text-slate-700 dark:group-hover:text-slate-50 transition-colors">
          {solution.display_name || solution.name}
        </h3>
        <div className="h-5 flex items-center gap-2">
          {solution.source === "official" ? (
            <OfficialBadge text={isZh ? "官方" : "Official"} />
          ) : (
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {t("market.by", {
                defaultValue: "By {{author}}",
                author: solution.author,
              })}
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 px-4 py-3 flex flex-col gap-3 pb-16 min-h-[120px]">
        <p className="text-sm text-slate-600 dark:text-slate-300 line-clamp-3 flex-1">
          {solution.description}
        </p>

        {/* Composition badges */}
        {!isTeam &&
          (solution.agent_count !== undefined ||
            solution.skill_count !== undefined ||
            solution.mcp_count !== undefined) && (
            <div className="flex items-center gap-2 text-xs">
              {solution.agent_count !== undefined &&
                solution.agent_count > 0 && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300">
                    <Layers className="h-3 w-3" />
                    {solution.agent_count}A
                  </span>
                )}
              {solution.skill_count !== undefined &&
                solution.skill_count > 0 && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300">
                    {solution.skill_count}S
                  </span>
                )}
              {solution.mcp_count !== undefined && solution.mcp_count > 0 && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300">
                  {solution.mcp_count}M
                </span>
              )}
            </div>
          )}

        {/* Team members */}
        {isTeam && solution.members && solution.members.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {solution.members.slice(0, 6).map((member, i) => {
              const label = isZh ? member.role_name_zh : member.role_name;
              return (
                <span
                  key={i}
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] ${
                    member.is_lead
                      ? "bg-slate-100 dark:bg-slate-700 text-slate-900 dark:text-slate-100"
                      : "bg-slate-50 dark:bg-slate-700/50 text-slate-600 dark:text-slate-300"
                  }`}
                  style={{ height: "20px" }}
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${
                      member.is_lead
                        ? "bg-slate-700 dark:bg-slate-200"
                        : "bg-slate-400"
                    }`}
                  />
                  {label}
                </span>
              );
            })}
          </div>
        )}

        {/* Guardrails */}
        {isTeam && solution.has_guardrails && (
          <div>
            <span className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300">
              <ShieldCheck className="h-3 w-3" />
              {solution.guardrails_label ||
                (isZh ? "行业规则已激活" : "Guardrails active")}
            </span>
          </div>
        )}

        {/* Tags */}
        <div className="min-h-[24px]">
          {solution.tags && solution.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 max-h-6 overflow-hidden">
              {solution.tags.slice(0, 3).map((tag) => (
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
      </div>

      {/* Footer */}
      <div className="absolute left-0 right-0 bottom-0 px-4 py-3 border-t border-slate-100 dark:border-slate-700 flex items-center gap-2">
        {isResolved ? (
          isAvailable ? (
            <button
              onClick={handleInstall}
              className="flex-1 px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-all duration-300 flex items-center justify-center gap-2"
            >
              <MessageCircle className="h-4 w-4" />
              {isZh ? "开始对话" : "Start chat"}
            </button>
          ) : (
            <button
              onClick={handleInstall}
              className="flex-1 px-4 py-2 rounded-md bg-amber-500 hover:bg-amber-600 text-white text-sm font-medium transition-all duration-300 flex items-center justify-center gap-2"
            >
              <Settings className="h-4 w-4" />
              {isZh
                ? `去配置${reasons.includes("model_unavailable") ? " · LLM" : ""}`
                : "Configure"}
            </button>
          )
        ) : installing ? (
          <button
            disabled
            className="flex-1 px-4 py-2 rounded-md bg-slate-400 text-white text-sm font-medium flex items-center justify-center gap-2 cursor-wait"
          >
            <Loader2 className="h-4 w-4 animate-spin" />
            {isZh ? "安装中..." : "Installing..."}
          </button>
        ) : (
          <button
            onClick={handleInstall}
            className="flex-1 px-4 py-2 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium transition-all duration-300 flex items-center justify-center gap-2"
          >
            <Download className="h-4 w-4" />
            {isZh ? "一键安装" : "Install"}
          </button>
        )}
        {isResolved && onConfig && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onConfig(solution);
            }}
            title={isZh ? "配置" : "Configure"}
            className="shrink-0 px-3 py-2 rounded-md border border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 text-sm transition-all duration-300 flex items-center gap-1"
          >
            <Settings className="h-4 w-4" />
          </button>
        )}
      </div>
    </motion.div>
  );
}

export default SolutionMarketCard;
