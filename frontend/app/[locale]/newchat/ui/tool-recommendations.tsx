"use client";

import { type FC } from "react";
import {
  AlertTriangleIcon,
  SearchXIcon,
  ServerIcon,
  SparklesIcon,
  WrenchIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import type {
  Nl2aLocalMcpRecommendationPayload,
  Nl2aToolRecommendation,
} from "../adapter/remote-chat-model-adapter";

const formatMatchScore = (score: number): string => {
  const normalizedScore = Number.isFinite(score)
    ? Math.min(1, Math.max(0, score))
    : 0;
  return `${Math.round(normalizedScore * 100)}%`;
};

const ToolRecommendationsEmpty: FC = () => {
  const { t } = useTranslation("common");

  return (
    <div className="flex flex-col items-center rounded-lg border border-dashed px-5 py-8 text-center">
      <SearchXIcon className="mb-3 size-8 text-muted-foreground/70" />
      <p className="text-sm font-medium text-foreground">
        {t("nl2agent.toolRecommendations.emptyTitle")}
      </p>
      <p className="mt-1 max-w-md text-xs text-muted-foreground">
        {t("nl2agent.toolRecommendations.emptyDescription")}
      </p>
    </div>
  );
};

const ToolRecommendationsError: FC = () => {
  const { t } = useTranslation("common");

  return (
    <div
      role="status"
      className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50/70 p-4 dark:border-amber-900 dark:bg-amber-950/20"
    >
      <AlertTriangleIcon className="mt-0.5 size-5 shrink-0 text-amber-600 dark:text-amber-400" />
      <div>
        <p className="text-sm font-medium text-foreground">
          {t("nl2agent.toolRecommendations.errorTitle")}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {t("nl2agent.toolRecommendations.errorDescription")}
        </p>
      </div>
    </div>
  );
};

export const ToolRecommendations: FC<{
  payload: Nl2aLocalMcpRecommendationPayload;
  disabled?: boolean;
}> = ({ payload }) => {
  const { t } = useTranslation("common");
  const content = payload;
  const isSuccess = content.status === "success";
  const recommendations: Nl2aToolRecommendation[] =
    content.status === "success" ? content.recommendations : [];
  return (
    <section
      data-slot="aui-tool-recommendations"
      className="my-4 overflow-hidden rounded-xl border bg-card shadow-sm"
    >
      <div className="flex items-center gap-3 border-b bg-muted/30 px-4 py-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10">
          <SparklesIcon className="size-4 text-primary" />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-foreground">
            {t("nl2agent.toolRecommendations.title")}
          </h3>
          {content.status === "success" && (
            <p className="text-xs text-muted-foreground">
              {t("nl2agent.toolRecommendations.count", {
                count: content.recommendation_count,
              })}
            </p>
          )}
        </div>
      </div>

      <div className="p-4">
        {!isSuccess ? (
          <ToolRecommendationsError />
        ) : recommendations.length === 0 ? (
          <ToolRecommendationsEmpty />
        ) : (
          <div className="space-y-3">
            {recommendations.map((tool) => {
              return (
                <div
                  key={tool.tool_id}
                  className="block rounded-lg border bg-background p-4"
                >
                  <div className="flex items-start gap-3">
                    <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
                      <WrenchIcon className="size-4 text-muted-foreground" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="min-w-0">
                          <h4 className="truncate text-sm font-semibold text-foreground">
                            {tool.name}
                          </h4>
                          {tool.origin_name &&
                            tool.origin_name !== tool.name && (
                              <p className="truncate text-xs text-muted-foreground">
                                {tool.origin_name}
                              </p>
                            )}
                        </div>
                        <Badge variant="success" size="sm">
                          {t("nl2agent.toolRecommendations.match", {
                            score: formatMatchScore(tool.score),
                          })}
                        </Badge>
                      </div>

                      <p className="mt-2 text-sm text-muted-foreground">
                        {tool.description}
                      </p>

                      <div className="mt-3 flex flex-wrap items-center gap-1.5">
                        <Badge variant="info" size="sm">
                          {tool.source.toUpperCase()}
                        </Badge>
                        {tool.usage && (
                          <Badge variant="outline" size="sm">
                            <ServerIcon />
                            {tool.usage}
                          </Badge>
                        )}
                        {tool.labels.map((label) => (
                          <Badge key={label} variant="muted" size="sm">
                            {label}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
};
