"use client";

import React from "react";
import { Modal } from "antd";
import { useTranslation } from "react-i18next";
import { Tag, Calendar, User, ExternalLink, Copy, Check } from "lucide-react";
import { SkillMarketDetail } from "@/types/skillMarket";
import { useState } from "react";

interface SkillMarketDetailModalProps {
  visible: boolean;
  onClose: () => void;
  skillDetails: SkillMarketDetail | null;
}

/**
 * Skill market detail modal component
 * Displays full skill information in a modal
 */
export default function SkillMarketDetailModal({
  visible,
  onClose,
  skillDetails,
}: SkillMarketDetailModalProps) {
  const { t, i18n } = useTranslation("common");
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";
  const [copied, setCopied] = useState(false);

  if (!skillDetails) {
    return null;
  }

  const handleCopySkill = async () => {
    try {
      const content = isZh ? skillDetails.content_zh : skillDetails.content;
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error("Failed to copy skill content:", error);
    }
  };

  return (
    <Modal
      open={visible}
      onCancel={onClose}
      footer={null}
      width={720}
      centered
      title={
        <div className="flex items-center gap-3">
          <span className="text-3xl">{skillDetails.category.icon}</span>
          <div>
            <div className="text-lg font-semibold">
              {isZh ? skillDetails.display_name_zh : skillDetails.display_name}
            </div>
            <div className="text-sm font-normal text-slate-500 dark:text-slate-400">
              {skillDetails.author}
            </div>
          </div>
        </div>
      }
      className="skill-market-detail-modal"
    >
      <div className="py-4">
        {/* Metadata section */}
        <div className="flex flex-wrap gap-4 mb-4 pb-4 border-b border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <User className="h-4 w-4" />
            <span>{t("skillMarket.author", "Author")}:</span>
            <a
              href={skillDetails.author_url || `https://github.com/${skillDetails.author}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
            >
              {skillDetails.author}
              <ExternalLink className="h-3 w-3" />
            </a>
          </div>

          <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <Calendar className="h-4 w-4" />
            <span>{t("skillMarket.updated", "Updated")}:</span>
            <span>{skillDetails.updated_at}</span>
          </div>

          <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <Tag className="h-4 w-4" />
            <span>{t("skillMarket.category", "Category")}:</span>
            <span className="px-2 py-0.5 rounded bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300">
              {isZh ? skillDetails.category.display_name_zh : skillDetails.category.display_name}
            </span>
          </div>
        </div>

        {/* Tags */}
        {skillDetails.tags && skillDetails.tags.length > 0 && (
          <div className="mb-4">
            <div className="flex flex-wrap gap-2">
              {skillDetails.tags.map((tag) => (
                <span
                  key={tag.id}
                  className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-sm bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300"
                >
                  <Tag className="h-3 w-3" />
                  {tag.display_name}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Description */}
        <div className="mb-6">
          <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-200 mb-2">
            {t("skillMarket.description", "Description")}
          </h4>
          <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed">
            {isZh ? skillDetails.description_zh : skillDetails.description}
          </p>
        </div>

        {/* Skill content */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
              {t("skillMarket.skillContent", "Skill Content")}
            </h4>
            <button
              onClick={handleCopySkill}
              className="flex items-center gap-1 px-3 py-1 rounded-md text-sm bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
            >
              {copied ? (
                <>
                  <Check className="h-4 w-4 text-green-500" />
                  {t("skillMarket.copied", "Copied!")}
                </>
              ) : (
                <>
                  <Copy className="h-4 w-4" />
                  {t("skillMarket.copyContent", "Copy Content")}
                </>
              )}
            </button>
          </div>
          <div className="bg-slate-50 dark:bg-slate-900 rounded-lg p-4 max-h-[400px] overflow-y-auto">
            <pre className="text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap font-mono">
              {isZh ? skillDetails.content_zh : skillDetails.content}
            </pre>
          </div>
        </div>

        {/* Source repo */}
        <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
          <ExternalLink className="h-4 w-4" />
          <span>{t("skillMarket.sourceRepo", "Source Repository")}:</span>
          <a
            href={`https://github.com/${skillDetails.source_repo}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 dark:text-blue-400 hover:underline"
          >
            {skillDetails.source_repo}
          </a>
        </div>
      </div>
    </Modal>
  );
}
