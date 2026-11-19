// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Button, Spin } from "antd";
import Image from "next/image";
import {
  BookOpen,
  Bot,
  Calendar,
  ChevronDown,
  ChevronUp,
  Cpu,
  Download,
  Pencil,
  Sparkles,
  Tag as TagIcon,
  UserRound,
  Wrench,
} from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { useUserDisplayName } from "@/hooks/auth/useUserDisplayName";
import { useTranslation } from "react-i18next";
import ResourceDetail from "@/components/resource/ResourceDetail";
import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";
import type { MyAgentDetailView } from "@/lib/myAgentDetail";
import { MODEL_PROVIDER_LOGOS } from "@/const/modelConfig";
import { formatModelTokenLabel } from "@/lib/modelTokenLabel";
import { formatDateTimeLocale } from "@/lib/date";
import type { AgentRepositoryListingStatus } from "@/types/agentRepository";

interface AgentDetailProps {
  open: boolean;
  onClose: () => void;
  onEdit?: () => void;
  detail: MyAgentDetailView | null | undefined;
  agentIcon?: ReactNode;
  footerActions?: ReactNode;
  published: boolean;
  status?: AgentRepositoryListingStatus;
  showRepositoryInfo?: boolean;
  isLoading?: boolean;
  isError?: boolean;
  isFetching?: boolean;
  onRetry?: () => void;
}

function formatCreatedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

function DetailSection({
  icon,
  title,
  items,
  tone = "neutral",
}: {
  icon: ReactNode;
  title: string;
  items: string[];
  tone?: "neutral" | "blue";
}) {
  if (items.length === 0) return null;

  return (
    <section className="space-y-2">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800 dark:text-slate-100">
        <span className="text-slate-500 dark:text-slate-400">{icon}</span>
        {title}
        <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium leading-none text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          {items.length}
        </span>
      </h3>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span
            key={item}
            className={
              tone === "blue"
                ? "rounded-md bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 dark:bg-blue-500/10 dark:text-blue-300"
                : "max-w-full break-all rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
            }
          >
            {item}
          </span>
        ))}
      </div>
    </section>
  );
}

