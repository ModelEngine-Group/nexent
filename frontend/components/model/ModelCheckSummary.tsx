// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
import {
  groupModelCheckIssues,
  type ModelCheckIssue,
} from "@/lib/modelCheckIssues";

/** Shared connection failures appear once; body failures retain model ownership. */
export function ModelCheckSummary({
  issues,
  modelNames,
  onConfigure,
  onRetry,
  onRetryShared,
}: {
  issues: Record<string, ModelCheckIssue>;
  modelNames?: Record<string, string>;
  onConfigure?: (id: string) => void;
  onRetry?: (id: string) => void;
  onRetryShared?: () => void;
}) {
  const { t, i18n } = useTranslation();
  const { shared, models } = groupModelCheckIssues(issues);
  const count = shared.length + models.length;
  if (!count) return null;
  const text = (issue: ModelCheckIssue) => {
    const locale = (
      i18n?.resolvedLanguage ??
      i18n?.language ??
      "en"
    ).startsWith("zh")
      ? "zh"
      : "en";
    const localized = issue.messages?.[locale] ?? issue.messages?.en;
    if (localized) return localized;
    const key = `modelProfile.checkErrors.${issue.scope === "model" && issue.category === "MODEL_NOT_FOUND" ? "modelMissing" : issue.category}`;
    const known = t(key, { defaultValue: "" });
    if (issue.message && (issue.message_source === "provider" || !known))
      return `${t(issue.message_source === "provider" ? "modelProfile.originalServiceError" : "modelProfile.unrecognizedError")} ${issue.message}`;
    return [
      known || t("modelProfile.checkErrors.unknown"),
      issue.http_status ? `HTTP ${issue.http_status}` : null,
      issue.parameter,
    ]
      .filter(Boolean)
      .join(" · ");
  };
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button type="button" className="text-xs text-destructive">
          {t("modelProfile.checkIssues", { count })}
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="end"
        className="max-h-64 w-80 max-w-[calc(100vw-2rem)] overflow-auto p-3 text-xs"
        aria-label={t("modelProfile.checkIssueDetails")}
      >
        <div
          className="space-y-2"
          role="region"
          aria-label={t("modelProfile.checkIssueDetails")}
        >
          {shared.map((issue) => (
            <p
              key={`${issue.category}:${issue.http_status ?? ""}:${issue.message ?? ""}`}
            >
              {text(issue)}
            </p>
          ))}
          {shared.length > 0 && onRetryShared && (
            <button
              type="button"
              className="text-primary"
              onClick={onRetryShared}
            >
              {t("modelProfile.retryCheck")}
            </button>
          )}
          {models.map(({ id, issue }) => (
            <div key={id} className="space-y-1">
              <p>
                <strong>{modelNames?.[id] ?? id}</strong>: {text(issue)}
              </p>
              {onConfigure && (
                <button
                  type="button"
                  className="mr-3 text-primary"
                  onClick={() => onConfigure(id)}
                >
                  {t("modelProfile.configureModel")}
                </button>
              )}
              {onRetry && (
                <button
                  type="button"
                  className="text-primary"
                  onClick={() => onRetry(id)}
                >
                  {t("modelProfile.retryCheck")}
                </button>
              )}
            </div>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
