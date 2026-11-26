// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { Progress, Spin } from "antd";
import { useTranslation } from "react-i18next";
import type { Nl2AgentStateEvent } from "../adapter/remote-chat-model-adapter";

export type RetrievalProgress = Extract<
  Nl2AgentStateEvent,
  { event: "resource_retrieval_progress" }
>;

export function Nl2AgentRetrievalProgress({
  value,
  fallback = false,
}: {
  value: RetrievalProgress;
  fallback?: boolean;
}) {
  const { t } = useTranslation("common");
  const percent =
    value.total === undefined
      ? undefined
      : Math.floor((100 * (value.completed ?? 0)) / value.total);
  return (
    <div
      className="shrink-0 px-4 py-2 text-sm text-muted-foreground"
      role="status"
      aria-live="polite"
      data-testid="retrieval-progress"
    >
      {fallback && value.stage !== "fallback_to_text" && (
        <div>{t("nl2agent.retrieval.fallback_to_text")}</div>
      )}
      <div className="flex items-center gap-2">
        {percent === undefined && <Spin size="small" />}
        <span>{t(`nl2agent.retrieval.${value.stage}`)}</span>
      </div>
      {percent !== undefined && (
        <Progress
          percent={percent}
          size="small"
          status={percent === 100 ? "normal" : "active"}
        />
      )}
    </div>
  );
}
