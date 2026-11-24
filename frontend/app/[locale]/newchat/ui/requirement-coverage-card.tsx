// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";
import { useAui, useAuiState } from "@assistant-ui/react";
import { useTranslation } from "react-i18next";
import {
  ArrowRight,
  ChevronDown,
  ChevronRight,
  Circle,
  CircleCheck,
  CircleDashed,
  CircleDot,
  ListChecks,
  Pencil,
  Plus,
  Plug,
  Sparkles,
  Target,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import { fetchWithAuth } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";
import { listMcpTools } from "@/services/mcpToolsService";
import type {
  Nl2AgentCardAction,
  Nl2aUnifiedResourcesPayload,
  Nl2aSuggestedResourceInstallationPayload,
} from "../adapter/remote-chat-model-adapter";
import { nl2AgentCardRunConfig } from "./nl2agent-card-run-config";
import { Nl2AgentResourceKindBadge } from "./nl2agent-resource-kind-badge";
import {
  SuggestedResourceInstallationCard,
  type InstallationAttemptInput,
  type InstallationAttemptResult,
} from "./suggested-resource-installation-card";

const SkillBuildModal = dynamic(
  () => import("../../agents/components/capability/SkillBuildModal"),
  { ssr: false }
);
const AddMcpServiceModal = dynamic(
  () => import("../../mcp-space/components/add/AddMcpServiceModal"),
  { ssr: false }
);

type DraftRow = { query: string } & (
  | { requirement_id: string; client_key?: never }
  | { client_key: string; requirement_id?: never }
);

type InstallationTarget = {
  requirement_id: string;
  candidate_ref: string;
};
type LinkTarget = {
  requirement_id?: string;
  client_key?: string;
  candidate_ref?: string;
};
type InstalledResource = {
  resource_type: "skill" | "mcp_server";
  resource_id: number;
};
type McpInstallationStatus = "installed" | "disabled";

const requirementAppearance = {
  choose: { Icon: Circle, color: "text-muted-foreground" },
  pending: { Icon: CircleDot, color: "text-primary" },
  ready: { Icon: CircleCheck, color: "text-[var(--color-success)]" },
  unmatched: { Icon: CircleDashed, color: "text-[var(--color-alert)]" },
};

function RelevanceScore({ score }: { score: number }) {
  const { t } = useTranslation("common");
  return (
    <span className="shrink-0 text-muted-foreground tabular-nums">
      {t("nl2agent.coverage.relevanceScore", "Relevance score")}:{" "}
      <span className="text-[var(--color-success)]">
        {Math.round(score * 100)}
      </span>
      {t("nl2agent.coverage.scoreUnit", " points")}
    </span>
  );
}

export interface UnifiedBindingView {
  busy: boolean;
  footer: ReactNode;
  renderResources: (requirementId: string) => ReactNode;
  status: (
    requirementId: string
  ) => "ready" | "pending" | "choose" | "unmatched";
  onAccepted: () => void;
  onEditingChange: (editing: boolean) => void;
  onResourceBusyChange?: (busy: boolean) => void;
}

export function RequirementCoverageCard({
  payload,
  disabled = false,
  binding,
}: {
  payload: Nl2aUnifiedResourcesPayload;
  disabled?: boolean;
  binding: UnifiedBindingView;
}) {
  const { t } = useTranslation("common");
  const aui = useAui();
  const running = useAuiState((state) => state.thread.isRunning);
  const { registerCard, submitCard, isCardInteractive } = useNl2AgentFlow();
  const cardKey = payload.card_id;
  const requirements = payload.requirements;
  const [rows, setRows] = useState<DraftRow[]>(() =>
    requirements.map(({ requirement_id, query }) => ({
      requirement_id,
      query,
    }))
  );
  const [failed, setFailed] = useState(false);
  const [editingRequirements, setEditingRequirements] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [newQuery, setNewQuery] = useState("");
  const [editing, setEditing] = useState<{ key: string; value: string } | null>(
    null
  );
  const [installation, setInstallation] = useState<{
    target: InstallationTarget;
    options: Nl2aSuggestedResourceInstallationPayload;
  } | null>(null);
  const [pendingLink, setPendingLink] = useState<
    (LinkTarget & InstalledResource) | null
  >(null);
  const [installationBusy, setInstallationBusy] = useState(false);
  const [installationError, setInstallationError] = useState(false);
  const [mcpStatuses, setMcpStatuses] = useState<Record<
    string,
    McpInstallationStatus
  > | null>();
  const [linked, setLinked] = useState<string[]>([]);
  const [manual, setManual] = useState<{
    target: LinkTarget;
    type: "skill" | "mcp_server";
  } | null>(null);
  const [pendingMcp, setPendingMcp] = useState<{
    target: LinkTarget;
    name: string;
  } | null>(null);
  useEffect(() => {
    binding.onResourceBusyChange?.(
      Boolean(
        installationBusy || installation || manual || pendingMcp || pendingLink
      )
    );
  }, [
    binding.onResourceBusyChange,
    installationBusy,
    installation,
    manual,
    pendingMcp,
    pendingLink,
  ]);
  const recommendation = payload.purpose === "recommend";
  const hasRepositoryMcp = requirements.some(({ installable_resources }) =>
    installable_resources.some(({ candidate_ref }) =>
      candidate_ref.startsWith("tenant_mcp_repository:")
    )
  );
  const locked =
    disabled || running || !isCardInteractive(cardKey) || binding.busy;
  const resourceLocked = locked || editingRequirements;
  const changed =
    rows.length !== requirements.length ||
    rows.some(
      (row) =>
        row.query.trim() !==
        requirements.find(
          (original) => original.requirement_id === row.requirement_id
        )?.query
    );
  const startEditing = () => {
    if (
      locked ||
      installationBusy ||
      installation ||
      pendingLink ||
      manual ||
      pendingMcp
    )
      return;
    setEditingRequirements(true);
    binding.onEditingChange(true);
  };
  const cancelEditing = () => {
    setRows(
      requirements.map(({ requirement_id, query }) => ({
        requirement_id,
        query,
      }))
    );
    setNewQuery("");
    setEditing(null);
    setEditingRequirements(false);
    binding.onEditingChange(false);
  };
  const refreshInstallationStatus =
    hasRepositoryMcp && !locked && !recommendation;

  useEffect(() => {
    if (!refreshInstallationStatus) return;
    let current = true;
    const controller = new AbortController();
    void fetchWithAuth(
      `${API_ENDPOINTS.mcp.list}?installation_status_only=true`,
      { signal: controller.signal }
    )
      .then(async (response) => {
        if (!response.ok) throw new Error("Installation status unavailable");
        const result = (await response.json()) as {
          remote_mcp_server_list: { market_id: number; enabled: boolean }[];
        };
        if (!current) return;
        const statuses: Record<string, McpInstallationStatus> = {};
        for (const service of result.remote_mcp_server_list) {
          const ref = `tenant_mcp_repository:${service.market_id}`;
          if (statuses[ref] !== "installed") {
            statuses[ref] = service.enabled ? "installed" : "disabled";
          }
        }
        setMcpStatuses(statuses);
      })
      .catch(() => {
        if (current) setMcpStatuses(null);
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [cardKey, refreshInstallationStatus]);

  useEffect(() => {
    if (cardKey && !disabled) registerCard(cardKey, payload.subtype, true);
  }, [cardKey, disabled, failed, payload.subtype, registerCard]);

  const finishEdit = (key: string, value: string) => {
    const query = value.trim();
    if (query) {
      setRows((current) =>
        current.map((row) =>
          (row.requirement_id ?? row.client_key) === key
            ? { ...row, query }
            : row
        )
      );
    }
    setEditing(null);
  };
  const targetKey = (target: LinkTarget) =>
    `${target.requirement_id ?? target.client_key}:${target.candidate_ref ?? ""}`;
  const entries = rows.map((row) => {
    const original = requirements.find(
      (item) => item.requirement_id === row.requirement_id
    );
    const unchanged = original !== undefined && original.query === row.query;
    const target = {
      requirement_id: row.requirement_id,
      client_key: row.client_key,
    };
    return { row, original, unchanged, target };
  });
  const atLimit = rows.length >= 8;
  const addRequirement = () => {
    const query = newQuery.trim();
    if (!query || locked || atLimit) return;
    startEditing();
    setRows((current) => [
      ...current,
      { client_key: crypto.randomUUID(), query },
    ]);
    setNewQuery("");
  };
  const resourceRequest = (url: string, data: object) =>
    fetchWithAuth(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...data,
        agent_id: payload.agent_id,
        conversation_id: Number(payload.conversation_id),
        card_id: cardKey,
        state_version: payload.state_version,
      }),
    });

  const openInstallation = async (target: InstallationTarget) => {
    setInstallationBusy(true);
    setInstallationError(false);
    try {
      const response = await resourceRequest(
        API_ENDPOINTS.agent.nl2agentResourceInstallations,
        target
      );
      if (!response.ok) throw new Error("Installation details unavailable");
      const options =
        (await response.json()) as Nl2aSuggestedResourceInstallationPayload & {
          installation_status?: McpInstallationStatus;
        };
      if (options.installation_status) {
        const status = options.installation_status;
        setMcpStatuses((current) => ({
          ...current,
          [target.candidate_ref]: status,
        }));
        return;
      }
      if (options.resources.length !== 1)
        throw new Error("Missing installation resource");
      setInstallation({ target, options });
    } catch {
      setInstallationError(true);
    } finally {
      setInstallationBusy(false);
    }
  };

  const registerInstallation = async (data: LinkTarget & InstalledResource) => {
    setPendingLink(data);
    setInstallationBusy(true);
    setInstallationError(false);
    try {
      const response = await resourceRequest(
        API_ENDPOINTS.agent.nl2agentResourceLinks,
        data
      );
      if (!response.ok) throw new Error("Installed resource was not linked");
      setLinked((current) => [...current, targetKey(data)]);
      setPendingLink(null);
      setInstallation(null);
    } catch {
      setInstallationError(true);
    } finally {
      setInstallationBusy(false);
    }
  };

  const resolveCreatedMcp = async (target: LinkTarget, name: string) => {
    setPendingMcp({ target, name });
    setInstallationBusy(true);
    setInstallationError(false);
    try {
      const result = await listMcpTools();
      const record = result.data.find((item) => item.name === name);
      if (!record || !Number.isSafeInteger(record.mcpId) || record.mcpId <= 0) {
        throw new Error("Persisted MCP service has not been resolved");
      }
      setPendingMcp(null);
      await registerInstallation({
        ...target,
        resource_type: "mcp_server",
        resource_id: record.mcpId,
      });
    } catch {
      setInstallationError(true);
    } finally {
      setInstallationBusy(false);
    }
  };

  const runInstallationAttempt = async (
    target: InstallationTarget,
    input: InstallationAttemptInput
  ) => {
    const response = await resourceRequest(
      API_ENDPOINTS.agent.nl2agentResourceInstallationAttempts,
      {
        ...target,
        ...input,
      }
    );
    return (await response.json()) as InstallationAttemptResult;
  };

  const submit = () => {
    if (locked || editing || !cardKey || !payload.state_version) return;
    setFailed(false);
    const result = {
      card_id: cardKey,
      state_version: payload.state_version,
      requirements: rows,
    };
    const action: Nl2AgentCardAction = {
      type: "nl2agent_card_action",
      subtype: payload.subtype,
      agent_id: payload.agent_id,
      action: "confirm_requirements",
      result,
    };
    aui.thread().append({
      runConfig: nl2AgentCardRunConfig(
        aui.thread().composer().getState().runConfig,
        payload.agent_id,
        {
          onAccepted: () => {
            binding.onAccepted();
            submitCard(cardKey);
          },
          onRejected: () => setFailed(true),
        }
      ),
      role: "user",
      content: [
        {
          type: "text",
          text: t("nl2agent.unified.update"),
        },
      ],
      metadata: { custom: { nl2agentCardAction: action } },
      startRun: true,
    });
  };

  return (
    <section
      className="bg-card text-sm text-foreground"
      data-testid={payload.subtype}
    >
      <header className="flex items-start justify-between gap-3 border-b bg-muted/25 px-4 py-3.5">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-primary">
            <ListChecks className="size-4" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h3 className="font-semibold">{t("nl2agent.unified.title")}</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {t("nl2agent.unified.description")}
            </p>
          </div>
        </div>
        <span
          aria-live="polite"
          className="shrink-0 pt-1 text-xs tabular-nums text-muted-foreground"
        >
          {t("nl2agent.unified.total", { count: rows.length })}
        </span>
      </header>
      {!editingRequirements ? (
        <div
          className="flex flex-wrap gap-4 border-b px-4 py-2 text-xs"
          aria-live="polite"
        >
          {(["choose", "pending", "ready", "unmatched"] as const).map(
            (state) => {
              const { Icon, color } = requirementAppearance[state];
              return (
                <span key={state} className="inline-flex items-center gap-1.5">
                  <Icon
                    className={`size-3.5 shrink-0 ${color}`}
                    aria-hidden="true"
                  />
                  {t(`nl2agent.unified.status.${state}`)}{" "}
                  {
                    requirements.filter(
                      (row) => binding.status(row.requirement_id) === state
                    ).length
                  }
                </span>
              );
            }
          )}
        </div>
      ) : null}
      {editingRequirements ? (
        <p role="status" className="border-b bg-brand-soft px-4 py-2 text-xs">
          {t("nl2agent.unified.editingNotice")}
        </p>
      ) : null}
      <ul className="divide-y divide-border">
        {entries.map(({ row, original, unchanged, target }, index) => {
          const rowKey = row.requirement_id ?? row.client_key;
          const phase = binding.status(rowKey);
          const { Icon, color } = requirementAppearance[phase];
          const resources = original?.installable_resources ?? [];
          const rowExpanded = expanded[rowKey] !== false;
          return (
            <li
              key={rowKey}
              className="nl2agent-requirement-row grid grid-cols-[auto_minmax(0,1fr)] items-start gap-3 px-4 py-3"
            >
              <span
                className={`flex size-5 items-center justify-center rounded-full ${color}`}
                aria-label={t(`nl2agent.unified.status.${phase}`)}
                role="img"
              >
                <Icon className="size-4" aria-hidden="true" />
              </span>
              <div className="min-w-0 space-y-1.5">
                <div className="flex items-start gap-2">
                  {editing?.key === rowKey ? (
                    <Input
                      autoFocus
                      aria-label={t(
                        "nl2agent.coverage.requirement",
                        "Requirement"
                      )}
                      className="h-7 min-w-0 flex-1 text-xs md:text-xs"
                      maxLength={500}
                      disabled={locked}
                      value={editing.value}
                      onChange={(event) =>
                        setEditing({ key: rowKey, value: event.target.value })
                      }
                      onBlur={(event) =>
                        finishEdit(rowKey, event.currentTarget.value)
                      }
                      onKeyDown={(event) => {
                        if (event.nativeEvent.isComposing) return;
                        if (event.key === "Enter") {
                          event.preventDefault();
                          event.currentTarget.blur();
                        } else if (event.key === "Escape") {
                          event.preventDefault();
                          setEditing(null);
                        }
                      }}
                    />
                  ) : (
                    <p className="min-w-0 flex-1 whitespace-pre-wrap break-words text-[13px] font-semibold">
                      {row.query}
                    </p>
                  )}
                  {!locked ? (
                    <div className="nl2agent-requirement-actions -my-1 flex shrink-0 items-center">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="size-7 text-muted-foreground"
                        aria-label={t(
                          "nl2agent.coverage.edit",
                          "Edit requirement"
                        )}
                        disabled={
                          editing?.key === rowKey ||
                          Boolean(installation) ||
                          installationBusy
                        }
                        onClick={() => {
                          startEditing();
                          setEditing({ key: rowKey, value: row.query });
                        }}
                      >
                        <Pencil className="size-3.5" aria-hidden="true" />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="size-7 text-muted-foreground"
                        aria-label={t("nl2agent.coverage.remove", "Remove")}
                        disabled={Boolean(installation) || installationBusy}
                        onClick={() => {
                          startEditing();
                          setRows((current) =>
                            current.filter((_, i) => i !== index)
                          );
                        }}
                      >
                        <Trash2 className="size-3.5" aria-hidden="true" />
                      </Button>
                    </div>
                  ) : null}
                </div>
                <div className="relative min-h-5 flex items-center">
                  <button
                    type="button"
                    className="absolute -left-9 top-1/2 -translate-y-1/2 inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={t("nl2agent.unified.toggleDetails", {
                      query: row.query,
                    })}
                    aria-expanded={rowExpanded}
                    onClick={() =>
                      setExpanded((current) => ({
                        ...current,
                        [rowKey]: !rowExpanded,
                      }))
                    }
                  >
                    {rowExpanded ? (
                      <ChevronDown className="size-4" aria-hidden="true" />
                    ) : (
                      <ChevronRight className="size-4" aria-hidden="true" />
                    )}
                  </button>
                  {original?.search_queries ? (
                    <p className="text-xs text-muted-foreground">
                      {original.search_queries.zh} ·{" "}
                      {original.search_queries.en}
                    </p>
                  ) : null}
                </div>
                <div hidden={!rowExpanded} className="space-y-1.5">
                  {original?.covered_resources.length
                    ? binding.renderResources(rowKey)
                    : null}
                  {!unchanged ? (
                    <p className="text-xs text-muted-foreground">
                      {t("nl2agent.unified.pendingMatch")}
                    </p>
                  ) : null}
                  {resources.length ? (
                    <div className="flex items-start gap-2">
                      <span className="inline-flex shrink-0 items-center gap-1 text-[11px] leading-5 text-muted-foreground">
                        <Target className="size-3" aria-hidden="true" />
                        {t(
                          "nl2agent.coverage.relatedResources",
                          "Related resources"
                        )}
                      </span>
                      <ul className="min-w-0 flex-1 space-y-1.5">
                        {resources.map((resource) => {
                          const installTarget = {
                            ...target,
                            candidate_ref: resource.candidate_ref,
                          };
                          const alreadyLinked = linked.includes(
                            targetKey(installTarget)
                          );
                          const requirementId = target.requirement_id;
                          const repositoryMcp =
                            resource.candidate_ref.startsWith(
                              "tenant_mcp_repository:"
                            );
                          const installationStatus =
                            repositoryMcp &&
                            refreshInstallationStatus &&
                            mcpStatuses
                              ? mcpStatuses[resource.candidate_ref]
                              : resource.installation_status;
                          const activeInstallation =
                            installation &&
                            targetKey(installation.target) ===
                              targetKey(installTarget)
                              ? installation
                              : null;
                          const canInstall =
                            !recommendation &&
                            !editingRequirements &&
                            !installationStatus &&
                            original?.installable_resources.some(
                              (candidate) =>
                                candidate.candidate_ref ===
                                resource.candidate_ref
                            );
                          const resourceKind =
                            resource.resource_type === "mcp_server" ||
                            resource.source === "MCP_TOOL"
                              ? "MCP"
                              : resource.resource_type === "skill" ||
                                  resource.candidate_ref.startsWith("skill:")
                                ? "Skill"
                                : resource.resource_type === "tool" ||
                                    resource.candidate_ref.startsWith("tool:")
                                  ? "Tool"
                                  : null;
                          return (
                            <li
                              key={resource.candidate_ref}
                              className="flex min-h-5 flex-wrap items-center justify-between gap-x-3 gap-y-1"
                            >
                              <div className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-xs">
                                {resourceKind ? (
                                  <Nl2AgentResourceKindBadge
                                    kind={resourceKind}
                                  />
                                ) : null}
                                <span className="inline-flex min-w-0 items-center gap-1.5">
                                  <span
                                    className="break-all"
                                  >
                                    {resource.name}
                                  </span>
                                  {typeof resource.retrieval_score ===
                                    "number" &&
                                  Number.isFinite(resource.retrieval_score) ? (
                                    <RelevanceScore
                                      score={resource.retrieval_score}
                                    />
                                  ) : null}
                                </span>
                              </div>
                              {activeInstallation ? (
                                <SuggestedResourceInstallationCard
                                  key={targetKey(activeInstallation.target)}
                                  payload={activeInstallation.options}
                                  disabled={
                                    resourceLocked ||
                                    installationBusy ||
                                    Boolean(pendingLink)
                                  }
                                  onInstalled={(resource) =>
                                    void registerInstallation({
                                      ...activeInstallation.target,
                                      ...resource,
                                    })
                                  }
                                  installationAttempt={(input) =>
                                    runInstallationAttempt(
                                      activeInstallation.target,
                                      input
                                    )
                                  }
                                  onCloseInline={() => setInstallation(null)}
                                />
                              ) : installationStatus || alreadyLinked ? (
                                <span className="text-xs text-muted-foreground">
                                  {installationStatus === "disabled"
                                    ? t(
                                        "nl2agent.coverage.installedDisabled",
                                        "Installed, disabled"
                                      )
                                    : t(
                                        "nl2agent.coverage.installed",
                                        "Installed"
                                      )}
                                </span>
                              ) : canInstall && requirementId ? (
                                <Button
                                  type="button"
                                  size="sm"
                                  className="h-6 px-2 text-xs"
                                  disabled={
                                    resourceLocked ||
                                    installationBusy ||
                                    Boolean(installation || pendingLink) ||
                                    (repositoryMcp &&
                                      mcpStatuses === undefined) ||
                                    Boolean(editing)
                                  }
                                  aria-label={t(
                                    "nl2agent.coverage.install",
                                    "Install {{resource}}",
                                    { resource: resource.name }
                                  )}
                                  onClick={() =>
                                    void openInstallation({
                                      requirement_id: requirementId,
                                      candidate_ref: resource.candidate_ref,
                                    })
                                  }
                                >
                                  {t("nl2agent.coverage.installAction")}
                                </Button>
                              ) : null}
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  ) : null}
                  <div
                    className={
                      phase === "unmatched"
                        ? "space-y-2 rounded-xl border border-dashed border-[var(--color-alert)] bg-[var(--color-alert-subtler)]/60 p-3"
                        : "flex flex-wrap items-center gap-x-2 gap-y-1"
                    }
                  >
                    <p
                      className={
                        phase === "unmatched"
                          ? "text-xs text-foreground"
                          : "text-xs text-muted-foreground"
                      }
                    >
                      {phase === "unmatched"
                        ? t("nl2agent.unified.unmatchedTitle")
                        : t("nl2agent.unified.otherResources")}
                    </p>
                    {phase === "unmatched" ? (
                      <p className="text-xs text-muted-foreground">
                        {t("nl2agent.unified.unmatchedDescription")}
                      </p>
                    ) : null}
                    {!recommendation ? (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Button
                          type="button"
                          size="sm"
                          variant={phase !== "unmatched" ? "link" : "outline"}
                          className={
                            phase !== "unmatched"
                              ? "h-auto p-0 text-[11px] font-normal"
                              : "h-6 gap-1 px-2 text-xs"
                          }
                          disabled={
                            resourceLocked ||
                            installationBusy ||
                            Boolean(
                              manual ||
                              pendingLink ||
                              pendingMcp ||
                              installation
                            )
                          }
                          onClick={() => setManual({ target, type: "skill" })}
                        >
                          {phase === "unmatched" ? (
                            <Sparkles className="size-3" aria-hidden="true" />
                          ) : null}
                          {t("nl2agent.coverage.createSkill", "Create Skill")}
                        </Button>
                        {phase !== "unmatched" ? (
                          <span
                            aria-hidden="true"
                            className="text-[11px] text-muted-foreground"
                          >
                            /
                          </span>
                        ) : null}
                        <Button
                          type="button"
                          size="sm"
                          variant={phase !== "unmatched" ? "link" : "outline"}
                          className={
                            phase !== "unmatched"
                              ? "h-auto p-0 text-[11px] font-normal"
                              : "h-6 gap-1 px-2 text-xs"
                          }
                          disabled={
                            resourceLocked ||
                            installationBusy ||
                            Boolean(
                              manual ||
                              pendingLink ||
                              pendingMcp ||
                              installation
                            )
                          }
                          onClick={() =>
                            setManual({ target, type: "mcp_server" })
                          }
                        >
                          {phase === "unmatched" ? (
                            <Plug className="size-3" aria-hidden="true" />
                          ) : null}
                          {t("nl2agent.unified.createMcp")}
                        </Button>
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      {!locked ? (
        <div className="flex items-center gap-2 border-t px-4 py-2">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7 shrink-0"
            aria-label={t("nl2agent.coverage.add", "Add requirement")}
            disabled={atLimit}
            onClick={() => {
              startEditing();
              if (newQuery.trim()) addRequirement();
            }}
          >
            <Plus className="size-4" aria-hidden="true" />
          </Button>
          {editingRequirements ? (
            <input
              type="text"
              aria-label={t("nl2agent.coverage.add", "Add requirement")}
              className="h-8 min-w-0 flex-1 rounded-md bg-transparent text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              placeholder={
                atLimit
                  ? t("nl2agent.coverage.limit")
                  : t("nl2agent.coverage.addPlaceholder")
              }
              maxLength={500}
              disabled={atLimit}
              value={newQuery}
              onChange={(event) => setNewQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter" || event.nativeEvent.isComposing)
                  return;
                event.preventDefault();
                addRequirement();
              }}
            />
          ) : (
            <button
              type="button"
              className="text-[13px] text-primary"
              onClick={startEditing}
            >
              {t("nl2agent.coverage.add", "Add requirement")}
            </button>
          )}
        </div>
      ) : null}
      {manual?.type === "skill" ? (
        <SkillBuildModal
          isOpen
          onCancel={() => setManual(null)}
          onSuccess={() => undefined}
          onCreated={(resource_id) =>
            void registerInstallation({
              ...manual.target,
              resource_type: "skill",
              resource_id,
            })
          }
        />
      ) : null}
      {manual?.type === "mcp_server" ? (
        <AddMcpServiceModal
          open
          onClose={() => setManual(null)}
          onCreated={(name, mcpId) => {
            if (mcpId) {
              void registerInstallation({
                ...manual.target,
                resource_type: "mcp_server",
                resource_id: mcpId,
              });
            } else {
              void resolveCreatedMcp(manual.target, name);
            }
          }}
        />
      ) : null}
      {installationError ? (
        <p role="alert" className="border-t px-4 py-2 text-xs text-destructive">
          {t(
            "nl2agent.coverage.installFailed",
            "The installation details or association could not be loaded."
          )}
          {pendingLink ? (
            <Button
              size="sm"
              variant="ghost"
              disabled={installationBusy}
              onClick={() => void registerInstallation(pendingLink)}
            >
              {t("common.retry", "Retry")}
            </Button>
          ) : null}
          {pendingMcp ? (
            <Button
              size="sm"
              variant="ghost"
              disabled={installationBusy}
              onClick={() =>
                void resolveCreatedMcp(pendingMcp.target, pendingMcp.name)
              }
            >
              {t("common.retry", "Retry")}
            </Button>
          ) : null}
          {pendingLink || pendingMcp ? (
            <Button
              size="sm"
              variant="ghost"
              disabled={installationBusy}
              onClick={() => {
                setPendingLink(null);
                setPendingMcp(null);
                setInstallation(null);
                setInstallationError(false);
              }}
            >
              {t("common.cancel", "Cancel")}
            </Button>
          ) : null}
        </p>
      ) : null}
      {failed ? (
        <p role="alert" className="border-t px-4 py-2 text-xs text-destructive">
          {t(
            "nl2agent.coverage.submitFailed",
            "Could not confirm this card. Try again or request a new search."
          )}
        </p>
      ) : null}
      {!editingRequirements && !linked.length ? (
        binding.footer
      ) : (
        <footer className="flex justify-end border-t bg-muted/25 px-4 py-2.5">
          {editingRequirements ? (
            <Button
              variant="outline"
              size="sm"
              className="mr-2 h-7 text-xs"
              disabled={locked}
              onClick={cancelEditing}
            >
              {t("nl2agent.unified.cancel")}
            </Button>
          ) : null}
          <Button
            type="button"
            size="sm"
            className="h-7 gap-1.5 px-2.5 py-0 text-xs [&_svg]:size-3.5"
            onClick={submit}
            disabled={
              locked ||
              (!changed && !linked.length) ||
              Boolean(editing) ||
              rows.length > 8 ||
              Boolean(
                newQuery.trim() ||
                installation ||
                pendingLink ||
                pendingMcp ||
                manual
              ) ||
              installationBusy ||
              rows.some((row) => !row.query.trim())
            }
          >
            {rows.length === 0
              ? t(
                  recommendation
                    ? "nl2agent.unified.clear"
                    : "nl2agent.unified.noResources"
                )
              : t(
                  linked.length && !changed
                    ? "nl2agent.unified.verify"
                    : "nl2agent.unified.update"
                )}
            <ArrowRight className="size-3.5" aria-hidden="true" />
          </Button>
        </footer>
      )}
    </section>
  );
}
