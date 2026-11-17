// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useAui, useAuiState } from "@assistant-ui/react";
import { useTranslation } from "react-i18next";
import {
  ArrowRight,
  Check,
  Clock3,
  Download,
  ListChecks,
  Pencil,
  Plus,
  Plug,
  Sparkles,
  Target,
  Trash2,
  TriangleAlert,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import { fetchWithAuth } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";
import { listMcpTools } from "@/services/mcpToolsService";
import type {
  Nl2AgentCardAction,
  Nl2aCoveragePayload,
  Nl2aRequirementClarificationPayload,
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

type EditablePayload =
  Nl2aCoveragePayload | Nl2aRequirementClarificationPayload;

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

const coverageAppearance = {
  covered: { Icon: Check, color: "bg-[var(--color-success)] text-white" },
  installable: { Icon: Download, color: "bg-brand-soft text-primary" },
  uncovered: {
    Icon: TriangleAlert,
    color: "bg-[var(--color-warning-subtler)] text-[var(--color-warning-bold)]",
  },
  pending: { Icon: Clock3, color: "bg-muted text-muted-foreground" },
};

function RelevanceSignal({ score }: { score: number }) {
  const { t } = useTranslation("common");
  const level = score >= 0.85 ? 3 : score >= 0.6 ? 2 : 1;
  const label =
    level === 3
      ? t("nl2agent.coverage.relevanceHigh", "High relevance")
      : level === 2
        ? t("nl2agent.coverage.relevanceMedium", "Medium relevance")
        : t("nl2agent.coverage.relevanceLow", "Low relevance");
  return (
    <span
      className="inline-flex h-3 shrink-0 items-end gap-px"
      role="img"
      aria-label={label}
      title={label}
    >
      {["h-1", "h-2", "h-3"].map((height, index) => (
        <span
          key={height}
          aria-hidden="true"
          className={`w-1 rounded-[1px] ${height} ${index < level ? "bg-[var(--color-success)]" : "bg-border"}`}
        />
      ))}
    </span>
  );
}

export function RequirementCoverageCard({
  payload,
  disabled = false,
  readOnly = false,
}: {
  payload: EditablePayload;
  disabled?: boolean;
  readOnly?: boolean;
}) {
  const { t } = useTranslation("common");
  const aui = useAui();
  const running = useAuiState((state) => state.thread.isRunning);
  const { registerCard, submitCard, isCardInteractive } = useNl2AgentFlow();
  const cardKey = payload.card_id ?? "";
  const requirements = payload.requirements ?? [];
  const [rows, setRows] = useState<DraftRow[]>(() =>
    requirements.map(({ requirement_id, query }) => ({
      requirement_id,
      query,
    }))
  );
  const [failed, setFailed] = useState(false);
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
  const recommendation = payload.subtype === "resource_recommendation";
  const clarification = payload.subtype === "requirement_clarification";
  const hasRepositoryMcp = requirements.some(({ installable_resources }) =>
    installable_resources.some(({ candidate_ref }) =>
      candidate_ref.startsWith("tenant_mcp_repository:")
    )
  );
  const locked = readOnly || disabled || running || !isCardInteractive(cardKey);
  const refreshInstallationStatus =
    hasRepositoryMcp && !locked && !recommendation && !clarification;

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
    if (cardKey && !readOnly && !disabled)
      registerCard(cardKey, payload.subtype, true);
  }, [cardKey, disabled, failed, payload.subtype, readOnly, registerCard]);

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
  const title = recommendation
    ? t("nl2agent.coverage.recommendation", "Recommended resources")
    : clarification
      ? t("nl2agent.requirementClarification.title", "Clarify requirements")
      : t("nl2agent.coverage.title", "Review resource coverage");
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
    const awaitingVerification = [
      target,
      ...(original?.installable_resources ?? []).map(({ candidate_ref }) => ({
        ...target,
        candidate_ref,
      })),
    ].some((resource) => linked.includes(targetKey(resource)));
    const status: keyof typeof coverageAppearance =
      unchanged && !awaitingVerification ? original.coverage_status : "pending";
    return { row, original, unchanged, target, status };
  });
  const covered = entries.filter(({ status }) => status === "covered").length;
  const atLimit = rows.length >= 8;
  const addRequirement = () => {
    const query = newQuery.trim();
    if (!query || locked || atLimit) return;
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
      ...(!recommendation ? { requirements: rows } : {}),
    };
    const action: Nl2AgentCardAction = {
      type: "nl2agent_card_action",
      subtype: payload.subtype,
      agent_id: payload.agent_id,
      action: recommendation ? "use_recommendation" : "confirm_requirements",
      result,
    };
    aui.thread().append({
      runConfig: nl2AgentCardRunConfig(
        aui.thread().composer().getState().runConfig,
        payload.agent_id,
        {
          onAccepted: () => submitCard(cardKey),
          onRejected: () => setFailed(true),
        }
      ),
      role: "user",
      content: [
        {
          type: "text",
          text: t("nl2agent.coverage.confirm", "Confirm requirements"),
        },
      ],
      metadata: { custom: { nl2agentCardAction: action } },
      startRun: true,
    });
  };

  return (
    <section
      className="my-4 overflow-hidden rounded-2xl border border-border bg-card text-sm text-foreground shadow-sm"
      data-testid={payload.subtype}
    >
      <header className="flex items-start justify-between gap-3 border-b bg-muted/25 px-4 py-3.5">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-primary">
            <ListChecks className="size-4" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h3 className="font-semibold">{title}</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {clarification
                ? t("nl2agent.coverage.clarificationDescription")
                : t("nl2agent.coverage.description")}
            </p>
          </div>
        </div>
        <span
          aria-live="polite"
          className="shrink-0 pt-1 text-xs tabular-nums text-muted-foreground"
        >
          {t("nl2agent.coverage.progress", { covered, total: rows.length })}
        </span>
      </header>
      <ul className="divide-y divide-border">
        {entries.map(({ row, original, unchanged, target, status }, index) => {
          const rowKey = row.requirement_id ?? row.client_key;
          const { Icon, color } = coverageAppearance[status];
          const resources = unchanged
            ? [
                ...(original?.covered_resources ?? []),
                ...(original?.installable_resources ?? []),
              ]
            : [];
          const coveredStatus =
            status === "covered" ? (
              <span className="ml-auto shrink-0 whitespace-nowrap text-xs leading-5 text-muted-foreground">
                {t("nl2agent.coverage.covered", "Covered")}
              </span>
            ) : null;
          return (
            <li
              key={rowKey}
              className="nl2agent-requirement-row grid grid-cols-[auto_minmax(0,1fr)] items-start gap-3 px-4 py-3"
            >
              <span
                className={`mt-0.5 flex size-5 items-center justify-center rounded-full ${color}`}
              >
                <Icon className="size-3" aria-hidden="true" />
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
                    <p className="min-w-0 flex-1 whitespace-pre-wrap break-words text-xs font-semibold">
                      {row.query}
                    </p>
                  )}
                  {resources.length === 0 ? coveredStatus : null}
                  {!recommendation && !locked ? (
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
                        onClick={() =>
                          setEditing({ key: rowKey, value: row.query })
                        }
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
                        onClick={() =>
                          setRows((current) =>
                            current.filter((_, i) => i !== index)
                          )
                        }
                      >
                        <Trash2 className="size-3.5" aria-hidden="true" />
                      </Button>
                    </div>
                  ) : null}
                </div>
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
                        const repositoryMcp = resource.candidate_ref.startsWith(
                          "tenant_mcp_repository:"
                        );
                        const installationStatus =
                          repositoryMcp && refreshInstallationStatus && mcpStatuses
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
                          !clarification &&
                          !installationStatus &&
                          original?.installable_resources.some(
                            (candidate) =>
                              candidate.candidate_ref === resource.candidate_ref
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
                                <span className="break-all">
                                  {resource.name}
                                </span>
                                {typeof resource.retrieval_score === "number" &&
                                Number.isFinite(resource.retrieval_score) ? (
                                  <RelevanceSignal
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
                                  locked ||
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
                                  locked ||
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
                    {coveredStatus}
                  </div>
                ) : null}
                {status === "uncovered" || status === "pending" ? (
                  <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                    <p
                      className={
                        status === "uncovered"
                          ? "text-xs text-[var(--color-warning-bold)] dark:text-muted-foreground"
                          : "text-xs text-muted-foreground"
                      }
                    >
                      {status === "uncovered"
                        ? t(
                            "nl2agent.coverage.uncovered",
                            "No confirmed resource"
                          )
                        : t(
                            "nl2agent.coverage.pending",
                            "Pending verification"
                          )}
                    </p>
                    {!recommendation && !locked && status === "uncovered" ? (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-6 gap-1 px-2 text-xs"
                          disabled={
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
                          <Sparkles className="size-3" aria-hidden="true" />
                          {t("nl2agent.coverage.createSkill", "Create Skill")}
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-6 gap-1 px-2 text-xs"
                          disabled={
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
                          <Plug className="size-3" aria-hidden="true" />
                          {t("nl2agent.coverage.addMcp", "Add MCP")}
                        </Button>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
      {!recommendation && !locked ? (
        <div className="flex items-center gap-2 border-t px-4 py-2">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7 shrink-0"
            aria-label={t("nl2agent.coverage.add", "Add requirement")}
            disabled={atLimit || !newQuery.trim()}
            onClick={addRequirement}
          >
            <Plus className="size-4" aria-hidden="true" />
          </Button>
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
      <footer className="flex justify-end border-t bg-muted/25 px-4 py-2.5">
        <Button
          type="button"
          size="sm"
          className="h-7 gap-1.5 px-2.5 py-0 text-xs [&_svg]:size-3.5"
          onClick={submit}
          disabled={
            locked ||
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
          {recommendation
            ? t("nl2agent.coverage.use", "Use recommended resources")
            : t("nl2agent.coverage.confirm", "Confirm requirements")}
          <ArrowRight className="size-3.5" aria-hidden="true" />
        </Button>
      </footer>
    </section>
  );
}
