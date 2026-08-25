"use client";

import { useEffect, useId, useMemo, useReducer, useRef, useState } from "react";
import { useAui } from "@assistant-ui/react";
import { useQueryClient } from "@tanstack/react-query";
import { App, Input, InputNumber, Modal, Select } from "antd";
import dynamic from "next/dynamic";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  Loader2,
  Pencil,
  RefreshCw,
  Settings2,
  SkipForward,
  WandSparkles,
  Wrench,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MCP_TOOLS_QUERY_KEYS, McpSource } from "@/const/mcpTools";
import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import { MCP_SERVERS_QUERY_KEY } from "@/hooks/mcp/useMcpServerList";
import { refreshToolListWithToast } from "@/hooks/mcpTools/useRefreshToolListWithToast";
import {
  addContainerMcpToolService,
  addMcpToolService,
  checkMcpContainerPortConflictService,
  incrementCommunityMcpDownloadCount,
  listMcpTools,
  parseContainerMcpConfigJson,
  suggestMcpContainerPortService,
} from "@/services/mcpToolsService";
import {
  type CreatedSkillResult,
  installOfficialSkills,
  fetchOfficialSkillsWithStatus,
} from "@/services/skillService";
import skillRepositoryService from "@/services/skillRepositoryService";
import { toApiError, type ApiError } from "@/services/api";
import {
  recordNl2AgentSkillCreationEvent,
  type Nl2AgentSkillCreationEvent,
} from "@/services/nl2AgentService";
import type { CommunityQuickAddDraft } from "@/types/mcpTools";
import type {
  Nl2AgentCardAction,
  Nl2aInstallableResource,
  Nl2aResourceCandidate,
  Nl2aResourceInstallationOption,
  Nl2aSkillCreationRequest,
  Nl2aSuggestedResourceInstallationPayload,
  Nl2aWeakSkillResource,
} from "../adapter/remote-chat-model-adapter";
import { Nl2AgentResourceSourceBadge } from "./nl2agent-resource-source-badge";

const SkillBuildModal = dynamic(
  () => import("../../agents/components/agentConfig/SkillBuildModal")
);

type InstallationStatus =
  | "not_started"
  | "configuring"
  | "installing"
  | "installed"
  | "failed"
  | "skipped";

interface InstallationDraft {
  optionId: string;
  targetName: string;
  name: string;
  serverUrl: string;
  authorizationToken: string;
  customHeaders: string;
  containerConfigJson: string;
  containerPort?: number;
}

interface InstallationItem {
  resource: Nl2aInstallableResource | Nl2aWeakSkillResource;
  status: InstallationStatus;
  draft: InstallationDraft;
  resourceId?: number;
  error?: ApiError;
  skipReason?: "not_selected" | "install_failed" | "user_skipped";
}

type InstallationAction =
  | { type: "configure"; ref: string }
  | {
      type: "cancel_config";
      ref: string;
      status: "not_started" | "failed";
    }
  | {
      type: "save_config";
      ref: string;
      draft: InstallationDraft;
      status: "not_started" | "failed";
    }
  | { type: "install"; ref: string }
  | { type: "installed"; ref: string; resourceId: number }
  | { type: "failed"; ref: string; error: ApiError }
  | {
      type: "skip";
      ref: string;
      reason: "install_failed" | "user_skipped";
    }
  | {
      type: "accept_weak_resource";
      resource: Nl2aWeakSkillResource;
      requirementId: string;
    };

const candidateRef = (item: InstallationItem) =>
  item.resource.candidate.candidate_ref;

const installedCandidateRef = (item: InstallationItem): string =>
  item.resource.candidate.resource_type === "skill" && item.resourceId
    ? `skill:${item.resourceId}`
    : candidateRef(item);

const optionConfig = (
  option: Nl2aResourceInstallationOption
): Record<string, unknown> =>
  !Array.isArray(option.config) && option.config ? option.config : {};

const uniqueValues = (values: string[]): string[] => [...new Set(values)];

const mergeCandidateCoverage = (
  current: Nl2aResourceCandidate,
  added: Nl2aResourceCandidate
): Nl2aResourceCandidate => ({
  ...current,
  requirement_ids: uniqueValues([
    ...current.requirement_ids,
    ...added.requirement_ids,
  ]),
  user_confirmed_requirement_ids: uniqueValues([
    ...current.user_confirmed_requirement_ids,
    ...added.user_confirmed_requirement_ids,
  ]),
});

const confirmCandidateRequirement = (
  candidate: Nl2aResourceCandidate,
  requirementId: string
): Nl2aResourceCandidate => ({
  ...candidate,
  requirement_ids: uniqueValues([...candidate.requirement_ids, requirementId]),
  user_confirmed_requirement_ids: uniqueValues([
    ...candidate.user_confirmed_requirement_ids,
    requirementId,
  ]),
});

const candidateInstalledSkillId = (ref: string): number | undefined => {
  if (!ref.startsWith("skill:")) return undefined;
  const skillId = Number(ref.slice("skill:".length));
  return Number.isInteger(skillId) && skillId > 0 ? skillId : undefined;
};

