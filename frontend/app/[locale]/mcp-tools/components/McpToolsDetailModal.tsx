"use client";

import React from "react";
import { Modal } from "antd";
import { useTranslation } from "react-i18next";
import { Tag, Calendar, User, ExternalLink, Copy, Check, Github, Star } from "lucide-react";
import { McpToolsDetail } from "@/types/mcpTools";
import { useState } from "react";

interface McpToolsDetailModalProps {
  visible: boolean;
  onClose: () => void;
  toolDetails: McpToolsDetail | null;
}

/**
 * MCP Tools detail modal component
 * Displays full tool information in a modal
 */
export default function McpToolsDetailModal({
  visible,
  onClose,
  toolDetails,
}: McpToolsDetailModalProps) {
  const { t, i18n } = useTranslation("common");
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";
  const [copied, setCopied] = useState(false);

  if (!toolDetails) {
    return null;
  }

  const handleCopyContent = async () => {
    try {
      const content = isZh ? toolDetails.content_zh : toolDetails.content;
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error("Failed to copy tool content:", error);
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
          <span className="text-3xl">{toolDetails.category.icon}</span>
          <div>
            <div className="text-lg font-semibold">
              {toolDetails.display_name}
            </div>
            <div className="text-sm font-normal text-slate-500 dark:text-slate-400 flex items-center gap-2">
              <span>{toolDetails.author}</span>
              <span className="flex items-center gap-1">
                <Star className="h-3 w-3 text-amber-500" />
                <span>{toolDetails.github_stars.toLocaleString()}</span>
              </span>
            </div>
          </div>
        </div>
      }
      className="mcp-tools-detail-modal"
    >
      <div className="py-4">
        {/* Metadata section */}
        <div className="flex flex-wrap gap-4 mb-4 pb-4 border-b border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <User className="h-4 w-4" />
            <span>{t("mcpTools.author", "Author")}:</span>
            <a
              href={toolDetails.author_url || `https://github.com/${toolDetails.author}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-amber-600 dark:text-amber-400 hover:underline flex items-center gap-1"
            >
              {toolDetails.author}
              <ExternalLink className="h-3 w-3" />
            </a>
          </div>

          <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <Calendar className="h-4 w-4" />
            <span>{t("mcpTools.updated", "Updated")}:</span>
            <span>{toolDetails.updated_at}</span>
          </div>

          <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <Tag className="h-4 w-4" />
            <span>{t("mcpTools.category", "Category")}:</span>
            <span className="px-2 py-0.5 rounded bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300">
              {isZh ? toolDetails.category.display_name_zh : toolDetails.category.display_name}
            </span>
          </div>
        </div>

        {/* Tags */}
        {toolDetails.tags && toolDetails.tags.length > 0 && (
          <div className="mb-4">
            <div className="flex flex-wrap gap-2">
              {toolDetails.tags.map((tag) => (
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
            {t("mcpTools.description", "Description")}
          </h4>
          <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed">
            {isZh ? toolDetails.description_zh : toolDetails.description}
          </p>
        </div>

        {/* Tool content */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
              {t("mcpTools.toolContent", "Tool Documentation")}
            </h4>
            <button
              onClick={handleCopyContent}
              className="flex items-center gap-1 px-3 py-1 rounded-md text-sm bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
            >
              {copied ? (
                <>
                  <Check className="h-4 w-4 text-green-500" />
                  {t("mcpTools.copied", "Copied!")}
                </>
              ) : (
                <>
                  <Copy className="h-4 w-4" />
                  {t("mcpTools.copyContent", "Copy Content")}
                </>
              )}
            </button>
          </div>
          <div className="bg-slate-50 dark:bg-slate-900 rounded-lg p-4 max-h-[400px] overflow-y-auto">
            <pre className="text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap font-mono">
              {isZh ? toolDetails.content_zh : toolDetails.content}
            </pre>
          </div>
        </div>

        {/* Source repo and official URL */}
        <div className="flex flex-col gap-2 text-sm text-slate-600 dark:text-slate-300">
          <div className="flex items-center gap-2">
            <Github className="h-4 w-4" />
            <span>{t("mcpTools.sourceRepo", "Source Repository")}:</span>
            <a
              href={`https://github.com/${toolDetails.source_repo}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-amber-600 dark:text-amber-400 hover:underline flex items-center gap-1"
            >
              {toolDetails.source_repo}
              <ExternalLink className="h-3 w-3" />
            </a>
          </div>

          {toolDetails.official_url && (
            <div className="flex items-center gap-2">
              <ExternalLink className="h-4 w-4" />
              <span>{t("mcpTools.officialPage", "Official Page")}:</span>
              <a
                href={toolDetails.official_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-amber-600 dark:text-amber-400 hover:underline flex items-center gap-1"
              >
                MCP Market
                <ExternalLink className="h-3 w-3" />
              </a>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
