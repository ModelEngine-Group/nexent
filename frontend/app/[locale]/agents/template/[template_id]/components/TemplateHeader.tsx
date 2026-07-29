"use client";

import React from "react";
import { Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { OfficialBadge } from "@/components/market/OfficialBadge";

export interface TemplateHeaderData {
  id: number;
  name: string;
  display_name: string;
  description: string;
  version: string;
  author: string;
  source: "official" | "community";
  download_count: number;
  updated_at: string;
  icon: string;
}

interface TemplateHeaderProps {
  template: TemplateHeaderData;
  onCreate?: () => void;
}

/**
 * TemplateHeader - Header section for template detail page
 * Left color bar + avatar + badges + title + meta + create button
 */
export function TemplateHeader({ template, onCreate }: TemplateHeaderProps) {
  const { t, i18n } = useTranslation("common");
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4 sm:p-5 flex items-center gap-4 border-l-4 border-l-[#534AB7]">
      {/* Avatar */}
      <div className="w-11 h-11 rounded-full bg-[#EEEDFE] dark:bg-purple-900/30 border-[1.5px] border-[#534AB7] flex items-center justify-center text-xl flex-shrink-0">
        {template.icon}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          {template.source === "official" && (
            <OfficialBadge text={isZh ? "官方" : "Official"} />
          )}
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#EEEDFE] dark:bg-purple-900/30 text-[#534AB7] dark:text-purple-400 border border-[#534AB7]" style={{ height: "18px" }}>
            {isZh ? "模板" : "Template"}
          </span>
        </div>
        <h1 className="text-base font-semibold text-[#534AB7] dark:text-purple-400">
          {template.display_name || template.name}
        </h1>
        <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
          v{template.version} · {template.download_count} {isZh ? "下载" : "downloads"} ·{" "}
          {isZh ? "更新于" : "Updated"}{" "}
          {new Date(template.updated_at).toLocaleDateString(isZh ? "zh-CN" : "en-US")}
        </p>
      </div>

      {/* Direct-chat button: launch (get-or-create) with default Recipe values */}
      <button
        onClick={onCreate}
        className="px-6 py-2.5 rounded-lg bg-[#534AB7] hover:bg-[#7F77DD] text-white text-sm font-medium transition-all duration-300 flex items-center gap-2 flex-shrink-0"
      >
        <Sparkles className="h-4 w-4" />
        {isZh ? "直接开聊" : "Start chat"}
      </button>
    </div>
  );
}

export default TemplateHeader;
