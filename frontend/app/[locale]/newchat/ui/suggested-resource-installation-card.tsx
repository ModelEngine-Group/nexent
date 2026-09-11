"use client";

import { useEffect, useId, useReducer, useState } from "react";
import { useAui } from "@assistant-ui/react";
import { useQueryClient } from "@tanstack/react-query";
import { App } from "antd";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  Loader2,
  SkipForward,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import {
  API_ENDPOINTS,
  fetchWithErrorHandling,
  toApiError,
  type ApiError,
} from "@/services/api";
import type {
  Nl2AgentCardAction,
  Nl2aInstallableResource,
  Nl2aSuggestedResourceInstallationPayload,
} from "../adapter/remote-chat-model-adapter";
import { Nl2AgentResourceSourceBadge } from "./nl2agent-resource-source-badge";

type Status = "idle" | "installing" | "installed" | "failed" | "skipped";
type Item = {
  resource: Nl2aInstallableResource;
  status: Status;
  resourceId?: number;
  error?: ApiError;
  skipReason?: string;
};
type Action =
  | { type: "installing"; ref: string }
  | { type: "installed"; ref: string; resourceId: number }
  | { type: "failed"; ref: string; error: ApiError }
  | { type: "skipped"; ref: string; reason: string };
const ref = (item: Item) => item.resource.candidate.candidate_ref;
function reducer(items: Item[], action: Action): Item[] {
  return items.map((item) => {
    if (ref(item) !== action.ref) return item;
    if (action.type === "installing")
      return { ...item, status: "installing", error: undefined };
    if (action.type === "installed")
      return {
        ...item,
        status: "installed",
        resourceId: action.resourceId,
        error: undefined,
      };
    if (action.type === "failed")
      return { ...item, status: "failed", error: action.error };
    return {
      ...item,
      status: "skipped",
      skipReason: action.reason,
      error: undefined,
    };
  });
}

