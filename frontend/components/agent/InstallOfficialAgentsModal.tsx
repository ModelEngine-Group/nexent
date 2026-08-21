"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Input,
  Modal,
  Radio,
  Segmented,
  Select,
  Spin,
  Steps,
  Tag,
} from "antd";
import {
  Bot,
  CircleCheck,
  CircleOff,
  Database,
  Download,
  ExternalLink,
  GitBranch,
  LoaderCircle,
  Plug,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  useInstallOfficialAgents,
  useInstallOfficialAgentsFromGitcode,
  useOfficialAgents,
  useOfficialAgentsFromGitcode,
} from "@/hooks/agentRepository/useAgentRepositoryListings";
import { useModelList } from "@/hooks/model/useModelList";
import { checkAgentNameConflictBatch } from "@/services/agentConfigService";
import type { ModelOption } from "@/types/modelConfig";
import type {
  OfficialAgentGithubDiscoverResult,
  OfficialAgentInstallItem,
  OfficialAgentInstallStep,
  OfficialAgentItem,
} from "@/types/agentRepository";

interface InstallOfficialAgentsModalProps {
  open: boolean;
  onClose: () => void;
  onInstalled?: () => void;
  tenantId?: string;
}

interface ConflictItem {
  bundleName: string;
  agentName: string;
  conflictAgents: Array<{ name?: string; display_name?: string }>;
}

interface ResourceConflict {
  bundleName: string;
  /** Skill name or KB logical index name, used as the resolution key. */
  key: string;
  /** Displayed name (skill name or KB display name). */
  display: string;
}

interface ResourceResolution {
  action: "reuse" | "rename";
  newName: string;
}

/** MCP conflicts cannot be reused (same name, different url), so the only choices are rename or skip. */
interface McpResolution {
  action: "rename" | "skip";
  newName: string;
}

/** A conflict is resolved when a choice is committed and, for rename, a non-empty new name is given. */
function isResolutionValid(res?: ResourceResolution): boolean {
  return (
    !!res &&
    (res.action === "reuse" ||
      (res.action === "rename" && res.newName.trim() !== ""))
  );
}

function isMcpResolutionValid(res?: McpResolution): boolean {
  return (
    !!res &&
    (res.action === "skip" ||
      (res.action === "rename" && res.newName.trim() !== ""))
  );
}

