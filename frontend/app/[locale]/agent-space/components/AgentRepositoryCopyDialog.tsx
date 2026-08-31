"use client";

import { useEffect, useMemo, useState } from "react";
import { App, Button, Input, Modal, Popover, Select, Spin } from "antd";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Copy,
  Cpu,
  Database,
  ExternalLink,
  Plug,
  RefreshCw,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  useImportAgentFromRepository,
  useRepositoryImportPrecheck,
} from "@/hooks/agentRepository/useAgentRepositoryListings";
import {
  getRepositoryRequirementActivatePath,
  getRepositoryRequirementReasonLabel,
  getRepositoryRequirementTypeLabel,
  getRepositoryRequirementTypeOrder,
} from "@/lib/agentRepositoryLabels";
import log from "@/lib/logger";
import { useModelList } from "@/hooks/model/useModelList";
import { installAgentRepositorySkill } from "@/services/agentRepositoryService";
import { addMcpServer, updateToolList } from "@/services/mcpService";
import type {
  AgentRepositoryListingItem,
  RepositoryImportRequirementItem,
  RepositoryImportRequirementType,
} from "@/types/agentRepository";

const TYPE_ICON: Record<RepositoryImportRequirementType, typeof Database> = {
  model: Cpu,
  knowledge_base: Database,
  mcp: Plug,
  skill: Sparkles,
  tool: Wrench,
};

interface AgentRepositoryCopyDialogProps {
  listing: AgentRepositoryListingItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: () => void;
}

function groupByType(items: RepositoryImportRequirementItem[]) {
  const order = getRepositoryRequirementTypeOrder();
  return order
    .map((type) => ({
      type,
      items: items.filter((item) => item.type === type),
    }))
    .filter((group) => group.items.length > 0);
}

