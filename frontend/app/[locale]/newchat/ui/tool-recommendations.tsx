"use client";

import { useId, useRef, useState, type FC } from "react";
import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  SearchXIcon,
  ServerIcon,
  SparklesIcon,
  WrenchIcon,
} from "lucide-react";
import { useAui } from "@assistant-ui/react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAgentStore } from "@/stores/agentStore";
import type { Tool } from "@/types/agentConfig";
import type {
  Nl2AgentToolSelection,
  Nl2AgentSelectedTool,
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
}> = ({ payload, disabled = false }) => {
  const { t } = useTranslation("common");
  const aui = useAui();
  const updateTools = useAgentStore((state) => state.updateTools);
  const checkboxIdPrefix = useId();
  const content = payload;
  const isSuccess = content.status === "success";
  const recommendations: Nl2aToolRecommendation[] =
    content.status === "success" ? content.recommendations : [];
  const [selectedToolIds, setSelectedToolIds] = useState(
    () => new Set(recommendations.map((tool) => tool.tool_id))
  );
  const [isConfirmed, setIsConfirmed] = useState(false);
  const confirmationStarted = useRef(false);

  const toggleTool = (toolId: number) => {
    if (isConfirmed || disabled) return;
    setSelectedToolIds((current) => {
      const next = new Set(current);
      if (next.has(toolId)) {
        next.delete(toolId);
      } else {
        next.add(toolId);
      }
      return next;
    });
  };

  const confirmSelection = () => {
    if (!isSuccess || disabled || confirmationStarted.current) return;
    confirmationStarted.current = true;
    setIsConfirmed(true);

    const tools: Nl2AgentSelectedTool[] = recommendations
      .filter((tool) => selectedToolIds.has(tool.tool_id))
      .map((tool) => ({
        tool_id: tool.tool_id,
        name: tool.name,
        origin_name: tool.origin_name,
        description: tool.description,
        source: tool.source,
        usage: tool.usage,
        labels: tool.labels,
        inputs: JSON.stringify(tool.inputs),
      }));
    const agentTools: Tool[] = tools.map((tool) => ({
      id: String(tool.tool_id),
      name: tool.name,
      origin_name: tool.origin_name ?? undefined,
      description: tool.description,
      source: tool.source,
      initParams: [],
      usage: tool.usage,
      inputs: tool.inputs,
      labels: tool.labels,
    }));
    const selection: Nl2AgentToolSelection = {
      type: "nl2agent_tool_selection",
      tools,
    };

    updateTools(agentTools);
    aui.thread().append({
      role: "user",
      content: [
        {
          type: "text",
          text: t("nl2agent.toolRecommendations.confirmedSummary", {
            count: tools.length,
          }),
        },
      ],
      metadata: {
        custom: { nl2agentToolSelection: selection },
      },
      startRun: true,
    });
  };

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
            {recommendations.map((tool, index) => {
              const checkboxId = `${checkboxIdPrefix}-${index}`;
              return (
                <label
                  key={tool.tool_id}
                  htmlFor={checkboxId}
                  className="block rounded-lg border bg-background p-4 transition-colors has-checked:border-primary/50 has-checked:bg-primary/[0.03]"
                >
                  <div className="flex items-start gap-3">
                    <input
                      id={checkboxId}
                      type="checkbox"
                      checked={selectedToolIds.has(tool.tool_id)}
                      disabled={isConfirmed || disabled}
                      onChange={() => toggleTool(tool.tool_id)}
                      className="mt-2 size-4 shrink-0 accent-primary disabled:cursor-not-allowed"
                      aria-label={t("nl2agent.toolRecommendations.selectTool", {
                        name: tool.name,
                      })}
                    />
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
                </label>
              );
            })}
          </div>
        )}
      </div>

      {isSuccess && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t bg-muted/20 px-4 py-3">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            {isConfirmed && (
              <CheckCircle2Icon className="size-4 text-emerald-600 dark:text-emerald-400" />
            )}
            <span>
              {isConfirmed
                ? t("nl2agent.toolRecommendations.confirmed")
                : t("nl2agent.toolRecommendations.selectedCount", {
                    count: selectedToolIds.size,
                  })}
            </span>
          </div>
          <Button
            type="button"
            size="sm"
            disabled={isConfirmed || disabled}
            onClick={confirmSelection}
          >
            <CheckCircle2Icon />
            {selectedToolIds.size === 0
              ? t("nl2agent.toolRecommendations.continueWithoutTools")
              : t("nl2agent.toolRecommendations.confirm")}
          </Button>
        </div>
      )}
    </section>
  );
};