export function InstallOfficialAgentsModal({
  open,
  onClose,
  onInstalled,
  tenantId,
}: InstallOfficialAgentsModalProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const locale = params.locale || "zh";

  const [currentStep, setCurrentStep] = useState(0);
  const [activeSource, setActiveSource] = useState<"local" | "gitcode">("local");
  const [selectedNames, setSelectedNames] = useState<Set<string>>(new Set());
  const [conflicts, setConflicts] = useState<ConflictItem[]>([]);
  const [renameDrafts, setRenameDrafts] = useState<Record<string, string>>({});
  const [renames, setRenames] = useState<Record<string, string>>({});
  const [modelSelections, setModelSelections] = useState<
    Record<string, number>
  >({});
  const [embeddingModelSelections, setEmbeddingModelSelections] = useState<
    Record<string, number>
  >({});
  const [checking, setChecking] = useState(false);
  const [isInstalling, setIsInstalling] = useState(false);
  const [lastResults, setLastResults] = useState<
    OfficialAgentInstallItem[] | null
  >(null);
  const [skillResolutions, setSkillResolutions] = useState<
    Record<string, ResourceResolution>
  >({});
  const [kbResolutions, setKbResolutions] = useState<
    Record<string, ResourceResolution>
  >({});
  const [mcpResolutions, setMcpResolutions] = useState<
    Record<string, McpResolution>
  >({});

  // GitCode 固定源视图状态（上提到父组件，供底部 footer 渲染操作按钮）
  const [gcStage, setGcStage] = useState<
    "catalog" | "resources" | "model" | "done"
  >("catalog");
  const [gcSelected, setGcSelected] = useState<Set<string>>(new Set());
  const [gcModelSelections, setGcModelSelections] = useState<
    Record<string, number>
  >({});
  const [gcEmbeddingModelSelections, setGcEmbeddingModelSelections] = useState<
    Record<string, number>
  >({});
  const [gcSkillResolutions, setGcSkillResolutions] = useState<
    Record<string, ResourceResolution>
  >({});
  const [gcKbResolutions, setGcKbResolutions] = useState<
    Record<string, ResourceResolution>
  >({});
  const [gcMcpResolutions, setGcMcpResolutions] = useState<
    Record<string, McpResolution>
  >({});
  const [gcInstalling, setGcInstalling] = useState(false);
  const [gcResults, setGcResults] = useState<
    OfficialAgentInstallItem[] | null
  >(null);
  const [gcInstalledNamesState, setGcInstalledNamesState] = useState<
    Set<string>
  >(new Set());

  const { data: agents, isLoading } = useOfficialAgents(open, tenantId);
  const installMutation = useInstallOfficialAgents(tenantId);
  const { availableLlmModels, models: allModels } = useModelList();

  const gitcodeCatalog = useOfficialAgentsFromGitcode(open, tenantId);
  const gitcodeInstallMutation = useInstallOfficialAgentsFromGitcode(tenantId);

  const gcInstalledStorageKey = `nexent:official-gitcode-installed:${tenantId ?? "default"}`;

  useEffect(() => {
    if (!open || typeof window === "undefined") return;
    try {
      const stored = window.localStorage.getItem(gcInstalledStorageKey);
      const names = stored ? JSON.parse(stored) : [];
      setGcInstalledNamesState(new Set(Array.isArray(names) ? names : []));
    } catch {
      setGcInstalledNamesState(new Set());
    }
  }, [gcInstalledStorageKey, open]);

  const gcInstalledNames = useMemo(
    () =>
      new Set(
        [
          ...gcInstalledNamesState,
          ...(gcResults ?? [])
            .filter(
              (result) =>
                result.status === "installed" ||
                result.status === "already_installed"
            )
            .map((result) => result.name),
        ]
      ),
    [gcInstalledNamesState, gcResults]
  );

  const gcAllBundles = useMemo(
    () =>
      (gitcodeCatalog.data?.groups ?? []).flatMap((group) =>
        group.categories.flatMap((cat) =>
          cat.bundles.map((bundle) =>
            gcInstalledNames.has(bundle.name)
              ? { ...bundle, status: "installed" as const }
              : bundle
          )
        )
      ),
    [gitcodeCatalog.data, gcInstalledNames]
  );
  const gcInstallableBundles = useMemo(
    () => gcAllBundles.filter((b) => b.status === "installable"),
    [gcAllBundles]
  );
  const gcSelectedBundles = useMemo(
    () => gcAllBundles.filter((b) => gcSelected.has(b.name)),
    [gcAllBundles, gcSelected]
  );
  const gcAllSelected =
    gcInstallableBundles.length > 0 &&
    gcInstallableBundles.every((b) => gcSelected.has(b.name));

  // Available vector/embedding models (embedding + multi_embedding), used for
  // the knowledge bases created during install.
  const availableEmbeddingModels = useMemo(
    () =>
      allModels.filter(
        (m) =>
          (m.type === "embedding" || m.type === "multi_embedding") &&
          m.connect_status === "available"
      ),
    [allModels]
  );

  // Pre-select the first available LLM for every selected GitCode bundle on the
  // model stage.
  useEffect(() => {
    if (gcStage !== "model" || !availableLlmModels.length) return;
    const first = availableLlmModels[0].id;
    setGcModelSelections((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const b of gcSelectedBundles) {
        if (next[b.name] == null) {
          next[b.name] = first;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gcStage, availableLlmModels, gcSelectedBundles]);

  useEffect(() => {
    if (!open) return;
    setActiveSource("local");
    setCurrentStep(0);
    setSelectedNames(new Set());
    setConflicts([]);
    setRenameDrafts({});
    setRenames({});
    setModelSelections({});
    setEmbeddingModelSelections({});
    setChecking(false);
    setIsInstalling(false);
    setLastResults(null);
    setSkillResolutions({});
    setKbResolutions({});
    setMcpResolutions({});
    setGcStage("catalog");
    setGcSelected(new Set());
    setGcModelSelections({});
    setGcEmbeddingModelSelections({});
    setGcSkillResolutions({});
    setGcKbResolutions({});
    setGcMcpResolutions({});
    setGcInstalling(false);
  }, [open]);

  const allAgents = useMemo(() => agents ?? [], [agents]);
  const installableAgents = useMemo(
    () => allAgents.filter((agent) => agent.status === "installable"),
    [allAgents]
  );
  const selectedAgents = useMemo(
    () => allAgents.filter((agent) => selectedNames.has(agent.name)),
    [allAgents, selectedNames]
  );
  const allSelected =
    installableAgents.length > 0 &&
    installableAgents.every((agent) => selectedNames.has(agent.name));
  const someSelected =
    installableAgents.some((agent) => selectedNames.has(agent.name)) &&
    !allSelected;

  const hasSelectedMcps = selectedAgents.some(
    (a) => (a.mcps?.length ?? 0) > 0
  );

  // Skill / knowledge base / MCP name conflicts across the currently selected
  // bundles (drives the "reuse vs rename / skip" resources step).
  const resourceConflicts = useMemo(() => {
    const skills: ResourceConflict[] = [];
    const kbs: ResourceConflict[] = [];
    const mcps: ResourceConflict[] = [];
    for (const a of selectedAgents) {
      for (const s of a.skills ?? []) {
        if (s.exists) skills.push({ bundleName: a.name, key: s.name, display: s.name });
      }
      for (const k of a.knowledge_bases ?? []) {
        if (k.exists)
          kbs.push({
            bundleName: a.name,
            key: k.logical_index_name,
            display: k.display_name || k.logical_index_name,
          });
      }
      for (const m of a.mcps ?? []) {
        if (m.conflict)
          mcps.push({
            bundleName: a.name,
            key: m.mcp_server_name,
            display: m.mcp_server_name,
          });
      }
    }
    return { skills, kbs, mcps };
  }, [selectedAgents]);
  const hasResourceConflicts =
    resourceConflicts.skills.length > 0 ||
    resourceConflicts.kbs.length > 0 ||
    resourceConflicts.mcps.length > 0;

  // Same computation for the GitCode source (selected bundles at catalog stage).
  const gcResourceConflicts = useMemo(() => {
    const skills: ResourceConflict[] = [];
    const kbs: ResourceConflict[] = [];
    const mcps: ResourceConflict[] = [];
    for (const a of gcSelectedBundles) {
      for (const s of a.skills ?? []) {
        if (s.exists) skills.push({ bundleName: a.name, key: s.name, display: s.name });
      }
      for (const k of a.knowledge_bases ?? []) {
        if (k.exists)
          kbs.push({
            bundleName: a.name,
            key: k.logical_index_name,
            display: k.display_name || k.logical_index_name,
          });
      }
      for (const m of a.mcps ?? []) {
        if (m.conflict)
          mcps.push({
            bundleName: a.name,
            key: m.mcp_server_name,
            display: m.mcp_server_name,
          });
      }
    }
    return { skills, kbs, mcps };
  }, [gcSelectedBundles]);
  const gcHasResourceConflicts =
    gcResourceConflicts.skills.length > 0 ||
    gcResourceConflicts.kbs.length > 0 ||
    gcResourceConflicts.mcps.length > 0;

  const resourceAllResolved = useMemo(
    () =>
      resourceConflicts.skills.every((c) =>
        isResolutionValid(skillResolutions[c.key])
      ) &&
      resourceConflicts.kbs.every((c) => isResolutionValid(kbResolutions[c.key])) &&
      resourceConflicts.mcps.every((c) =>
        isMcpResolutionValid(mcpResolutions[c.key])
      ),
    [resourceConflicts, skillResolutions, kbResolutions, mcpResolutions]
  );

  const gcResourceAllResolved = useMemo(
    () =>
      gcResourceConflicts.skills.every((c) =>
        isResolutionValid(gcSkillResolutions[c.key])
      ) &&
      gcResourceConflicts.kbs.every((c) =>
        isResolutionValid(gcKbResolutions[c.key])
      ) &&
      gcResourceConflicts.mcps.every((c) =>
        isMcpResolutionValid(gcMcpResolutions[c.key])
      ),
    [gcResourceConflicts, gcSkillResolutions, gcKbResolutions, gcMcpResolutions]
  );

  const steps = useMemo(() => {
    const items: Array<{ key: string; title: string }> = [
      { key: "select", title: t("officialAgent.wizard.select") },
    ];
    if (conflicts.length > 0) {
      items.push({ key: "rename", title: t("officialAgent.wizard.rename") });
    }
    if (hasResourceConflicts) {
      items.push({
        key: "resources",
        title: t("officialAgent.wizard.resources"),
      });
    }
    if (hasSelectedMcps) {
      items.push({ key: "mcp", title: t("officialAgent.wizard.mcp") });
    }
    items.push({ key: "model", title: t("officialAgent.wizard.model") });
    return items;
  }, [conflicts.length, hasResourceConflicts, hasSelectedMcps, t]);

  const currentStepKey = steps[currentStep]?.key;

  // Pre-select the first available LLM for every selected bundle on the model step.
  useEffect(() => {
    if (currentStepKey !== "model" || !availableLlmModels.length) return;
    const first = availableLlmModels[0].id;
    setModelSelections((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const b of selectedAgents) {
        if (next[b.name] == null) {
          next[b.name] = first;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentStepKey, availableLlmModels, selectedAgents]);

  // Pre-select the first available embedding model for KB-bearing bundles.
  useEffect(() => {
    if (currentStepKey !== "model" || !availableEmbeddingModels.length) return;
    const first = availableEmbeddingModels[0].id;
    setEmbeddingModelSelections((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const b of selectedAgents) {
        if (b.has_knowledge && next[b.name] == null) {
          next[b.name] = first;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentStepKey, availableEmbeddingModels, selectedAgents]);

  const goConfigureModel = () => {
    router.push(`/${locale}/models`);
  };

  const handleToggleAll = () => {
    if (allSelected) {
      setSelectedNames(new Set());
    } else {
      setSelectedNames(new Set(installableAgents.map((agent) => agent.name)));
    }
  };

  const handleCancel = () => {
    if (isInstalling || gcInstalling) return;
    onClose();
  };

  // ----- GitCode 固定源处理逻辑（状态在父组件，footer 渲染操作按钮） -----

  const handleGcToggle = (name: string) => {
    setGcSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const handleGcToggleAll = () => {
    if (gcAllSelected) {
      setGcSelected(new Set());
    } else {
      setGcSelected(new Set(gcInstallableBundles.map((b) => b.name)));
    }
  };

  const handleGcNext = () => {
    if (gcSelected.size === 0) {
      message.warning(t("officialAgent.installModal.selectAtLeastOne"));
      return;
    }
    setGcStage(gcHasResourceConflicts ? "resources" : "model");
  };

  const handleGcResourcesNext = () => {
    if (!gcResourceAllResolved) {
      message.warning(t("officialAgent.resources.required"));
      return;
    }
    setGcStage("model");
  };

  const handleGcBack = () => {
    if (gcStage === "model") {
      setGcStage(gcHasResourceConflicts ? "resources" : "catalog");
    } else {
      setGcStage("catalog");
    }
  };

  const handleGcInstall = async () => {
    const finalModelIds: Record<string, number> = { ...gcModelSelections };
    for (const b of gcSelectedBundles) {
      if (finalModelIds[b.name] == null) {
        if (!availableLlmModels.length) {
          message.warning(t("officialAgent.modelStep.placeholder"));
          return;
        }
        finalModelIds[b.name] = availableLlmModels[0].id;
      }
    }
    setGcModelSelections(finalModelIds);

    const finalEmbeddingModelIds: Record<string, number> = {
      ...gcEmbeddingModelSelections,
    };
    for (const b of gcSelectedBundles) {
      if (!b.has_knowledge) continue;
      if (finalEmbeddingModelIds[b.name] == null) {
        if (!availableEmbeddingModels.length) {
          message.warning(t("officialAgent.modelStep.embeddingPlaceholder"));
          return;
        }
        finalEmbeddingModelIds[b.name] = availableEmbeddingModels[0].id;
      }
    }

    const gcSkillRenames: Record<string, string> = {};
    for (const c of gcResourceConflicts.skills) {
      const r = gcSkillResolutions[c.key];
      if (r?.action === "rename" && r.newName.trim()) {
        gcSkillRenames[c.key] = r.newName.trim();
      }
    }
    const gcKbRenames: Record<string, string> = {};
    for (const c of gcResourceConflicts.kbs) {
      const r = gcKbResolutions[c.key];
      if (r?.action === "rename" && r.newName.trim()) {
        gcKbRenames[c.key] = r.newName.trim();
      }
    }
    const gcMcpRenames: Record<string, string> = {};
    const gcMcpSkips: string[] = [];
    for (const c of gcResourceConflicts.mcps) {
      const r = gcMcpResolutions[c.key];
      if (r?.action === "rename" && r.newName.trim()) {
        gcMcpRenames[c.key] = r.newName.trim();
      } else if (r?.action === "skip") {
        gcMcpSkips.push(c.key);
      }
    }

    setGcInstalling(true);
    try {
      const res = await gitcodeInstallMutation.mutateAsync({
        names: Array.from(gcSelected),
        model_ids: Object.keys(finalModelIds).length
          ? finalModelIds
          : undefined,
        embedding_model_ids: Object.keys(finalEmbeddingModelIds).length
          ? finalEmbeddingModelIds
          : undefined,
        skill_renames: Object.keys(gcSkillRenames).length
          ? gcSkillRenames
          : undefined,
        kb_renames: Object.keys(gcKbRenames).length
          ? gcKbRenames
          : undefined,
        mcp_renames: Object.keys(gcMcpRenames).length
          ? gcMcpRenames
          : undefined,
        mcp_skips: gcMcpSkips.length ? gcMcpSkips : undefined,
      });
      setGcResults(res);
      const successfulNames = res
        .filter(
          (result) =>
            result.status === "installed" ||
            result.status === "already_installed"
        )
        .map((result) => result.name);
      if (successfulNames.length > 0) {
        setGcInstalledNamesState((previous) => {
          const merged = new Set([...previous, ...successfulNames]);
          window.localStorage.setItem(
            gcInstalledStorageKey,
            JSON.stringify([...merged])
          );
          return merged;
        });
      }
      setGcStage("done");
      onInstalled?.();
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("officialAgent.installModal.failed")
      );
    } finally {
      setGcInstalling(false);
    }
  };


  // select -> conflict pre-check -> rename / mcp / model
  const handleSelectNext = async () => {
    if (selectedNames.size === 0) {
      message.warning(t("officialAgent.installModal.selectAtLeastOne"));
      return;
    }
    setChecking(true);
    try {
      const items: Array<{ name: string; display_name?: string }> = [];
      const meta: Array<{ bundleName: string; agentName: string }> = [];
      for (const b of selectedAgents) {
        for (const a of b.agents ?? []) {
          items.push({
            name: a.name,
            display_name: a.display_name ?? undefined,
          });
          meta.push({ bundleName: b.name, agentName: a.name });
        }
      }
      const res = await checkAgentNameConflictBatch({ items });
      if (!res.success || !Array.isArray(res.data)) {
        message.error(t("officialAgent.rename.checkFailed"));
        return;
      }
      const found: ConflictItem[] = [];
      res.data.forEach((r: any, i: number) => {
        if (r?.name_conflict && meta[i]) {
          found.push({
            bundleName: meta[i].bundleName,
            agentName: meta[i].agentName,
            conflictAgents: Array.isArray(r.conflict_agents)
              ? r.conflict_agents
              : [],
          });
        }
      });
      setConflicts(found);
      const drafts: Record<string, string> = {};
      for (const c of found) drafts[c.agentName] = c.agentName;
      setRenameDrafts(drafts);

      // Advance to the first available step after select.
      const nextKeys = [
        "select",
        ...(found.length > 0 ? ["rename"] : []),
        ...(hasResourceConflicts ? ["resources"] : []),
        ...(hasSelectedMcps ? ["mcp"] : []),
        "model",
      ];
      const target = found.length > 0
        ? "rename"
        : hasResourceConflicts
          ? "resources"
          : hasSelectedMcps
            ? "mcp"
            : "model";
      setCurrentStep(nextKeys.indexOf(target));
    } finally {
      setChecking(false);
    }
  };

  const handleNext = () => {
    if (currentStepKey === "select") {
      handleSelectNext();
      return;
    }
    if (currentStepKey === "rename") {
      const next: Record<string, string> = {};
      for (const c of conflicts) {
        const value = renameDrafts[c.agentName]?.trim();
        if (value && value !== c.agentName) {
          next[c.agentName] = value;
        }
      }
      setRenames(next);
    }
    if (currentStepKey === "resources" && !resourceAllResolved) {
      message.warning(t("officialAgent.resources.required"));
      return;
    }
    setCurrentStep(currentStep + 1);
  };

  const handleInstall = async () => {
    const finalModelIds: Record<string, number> = { ...modelSelections };
    for (const b of selectedAgents) {
      if (finalModelIds[b.name] == null) {
        if (!availableLlmModels.length) {
          message.warning(t("officialAgent.modelStep.placeholder"));
          return;
        }
        finalModelIds[b.name] = availableLlmModels[0].id;
      }
    }
    setModelSelections(finalModelIds);

    // Embedding model for KB-bearing bundles, defaulting to the first available.
    const finalEmbeddingModelIds: Record<string, number> = {
      ...embeddingModelSelections,
    };
    for (const b of selectedAgents) {
      if (!b.has_knowledge) continue;
      if (finalEmbeddingModelIds[b.name] == null) {
        if (!availableEmbeddingModels.length) {
          message.warning(t("officialAgent.modelStep.embeddingPlaceholder"));
          return;
        }
        finalEmbeddingModelIds[b.name] = availableEmbeddingModels[0].id;
      }
    }

    const skillRenames: Record<string, string> = {};
    for (const c of resourceConflicts.skills) {
      const r = skillResolutions[c.key];
      if (r?.action === "rename" && r.newName.trim()) {
        skillRenames[c.key] = r.newName.trim();
      }
    }
    const kbRenames: Record<string, string> = {};
    for (const c of resourceConflicts.kbs) {
      const r = kbResolutions[c.key];
      if (r?.action === "rename" && r.newName.trim()) {
        kbRenames[c.key] = r.newName.trim();
      }
    }
    const mcpRenames: Record<string, string> = {};
    const mcpSkips: string[] = [];
    for (const c of resourceConflicts.mcps) {
      const r = mcpResolutions[c.key];
      if (r?.action === "rename" && r.newName.trim()) {
        mcpRenames[c.key] = r.newName.trim();
      } else if (r?.action === "skip") {
        mcpSkips.push(c.key);
      }
    }

    setIsInstalling(true);
    try {
      const results = await installMutation.mutateAsync({
        names: Array.from(selectedNames),
        renames: Object.keys(renames).length ? renames : undefined,
        model_ids: Object.keys(finalModelIds).length
          ? finalModelIds
          : undefined,
        embedding_model_ids: Object.keys(finalEmbeddingModelIds).length
          ? finalEmbeddingModelIds
          : undefined,
        skill_renames: Object.keys(skillRenames).length
          ? skillRenames
          : undefined,
        kb_renames: Object.keys(kbRenames).length ? kbRenames : undefined,
        mcp_renames: Object.keys(mcpRenames).length ? mcpRenames : undefined,
        mcp_skips: mcpSkips.length ? mcpSkips : undefined,
      });
      setLastResults(results);
      onInstalled?.();
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("officialAgent.installModal.failed")
      );
    } finally {
      setIsInstalling(false);
    }
  };

  const canProceed = () => {
    if (checking) return false;
    if (currentStepKey === "select") {
      return selectedNames.size > 0 && !isLoading;
    }
    if (currentStepKey === "resources") {
      return resourceAllResolved;
    }
    if (currentStepKey === "model") {
      return availableLlmModels.length > 0;
    }
    return true;
  };

  const renderStepContent = () => {
    if (isInstalling) {
      return <InstallStepsView installing />;
    }
    if (lastResults) {
      return (
        <InstallResultsView
          results={lastResults}
          onGoConfigure={goConfigureModel}
        />
      );
    }
    if (checking && currentStepKey === "select") {
      return (
        <div className="flex items-center justify-center py-12">
          <Spin size="large" />
          <span className="ml-4 text-gray-600 dark:text-gray-400">
            {t("officialAgent.rename.checking", "Checking agent names...")}
          </span>
        </div>
      );
    }
    if (currentStepKey === "select") {
      return (
        <SelectStep
          agents={allAgents}
          selectedNames={selectedNames}
          allSelected={allSelected}
          someSelected={someSelected}
          onToggleAll={handleToggleAll}
          onToggle={(name) => {
            setSelectedNames((prev) => {
              const next = new Set(prev);
              if (next.has(name)) next.delete(name);
              else next.add(name);
              return next;
            });
          }}
          onGoConfigure={goConfigureModel}
        />
      );
    }
    if (currentStepKey === "rename") {
      return (
        <RenameStep
          conflicts={conflicts}
          drafts={renameDrafts}
          onChange={(agentName, value) =>
            setRenameDrafts((prev) => ({ ...prev, [agentName]: value }))
          }
        />
      );
    }
    if (currentStepKey === "resources") {
      return (
        <ResourceConflictStep
          skills={resourceConflicts.skills}
          kbs={resourceConflicts.kbs}
          mcps={resourceConflicts.mcps}
          skillResolutions={skillResolutions}
          kbResolutions={kbResolutions}
          mcpResolutions={mcpResolutions}
          onSkillChange={(key, res) =>
            setSkillResolutions((prev) => ({ ...prev, [key]: res }))
          }
          onKbChange={(key, res) =>
            setKbResolutions((prev) => ({ ...prev, [key]: res }))
          }
          onMcpChange={(key, res) =>
            setMcpResolutions((prev) => ({ ...prev, [key]: res }))
          }
        />
      );
    }
    if (currentStepKey === "mcp") {
      return <McpPreviewStep agents={selectedAgents} />;
    }
    if (currentStepKey === "model") {
      return (
        <ModelStep
          agents={selectedAgents}
          selections={modelSelections}
          onChange={(bundleName, modelId) =>
            setModelSelections((prev) => ({ ...prev, [bundleName]: modelId }))
          }
          availableLlmModels={availableLlmModels}
          embeddingSelections={embeddingModelSelections}
          onEmbeddingChange={(bundleName, modelId) =>
            setEmbeddingModelSelections((prev) => ({
              ...prev,
              [bundleName]: modelId,
            }))
          }
          availableEmbeddingModels={availableEmbeddingModels}
        />
      );
    }
    return null;
  };

  const isLastStep = currentStep === steps.length - 1;

  return (
    <Modal
      title={
        <div className="flex items-center gap-2">
          <Download size={20} />
          <span>{t("officialAgent.installModal.title")}</span>
        </div>
      }
      open={open}
      onCancel={handleCancel}
      width={800}
      destroyOnHidden
      footer={
        activeSource === "gitcode" ? (
          // GitCode：操作按钮固定在底部 footer、紧邻取消键左侧
          <div className="flex items-center justify-end gap-2">
            {(gcStage === "model" || gcStage === "resources") &&
              !gcInstalling &&
              !gcResults && (
                <Button onClick={handleGcBack}>
                  {t("officialAgent.wizard.back", "Previous")}
                </Button>
              )}
            {gcResults ? (
              <Button type="primary" onClick={onClose}>
                {t("common.confirm", "OK")}
              </Button>
            ) : gcStage === "catalog" ? (
              <Button
                type="primary"
                disabled={gcSelected.size === 0 || gitcodeCatalog.isLoading}
                onClick={handleGcNext}
              >
                {t("officialAgent.wizard.next", "Next")}
              </Button>
            ) : gcStage === "resources" ? (
              <Button
                type="primary"
                disabled={!gcResourceAllResolved}
                onClick={handleGcResourcesNext}
              >
                {t("officialAgent.wizard.next", "Next")}
              </Button>
            ) : (
              <Button
                type="primary"
                loading={gcInstalling}
                onClick={handleGcInstall}
                icon={<Download size={16} />}
              >
                {gcInstalling
                  ? t("officialAgent.wizard.installing", "Installing...")
                  : t("officialAgent.wizard.install", "Install")}
              </Button>
            )}
            <Button onClick={handleCancel}>
              {t("common.cancel", "Cancel")}
            </Button>
          </div>
        ) : (
          <div className="flex items-center justify-end gap-2">
            {currentStep > 0 && !isInstalling && !lastResults && (
              <Button onClick={() => setCurrentStep(currentStep - 1)}>
                {t("officialAgent.wizard.back", "Previous")}
              </Button>
            )}
            {lastResults ? (
              <Button type="primary" onClick={onClose}>
                {t("common.confirm", "OK")}
              </Button>
            ) : !isLastStep ? (
              <Button
                type="primary"
                onClick={handleNext}
                disabled={!canProceed()}
                loading={checking}
              >
                {t("officialAgent.wizard.next", "Next")}
              </Button>
            ) : (
              <Button
                type="primary"
                onClick={handleInstall}
                disabled={!canProceed()}
                loading={isInstalling}
                icon={<Download size={16} />}
              >
                {isInstalling
                  ? t("officialAgent.wizard.installing", "Installing...")
                  : t("officialAgent.wizard.install", "Install")}
              </Button>
            )}
            <Button onClick={handleCancel}>
              {t("common.cancel", "Cancel")}
            </Button>
          </div>
        )
      }
    >
      <div className="pt-6 pb-4">
        <Segmented
          style={{ marginBottom: "1.5rem" }}
          value={activeSource}
          onChange={(value) => setActiveSource(value as "local" | "gitcode")}
          options={[
            { label: t("officialAgent.gitcode.sourceLocal"), value: "local" },
            { label: t("officialAgent.gitcode.sourceGitcode"), value: "gitcode" },
          ]}
        />

        {activeSource === "local" ? (
          <>
            <Steps
              current={currentStep}
              items={steps.map((step) => ({ title: step.title }))}
              style={{ marginBottom: "1.5rem" }}
            />

            <div className="min-h-[300px] max-h-[70vh] overflow-y-auto pr-1">
              {renderStepContent()}
            </div>
          </>
        ) : gitcodeCatalog.isLoading ? (
          <div className="flex min-h-[300px] items-center justify-center">
            <Spin size="large" />
          </div>
        ) : gitcodeCatalog.isError || !gitcodeCatalog.data ? (
          <div className="flex min-h-[300px] flex-col items-center justify-center gap-3">
            <CircleOff className="size-8 text-red-400" />
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {t("officialAgent.gitcode.loadError")}
            </p>
            <Button
              icon={<RefreshCw className="size-3.5" />}
              onClick={() => gitcodeCatalog.refetch()}
            >
              {t("officialAgent.gitcode.refresh")}
            </Button>
          </div>
        ) : (
          <div className="min-h-[300px] max-h-[70vh] overflow-y-auto pr-1">
            <GitcodeView
              data={gitcodeCatalog.data}
              stage={gcStage}
              selected={gcSelected}
              allSelected={gcAllSelected}
              selectedBundles={gcSelectedBundles}
              modelSelections={gcModelSelections}
              onModelChange={(bundleName, modelId) =>
                setGcModelSelections((prev) => ({
                  ...prev,
                  [bundleName]: modelId,
                }))
              }
              embeddingSelections={gcEmbeddingModelSelections}
              onEmbeddingChange={(bundleName, modelId) =>
                setGcEmbeddingModelSelections((prev) => ({
                  ...prev,
                  [bundleName]: modelId,
                }))
              }
              availableLlmModels={availableLlmModels}
              availableEmbeddingModels={availableEmbeddingModels}
              onToggle={handleGcToggle}
              onToggleAll={handleGcToggleAll}
              onGoConfigureModel={goConfigureModel}
              onRefresh={() => gitcodeCatalog.refetch()}
              refreshing={gitcodeCatalog.isFetching}
              onBackToCatalog={() => {
                setGcStage("catalog");
                setGcSelected(new Set());
              }}
              results={gcResults}
              skills={gcResourceConflicts.skills}
              kbs={gcResourceConflicts.kbs}
              mcps={gcResourceConflicts.mcps}
              skillResolutions={gcSkillResolutions}
              kbResolutions={gcKbResolutions}
              mcpResolutions={gcMcpResolutions}
              onSkillChange={(key, res) =>
                setGcSkillResolutions((prev) => ({ ...prev, [key]: res }))
              }
              onKbChange={(key, res) =>
                setGcKbResolutions((prev) => ({ ...prev, [key]: res }))
              }
              onMcpChange={(key, res) =>
                setGcMcpResolutions((prev) => ({ ...prev, [key]: res }))
              }
            />
          </div>
        )}
      </div>
    </Modal>
  );
}

function SelectStep({
  agents,
  selectedNames,
  allSelected,
  someSelected,
  onToggleAll,
  onToggle,
  onGoConfigure,
}: {
  agents: OfficialAgentItem[];
  selectedNames: Set<string>;
  allSelected: boolean;
  someSelected: boolean;
  onToggleAll: () => void;
  onToggle: (name: string) => void;
  onGoConfigure: () => void;
}) {
  const { t } = useTranslation("common");

  return (
    <div className="space-y-4">
      <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
        <div className="flex items-center gap-2 mb-3">
          <input
            type="checkbox"
            checked={allSelected}
            ref={(el) => {
              if (el) el.indeterminate = someSelected;
            }}
            onChange={onToggleAll}
            className="h-4 w-4 shrink-0 cursor-pointer accent-blue-500"
          />
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
            {t("common.selectAll")}
          </span>
        </div>
        <div className="space-y-3">
          {agents.map((agent) => (
            <AgentSelectCard
              key={agent.name}
              agent={agent}
              checked={selectedNames.has(agent.name)}
              onToggle={onToggle}
              onGoConfigure={onGoConfigure}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function AgentSelectCard({
  agent,
  checked,
  onToggle,
  onGoConfigure,
}: {
  agent: OfficialAgentItem;
  checked: boolean;
  onToggle: (name: string) => void;
  onGoConfigure: () => void;
}) {
  const { t } = useTranslation("common");

  const isDisabled =
    agent.status === "installed" || agent.status === "needs_model";
  const title =
    agent.display_name?.trim() ||
    agent.name ||
    t("officialAgent.card.untitled");

  return (
    <div
      className={`flex items-start gap-3 rounded-lg border p-3 ${
        isDisabled
          ? "opacity-60 border-gray-200 dark:border-gray-700"
          : "border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800/50"
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={() => {
          if (isDisabled) return;
          onToggle(agent.name);
        }}
        disabled={isDisabled}
        className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer accent-blue-500"
      />
      <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-base text-primary">
        {agent.icon?.trim() ? (
          <span aria-hidden>{agent.icon.trim()}</span>
        ) : (
          <Bot className="size-4" aria-hidden />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
            {title}
          </span>
          <AgentCountChips agent={agent} />
        </div>
        {agent.description?.trim() ? (
          <p className="mt-0.5 truncate text-xs text-gray-500 dark:text-gray-400">
            {agent.description.trim()}
          </p>
        ) : null}
      </div>
      <div className="shrink-0">
        {agent.status === "needs_model" ? (
          <Button
            type="link"
            size="small"
            className="flex items-center gap-1 p-0 text-amber-600"
            onClick={onGoConfigure}
          >
            <CircleOff className="size-3.5" />
            <span>{t("officialAgent.install.goConfigure")}</span>
            <ExternalLink className="size-3" />
          </Button>
        ) : agent.status === "installed" ? (
          <Tag color="success" icon={<CircleCheck size={14} />}>
            {t("officialAgent.status.installed")}
          </Tag>
        ) : null}
      </div>
    </div>
  );
}

function RenameStep({
  conflicts,
  drafts,
  onChange,
}: {
  conflicts: ConflictItem[];
  drafts: Record<string, string>;
  onChange: (agentName: string, value: string) => void;
}) {
  const { t } = useTranslation("common");

  return (
    <div className="space-y-6">
      <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4 space-y-2">
        <p className="text-sm font-semibold text-yellow-800 dark:text-yellow-200">
          {t("officialAgent.rename.title")}
        </p>
        <p className="text-xs text-yellow-800 dark:text-yellow-200">
          {t("officialAgent.rename.desc")}
        </p>
      </div>

      <div className="space-y-6">
        {conflicts.map((c) => (
          <div
            key={`${c.bundleName}:${c.agentName}`}
            className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 space-y-4"
          >
            <div className="flex items-center gap-2">
              <Tag color="purple">{c.bundleName}</Tag>
              <h4 className="text-base font-semibold text-gray-900 dark:text-gray-100">
                {c.agentName}
              </h4>
            </div>

            {c.conflictAgents.length > 0 && (
              <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded p-2 mb-3">
                <p className="text-xs text-red-700 dark:text-red-300 mb-1">
                  {t("officialAgent.rename.conflictWith")}
                </p>
                <ul className="list-disc list-inside text-xs text-red-700 dark:text-red-300">
                  {c.conflictAgents.map(
                    (agent: { name?: string; display_name?: string }, idx: number) => (
                      <li key={idx}>
                        {[agent.name, agent.display_name]
                          .filter(Boolean)
                          .join(" / ")}
                      </li>
                    )
                  )}
                </ul>
              </div>
            )}

            <div>
              <label className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 block">
                {t("officialAgent.rename.name", "Agent Name")}
              </label>
              <Input
                value={drafts[c.agentName] ?? c.agentName}
                onChange={(e) => onChange(c.agentName, e.target.value)}
                placeholder={c.agentName}
                size="large"
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ResourceConflictStep({
  skills,
  kbs,
  mcps,
  skillResolutions,
  kbResolutions,
  mcpResolutions,
  onSkillChange,
  onKbChange,
  onMcpChange,
}: {
  skills: ResourceConflict[];
  kbs: ResourceConflict[];
  mcps: ResourceConflict[];
  skillResolutions: Record<string, ResourceResolution>;
  kbResolutions: Record<string, ResourceResolution>;
  mcpResolutions: Record<string, McpResolution>;
  onSkillChange: (key: string, res: ResourceResolution) => void;
  onKbChange: (key: string, res: ResourceResolution) => void;
  onMcpChange: (key: string, res: McpResolution) => void;
}) {
  const { t } = useTranslation("common");

  if (skills.length === 0 && kbs.length === 0 && mcps.length === 0) return null;

  const renderItem = (
    conflict: ResourceConflict,
    resolution: ResourceResolution | undefined,
    onChange: (key: string, res: ResourceResolution) => void
  ) => (
    <div
      key={conflict.key}
      className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 space-y-3"
    >
      <div className="flex items-center gap-2">
        <Tag color="purple">{conflict.bundleName}</Tag>
        <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          {conflict.display}
        </span>
      </div>
      <Radio.Group
        value={resolution?.action}
        onChange={(e) =>
          onChange(conflict.key, {
            action: e.target.value,
            newName: e.target.value === "rename" ? resolution?.newName ?? "" : "",
          })
        }
      >
        <Radio value="reuse">{t("officialAgent.resources.reuse")}</Radio>
        <Radio value="rename">{t("officialAgent.resources.rename")}</Radio>
      </Radio.Group>
      {resolution?.action === "rename" ? (
        <Input
          value={resolution.newName}
          onChange={(e) =>
            onChange(conflict.key, { action: "rename", newName: e.target.value })
          }
          placeholder={t("officialAgent.resources.newNamePlaceholder")}
          size="large"
        />
      ) : null}
    </div>
  );

  const renderMcpItem = (
    conflict: ResourceConflict,
    resolution: McpResolution | undefined,
    onChange: (key: string, res: McpResolution) => void
  ) => (
    <div
      key={conflict.key}
      className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 space-y-3"
    >
      <div className="flex items-center gap-2">
        <Tag color="purple">{conflict.bundleName}</Tag>
        <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          {conflict.display}
        </span>
      </div>
      <Radio.Group
        value={resolution?.action}
        onChange={(e) =>
          onChange(conflict.key, {
            action: e.target.value,
            newName:
              e.target.value === "rename" ? resolution?.newName ?? "" : "",
          })
        }
      >
        <Radio value="rename">{t("officialAgent.resources.rename")}</Radio>
        <Radio value="skip">{t("officialAgent.resources.skip")}</Radio>
      </Radio.Group>
      {resolution?.action === "rename" ? (
        <Input
          value={resolution.newName}
          onChange={(e) =>
            onChange(conflict.key, { action: "rename", newName: e.target.value })
          }
          placeholder={t("officialAgent.resources.newNamePlaceholder")}
          size="large"
        />
      ) : resolution?.action === "skip" ? (
        <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded p-2">
          <p className="text-xs text-yellow-800 dark:text-yellow-200">
            {t("officialAgent.resources.mcpSkipWarning")}
          </p>
        </div>
      ) : null}
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
        <p className="text-sm font-semibold text-yellow-800 dark:text-yellow-200">
          {t("officialAgent.resources.title")}
        </p>
        <p className="text-xs text-yellow-800 dark:text-yellow-200">
          {t("officialAgent.resources.desc")}
        </p>
      </div>

      {skills.length > 0 ? (
        <div className="space-y-3">
          <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
            {t("officialAgent.resources.skills")}
          </p>
          {skills.map((c) => renderItem(c, skillResolutions[c.key], onSkillChange))}
        </div>
      ) : null}

      {kbs.length > 0 ? (
        <div className="space-y-3">
          <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
            {t("officialAgent.resources.knowledgeBases")}
          </p>
          {kbs.map((c) => renderItem(c, kbResolutions[c.key], onKbChange))}
        </div>
      ) : null}

      {mcps.length > 0 ? (
        <div className="space-y-3">
          <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
            {t("officialAgent.resources.mcps")}
          </p>
          {mcps.map((c) =>
            renderMcpItem(c, mcpResolutions[c.key], onMcpChange)
          )}
        </div>
      ) : null}
    </div>
  );
}

function McpPreviewStep({ agents }: { agents: OfficialAgentItem[] }) {
  const { t } = useTranslation("common");

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
        {t("officialAgent.mcpPreview.desc")}
      </p>
      <div className="space-y-3">
        {agents.map((b) => {
          const mcps = b.mcps ?? [];
          if (mcps.length === 0) return null;
          const title = b.display_name?.trim() || b.name;
          return (
            <div
              key={b.name}
              className="border border-gray-200 dark:border-gray-700 rounded-lg p-4"
            >
              <p className="mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">
                {title}
              </p>
              <div className="space-y-3">
                {mcps.map((m) => (
                  <div
                    key={m.mcp_server_name}
                    className="flex items-center justify-between w-full gap-4"
                  >
                    <div className="flex items-center gap-2">
                      <Plug className="size-4 text-slate-400" />
                      <span className="font-medium text-sm">
                        {m.mcp_server_name}
                      </span>
                    </div>
                    {m.installed ? (
                      <Tag
                        icon={<CircleCheck size={14} />}
                        color="success"
                        className="inline-flex items-center gap-1 text-xs"
                      >
                        {t("officialAgent.mcpPreview.installed")}
                      </Tag>
                    ) : (
                      <Tag
                        color="blue"
                        className="inline-flex items-center gap-1 text-xs"
                      >
                        {t("officialAgent.mcpPreview.toInstall")}
                      </Tag>
                    )}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ModelStep({
  agents,
  selections,
  onChange,
  availableLlmModels,
  embeddingSelections,
  onEmbeddingChange,
  availableEmbeddingModels,
}: {
  agents: OfficialAgentItem[];
  selections: Record<string, number>;
  onChange: (bundleName: string, modelId: number) => void;
  availableLlmModels: ModelOption[];
  embeddingSelections: Record<string, number>;
  onEmbeddingChange: (bundleName: string, modelId: number) => void;
  availableEmbeddingModels: ModelOption[];
}) {
  const { t } = useTranslation("common");

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
        {t("officialAgent.modelStep.desc")}
      </p>
      <div className="space-y-4">
        {agents.map((b) => {
          const title = b.display_name?.trim() || b.name;
          return (
            <div
              key={b.name}
              className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 space-y-4"
            >
              <div>
                <label className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 block">
                  {title}
                  <span className="text-red-500 ml-1">*</span>
                </label>
                {availableLlmModels.length === 0 ? (
                  <Spin />
                ) : (
                  <Select
                    value={selections[b.name]}
                    onChange={(v) => onChange(b.name, v)}
                    size="large"
                    style={{ width: "100%" }}
                    placeholder={t("officialAgent.modelStep.placeholder")}
                  >
                    {availableLlmModels.map((m) => (
                      <Select.Option key={m.id} value={m.id}>
                        {m.displayName || m.name}
                      </Select.Option>
                    ))}
                  </Select>
                )}
              </div>

              {b.has_knowledge ? (
                <div>
                  <label className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 block">
                    {t("officialAgent.modelStep.embeddingLabel")}
                    <span className="text-red-500 ml-1">*</span>
                  </label>
                  {availableEmbeddingModels.length === 0 ? (
                    <Spin />
                  ) : (
                    <Select
                      value={embeddingSelections[b.name]}
                      onChange={(v) => onEmbeddingChange(b.name, v)}
                      size="large"
                      style={{ width: "100%" }}
                      placeholder={t(
                        "officialAgent.modelStep.embeddingPlaceholder"
                      )}
                    >
                      {availableEmbeddingModels.map((m) => (
                        <Select.Option key={m.id} value={m.id}>
                          {m.displayName || m.name}
                        </Select.Option>
                      ))}
                    </Select>
                  )}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function AgentCountChips({ agent }: { agent: OfficialAgentItem }) {
  const chips: React.ReactNode[] = [];

  if (agent.mcp_count > 0) {
    chips.push(
      <span
        key="mcp"
        className="inline-flex items-center gap-0.5 text-[11px] text-slate-500"
        aria-label={`${agent.mcp_count} MCP`}
      >
        <Plug className="size-3" aria-hidden />
        {agent.mcp_count}
      </span>
    );
  }
  if (agent.skill_count > 0) {
    chips.push(
      <span
        key="skill"
        className="inline-flex items-center gap-0.5 text-[11px] text-slate-500"
        aria-label={`${agent.skill_count} skills`}
      >
        <Sparkles className="size-3" aria-hidden />
        {agent.skill_count}
      </span>
    );
  }
  if (agent.kb_count > 0) {
    chips.push(
      <span
        key="kb"
        className="inline-flex items-center gap-0.5 text-[11px] text-slate-500"
        aria-label={`${agent.kb_count} KB`}
      >
        <Database className="size-3" aria-hidden />
        {agent.kb_count}
      </span>
    );
  }

  return <span className="flex items-center gap-1.5">{chips}</span>;
}

// Install steps shown during (installing) and after (steps) an install.
const INSTALL_STEP_NAMES: Array<{ key: string; i18n: string }> = [
  { key: "mcp", i18n: "officialAgent.step.mcp" },
  { key: "skill", i18n: "officialAgent.step.skill" },
  { key: "knowledge_base", i18n: "officialAgent.step.knowledgeBase" },
  { key: "agent", i18n: "officialAgent.step.agent" },
];

function InstallStepsView({
  installing,
  steps,
}: {
  installing: boolean;
  steps?: OfficialAgentInstallStep[];
}) {
  const { t } = useTranslation("common");

  const stepMap = new Map(steps?.map((s) => [s.name, s]) ?? []);

  return (
    <div className="space-y-3">
      {INSTALL_STEP_NAMES.map(({ key, i18n }) => {
        const result = stepMap.get(key);
        if (installing) {
          return (
            <div
              key={key}
              className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 flex items-center gap-3"
            >
              <LoaderCircle className="size-5 shrink-0 animate-spin text-primary" />
              <span className="text-sm text-gray-700 dark:text-gray-300">
                {t(i18n)}
              </span>
              <span className="ml-auto text-xs text-gray-400">
                {t("officialAgent.step.inProgress")}
              </span>
            </div>
          );
        }
        if (!result) {
          return null;
        }
        if (result.status === "failed") {
          return (
            <div
              key={key}
              className="border border-red-200 dark:border-red-800 rounded-lg p-4"
            >
              <div className="flex items-center gap-2 text-sm text-red-700 dark:text-red-300">
                <CircleOff className="size-5 shrink-0" />
                <span>{t(i18n)}</span>
                <span className="ml-auto text-xs">
                  {t("officialAgent.step.failed")}
                </span>
              </div>
              {result.message ? (
                <p className="mt-1 text-xs leading-relaxed text-red-600 dark:text-red-400">
                  {result.message}
                </p>
              ) : null}
            </div>
          );
        }
        return (
          <div
            key={key}
            className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 flex items-center gap-3"
          >
            <CircleCheck className="size-5 shrink-0 text-green-500" />
            <span className="text-sm text-gray-700 dark:text-gray-300">
              {t(i18n)}
            </span>
            <span className="ml-auto text-xs text-gray-400">
              {t("officialAgent.step.done")}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function InstallResultsView({
  results,
  onGoConfigure,
}: {
  results: OfficialAgentInstallItem[];
  onGoConfigure: () => void;
}) {
  const { t } = useTranslation("common");

  return (
    <div className="space-y-3">
      {results.map((result) => {
        const isInstalled =
          result.status === "installed" || result.status === "already_installed";
        const title = result.name || t("officialAgent.card.untitled");
        return (
          <div
            key={result.name}
            className="border border-gray-200 dark:border-gray-700 rounded-lg p-4"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-sm font-semibold text-gray-900 dark:text-gray-100">
                {title}
              </span>
              {isInstalled ? (
                <Tag color="success" icon={<CircleCheck size={14} />}>
                  {t("officialAgent.status.installed")}
                </Tag>
              ) : (
                <Tag color="error" icon={<CircleOff size={14} />}>
                  {t("officialAgent.installModal.failed")}
                </Tag>
              )}
            </div>
            <div className="mt-3">
              <InstallStepsView installing={false} steps={result.steps} />
            </div>
            {!isInstalled && !result.steps?.length ? (
              <p className="mt-2 text-xs text-red-600">
                {result.message || t("officialAgent.installModal.failed")}
              </p>
            ) : null}
          </div>
        );
      })}
      {results.some((r) => r.status === "needs_model") ? (
        <Button
          type="link"
          className="flex items-center gap-1 p-0 text-primary"
          onClick={onGoConfigure}
        >
          {t("officialAgent.install.goConfigure")}
          <ExternalLink className="size-3" />
        </Button>
      ) : null}
    </div>
  );
}

/**
 * GitCode 固定源目录视图（纯展示）。
 *
 * 状态与操作由父组件管理（footer 渲染操作按钮）；此处仅渲染目录或选模型表单。
 */
function GitcodeView({
  data,
  stage,
  selected,
  allSelected,
  selectedBundles,
  modelSelections,
  onModelChange,
  embeddingSelections,
  onEmbeddingChange,
  availableLlmModels,
  availableEmbeddingModels,
  onToggle,
  onToggleAll,
  onGoConfigureModel,
  onRefresh,
  refreshing,
  onBackToCatalog,
  results,
  skills,
  kbs,
  mcps,
  skillResolutions,
  kbResolutions,
  mcpResolutions,
  onSkillChange,
  onKbChange,
  onMcpChange,
}: {
  data: OfficialAgentGithubDiscoverResult;
  stage: "catalog" | "resources" | "model" | "done";
  selected: Set<string>;
  allSelected: boolean;
  selectedBundles: OfficialAgentItem[];
  modelSelections: Record<string, number>;
  onModelChange: (bundleName: string, modelId: number) => void;
  embeddingSelections: Record<string, number>;
  onEmbeddingChange: (bundleName: string, modelId: number) => void;
  availableLlmModels: ModelOption[];
  availableEmbeddingModels: ModelOption[];
  onToggle: (name: string) => void;
  onToggleAll: () => void;
  onGoConfigureModel: () => void;
  onRefresh: () => void;
  refreshing: boolean;
  onBackToCatalog: () => void;
  results: OfficialAgentInstallItem[] | null;
  skills: ResourceConflict[];
  kbs: ResourceConflict[];
  mcps: ResourceConflict[];
  skillResolutions: Record<string, ResourceResolution>;
  kbResolutions: Record<string, ResourceResolution>;
  mcpResolutions: Record<string, McpResolution>;
  onSkillChange: (key: string, res: ResourceResolution) => void;
  onKbChange: (key: string, res: ResourceResolution) => void;
  onMcpChange: (key: string, res: McpResolution) => void;
}) {
  const { t } = useTranslation("common");

  if (stage === "done") {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
            {data.repo}
          </span>
          <Button type="link" onClick={onBackToCatalog}>
            {t("officialAgent.gitcode.backToCatalog")}
          </Button>
        </div>
        <InstallResultsView
          results={results ?? []}
          onGoConfigure={onGoConfigureModel}
        />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex min-w-0 items-center gap-2">
          <GitBranch className="size-4 shrink-0 text-slate-400" />
          <span className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
            {data.repo}
          </span>
          {data.commit ? <Tag>{data.commit.slice(0, 7)}</Tag> : null}
          <Tag color="blue">{data.ref}</Tag>
        </div>
        <Button
          size="small"
          icon={<RefreshCw className="size-3.5" />}
          loading={refreshing}
          onClick={onRefresh}
        >
          {t("officialAgent.gitcode.refresh")}
        </Button>
      </div>

      {stage === "catalog" ? (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={onToggleAll}
              className="h-4 w-4 shrink-0 cursor-pointer accent-blue-500"
            />
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
              {t("common.selectAll")}
            </span>
          </div>
          {data.groups.map((group) => (
            <div key={group.name}>
              <h3 className="mb-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
                {group.name}
              </h3>
              {group.categories.map((cat) => (
                <div key={cat.name} className="mb-3">
                  <p className="mb-1 text-xs font-medium text-slate-500 dark:text-slate-400">
                    {cat.name}
                  </p>
                  <div className="space-y-2">
                    {cat.bundles.map((agent) => (
                      <AgentSelectCard
                        key={agent.name}
                        agent={agent}
                        checked={selected.has(agent.name)}
                        onToggle={onToggle}
                        onGoConfigure={onGoConfigureModel}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      ) : stage === "resources" ? (
        <ResourceConflictStep
          skills={skills}
          kbs={kbs}
          mcps={mcps}
          skillResolutions={skillResolutions}
          kbResolutions={kbResolutions}
          mcpResolutions={mcpResolutions}
          onSkillChange={onSkillChange}
          onKbChange={onKbChange}
          onMcpChange={onMcpChange}
        />
      ) : (
        <ModelStep
          agents={selectedBundles}
          selections={modelSelections}
          onChange={onModelChange}
          availableLlmModels={availableLlmModels}
          embeddingSelections={embeddingSelections}
          onEmbeddingChange={onEmbeddingChange}
          availableEmbeddingModels={availableEmbeddingModels}
        />
      )}
    </div>
  );
}