export function AgentRepositoryCopyDialog({
  listing,
  open,
  onOpenChange,
  onSuccess,
}: AgentRepositoryCopyDialogProps) {
  const { t } = useTranslation("common");
  const { message, modal } = App.useApp();
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const locale = params.locale || "zh";

  const [warningDismissed, setWarningDismissed] = useState(false);
  const [abnormalOpen, setAbnormalOpen] = useState(true);
  const [availableOpen, setAvailableOpen] = useState(true);
  const [mcpUrlOverrides, setMcpUrlOverrides] = useState<
    Record<string, string>
  >({});
  const [installingMcpKeys, setInstallingMcpKeys] = useState<Set<string>>(
    new Set()
  );
  const [installingSkillKeys, setInstallingSkillKeys] = useState<Set<string>>(
    new Set()
  );
  const [modelReplacements, setModelReplacements] = useState<
    Record<string, number>
  >({});

  const agentRepositoryId = listing?.agent_repository_id ?? null;
  const listingTitle =
    listing?.display_name?.trim() ||
    listing?.name?.trim() ||
    t("agentRepository.card.untitled");

  const {
    data: precheck,
    isLoading,
    isError,
    isFetching,
    refetch,
  } = useRepositoryImportPrecheck(agentRepositoryId, open);

  const importMutation = useImportAgentFromRepository();
  const {
    availableLlmModels,
    isLoading: isLoadingModels,
    isFetching: isFetchingModels,
    isError: isModelsError,
  } = useModelList({
    enabled: open,
  });

  useEffect(() => {
    setModelReplacements({});
  }, [agentRepositoryId]);

  const effectiveItems = useMemo(
    () =>
      precheck?.items.map((item) => {
        if (item.type !== "model" || item.available) return item;
        return {
          ...item,
          available:
            !isModelsError &&
            availableLlmModels.some(
              (model) => model.id === modelReplacements[item.key]
            ),
        };
      }) ?? [],
    [precheck, availableLlmModels, modelReplacements, isModelsError]
  );
  const abnormalItems = effectiveItems.filter((item) => !item.available);
  const availableItems = effectiveItems.filter((item) => item.available);
  const hasAbnormal = abnormalItems.length > 0;
  const percent = effectiveItems.length
    ? Math.round((availableItems.length / effectiveItems.length) * 100)
    : 100;
  const hasSelectedReplacement = Object.keys(modelReplacements).length > 0;
  const copyDisabled =
    !precheck ||
    isLoading ||
    isFetching ||
    isError ||
    hasAbnormal ||
    (hasSelectedReplacement &&
      (isLoadingModels || isFetchingModels || isModelsError)) ||
    installingMcpKeys.size > 0 ||
    installingSkillKeys.size > 0 ||
    importMutation.isPending;

  const handleModelReplacementChange = (key: string, modelId: number) => {
    setModelReplacements((current) => ({ ...current, [key]: modelId }));
    setAvailableOpen(true);
  };

  const handleOpenActivate = (type: RepositoryImportRequirementType) => {
    const path = getRepositoryRequirementActivatePath(type);
    if (!path) {
      return;
    }
    router.push(`/${locale}${path}`);
  };

  const handleCopy = async () => {
    if (!agentRepositoryId || copyDisabled) {
      return;
    }
    try {
      await importMutation.mutateAsync({
        agentRepositoryId,
        modelReplacements,
      });
      message.success(
        t("agentRepository.copy.success", { name: listingTitle })
      );
      onOpenChange(false);
      onSuccess?.();
    } catch (error) {
      const err = error as Error & {
        status?: number;
        detail?: { type?: string; duplicate_skills?: string[] } | string;
      };
      const detail =
        typeof err.detail === "object" && err.detail !== null
          ? err.detail
          : null;
      if (
        err.status === 409 &&
        detail?.type === "skill_duplicate" &&
        Array.isArray(detail.duplicate_skills)
      ) {
        message.error(
          t("agentRepository.copy.skillDuplicate", {
            names: detail.duplicate_skills.join(", "),
          })
        );
        return;
      }
      log.error("Failed to import agent from repository:", error);
      message.error(t("agentRepository.copy.failed"));
    }
  };

  const handleInstallMcp = async (item: RepositoryImportRequirementItem) => {
    const originalUrl = item.mcp_url?.trim() || "";
    const url = (mcpUrlOverrides[item.key] ?? originalUrl).trim();
    if (!url || url === "<TO_CONFIG>" || url.startsWith("<TO_CONFIG:")) {
      message.error(
        t("market.install.error.mcpUrlRequired", "MCP URL is required")
      );
      return;
    }

    setInstallingMcpKeys((current) => new Set(current).add(item.key));
    try {
      const result = await addMcpServer(url, item.name);
      if (!result.success) {
        message.error(
          result.message ||
            t("market.install.error.mcpInstall", "Failed to install MCP server")
        );
        return;
      }
      await updateToolList();
      message.success(
        t(
          "market.install.success.mcpInstalled",
          "MCP server installed successfully"
        )
      );
      await refetch();
    } catch (error) {
      log.error("Failed to install repository MCP dependency:", error);
      message.error(
        t("market.install.error.mcpInstall", "Failed to install MCP server")
      );
    } finally {
      setInstallingMcpKeys((current) => {
        const next = new Set(current);
        next.delete(item.key);
        return next;
      });
    }
  };

  const installSkill = async (
    item: RepositoryImportRequirementItem,
    overwrite: boolean
  ) => {
    if (!agentRepositoryId) {
      return;
    }
    setInstallingSkillKeys((current) => new Set(current).add(item.key));
    try {
      await installAgentRepositorySkill(
        agentRepositoryId,
        item.name,
        overwrite
      );
      message.success(
        overwrite
          ? t("agentRepository.copy.skillOverwriteSuccess")
          : t("agentRepository.copy.skillInstallSuccess")
      );
      await refetch();
    } catch (error) {
      log.error("Failed to install repository Skill dependency:", error);
      message.error(t("agentRepository.copy.skillInstallFailed"));
    } finally {
      setInstallingSkillKeys((current) => {
        const next = new Set(current);
        next.delete(item.key);
        return next;
      });
    }
  };

  const handleInstallSkill = (item: RepositoryImportRequirementItem) => {
    if (!item.has_local_skill) {
      void installSkill(item, false);
      return;
    }
    modal.confirm({
      title: t("agentRepository.copy.skillOverwriteTitle"),
      content: t("agentRepository.copy.skillOverwriteWarning", {
        name: item.name,
      }),
      okText: t("agentRepository.copy.skillOverwriteConfirm"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: () => installSkill(item, true),
    });
  };

  const handleClose = () => {
    onOpenChange(false);
    setWarningDismissed(false);
    setAbnormalOpen(true);
    setAvailableOpen(true);
    setMcpUrlOverrides({});
    setInstallingMcpKeys(new Set());
    setInstallingSkillKeys(new Set());
    setModelReplacements({});
  };

  return (
    <Modal
      open={open}
      onCancel={handleClose}
      title={t("agentRepository.copy.title", { name: listingTitle })}
      centered
      width={520}
      destroyOnHidden
      footer={
        <div className="flex justify-end gap-2">
          <Button onClick={handleClose}>{t("common.cancel")}</Button>
          <Button
            type="primary"
            icon={<Copy className="size-4" />}
            loading={importMutation.isPending}
            disabled={copyDisabled}
            onClick={handleCopy}
          >
            {t("agentRepository.card.copy")}
          </Button>
        </div>
      }
      styles={{
        body: { maxHeight: "70vh", overflowY: "auto", paddingTop: 8 },
      }}
    >
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Spin />
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center gap-3 py-10 text-center">
          <p className="text-sm text-slate-500">
            {t("agentRepository.copy.loadError")}
          </p>
          <Button type="primary" onClick={() => refetch()} loading={isFetching}>
            {t("repository.common.retry")}
          </Button>
        </div>
      ) : precheck ? (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                {t("agentRepository.copy.configList")}
              </span>
              <span className="rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                {t("agentRepository.copy.percent", { percent })}
              </span>
            </div>
            <button
              type="button"
              onClick={() => refetch()}
              className="flex items-center gap-1 text-xs text-slate-500 transition-colors hover:text-slate-800 dark:hover:text-slate-200"
            >
              <RefreshCw className="size-3.5" />
              {t("agentRepository.copy.refresh")}
            </button>
          </div>

          {hasAbnormal && !warningDismissed ? (
            <div className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2.5 text-xs text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
              <AlertCircle className="mt-0.5 size-4 shrink-0" />
              <p className="flex-1 leading-relaxed">
                {t("agentRepository.copy.warning")}
              </p>
              <button
                type="button"
                onClick={() => setWarningDismissed(true)}
                aria-label={t("common.close")}
                className="shrink-0 text-amber-500 hover:text-amber-700"
              >
                <X className="size-3.5" />
              </button>
            </div>
          ) : null}

          <div className="space-y-1.5">
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${percent}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-xs text-slate-500">
              <span>
                {t("agentRepository.copy.availableCount", {
                  count: availableItems.length,
                })}
              </span>
              <span>
                {t("agentRepository.copy.pendingCount")}{" "}
                <span
                  className={
                    hasAbnormal ? "font-semibold text-amber-600" : undefined
                  }
                >
                  {abnormalItems.length}
                </span>
              </span>
            </div>
          </div>

          {hasAbnormal ? (
            <section className="space-y-2">
              <button
                type="button"
                onClick={() => setAbnormalOpen((value) => !value)}
                className="flex items-center gap-1 text-sm text-slate-900 dark:text-slate-100"
              >
                {abnormalOpen ? (
                  <ChevronDown className="size-4 text-amber-500" />
                ) : (
                  <ChevronRight className="size-4 text-amber-500" />
                )}
                <span>
                  {t("agentRepository.copy.abnormalSection", {
                    count: abnormalItems.length,
                  })}
                </span>
              </button>
              {abnormalOpen
                ? groupByType(abnormalItems).map((group) => (
                    <RequirementTypeGroup
                      key={`abn-${group.type}`}
                      type={group.type as RepositoryImportRequirementType}
                      items={group.items}
                      status="abnormal"
                      t={t}
                      onActivate={() =>
                        handleOpenActivate(
                          group.type as RepositoryImportRequirementType
                        )
                      }
                      mcpUrlOverrides={mcpUrlOverrides}
                      installingMcpKeys={installingMcpKeys}
                      onMcpUrlChange={(key, value) =>
                        setMcpUrlOverrides((current) => ({
                          ...current,
                          [key]: value,
                        }))
                      }
                      onInstallMcp={handleInstallMcp}
                      installingSkillKeys={installingSkillKeys}
                      onInstallSkill={handleInstallSkill}
                      modelReplacements={modelReplacements}
                      availableLlmModels={availableLlmModels}
                      isLoadingModels={isLoadingModels}
                      onModelReplacementChange={handleModelReplacementChange}
                    />
                  ))
                : null}
            </section>
          ) : null}

          {availableItems.length > 0 ? (
            <section className="space-y-2">
              <button
                type="button"
                onClick={() => setAvailableOpen((value) => !value)}
                className="flex items-center gap-1 text-sm text-slate-900 dark:text-slate-100"
              >
                {availableOpen ? (
                  <ChevronDown className="size-4 text-primary" />
                ) : (
                  <ChevronRight className="size-4 text-primary" />
                )}
                <span>
                  {t("agentRepository.copy.availableSection", {
                    count: availableItems.length,
                  })}
                </span>
              </button>
              {availableOpen
                ? groupByType(availableItems).map((group) => (
                    <RequirementTypeGroup
                      key={`ava-${group.type}`}
                      type={group.type as RepositoryImportRequirementType}
                      items={group.items}
                      status="available"
                      t={t}
                      modelReplacements={modelReplacements}
                      availableLlmModels={availableLlmModels}
                      isLoadingModels={isLoadingModels}
                      onModelReplacementChange={handleModelReplacementChange}
                      installingSkillKeys={installingSkillKeys}
                      onInstallSkill={handleInstallSkill}
                    />
                  ))
                : null}
            </section>
          ) : null}
        </div>
      ) : null}
    </Modal>
  );
}

