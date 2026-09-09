"use client";

import { useMemo, useState } from "react";
import { App, Button, Modal, Radio, Space, Spin, Tag } from "antd";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
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
import type {
  AgentRepositoryListingItem,
  RepositoryImportRequirementItem,
  RepositoryImportRequirementType,
} from "@/types/agentRepository";

const TYPE_ICON: Record<
  RepositoryImportRequirementType,
  typeof Database
> = {
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
  const { message } = App.useApp();
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const locale = params.locale || "zh";

  const [warningDismissed, setWarningDismissed] = useState(false);
  const [abnormalOpen, setAbnormalOpen] = useState(true);
  const [availableOpen, setAvailableOpen] = useState(true);
  const [skillResolutionActions, setSkillResolutionActions] = useState<Record<string, "rename" | "use_existing">>({});

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

  const abnormalItems = useMemo(
    () => precheck?.items.filter((item) => !item.available) ?? [],
    [precheck]
  );
  const availableItems = useMemo(
    () => precheck?.items.filter((item) => item.available) ?? [],
    [precheck]
  );

  const skillConflictItems = useMemo(
    () => abnormalItems.filter((item) => item.type === "skill" && item.reason_code === "skill_duplicate"),
    [abnormalItems]
  );
  const hasSkillConflicts = skillConflictItems.length > 0;

  const percent = precheck?.percent ?? 0;
  const hasAbnormal = precheck?.has_abnormal ?? false;

  const handleOpenActivate = (type: RepositoryImportRequirementType) => {
    const path = getRepositoryRequirementActivatePath(type);
    if (!path) {
      return;
    }
    router.push(`/${locale}${path}`);
  };

  const handleCopy = async () => {
    if (!agentRepositoryId) {
      return;
    }

    const skillResolutions = hasSkillConflicts
      ? skillConflictItems.map((item) => ({
          skill_name: item.name,
          action: (skillResolutionActions[item.name] ?? "rename") as "rename" | "use_existing",
          ...(skillResolutionActions[item.name] !== "use_existing"
            ? { new_name: item.suggested_new_name || `${item.name} 副本` }
            : {}),
        }))
      : undefined;

    try {
      await importMutation.mutateAsync({
        agentRepositoryId,
        skillResolutions,
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

  const handleClose = () => {
    onOpenChange(false);
    setWarningDismissed(false);
    setAbnormalOpen(true);
    setAvailableOpen(true);
    setSkillResolutionActions({});
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
            disabled={!precheck || isLoading || isError}
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

          {hasSkillConflicts ? (
            <section className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-700 dark:bg-amber-500/10">
              <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
                {t("agentRepository.copy.skillDuplicate.title", "Skill Name Conflict Detected")}
              </p>
              <p className="text-xs text-amber-700 dark:text-amber-300">
                {t("agentRepository.copy.skillDuplicate.message", "Choose how to handle each conflicting skill:")}
              </p>
              <div className="space-y-3">
                {skillConflictItems.map((item) => (
                  <div
                    key={item.key}
                    className="rounded-lg border border-amber-200 bg-white p-3 dark:border-amber-700 dark:bg-slate-800"
                  >
                    <div className="mb-2">
                      <Tag color="orange">{item.name}</Tag>
                    </div>
                    <Radio.Group
                      value={skillResolutionActions[item.name] ?? "rename"}
                      onChange={(event) => {
                        setSkillResolutionActions((prev) => ({
                          ...prev,
                          [item.name]: event.target.value,
                        }));
                      }}
                    >
                      <Space direction="vertical" size={8}>
                        <Radio value="rename">
                          {t("agentRepository.copy.skillDuplicate.rename", "Install as new skill")}
                          <span className="ml-2 text-xs text-slate-600 dark:text-slate-400">
                            {t("agentRepository.copy.skillDuplicate.renameTarget", {
                              name: item.suggested_new_name || `${item.name} 副本`,
                              defaultValue: `New name: ${item.suggested_new_name || `${item.name} 副本`}`,
                            })}
                          </span>
                        </Radio>
                        <Radio value="use_existing">
                          {t("agentRepository.copy.skillDuplicate.useExisting", "Use existing local skill")}
                        </Radio>
                      </Space>
                    </Radio.Group>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

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
}: {
  type: RepositoryImportRequirementType;
  items: RepositoryImportRequirementItem[];
  status: "abnormal" | "available";
  t: ReturnType<typeof useTranslation>["t"];
  onActivate?: () => void;
}) {
  const Icon = TYPE_ICON[type];
  const abnormal = status === "abnormal";
  const typeLabel = getRepositoryRequirementTypeLabel(type, t);
  const activatePath = getRepositoryRequirementActivatePath(type);

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
          ) : (
            <span className="flex items-center gap-1 text-xs text-amber-600">
              <AlertCircle className="size-3.5" />
              {getRepositoryRequirementReasonLabel(items[0]?.reason_code, t) ||
                t("agentRepository.copy.unavailable")}
            </span>
          )
        ) : (
          <span className="flex items-center gap-1 text-xs text-emerald-600">
            <CheckCircle2 className="size-3.5" />
            {t("agentRepository.copy.activated")}
          </span>
        )}
      </div>

      <ul className="space-y-2">
        {items.map((item) => (
          <li
            key={item.key}
            className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-700 dark:bg-slate-800/50"
          >
            <Icon className="size-4 shrink-0 text-primary" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-slate-900 dark:text-slate-100">
                {item.name}
              </p>
              {item.description ? (
                <p className="truncate text-xs text-slate-500 dark:text-slate-400">
                  {item.description}
                </p>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