const initialDraft = (
  resource: Nl2aInstallableResource | Nl2aWeakSkillResource
): InstallationDraft => {
  const optionId = resource.default_option_id || "";
  const option = resource.installation_options.find(
    (item) => item.option_id === optionId
  );
  const config = option ? optionConfig(option) : {};
  const targetParam = Array.isArray(option?.config)
    ? option.config.find((item) => item.name === "target_name")
    : undefined;
  return {
    optionId,
    targetName:
      targetParam && targetParam.value != null
        ? String(targetParam.value)
        : resource.candidate.name,
    name: String(config.name || resource.candidate.name),
    serverUrl: String(config.serverUrl || ""),
    authorizationToken: "",
    customHeaders: "",
    containerConfigJson: String(config.containerConfigJson || ""),
    containerPort:
      typeof config.containerPort === "number"
        ? config.containerPort
        : undefined,
  };
};

const initializeItems = (
  resources: Nl2aInstallableResource[]
): InstallationItem[] =>
  resources.map((resource) => ({
    resource,
    status: "not_started",
    draft: initialDraft(resource),
  }));

const initializeWeakResource = (
  resource: Nl2aWeakSkillResource
): InstallationItem => {
  const resourceId = candidateInstalledSkillId(
    resource.candidate.candidate_ref
  );
  return {
    resource,
    status: resourceId ? "installed" : "not_started",
    draft: initialDraft(resource),
    resourceId,
  };
};

function reducer(
  state: InstallationItem[],
  action: InstallationAction
): InstallationItem[] {
  if (action.type === "accept_weak_resource") {
    const acceptedCandidate = confirmCandidateRequirement(
      action.resource.candidate,
      action.requirementId
    );
    const existing = state.find(
      (item) => candidateRef(item) === acceptedCandidate.candidate_ref
    );
    if (!existing) {
      return [
        ...state,
        initializeWeakResource({
          ...action.resource,
          candidate: acceptedCandidate,
          recommendation: "recommended",
        }),
      ];
    }
    return state.map((item) =>
      candidateRef(item) === acceptedCandidate.candidate_ref
        ? {
            ...item,
            status: item.status === "skipped" ? "not_started" : item.status,
            skipReason: undefined,
            resource: {
              ...item.resource,
              candidate: mergeCandidateCoverage(
                item.resource.candidate,
                acceptedCandidate
              ),
              recommendation: "recommended",
            },
          }
        : item
    );
  }
  return state.map((item) => {
    if (candidateRef(item) !== action.ref) return item;
    switch (action.type) {
      case "configure":
        return { ...item, status: "configuring" };
      case "cancel_config":
        return { ...item, status: action.status };
      case "save_config":
        return {
          ...item,
          status: action.status,
          draft: action.draft,
          error: undefined,
        };
      case "install":
        return { ...item, status: "installing", error: undefined };
      case "installed":
        return {
          ...item,
          status: "installed",
          resourceId: action.resourceId,
          error: undefined,
        };
      case "failed":
        return { ...item, status: "failed", error: action.error };
      case "skip":
        return {
          ...item,
          status: "skipped",
          skipReason: action.reason,
          error: undefined,
        };
    }
  });
}

const parsePositiveId = (ref: string, prefix: string): number => {
  if (!ref.startsWith(`${prefix}:`)) throw new Error("Invalid resource ID");
  const value = Number(ref.slice(prefix.length + 1));
  if (!Number.isInteger(value) || value <= 0) {
    throw new Error("Invalid resource ID");
  }
  return value;
};

const decodeCandidateName = (ref: string, prefix: string): string => {
  if (!ref.startsWith(`${prefix}:`)) throw new Error("Invalid resource name");
  const name = decodeURIComponent(ref.slice(prefix.length + 1));
  if (!name) throw new Error("Invalid resource name");
  return name;
};

const requireMcpId = async (name: string): Promise<number> => {
  const result = await listMcpTools();
  const service = result.data.find((item) => item.name === name);
  if (!service || !Number.isInteger(service.mcpId) || service.mcpId <= 0) {
    throw new Error("Installed MCP service could not be resolved");
  }
  return service.mcpId;
};

const needsConfiguration = (
  resource: Nl2aInstallableResource | Nl2aWeakSkillResource
): boolean =>
  resource.candidate.source !== "INSTALLED_SKILL" &&
  resource.candidate.source !== "NEXENT_OFFICIAL_SKILL";

const installedSkillId = (ref: string | null): number | null => {
  if (!ref?.startsWith("skill:")) return null;
  const skillId = Number(ref.slice("skill:".length));
  return Number.isInteger(skillId) && skillId > 0 ? skillId : null;
};

const buildInitialSkillPrompt = (
  request: Nl2aSkillCreationRequest,
  language: string
): string => {
  const isZh = language.startsWith("zh");
  const lines = isZh
    ? [
        "请为以下能力需求创建一个可复用的 Skill。",
        `能力需求：${request.requirement.query}`,
      ]
    : [
        "Create a reusable Skill for the following capability requirement.",
        `Requirement: ${request.requirement.query}`,
      ];
  if (request.agent_description) {
    lines.push(
      isZh
        ? `当前 Agent：${request.agent_description}`
        : `Current Agent: ${request.agent_description}`
    );
  }
  if (request.requirement.search_terms.length > 0) {
    lines.push(
      `${isZh ? "关键词" : "Search terms"}: ${request.requirement.search_terms.join(", ")}`
    );
  }
  if (request.confirmed_constraints.length > 0) {
    lines.push(
      `${isZh ? "已确认约束" : "Confirmed constraints"}: ${request.confirmed_constraints.join("; ")}`
    );
  }
  return lines.join("\n");
};