function RequirementTypeGroup({
  type,
  items,
  status,
  t,
  onActivate,
  mcpUrlOverrides,
  installingMcpKeys,
  onMcpUrlChange,
  onInstallMcp,
  installingSkillKeys,
  onInstallSkill,
  modelReplacements,
  availableLlmModels,
  isLoadingModels,
  onModelReplacementChange,
}: {
  type: RepositoryImportRequirementType;
  items: RepositoryImportRequirementItem[];
  status: "abnormal" | "available";
  t: ReturnType<typeof useTranslation>["t"];
  onActivate?: () => void;
  mcpUrlOverrides?: Record<string, string>;
  installingMcpKeys?: Set<string>;
  onMcpUrlChange?: (key: string, value: string) => void;
  onInstallMcp?: (item: RepositoryImportRequirementItem) => void;
  installingSkillKeys?: Set<string>;
  onInstallSkill?: (item: RepositoryImportRequirementItem) => void;
  modelReplacements?: Record<string, number>;
  availableLlmModels?: Array<{
    id: number;
    displayName: string;
    source: string;
  }>;
  isLoadingModels?: boolean;
  onModelReplacementChange?: (key: string, modelId: number) => void;
}) {
  const Icon = TYPE_ICON[type];
  const abnormal = status === "abnormal";
  const typeLabel = getRepositoryRequirementTypeLabel(type, t);
  const activatePath =
    type === "mcp" ? null : getRepositoryRequirementActivatePath(type);

  return (
    <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-sm font-medium text-slate-900 dark:text-slate-100">
          <Icon className="size-4 text-slate-500" />
          {typeLabel}
        </div>
        {abnormal ? (
          activatePath ? (
            <button
              type="button"
              onClick={onActivate}
              className="flex items-center gap-2 text-xs"
            >
              <span className="flex items-center gap-1 text-amber-600">
                <AlertCircle className="size-3.5" />
                {t("agentRepository.copy.notActivated", { type: typeLabel })}
              </span>
              <span className="flex items-center gap-0.5 text-primary hover:underline">
                {t("agentRepository.copy.activate")}
                <ExternalLink className="size-3" />
              </span>
            </button>
          ) : type === "mcp" ? null : (
            <span className="flex items-center gap-1 text-xs text-amber-600">
              <AlertCircle className="size-3.5" />
              {getRepositoryRequirementReasonLabel(items[0]?.reason_code, t) ||
                t("agentRepository.copy.unavailable")}
            </span>
          )
        ) : (
          <span className="flex items-center gap-1 text-xs text-emerald-600">
            <CheckCircle2 className="size-3.5" />
            {type === "skill" || type === "model"
              ? t("agentRepository.copy.available")
              : t("agentRepository.copy.activated")}
          </span>
        )}
      </div>

      <ul className="space-y-2">
        {items.map((item) => (
          <li
            key={item.key}
            className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-700 dark:bg-slate-800/50"
          >
            <div className="flex items-center gap-2">
              <Icon className="size-4 shrink-0 text-primary" />
              <div className="min-w-0 flex-1">
                {type === "model" && item.source_model_names?.length ? (
                  <div className="flex flex-wrap gap-1.5">
                    {item.source_model_names.map((modelName) => (
                      <span
                        key={modelName}
                        className="rounded bg-slate-200 px-2 py-0.5 text-xs text-slate-700 dark:bg-slate-700 dark:text-slate-200"
                      >
                        {modelName}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="truncate text-sm text-slate-900 dark:text-slate-100">
                    {item.name}
                  </p>
                )}
                {item.description ? (
                  <p className="truncate text-xs text-slate-500 dark:text-slate-400">
                    {item.description}
                  </p>
                ) : null}
                {abnormal && type === "model" && item.reason_code ? (
                  <div className="mt-1 flex items-center gap-1 text-xs text-amber-600">
                    <span>
                      {getRepositoryRequirementReasonLabel(item.reason_code, t)}
                    </span>
                    <Popover
                      trigger="click"
                      placement="top"
                      title={t("agentRepository.copy.originalModelListTitle")}
                      content={
                        <ul className="max-w-72 space-y-1 text-xs text-slate-700 dark:text-slate-200">
                          {(item.source_model_names?.length
                            ? item.source_model_names
                            : [item.name]
                          ).map((modelName) => (
                            <li key={modelName} className="break-all">
                              {modelName}
                            </li>
                          ))}
                        </ul>
                      }
                    >
                      <button
                        type="button"
                        aria-label={t(
                          "agentRepository.copy.showOriginalModelList"
                        )}
                        className="inline-flex shrink-0 cursor-pointer rounded-sm text-amber-600 hover:text-amber-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
                      >
                        <CircleHelp className="size-3.5" />
                      </button>
                    </Popover>
                  </div>
                ) : null}
                {abnormal && type === "skill" && item.reason_code ? (
                  <p className="mt-1 text-xs text-amber-600">
                    {getRepositoryRequirementReasonLabel(item.reason_code, t)}
                  </p>
                ) : null}
                {item.will_auto_deselect ? (
                  <p className="mt-1 text-xs text-amber-600">
                    {t(
                      "agentRepository.copy.knowledgeBaseUnavailable",
                      "This knowledge base is unavailable. Resolve this configuration before copying."
                    )}
                  </p>
                ) : null}
              </div>
            </div>
            {abnormal && type === "mcp" ? (
              <div className="mt-2 flex gap-2 pl-6">
                <Input
                  value={
                    mcpUrlOverrides?.[item.key] ??
                    (item.mcp_url?.startsWith("<TO_CONFIG")
                      ? ""
                      : item.mcp_url || "")
                  }
                  placeholder={t(
                    "market.install.mcp.urlPlaceholder",
                    "Enter MCP server URL"
                  )}
                  onChange={(event) =>
                    onMcpUrlChange?.(item.key, event.target.value)
                  }
                />
                <Button
                  type="primary"
                  loading={installingMcpKeys?.has(item.key)}
                  onClick={() => onInstallMcp?.(item)}
                >
                  {t("market.install.mcp.install", "Install")}
                </Button>
              </div>
            ) : null}
            {type === "model" &&
            (abnormal ||
              item.requires_replacement ||
              modelReplacements?.[item.key] != null) ? (
              <div className="mt-2 pl-6">
                <Select
                  className="w-full"
                  loading={isLoadingModels}
                  value={modelReplacements?.[item.key]}
                  placeholder={t("agentRepository.copy.selectReplacementModel")}
                  options={(availableLlmModels || []).map((model) => ({
                    value: model.id,
                    label: `${model.displayName} (${model.source})`,
                  }))}
                  onChange={(modelId) => {
                    if (modelId != null) {
                      onModelReplacementChange?.(item.key, modelId);
                    }
                  }}
                />
              </div>
            ) : null}
            {type === "skill" &&
            !item.available &&
            !item.is_official_skill &&
            item.has_install_package ? (
              <div className="mt-2 flex justify-end pl-6">
                <Button
                  type="primary"
                  loading={installingSkillKeys?.has(item.key)}
                  onClick={() => onInstallSkill?.(item)}
                >
                  {t("agentRepository.copy.installSkill")}
                </Button>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