export function SuggestedResourceInstallationCard({
  payload,
  disabled = false,
}: {
  payload: Nl2aSuggestedResourceInstallationPayload;
  disabled?: boolean;
}) {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const aui = useAui();
  const queryClient = useQueryClient();
  const cardKey = `suggested_resource_installation:${payload.agent_id}:${useId()}`;
  const { registerCard, submitCard, isCardInteractive } = useNl2AgentFlow();
  const [items, dispatch] = useReducer(
    reducer,
    payload.resources,
    (resources) =>
      resources.map((resource) => ({ resource, status: "idle" as const }))
  );
  const [submitted, setSubmitted] = useState(false);
  const interactive = !disabled && !submitted && isCardInteractive(cardKey);
  const canContinue = items.every(
    (item) => item.status !== "idle" && item.status !== "installing"
  );
  useEffect(() => {
    registerCard(cardKey, payload.subtype);
  }, [cardKey, payload.subtype, registerCard]);
  const install = async (item: Item) => {
    if (
      !interactive ||
      item.status === "installing" ||
      item.status === "installed"
    )
      return;
    dispatch({ type: "installing", ref: ref(item) });
    try {
      const response = await fetchWithErrorHandling(
        API_ENDPOINTS.agent.nl2agentResourceInstallations,
        {
          method: "POST",
          body: JSON.stringify({
            agent_id: payload.agent_id,
            candidate_ref: ref(item),
          }),
        }
      );
      const result = await response.json();
      if (!Number.isInteger(result.resource_id) || result.resource_id <= 0)
        throw new Error("Installed resource could not be resolved");
      dispatch({
        type: "installed",
        ref: ref(item),
        resourceId: result.resource_id,
      });
      await queryClient.invalidateQueries();
      message.success(
        t("nl2agent.resourceInstallation.success", "Resource installed")
      );
    } catch (error) {
      dispatch({ type: "failed", ref: ref(item), error: toApiError(error) });
    }
  };
  const continueFlow = () => {
    if (!canContinue) return;
    const action: Nl2AgentCardAction = {
      type: "nl2agent_card_action",
      subtype: payload.subtype,
      agent_id: payload.agent_id,
      action: "continue",
      result: {
        installed: items
          .filter((item) => item.status === "installed")
          .map((item) => ({
            candidate_ref: ref(item),
            resource_type: item.resource.candidate.resource_type,
            resource_id: item.resourceId,
          })),
        skipped: items
          .filter((item) => item.status !== "installed")
          .map((item) => ({
            candidate_ref: ref(item),
            reason:
              item.skipReason ||
              (item.status === "failed" ? "install_failed" : "not_selected"),
          })),
      },
    };
    setSubmitted(true);
    submitCard(cardKey);
    aui
      .thread()
      .append({
        role: "user",
        content: [
          {
            type: "text",
            text: t(
              "nl2agent.resourceInstallation.submittedSummary",
              "Resource installation completed"
            ),
          },
        ],
        metadata: { custom: { nl2agentCardAction: action } },
        startRun: true,
      });
  };
  return (
    <section
      className="my-4 w-full max-w-3xl overflow-hidden rounded-md border border-border bg-background"
      data-testid="nl2agent-installation-card"
    >
      <div className="flex items-center gap-3 border-b bg-muted/30 px-4 py-3">
        <Download className="size-4 text-primary" />
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold">
            {t(
              "nl2agent.resourceInstallation.title",
              "Install suggested resources"
            )}
          </h3>
          <p className="text-xs text-muted-foreground">
            {t(
              "nl2agent.resourceInstallation.description",
              "Install the resources needed for this Agent."
            )}
          </p>
        </div>
        <Badge variant="outline">{items.length}</Badge>
      </div>
      <div className="divide-y">
        {items.map((item) => (
          <div
            key={ref(item)}
            className="flex min-h-20 flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center"
          >
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="break-words text-sm font-medium">
                  {item.resource.candidate.name}
                </span>
                <Nl2AgentResourceSourceBadge
                  source={item.resource.candidate.source}
                  availability={
                    item.status === "installed" ? "installed" : undefined
                  }
                />
              </div>
              {item.resource.candidate.description && (
                <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                  {item.resource.candidate.description}
                </p>
              )}
              {item.error && (
                <p className="mt-1 flex items-center gap-1 text-xs text-destructive">
                  <AlertTriangle className="size-3.5" />
                  {item.error.message}
                </p>
              )}
            </div>
            <div className="flex w-full shrink-0 items-center justify-end gap-2 sm:w-auto">
              {item.status === "installed" ? (
                <span className="flex h-9 items-center gap-1 text-xs text-emerald-600">
                  <CheckCircle2 className="size-4" />
                  {t("nl2agent.resourceInstallation.installed", "Installed")}
                </span>
              ) : item.status === "skipped" ? (
                <span className="text-xs text-muted-foreground">
                  {t("nl2agent.resourceInstallation.skipped", "Skipped")}
                </span>
              ) : (
                <>
                  <Button
                    type="button"
                    size="sm"
                    disabled={!interactive || item.status === "installing"}
                    onClick={() => install(item)}
                  >
                    {item.status === "installing" ? (
                      <Loader2 className="mr-1 size-4 animate-spin" />
                    ) : (
                      <Download className="mr-1 size-4" />
                    )}
                    {item.status === "failed"
                      ? t("common.retry", "Retry")
                      : t("nl2agent.resourceInstallation.install", "Install")}
                  </Button>
                  {item.status === "failed" && (
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      className="size-9"
                      onClick={() =>
                        dispatch({
                          type: "skipped",
                          ref: ref(item),
                          reason: "install_failed",
                        })
                      }
                    >
                      <SkipForward className="size-4" />
                    </Button>
                  )}
                </>
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="flex justify-end border-t px-4 py-3">
        <Button type="button" disabled={!canContinue} onClick={continueFlow}>
          {items.some((item) => item.status === "installed")
            ? t("nl2agent.resourceBinding.continue", "Continue")
            : t("nl2agent.resourceBinding.skip", "Skip")}
        </Button>
      </div>
    </section>
  );
}