function RepositoryAgentDetailContent({
  detail,
  agentIcon,
  author,
}: {
  detail: MyAgentDetailView;
  agentIcon: ReactNode;
  author: string;
}) {
  const { t, i18n } = useTranslation("common");
  const [expandedSections, setExpandedSections] = useState<
    Record<string, boolean>
  >({});
  const sectionId = useId();
  const repository = detail.repositoryInfo;
  const models = repository?.modelNames?.length
    ? repository.modelNames
    : detail.modelName
      ? [detail.modelName]
      : [];
  const sections = [
    {
      sectionKey: "knowledge",
      title: t("agentRepository.copy.type.knowledgeBase"),
      items: detail.knowledgeBases,
      Icon: BookOpen,
      iconColor: "bg-[#EEE7FF] text-[#765CEB]",
      knowledge: repository?.knowledgeDetails,
    },
    {
      sectionKey: "skills",
      title: t("agentRepository.mine.detail.skills"),
      items: detail.skills,
      Icon: Sparkles,
      iconColor: "bg-[#E6F2FF] text-[#4285D7]",
      tags: repository?.skillTags,
    },
    {
      sectionKey: "tools",
      title: t("agentRepository.mine.detail.tools"),
      items: detail.tools,
      Icon: Wrench,
      iconColor: "bg-[#E6F2FF] text-[#4285D7]",
      tags: repository?.toolTags,
    },
    {
      sectionKey: "sub-agents",
      title: t("resourceCenter.subAgents"),
      items: detail.subAgents,
      Icon: Bot,
      iconColor: "bg-[#E7F0FF] text-[#5878E8]",
      tags: repository?.subAgentTags,
    },
  ];

  const renderResourceList = ({
    sectionKey,
    title,
    items,
    Icon,
    iconColor,
    knowledge,
    tags,
    isModel = false,
  }: {
    sectionKey: string;
    title: string;
    items: string[];
    Icon: typeof Cpu;
    iconColor?: string;
    knowledge?: NonNullable<
      MyAgentDetailView["repositoryInfo"]
    >["knowledgeDetails"];
    tags?: Map<string, string[]>;
    isModel?: boolean;
  }) => {
    const id = `${sectionId}-${sectionKey}`;
    const expanded = Boolean(expandedSections[id]);
    const canExpand = items.length > 4;
    const visibleItems = canExpand && !expanded ? items.slice(0, 4) : items;
    return (
      <div key={sectionKey} className="space-y-2">
        {!isModel ? (
          <h4 className="flex items-center gap-2 text-xs font-normal text-muted-foreground">
            {title}
            <span>{items.length}</span>
          </h4>
        ) : null}
        {items.length > 0 ? (
          <ul id={id} className="space-y-2">
            {visibleItems.map((item) => {
              const model = isModel
                ? repository?.models?.find(
                    (candidate) =>
                      (candidate.displayName || candidate.name).trim() === item
                  )
                : undefined;
              const provider = String(
                model?.modelFactory || model?.source || ""
              ).toLowerCase();
              const logo =
                MODEL_PROVIDER_LOGOS[provider] ??
                (isModel && /^deepseek(?:[- /]|$)/i.test(item)
                  ? MODEL_PROVIDER_LOGOS.deepseek
                  : undefined);
              const badges = model
                ? [
                    formatModelTokenLabel(
                      model.contextWindowTokens ?? model.maxInputTokens
                    ),
                    model.type === "llm" &&
                      t("agent.highFidelity.modelCapability.text"),
                    model.reasoningCapability?.status === "supported" &&
                      t("agent.highFidelity.modelCapability.reasoning"),
                    model.supportToolCalls === true &&
                      t("agent.highFidelity.modelCapability.tools"),
                  ].filter((label): label is string => Boolean(label))
                : (tags?.get(item) ?? []);
              const base = knowledge?.get(item);
              return (
                <li
                  key={item}
                  className="flex min-h-9 items-center gap-3 rounded-md border border-border bg-background px-3 py-2 leading-[18px]"
                >
                  {logo ? (
                    <Image
                      src={logo}
                      alt=""
                      width={16}
                      height={16}
                      className="size-4 shrink-0 object-contain"
                    />
                  ) : (
                    <Icon
                      size={16}
                      className={`shrink-0 rounded ${iconColor ?? "text-[#777777]"}`}
                      aria-hidden
                    />
                  )}
                  <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="min-w-0 break-words">{item}</span>
                    {base ? (
                      <span className="flex flex-wrap items-center gap-2 text-xs leading-5 text-[#777777]">
                        {typeof base.updatedAt === "string" &&
                        base.updatedAt ? (
                          <span className="border-r border-[#DFDFDF] pr-2">
                            {t("knowledgeBase.tag.updatedAt", {
                              date: formatCreatedAt(base.updatedAt),
                            })}
                          </span>
                        ) : null}
                        {Number.isFinite(base.documentCount) ? (
                          <span>
                            {t("resourcePicker.knowledge.documents", {
                              count: base.documentCount,
                            })}
                          </span>
                        ) : null}
                        {Number.isFinite(base.chunkCount) ? (
                          <span>
                            {t("resourcePicker.knowledge.chunks", {
                              count: base.chunkCount,
                            })}
                          </span>
                        ) : null}
                      </span>
                    ) : null}
                    {badges.length > 0 ? (
                      <span
                        className={`flex flex-wrap gap-1 ${isModel ? "ml-auto" : ""}`}
                      >
                        {badges.map((badge) => (
                          <span
                            key={badge}
                            className="rounded bg-primary/5 px-2 text-xs leading-5 text-muted-foreground"
                          >
                            {badge}
                          </span>
                        ))}
                      </span>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        ) : null}
        {canExpand ? (
          <Button
            type="link"
            className="!inline-flex !h-[22px] !items-center !gap-1 !p-0 !text-[#0067D1]"
            aria-expanded={expanded}
            aria-controls={id}
            onClick={() =>
              setExpandedSections((current) => ({
                ...current,
                [id]: !expanded,
              }))
            }
          >
            {expanded ? (
              <ChevronUp size={14} aria-hidden />
            ) : (
              <ChevronDown size={14} aria-hidden />
            )}
            {t(
              expanded
                ? "mcpConfig.toolsList.button.collapse"
                : "resourceCenter.expandMore"
            )}
          </Button>
        ) : null}
      </div>
    );
  };
  const notRecorded = t("resourceCenter.notRecorded");
  const publishedAt = formatDateTimeLocale(
    repository?.publishedAt,
    i18n?.language
  );
  const updatedAt = repository?.updatedAt
    ? formatDateTimeLocale(repository.updatedAt, i18n?.language)
    : null;
  const metadata = [
    {
      label: t("agentRepository.mine.detail.author"),
      value: author || notRecorded,
    },
    {
      label: t("resourceCenter.publishedVersion"),
      value: detail.versionLabel || notRecorded,
    },
    {
      label: t("resourceCenter.publishedAt"),
      value:
        repository?.publishedAt && publishedAt !== "-" ? (
          <time dateTime={repository.publishedAt}>{publishedAt}</time>
        ) : (
          notRecorded
        ),
    },
    ...(repository?.updatedAt && updatedAt && updatedAt !== "-"
      ? [
          {
            label: t("agentConfig.list.column.updatedAt"),
            value: <time dateTime={repository.updatedAt}>{updatedAt}</time>,
          },
        ]
      : []),
    ...(repository
      ? [
          {
            label: t("resourceCenter.agentDetail.copied"),
            value: t("resourceCenter.agentDetail.copyCount", {
              count: repository.downloads,
            }),
          },
        ]
      : []),
  ];
  const relatedResources = sections.filter(({ items }) => items.length > 0);

  return (
    <div className="-mx-6 flex min-h-0 flex-1 flex-col text-sm leading-[22px] text-foreground">
      <header className="flex shrink-0 items-center gap-3 border-b border-border px-6 pb-4 pr-14">
        <div className="shrink-0">{agentIcon}</div>
        <div className="min-w-0 flex-1">
          <h2 className="break-words text-xl font-medium leading-7">
            {detail.title || t("agentRepository.card.untitled")}
          </h2>
          {repository?.isMainAgent !== undefined ? (
            <span className="mt-1 inline-block rounded bg-primary/10 px-1.5 text-xs text-primary">
              {t(
                repository.isMainAgent
                  ? "agentRepository.card.mainAgent"
                  : "space.detail.tabs.subAgents"
              )}
            </span>
          ) : null}
        </div>
      </header>
      <div className="repository-detail-body min-h-0 flex-1 overflow-y-auto">
        <section className="space-y-3 border-b border-border px-6 py-5">
          <h3 className="font-semibold">
            {t("resourceCenter.agentDetail.basicInfo")}
          </h3>
          <p
            className={`whitespace-pre-wrap break-words ${detail.description ? "" : "text-muted-foreground"}`}
          >
            {detail.description || t("agentRepository.card.noDescription")}
          </p>
          {detail.tags.length > 0 ? (
            <ul
              aria-label={t("agentRepository.mine.detail.tags")}
              className="flex flex-wrap gap-1.5"
            >
              {detail.tags.map((tag) => (
                <li
                  key={tag}
                  className="max-w-full break-words rounded bg-primary/5 px-2 text-xs leading-5 text-muted-foreground"
                >
                  {tag}
                </li>
              ))}
            </ul>
          ) : null}
          <dl className="grid grid-cols-[minmax(5rem,max-content)_minmax(0,1fr)] gap-x-3 gap-y-1">
            {metadata.map(({ label, value }) => (
              <div key={label} className="contents">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="min-w-0 [overflow-wrap:anywhere]">{value}</dd>
              </div>
            ))}
          </dl>
        </section>
        <section className="space-y-3 border-b border-border px-6 py-5">
          <h3 className="font-semibold">
            {t("resourceCenter.agentDetail.model")}
          </h3>
          {models.length ? (
            renderResourceList({
              sectionKey: "models",
              title: t("resourceCenter.agentDetail.model"),
              items: models,
              Icon: Cpu,
              iconColor: "text-primary",
              isModel: true,
            })
          ) : (
            <p className="text-muted-foreground">{notRecorded}</p>
          )}
        </section>
        <section className="space-y-3 px-6 py-5">
          <h3 className="font-semibold">
            {t("resourceCenter.agentDetail.relatedResources")}
          </h3>
          {relatedResources.length ? (
            relatedResources.map(renderResourceList)
          ) : (
            <p className="text-muted-foreground">
              {t("resourceCenter.agentDetail.noRelatedResources")}
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

export function AgentDetail({
  open,
  onClose,
  onEdit,
  detail,
  agentIcon,
  footerActions,
  published,
  status,
  showRepositoryInfo = false,
  isLoading = false,
  isError = false,
  isFetching = false,
  onRetry,
}: AgentDetailProps) {
  const { t } = useTranslation("common");
  const presentation = useRepositoryPresentation();
  const displayName = useUserDisplayName();

  return (
    <ResourceDetail
      open={open}
      onClose={onClose}
      width={560}
      className="agent-detail-modal [&_.ant-modal-close]:!z-20 [&_.ant-modal-content]:!overflow-hidden [&_.ant-modal-content]:!rounded-2xl [&_.ant-modal-content]:!p-0"
      bodyStyle={{ padding: 0 }}
    >
      <div
        className={
          presentation
            ? "flex min-h-0 flex-1 flex-col"
            : "flex max-h-[min(740px,calc(100dvh-3rem))] flex-col overflow-hidden"
        }
      >
        <div
          className={
            detail &&
            presentation &&
            showRepositoryInfo &&
            !isLoading &&
            !isError
              ? "flex min-h-0 flex-1 flex-col"
              : presentation
                ? "min-h-0 flex-1 overflow-y-auto pb-4"
                : "min-h-0 flex-1 overflow-y-auto px-3 pb-4 pt-4 sm:px-4"
          }
        >
          {isLoading ? (
            <div className="flex min-h-64 items-center justify-center">
              <Spin size="large" />
            </div>
          ) : isError ? (
            <div className="flex min-h-64 flex-col items-center justify-center gap-3 text-center">
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {t("agentRepository.detail.loadError")}
              </p>
              {onRetry ? (
                <Button type="primary" onClick={onRetry} loading={isFetching}>
                  {t("repository.common.retry")}
                </Button>
              ) : null}
            </div>
          ) : detail && presentation && showRepositoryInfo ? (
            <RepositoryAgentDetailContent
              detail={detail}
              agentIcon={agentIcon}
              author={displayName(
                detail.authorCasUsername,
                detail.author ?? ""
              )}
            />
          ) : detail ? (
            <>
              <div className="flex items-start gap-3 pr-6">
                {agentIcon}
                <div className="min-w-0 flex-1">
                  <h2 className="break-words text-lg font-semibold leading-7 text-slate-900 dark:text-slate-100">
                    {detail.title || t("agentRepository.card.untitled")}
                  </h2>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <span
                      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${
                        published
                          ? "border-emerald-100 bg-emerald-50 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300"
                          : "border-amber-100 bg-amber-50 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300"
                      }`}
                    >
                      <span
                        className="size-1.5 rounded-full bg-current"
                        aria-hidden
                      />
                      {t(
                        published
                          ? "agentRepository.mine.lifecycle.published"
                          : "agentRepository.mine.lifecycle.draft"
                      )}
                      {published && detail.versionLabel
                        ? ` · ${detail.versionLabel}`
                        : null}
                    </span>
                    {status && status !== "not_shared" ? (
                      <span
                        className={`rounded-full border px-2 py-0.5 text-xs font-medium ${
                          status === "rejected"
                            ? "border-rose-100 bg-rose-50 text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300"
                            : status === "pending_review"
                              ? "border-amber-100 bg-amber-50 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300"
                              : "border-blue-100 bg-blue-50 text-blue-700 dark:border-blue-500/20 dark:bg-blue-500/10 dark:text-blue-300"
                        }`}
                      >
                        {status === "shared"
                          ? t("agentRepository.mine.listed")
                          : t(`agentRepository.detail.status.${status}`)}
                      </span>
                    ) : null}
                  </div>
                </div>
              </div>

              <p className="mt-5 whitespace-pre-wrap text-sm leading-6 text-slate-600 dark:text-slate-300">
                {detail.description || t("agentRepository.card.noDescription")}
              </p>

              {showRepositoryInfo && detail.repositoryInfo ? (
                <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
                  <span className="inline-flex items-center gap-1">
                    <Download className="size-3.5" aria-hidden />
                    {t("agentRepository.detail.downloads", {
                      count: detail.repositoryInfo.downloads.toLocaleString(),
                    })}
                  </span>
                  {detail.repositoryInfo.createdAt ? (
                    <span className="inline-flex items-center gap-1">
                      <Calendar className="size-3.5" aria-hidden />
                      {formatCreatedAt(detail.repositoryInfo.createdAt)}
                    </span>
                  ) : null}
                </div>
              ) : null}

              {detail.author || detail.modelName ? (
                <div className="mt-4 space-y-2 rounded-xl bg-slate-50 px-3 py-3 text-sm dark:bg-slate-800/60">
                  {detail.author ? (
                    <div className="flex min-w-0 items-center gap-2 text-slate-500 dark:text-slate-400">
                      <UserRound className="size-4 shrink-0" aria-hidden />
                      <span className="shrink-0 whitespace-nowrap">
                        {t("agentRepository.mine.detail.author")}
                      </span>
                      <span
                        className="ml-auto min-w-0 flex-1 truncate text-right font-medium text-slate-900 dark:text-slate-100"
                        title={displayName(
                          detail.authorCasUsername,
                          detail.author
                        )}
                      >
                        {displayName(detail.authorCasUsername, detail.author)}
                      </span>
                    </div>
                  ) : null}
                  {detail.modelName ? (
                    <div className="flex min-w-0 items-center gap-2 text-slate-500 dark:text-slate-400">
                      <Cpu className="size-4 shrink-0" aria-hidden />
                      <span className="shrink-0 whitespace-nowrap">
                        {t("agentRepository.mine.detail.model")}
                      </span>
                      <span
                        className="ml-auto min-w-0 flex-1 truncate text-right font-medium text-slate-900 dark:text-slate-100"
                        title={detail.modelName}
                      >
                        {detail.modelName}
                      </span>
                    </div>
                  ) : null}
                </div>
              ) : null}

              <div className="mt-5 space-y-5">
                <DetailSection
                  icon={<Wrench className="size-4" aria-hidden />}
                  title={t("agentRepository.mine.detail.tools")}
                  items={detail.tools}
                />
                <DetailSection
                  icon={<Sparkles className="size-4" aria-hidden />}
                  title={t("agentRepository.mine.detail.skills")}
                  items={detail.skills}
                />
                <DetailSection
                  icon={<BookOpen className="size-4" aria-hidden />}
                  title={t("agentRepository.mine.detail.knowledgeBases")}
                  items={detail.knowledgeBases}
                />
                <DetailSection
                  icon={<Bot className="size-4" aria-hidden />}
                  title={t("agentRepository.mine.detail.subAgents")}
                  items={detail.subAgents}
                />
                <DetailSection
                  icon={<TagIcon className="size-4" aria-hidden />}
                  title={t("agentRepository.mine.detail.tags")}
                  items={detail.tags}
                  tone="blue"
                />
              </div>
            </>
          ) : null}
        </div>
        <footer
          className={
            presentation && showRepositoryInfo
              ? "-mx-6 flex shrink-0 items-center justify-between gap-4 border-t border-border bg-background px-6 py-3"
              : "flex shrink-0 items-center justify-end gap-2 border-t border-slate-200 bg-slate-50/60 px-3 py-3 dark:border-slate-700 dark:bg-slate-900/60 sm:px-4"
          }
        >
          {presentation && showRepositoryInfo ? null : (
            <Button onClick={onClose}>{t("common.close")}</Button>
          )}
          {footerActions}
          {onEdit && detail && !isError ? (
            <Button
              type="primary"
              icon={<Pencil className="size-4" />}
              onClick={onEdit}
            >
              {t("agentRepository.mine.edit")}
            </Button>
          ) : null}
        </footer>
      </div>
    </ResourceDetail>
  );
}