const recordSkillCreationEvent = (
  request: Nl2aSkillCreationRequest,
  event: Nl2AgentSkillCreationEvent
) => {
  recordNl2AgentSkillCreationEvent({
    event,
    non_skill_coverage: request.non_skill_coverage.status,
    created_skill_status: request.created_skill_status || "none",
    has_weak_matches: request.weak_skill_candidates.length > 0,
  }).catch(() => undefined);
};

export function SuggestedResourceInstallationCard({
  payload,
  disabled = false,
}: {
  payload: Nl2aSuggestedResourceInstallationPayload;
  disabled?: boolean;
}) {
  const { message } = App.useApp();
  const { t, i18n } = useTranslation("common");
  const aui = useAui();
  const queryClient = useQueryClient();
  const reactId = useId();
  const cardKey = `suggested_resource_installation:${payload.agent_id}:${reactId}`;
  const { registerCard, submitCard, isCardInteractive } = useNl2AgentFlow();
  const [items, dispatch] = useReducer(
    reducer,
    payload.resources,
    initializeItems
  );
  const [dialogRef, setDialogRef] = useState<string | null>(null);
  const [dialogDraft, setDialogDraft] = useState<InstallationDraft | null>(
    null
  );
  const [dialogPreviousStatus, setDialogPreviousStatus] = useState<
    "not_started" | "failed"
  >("not_started");
  const [submitted, setSubmitted] = useState(false);
  const [acceptedWeakSkills, setAcceptedWeakSkills] = useState<
    Record<string, Nl2aResourceCandidate>
  >({});
  const [activeSkillRequirementId, setActiveSkillRequirementId] = useState<
    string | null
  >(null);
  const [openedSkillRequirementIds, setOpenedSkillRequirementIds] = useState<
    string[]
  >([]);
  const exposedSkillRequirementIds = useRef(new Set<string>());
  const completedSkillModalRequirementIds = useRef(new Set<string>());

  useEffect(() => {
    registerCard(cardKey, payload.subtype);
  }, [cardKey, payload.subtype, registerCard]);

  useEffect(() => {
    payload.skill_creation_requests.forEach((request) => {
      const requirementId = request.requirement.requirement_id;
      if (exposedSkillRequirementIds.current.has(requirementId)) return;
      exposedSkillRequirementIds.current.add(requirementId);
      recordSkillCreationEvent(request, "exposure");
    });
  }, [payload.skill_creation_requests]);

  const unresolvedSkillRequests = useMemo(
    () =>
      payload.skill_creation_requests.filter(
        (request) => !acceptedWeakSkills[request.requirement.requirement_id]
      ),
    [acceptedWeakSkills, payload.skill_creation_requests]
  );
  const fixedCandidates = useMemo(() => {
    const byOriginalRef = new Map<string, Nl2aResourceCandidate>();
    Object.values(acceptedWeakSkills).forEach((candidate) => {
      const current = byOriginalRef.get(candidate.candidate_ref);
      byOriginalRef.set(
        candidate.candidate_ref,
        current ? mergeCandidateCoverage(current, candidate) : candidate
      );
    });
    const byInstalledRef = new Map<string, Nl2aResourceCandidate>();
    byOriginalRef.forEach((candidate, ref) => {
      const item = items.find((current) => candidateRef(current) === ref);
      let fixed = item
        ? mergeCandidateCoverage(item.resource.candidate, candidate)
        : candidate;
      if (
        item?.status === "installed" &&
        item.resourceId &&
        fixed.resource_type === "skill"
      ) {
        fixed = {
          ...fixed,
          candidate_ref: `skill:${item.resourceId}`,
          source: "INSTALLED_SKILL",
        };
      }
      const current = byInstalledRef.get(fixed.candidate_ref);
      byInstalledRef.set(
        fixed.candidate_ref,
        current ? mergeCandidateCoverage(current, fixed) : fixed
      );
    });
    return [...byInstalledRef.values()];
  }, [acceptedWeakSkills, items]);

  const interactive = !disabled && !submitted && isCardInteractive(cardKey);
  const dialogItem = items.find((item) => candidateRef(item) === dialogRef);
  const hasFailed = items.some((item) => item.status === "failed");
  const isBusy = items.some(
    (item) => item.status === "installing" || item.status === "configuring"
  );
  const hasPendingConfirmedSkill = items.some(
    (item) =>
      item.resource.candidate.user_confirmed_requirement_ids.length > 0 &&
      item.status !== "installed"
  );
  const installedCount = items.filter(
    (item) => item.status === "installed"
  ).length;
  const canContinue =
    interactive &&
    !hasFailed &&
    !isBusy &&
    !hasPendingConfirmedSkill &&
    unresolvedSkillRequests.length === 0;

  const resourceActionState = () => ({
    installed: items
      .filter((item) => item.status === "installed")
      .map((item) => ({
        candidate_ref: installedCandidateRef(item),
        resource_type: item.resource.candidate.resource_type,
        resource_id: item.resourceId,
        user_confirmed_requirement_ids:
          item.resource.candidate.user_confirmed_requirement_ids,
      })),
    skipped: items
      .filter((item) => item.status === "skipped")
      .map((item) => ({
        candidate_ref: candidateRef(item),
        reason: item.skipReason || "user_skipped",
      })),
    pending: items
      .filter(
        (item) => item.status !== "installed" && item.status !== "skipped"
      )
      .map((item) => candidateRef(item)),
  });

  const submitAction = (
    actionName: string,
    summary: string,
    result: Record<string, unknown>
  ) => {
    if (!interactive || hasPendingConfirmedSkill) return;
    const action: Nl2AgentCardAction = {
      type: "nl2agent_card_action",
      subtype: payload.subtype,
      agent_id: payload.agent_id,
      action: actionName,
      result: {
        requirements: payload.requirements,
        ...resourceActionState(),
        fixed_candidates: fixedCandidates,
        fixed_recommended_refs: fixedCandidates.map(
          (candidate) => candidate.candidate_ref
        ),
        ...result,
      },
    };
    setSubmitted(true);
    submitCard(cardKey);
    aui.thread().append({
      role: "user",
      content: [{ type: "text", text: summary }],
      metadata: { custom: { nl2agentCardAction: action } },
      startRun: true,
    });
  };

  const openSkillBuilder = (request: Nl2aSkillCreationRequest) => {
    if (!interactive || hasPendingConfirmedSkill || !request.can_create_skill) {
      return;
    }
    recordSkillCreationEvent(request, "create_click");
    const requirementId = request.requirement.requirement_id;
    setOpenedSkillRequirementIds((current) =>
      current.includes(requirementId) ? current : [...current, requirementId]
    );
    setActiveSkillRequirementId(requirementId);
  };

  const acceptWeakSkill = (
    request: Nl2aSkillCreationRequest,
    candidate: Nl2aResourceCandidate
  ) => {
    if (!interactive) return;
    const resource = request.weak_skill_resources.find(
      (item) => item.candidate.candidate_ref === candidate.candidate_ref
    );
    if (!resource) return;
    const requirementId = request.requirement.requirement_id;
    const confirmedCandidate = confirmCandidateRequirement(
      resource.candidate,
      requirementId
    );
    recordSkillCreationEvent(request, "weak_match_accepted");
    setAcceptedWeakSkills((current) => ({
      ...current,
      [requirementId]: confirmedCandidate,
    }));
    dispatch({
      type: "accept_weak_resource",
      resource,
      requirementId,
    });
    message.success(
      t(
        "nl2agent.skillCreation.weakMatchAccepted",
        "Skill added to recommended resources"
      )
    );
  };

  const handleSkillCreated = async (
    request: Nl2aSkillCreationRequest,
    skill: CreatedSkillResult
  ) => {
    if (!Number.isInteger(skill.skill_id) || skill.skill_id <= 0) {
      message.error(
        t(
          "nl2agent.skillCreation.invalidResult",
          "Created Skill could not be resolved"
        )
      );
      return;
    }
    completedSkillModalRequirementIds.current.add(
      request.requirement.requirement_id
    );
    recordSkillCreationEvent(request, "create_success");
    await queryClient.invalidateQueries({ queryKey: ["skills"] });
    submitAction(
      "skill_created",
      t("nl2agent.skillCreation.createdSummary", "Skill created"),
      {
        requirement: request.requirement,
        created_skill: {
          skill_id: skill.skill_id,
          candidate_ref: `skill:${skill.skill_id}`,
        },
      }
    );
  };

  const openConfig = async (item: InstallationItem) => {
    if (!interactive || item.status === "installed") return;
    let draft = { ...item.draft };
    const selected = item.resource.installation_options.find(
      (option) => option.option_id === draft.optionId
    );
    if (
      selected?.form_kind === "MCP_CONTAINER" &&
      draft.containerPort == null
    ) {
      try {
        const suggested = await suggestMcpContainerPortService();
        draft = { ...draft, containerPort: suggested.data.port };
      } catch {
        // The user can still enter a port manually.
      }
    }
    setDialogPreviousStatus(
      item.status === "failed" ? "failed" : "not_started"
    );
    dispatch({ type: "configure", ref: candidateRef(item) });
    setDialogRef(candidateRef(item));
    setDialogDraft(draft);
  };

  const saveConfig = () => {
    if (dialogItem && dialogDraft) {
      dispatch({
        type: "save_config",
        ref: candidateRef(dialogItem),
        draft: dialogDraft,
        status: dialogPreviousStatus,
      });
    }
    setDialogRef(null);
    setDialogDraft(null);
  };

  const cancelConfig = () => {
    if (dialogItem) {
      dispatch({
        type: "cancel_config",
        ref: candidateRef(dialogItem),
        status: dialogPreviousStatus,
      });
    }
    setDialogRef(null);
    setDialogDraft(null);
  };

  const installOfficialSkill = async (item: InstallationItem) => {
    const name = decodeCandidateName(
      candidateRef(item),
      "nexent_official_skill"
    );
    await installOfficialSkills(
      [name],
      i18n.language.startsWith("zh") ? "zh" : "en"
    );
    const skills = await fetchOfficialSkillsWithStatus();
    const installed = skills.find(
      (skill) => skill.name === name && skill.status === "installed"
    );
    if (!installed || installed.skill_id <= 0) {
      throw new Error("Installed Skill could not be resolved");
    }
    return installed.skill_id;
  };

  const installRepositorySkill = async (item: InstallationItem) => {
    const repositoryId = parsePositiveId(
      candidateRef(item),
      "tenant_skill_repository"
    );
    const targetName = item.draft.targetName.trim();
    const installed = await skillRepositoryService.installSkillFromRepository(
      repositoryId,
      targetName ? { target_name: targetName } : undefined
    );
    if (!installed.skill_id || installed.skill_id <= 0) {
      throw new Error("Installed Skill could not be resolved");
    }
    return installed.skill_id;
  };

  const ensureAvailablePort = async (port?: number) => {
    if (!port || !Number.isInteger(port) || port < 1 || port > 65535) {
      throw new Error("A valid container port is required");
    }
    const availability = await checkMcpContainerPortConflictService({ port });
    if (!availability.data.available)
      throw new Error("Container port is occupied");
    return port;
  };

  const refreshInstalledMcpTools = async (toastKey: string) => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: MCP_TOOLS_QUERY_KEYS.services,
      }),
      queryClient.invalidateQueries({ queryKey: MCP_SERVERS_QUERY_KEY }),
    ]);
    await refreshToolListWithToast({
      message,
      t,
      toastKey: `nl2agent-install-${toastKey}`,
    });
  };

  const installRepositoryMcp = async (item: InstallationItem) => {
    const marketId = parsePositiveId(
      candidateRef(item),
      "tenant_mcp_repository"
    );
    const draft = item.draft;
    const config = optionConfig(
      item.resource.installation_options.find(
        (option) => option.option_id === draft.optionId
      )!
    ) as unknown as CommunityQuickAddDraft;
    const name = draft.name.trim();
    if (!name) throw new Error("MCP service name is required");
    let customHeaders: Record<string, string> | undefined;
    if (draft.customHeaders.trim()) {
      const parsed = JSON.parse(draft.customHeaders);
      if (
        !parsed ||
        typeof parsed !== "object" ||
        Array.isArray(parsed) ||
        Object.values(parsed).some((value) => typeof value !== "string")
      ) {
        throw new Error("Custom headers must be a JSON object");
      }
      customHeaders = parsed as Record<string, string>;
    }
    if (
      item.resource.installation_options.find(
        (option) => option.option_id === draft.optionId
      )?.form_kind === "MCP_CONTAINER"
    ) {
      const mcpConfig = parseContainerMcpConfigJson(draft.containerConfigJson);
      if (!mcpConfig) throw new Error("Container configuration is invalid");
      const usesPublishedPort =
        typeof config.containerPort === "number" &&
        draft.containerPort === config.containerPort;
      if (usesPublishedPort) {
        await addMcpToolService({
          name,
          description: String(config.description || ""),
          source: McpSource.COMMUNITY,
          server_url: `http://localhost:${draft.containerPort}/mcp`,
          authorization_token: draft.authorizationToken.trim() || undefined,
          custom_headers: customHeaders,
          container_config: mcpConfig as unknown as Record<string, unknown>,
          container_port: draft.containerPort,
          tags: config.tags || [],
          version: config.version,
          market_id: marketId,
          skip_health_check: true,
          enabled: true,
          group_ids: "",
        });
      } else {
        const port = await ensureAvailablePort(draft.containerPort);
        await addContainerMcpToolService({
          name,
          description: String(config.description || ""),
          tags: config.tags || [],
          source: McpSource.COMMUNITY,
          authorization_token: draft.authorizationToken.trim() || undefined,
          market_id: marketId,
          port,
          mcp_config: mcpConfig,
        });
      }
    } else {
      if (!draft.serverUrl.trim())
        throw new Error("MCP server URL is required");
      await addMcpToolService({
        name,
        description: String(config.description || ""),
        source: McpSource.COMMUNITY,
        server_url: draft.serverUrl.trim(),
        authorization_token: draft.authorizationToken.trim() || undefined,
        custom_headers: customHeaders,
        tags: config.tags || [],
        version: config.version,
        market_id: marketId,
      });
    }
    incrementCommunityMcpDownloadCount(marketId).catch(() => undefined);
    await refreshInstalledMcpTools(`community-${marketId}`);
    return requireMcpId(name);
  };

  const installItem = async (item: InstallationItem) => {
    if (
      !interactive ||
      item.status === "installing" ||
      item.status === "installed"
    ) {
      return;
    }
    dispatch({ type: "install", ref: candidateRef(item) });
    try {
      let resourceId: number;
      switch (item.resource.candidate.source) {
        case "NEXENT_OFFICIAL_SKILL":
          resourceId = await installOfficialSkill(item);
          break;
        case "TENANT_SKILL_REPOSITORY":
          resourceId = await installRepositorySkill(item);
          break;
        case "TENANT_MCP_REPOSITORY":
          resourceId = await installRepositoryMcp(item);
          break;
        default:
          throw new Error("Unsupported installation source");
      }
      dispatch({ type: "installed", ref: candidateRef(item), resourceId });
      message.success(
        t("nl2agent.resourceInstallation.success", "Resource installed")
      );
    } catch (error) {
      dispatch({
        type: "failed",
        ref: candidateRef(item),
        error: toApiError(error),
      });
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
        requirements: payload.requirements,
        installed: items
          .filter((item) => item.status === "installed")
          .map((item) => ({
            candidate_ref: installedCandidateRef(item),
            resource_type: item.resource.candidate.resource_type,
            resource_id: item.resourceId,
            user_confirmed_requirement_ids:
              item.resource.candidate.user_confirmed_requirement_ids,
          })),
        skipped: items
          .filter((item) => item.status !== "installed")
          .map((item) => ({
            candidate_ref: candidateRef(item),
            reason:
              item.skipReason ||
              (item.status === "failed" ? "install_failed" : "not_selected"),
          })),
        fixed_candidates: fixedCandidates,
        fixed_recommended_refs: fixedCandidates.map(
          (candidate) => candidate.candidate_ref
        ),
      },
    };
    setSubmitted(true);
    submitCard(cardKey);
    aui.thread().append({
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

  const selectedInstallation = useMemo(() => {
    if (!dialogItem || !dialogDraft) return null;
    return (
      dialogItem.resource.installation_options.find(
        (option) => option.option_id === dialogDraft.optionId
      ) || null
    );
  }, [dialogDraft, dialogItem]);

  const changeOption = async (optionId: string) => {
    if (!dialogItem || !dialogDraft) return;
    const selected = dialogItem.resource.installation_options.find(
      (option) => option.option_id === optionId
    );
    let containerPort = dialogDraft.containerPort;
    if (selected?.form_kind === "MCP_CONTAINER" && !containerPort) {
      try {
        containerPort = (await suggestMcpContainerPortService()).data.port;
      } catch {
        containerPort = undefined;
      }
    }
    setDialogDraft({
      ...dialogDraft,
      optionId,
      containerPort,
    });
  };

  return (
    <section
      className="my-4 w-full max-w-3xl overflow-hidden rounded-md border border-border bg-background"
      data-testid="nl2agent-installation-card"
    >
      <div className="flex items-center gap-3 border-b bg-muted/30 px-4 py-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10">
          <Download className="size-4 text-primary" />
        </div>
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
        <Badge variant="outline">
          {items.length + unresolvedSkillRequests.length}
        </Badge>
      </div>

      <div className="divide-y">
        {items.map((item) => (
          <div
            key={candidateRef(item)}
            className="flex min-h-20 flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center"
            data-testid={`installation-resource-${candidateRef(item)}`}
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
                <Badge variant="outline" className="rounded-md text-[10px]">
                  {item.resource.recommendation === "recommended"
                    ? t("nl2agent.resourceBinding.recommended", "Recommended")
                    : t("nl2agent.resourceBinding.optional", "Optional")}
                </Badge>
              </div>
              {item.resource.candidate.description ? (
                <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                  {item.resource.candidate.description}
                </p>
              ) : null}
              <p className="mt-1 break-words text-xs text-muted-foreground">
                {t("nl2agent.resourceBinding.matches", "Matches")}:{" "}
                {item.resource.candidate.requirement_ids.join(", ")}
              </p>
              {item.resource.candidate.user_confirmed_requirement_ids.length >
              0 ? (
                <p className="mt-1 break-words text-xs font-medium text-primary">
                  {t(
                    "nl2agent.skillCreation.userConfirmedFor",
                    "User-confirmed for"
                  )}
                  :{" "}
                  {item.resource.candidate.user_confirmed_requirement_ids.join(
                    ", "
                  )}
                </p>
              ) : null}
              {item.resource.candidate.user_confirmed_requirement_ids.length >
                0 && item.status !== "installed" ? (
                <p className="mt-1 text-xs text-amber-700">
                  {t(
                    "nl2agent.skillCreation.manualInstallRequired",
                    "Configure and install this Skill before continuing."
                  )}
                </p>
              ) : null}
              {item.error ? (
                <p
                  className="mt-1 flex items-center gap-1 text-xs text-destructive"
                  role="alert"
                >
                  <AlertTriangle className="size-3.5 shrink-0" />
                  {item.error.message}
                </p>
              ) : null}
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
                  {needsConfiguration(item.resource) ? (
                    <Button
                      type="button"
                      size="icon"
                      variant="outline"
                      className="size-9 rounded-md"
                      title={t(
                        "nl2agent.resourceBinding.configure",
                        "Configure"
                      )}
                      aria-label={t(
                        "nl2agent.resourceBinding.configure",
                        "Configure"
                      )}
                      disabled={!interactive || item.status === "installing"}
                      onClick={() => openConfig(item)}
                    >
                      <Settings2 className="size-4" />
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    size="sm"
                    disabled={!interactive || item.status === "installing"}
                    onClick={() => installItem(item)}
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
                  {item.status === "failed" &&
                  item.resource.candidate.user_confirmed_requirement_ids
                    .length === 0 ? (
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      className="size-9"
                      title={t("common.skip", "Skip")}
                      aria-label={t("common.skip", "Skip")}
                      onClick={() =>
                        dispatch({
                          type: "skip",
                          ref: candidateRef(item),
                          reason: "install_failed",
                        })
                      }
                    >
                      <SkipForward className="size-4" />
                    </Button>
                  ) : null}
                </>
              )}
            </div>
          </div>
        ))}
        {unresolvedSkillRequests.map((request) => {
          const requirementId = request.requirement.requirement_id;
          return (
            <div
              key={requirementId}
              className="space-y-3 px-4 py-4"
              data-testid={`skill-creation-request-${requirementId}`}
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="break-words text-sm font-medium">
                      {request.requirement.query}
                    </span>
                    <Badge variant="secondary">
                      {t(
                        "nl2agent.skillCreation.noStrongMatch",
                        "No strongly matching Skill"
                      )}
                    </Badge>
                  </div>
                  {request.non_skill_coverage.status !== "none" ? (
                    <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                      <Wrench className="size-3.5 shrink-0" />
                      {request.non_skill_coverage.status === "installed"
                        ? t(
                            "nl2agent.skillCreation.installedToolCoverage",
                            "An installed tool or MCP already covers this requirement."
                          )
                        : t(
                            "nl2agent.skillCreation.installableToolCoverage",
                            "An installable tool or MCP can cover this requirement."
                          )}
                    </p>
                  ) : (
                    <p className="mt-1 flex items-center gap-1 text-xs text-amber-700">
                      <AlertTriangle className="size-3.5 shrink-0" />
                      {t(
                        "nl2agent.skillCreation.noResourceCoverage",
                        "No strongly matching resource currently covers this requirement."
                      )}
                    </p>
                  )}
                  {request.created_skill_status ? (
                    <p className="mt-2 text-xs text-amber-700">
                      {request.created_skill_status === "unverified"
                        ? t(
                            "nl2agent.skillCreation.unverified",
                            "The Skill was created but is not visible to resource search yet."
                          )
                        : t(
                            "nl2agent.skillCreation.weakAfterCreation",
                            "The created Skill is visible but remains a weak match."
                          )}
                    </p>
                  ) : null}
                </div>

                <div className="flex flex-wrap justify-end gap-2">
                  {request.created_skill_status === "unverified" ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={!interactive || hasPendingConfirmedSkill}
                      onClick={() =>
                        submitAction(
                          "retry_skill_validation",
                          t(
                            "nl2agent.skillCreation.retrySummary",
                            "Retry Skill validation"
                          ),
                          {
                            requirement: request.requirement,
                            created_skill_ref: request.created_skill_ref,
                          }
                        )
                      }
                    >
                      <RefreshCw className="mr-1 size-4" />
                      {t("common.retry", "Retry")}
                    </Button>
                  ) : null}
                  {request.created_skill_ref ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={!interactive || hasPendingConfirmedSkill}
                      onClick={() => openSkillBuilder(request)}
                    >
                      <Pencil className="mr-1 size-4" />
                      {t(
                        "nl2agent.skillCreation.continueEditing",
                        "Continue editing"
                      )}
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      disabled={
                        !interactive ||
                        hasPendingConfirmedSkill ||
                        !request.can_create_skill
                      }
                      title={
                        request.can_create_skill
                          ? undefined
                          : t(
                              "nl2agent.skillCreation.unauthorized",
                              "You do not have permission to create a Skill."
                            )
                      }
                      onClick={() => openSkillBuilder(request)}
                    >
                      <WandSparkles className="mr-1 size-4" />
                      {t("nl2agent.skillCreation.create", "Create Skill")}
                    </Button>
                  )}
                </div>
              </div>

              {request.weak_skill_candidates.length > 0 ? (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">
                    {t(
                      "nl2agent.skillCreation.weakMatches",
                      "Possible Skill matches"
                    )}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {request.weak_skill_candidates.map((candidate) => (
                      <Button
                        key={candidate.candidate_ref}
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={!interactive}
                        onClick={() => acceptWeakSkill(request, candidate)}
                      >
                        {candidate.name} ({candidate.score.toFixed(2)})
                      </Button>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="flex flex-wrap gap-2">
                {request.non_skill_coverage.status !== "none" ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={!interactive || hasPendingConfirmedSkill}
                    onClick={() => {
                      recordSkillCreationEvent(
                        request,
                        "non_skill_resource_selected"
                      );
                      submitAction(
                        "use_existing_non_skill_resource",
                        t(
                          "nl2agent.skillCreation.useToolSummary",
                          "Continue with the existing tool or MCP"
                        ),
                        {
                          requirement: request.requirement,
                          candidate_refs:
                            request.non_skill_coverage.candidate_refs,
                        }
                      );
                    }}
                  >
                    <Wrench className="mr-1 size-4" />
                    {t(
                      "nl2agent.skillCreation.useExistingTool",
                      "Use existing tool or MCP"
                    )}
                  </Button>
                ) : null}
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={!interactive || hasPendingConfirmedSkill}
                  onClick={() => {
                    submitAction(
                      "revise_requirement",
                      t(
                        "nl2agent.skillCreation.reviseSummary",
                        "Revise this requirement"
                      ),
                      { requirement: request.requirement }
                    );
                  }}
                >
                  {t(
                    "nl2agent.skillCreation.reviseRequirement",
                    "Revise requirement"
                  )}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={!interactive || hasPendingConfirmedSkill}
                  onClick={() => {
                    recordSkillCreationEvent(request, "requirement_abandoned");
                    submitAction(
                      "abandon_requirement",
                      t(
                        "nl2agent.skillCreation.abandonSummary",
                        "Abandon this requirement"
                      ),
                      { requirement: request.requirement }
                    );
                  }}
                >
                  {t(
                    "nl2agent.skillCreation.abandonRequirement",
                    "Abandon requirement"
                  )}
                </Button>
              </div>
            </div>
          );
        })}
      </div>

      {unresolvedSkillRequests.length === 0 ? (
        <div className="flex justify-end border-t px-4 py-3">
          <Button type="button" disabled={!canContinue} onClick={continueFlow}>
            {installedCount > 0
              ? t("nl2agent.resourceBinding.continue", "Continue")
              : t("nl2agent.resourceBinding.skip", "Skip")}
          </Button>
        </div>
      ) : null}

      <Modal
        open={Boolean(dialogItem && dialogDraft)}
        title={dialogItem?.resource.candidate.name}
        okText={t("common.save", "Save")}
        cancelText={t("common.cancel", "Cancel")}
        onOk={saveConfig}
        onCancel={cancelConfig}
        destroyOnHidden
      >
        {dialogItem && dialogDraft ? (
          <div className="space-y-4 py-2">
            {dialogItem.resource.installation_options.length > 1 ? (
              <label className="block text-sm">
                <span className="mb-1 block font-medium">
                  {t(
                    "nl2agent.resourceInstallation.method",
                    "Installation method"
                  )}
                </span>
                <Select
                  className="w-full"
                  value={dialogDraft.optionId}
                  options={dialogItem.resource.installation_options.map(
                    (option) => ({
                      value: option.option_id,
                      label: option.label,
                    })
                  )}
                  onChange={changeOption}
                />
              </label>
            ) : null}

            {dialogItem.resource.candidate.source ===
            "TENANT_SKILL_REPOSITORY" ? (
              <label className="block text-sm">
                <span className="mb-1 block font-medium">
                  {t("nl2agent.resourceInstallation.skillName", "Skill name")}
                </span>
                <Input
                  value={dialogDraft.targetName}
                  placeholder={t(
                    "nl2agent.resourceInstallation.skillNamePlaceholder",
                    "Leave blank to generate a copy name"
                  )}
                  onChange={(event) =>
                    setDialogDraft({
                      ...dialogDraft,
                      targetName: event.target.value,
                    })
                  }
                />
              </label>
            ) : null}

            {dialogItem.resource.candidate.resource_type === "mcp_server" ? (
              <label className="block text-sm">
                <span className="mb-1 block font-medium">
                  {t(
                    "nl2agent.resourceInstallation.serviceName",
                    "Service name"
                  )}
                </span>
                <Input
                  value={dialogDraft.name}
                  onChange={(event) =>
                    setDialogDraft({ ...dialogDraft, name: event.target.value })
                  }
                />
              </label>
            ) : null}

            {dialogItem.resource.candidate.source === "TENANT_MCP_REPOSITORY" &&
            selectedInstallation?.form_kind === "MCP_REMOTE" ? (
              <>
                <label className="block text-sm">
                  <span className="mb-1 block font-medium">URL</span>
                  <Input
                    value={dialogDraft.serverUrl}
                    onChange={(event) =>
                      setDialogDraft({
                        ...dialogDraft,
                        serverUrl: event.target.value,
                      })
                    }
                  />
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block font-medium">Authorization</span>
                  <Input.Password
                    value={dialogDraft.authorizationToken}
                    onChange={(event) =>
                      setDialogDraft({
                        ...dialogDraft,
                        authorizationToken: event.target.value,
                      })
                    }
                  />
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block font-medium">
                    {t(
                      "nl2agent.resourceInstallation.customHeaders",
                      "Custom headers (JSON)"
                    )}
                  </span>
                  <Input.TextArea
                    autoSize={{ minRows: 2, maxRows: 6 }}
                    value={dialogDraft.customHeaders}
                    onChange={(event) =>
                      setDialogDraft({
                        ...dialogDraft,
                        customHeaders: event.target.value,
                      })
                    }
                  />
                </label>
              </>
            ) : null}

            {dialogItem.resource.candidate.source === "TENANT_MCP_REPOSITORY" &&
            selectedInstallation?.form_kind === "MCP_CONTAINER" ? (
              <label className="block text-sm">
                <span className="mb-1 block font-medium">
                  {t(
                    "nl2agent.resourceInstallation.containerConfig",
                    "Container configuration (JSON)"
                  )}
                </span>
                <Input.TextArea
                  autoSize={{ minRows: 5, maxRows: 12 }}
                  value={dialogDraft.containerConfigJson}
                  onChange={(event) =>
                    setDialogDraft({
                      ...dialogDraft,
                      containerConfigJson: event.target.value,
                    })
                  }
                />
              </label>
            ) : null}

            {selectedInstallation?.form_kind === "MCP_CONTAINER" ? (
              <label className="block text-sm">
                <span className="mb-1 block font-medium">
                  {t("nl2agent.resourceInstallation.port", "Container port")}
                </span>
                <InputNumber
                  className="w-full"
                  min={1}
                  max={65535}
                  value={dialogDraft.containerPort}
                  onChange={(value) =>
                    setDialogDraft({
                      ...dialogDraft,
                      containerPort:
                        typeof value === "number" ? value : undefined,
                    })
                  }
                />
              </label>
            ) : null}
          </div>
        ) : null}
      </Modal>
      {openedSkillRequirementIds.map((requirementId) => {
        const request = payload.skill_creation_requests.find(
          (item) => item.requirement.requirement_id === requirementId
        );
        if (!request) return null;
        const skillId = installedSkillId(request.created_skill_ref);
        const createdCandidate = request.weak_skill_candidates.find(
          (candidate) => candidate.candidate_ref === request.created_skill_ref
        );
        return (
          <SkillBuildModal
            key={requirementId}
            isOpen={activeSkillRequirementId === requirementId}
            onCancel={() => {
              if (
                !completedSkillModalRequirementIds.current.delete(requirementId)
              ) {
                recordSkillCreationEvent(request, "create_cancel");
              }
              setActiveSkillRequirementId(null);
            }}
            onSuccess={async () => {
              if (!request.created_skill_ref) return;
              completedSkillModalRequirementIds.current.add(requirementId);
              await queryClient.invalidateQueries({ queryKey: ["skills"] });
              submitAction(
                "retry_skill_validation",
                t(
                  "nl2agent.skillCreation.retrySummary",
                  "Retry Skill validation"
                ),
                {
                  requirement: request.requirement,
                  created_skill_ref: request.created_skill_ref,
                }
              );
            }}
            onCreated={(skill) => handleSkillCreated(request, skill)}
            editingSkill={
              skillId
                ? {
                    skill_id: skillId,
                    name: createdCandidate?.name,
                    description: createdCandidate?.description,
                    repository_info: [],
                  }
                : null
            }
            initialPrompt={buildInitialSkillPrompt(request, i18n.language)}
            preserveDraftOnClose
            zIndex={1200}
          />
        );
      })}
    </section>
  );
}
