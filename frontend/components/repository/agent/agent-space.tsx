// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { hasRole } from "@/lib/roles";

import RepositoryDisplayControls, {
  AgentRepositorySort,
} from "@/components/repository/RepositoryDisplayControls";
import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";
import { useRepositoryTagPredicates } from "@/hooks/useRepositoryTagPredicates";

import {
  useRepositoryPageSize,
  useRepositoryQueryState,
} from "@/hooks/useRepositoryQueryState";
import ResourcePublishedAt from "@/components/repository/ResourcePublishedAt";
import { useMemo, useRef, useState } from "react";
import type { MenuProps } from "antd";
import {
  App,
  Button,
  Dropdown,
  Empty,
  Input,
  Modal,
  Select,
  Space,
  Spin,
} from "antd";
import {
  Bot,
  ChevronDown,
  Copy,
  Download,
  MoreHorizontal,
  PackageX,
  Search,
  ShieldCheck,
} from "lucide-react";
import { useUserDisplayName } from "@/hooks/auth/useUserDisplayName";
import { useTranslation } from "react-i18next";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";

import { useTagLibraries, useTagDefinitions } from "@/hooks/useTagManagement";
import { getTagSearchPredicates } from "@/lib/systemTagLabels";

import ResourceCardGrid from "@/components/resource/ResourceCardGrid";
import { AgentCardTags } from "./components/AgentCardTags";
import ResourceCard from "@/components/resource/ResourceCard";
import { AgentDetail } from "@/components/agent/agent-detail";
import TagFilterPopover from "@/components/tag/TagFilterPopover";
import { getAgentRepositoryTagLabel } from "@/lib/agentRepositoryLabels";
import type { TagResourcePredicate } from "@/types/tagManagement";
import type { AgentRepositoryListingItem } from "@/types/agentRepository";
import { AgentRepositoryCopyDialog } from "./components/AgentRepositoryCopyDialog";
import { RepositoryAgentIcon } from "./components/RepositoryAgentIcon";
import {
  useAgentRepositoryListings,
  useUpdateAgentRepositoryStatus,
} from "@/hooks/agentRepository/useAgentRepositoryListings";
import { useRepositoryAgentDetail } from "@/hooks/agentRepository/useRepositoryAgentDetail";

type RepositorySortOrder = "default" | "latest";

export function AgentSpace({
  active,
  enhanced = false,
  sortByPublished = false,
}: {
  active: boolean;
  enhanced?: boolean;
  sortByPublished?: boolean;
}) {
  const { t } = useTranslation("common");
  const presentation = useRepositoryPresentation();
  const sortByDownloads = presentation?.query?.get("sort") === "downloads";
  const displayName = useUserDisplayName();
  const { message } = App.useApp();
  const { user } = useAuthorizationContext();
  const showAdminMenu = hasRole(user, "ADMIN");
  const [searchQuery, setSearchQuery] = useRepositoryQueryState("search", "");
  const composingSearch = useRef(false);
  const [searchDraft, setSearchDraft] = useState<string | null>(null);
  const [tagPredicates, setTagPredicates] = useRepositoryTagPredicates();
  const [sortOrder, setSortOrder] = useState<RepositorySortOrder>("default");
  const [page, setPage] = useRepositoryQueryState("page", 1);
  const [pageSize, setPageSize] = useRepositoryPageSize();
  const { data: tagLibraries } = useTagLibraries();
  const defaultTagLibrary =
    tagLibraries?.find(
      (library) => library.bucket_key === "default_resource"
    ) ?? null;
  const { data: tagDefinitions } = useTagDefinitions(
    defaultTagLibrary?.bucket_id ?? null
  );
  const searchTagPredicates = useMemo(
    () => getTagSearchPredicates(tagDefinitions, searchQuery, t),
    [tagDefinitions, searchQuery, t]
  );
  const listingParams = useMemo(
    () => ({
      status: "shared" as const,
      page,
      page_size: pageSize,
      ...(searchQuery.trim() ? { search: searchQuery.trim() } : {}),
      ...(searchTagPredicates.length > 0
        ? { search_tag_predicates: searchTagPredicates }
        : {}),
      ...(tagPredicates.length > 0 ? { tag_predicates: tagPredicates } : {}),
      ...(sortByDownloads ? { sort_by_downloads: true } : {}),
      ...(sortOrder === "latest" || sortByPublished
        ? enhanced
          ? { sort_by_published_time: true }
          : { sort_by_update_time: true }
        : {}),
    }),
    [
      enhanced,
      page,
      pageSize,
      searchQuery,
      searchTagPredicates,
      tagPredicates,
      sortOrder,
      sortByPublished,
      sortByDownloads,
    ]
  );
  const { data, isLoading, isError, isFetching, isPlaceholderData, refetch } =
    useAgentRepositoryListings(listingParams, active, Boolean(presentation));
  const updateStatusMutation = useUpdateAgentRepositoryStatus();
  const listings = data?.items ?? [];
  const total = data?.pagination?.total ?? 0;
  const updatingRepositoryId = updateStatusMutation.isPending
    ? (updateStatusMutation.variables?.agentRepositoryId ?? null)
    : null;
  const onSearchChange = (value: string) => {
    if (value === searchQuery) return;
    setSearchQuery(value);
    if (!presentation?.updateQuery) setPage(1);
  };
  const onTagPredicatesChange = (value: TagResourcePredicate[]) => {
    setTagPredicates(value);
    setPage(1);
  };
  const onSortOrderChange = (value: RepositorySortOrder) => {
    setSortOrder(value);
    setPage(1);
  };
  const onTakeDown = (listing: AgentRepositoryListingItem) =>
    updateStatusMutation.mutateAsync({
      agentRepositoryId: listing.agent_repository_id,
      status: "not_shared",
    });
  const [copyListing, setCopyListing] =
    useState<AgentRepositoryListingItem | null>(null);
  const [detailListing, setDetailListing] =
    useState<AgentRepositoryListingItem | null>(null);
  const {
    detail,
    repositoryDetail,
    isLoading: isDetailLoading,
    isError: isDetailError,
    isFetching: isDetailFetching,
    retry: refetchDetail,
  } = useRepositoryAgentDetail(detailListing, active);
  const confirmTakeDown = (listing: AgentRepositoryListingItem) => {
    const title =
      listing.display_name?.trim() ||
      listing.name?.trim() ||
      t("agentRepository.card.untitled");

    Modal.confirm({
      title: t("repository.listingStatus.confirmTakeDownTitle"),
      content: t("repository.listingStatus.confirmTakeDownContent", {
        name: title,
      }),
      okText: t("repository.listingStatus.takeDown"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await onTakeDown(listing);
          message.success(t("repository.mine.takeDownSuccess"));
        } catch {
          message.error(t("repository.mine.takeDownError"));
          throw new Error("Take down failed");
        }
      },
    });
  };

  const renderListing = (listing: AgentRepositoryListingItem) => {
    const title =
      listing.display_name?.trim() ||
      listing.name?.trim() ||
      t("agentRepository.card.untitled");
    const author = displayName(
      listing.author_cas_username,
      listing.author?.trim() || ""
    );
    const tags = listing.tags?.filter((tag) => tag.trim()) ?? [];
    const toolCount = listing.tool_count ?? 0;
    const downloads = listing.downloads ?? 0;
    const isTakingDown = updatingRepositoryId === listing.agent_repository_id;
    const isOfficialListing = listing.is_official === true;
    const isMainAgent = listing.is_main_agent !== false;
    const showBadge =
      isOfficialListing || Boolean(listing.version_label) || isMainAgent;
    // Official templates are managed from the super-admin resource page.
    // The ordinary repository status menu must not expose take-down actions
    // for official listings to tenant administrators.
    const canManageListing = showAdminMenu && !listing.is_official;
    const showSplitAction =
      canManageListing && presentation?.layout === "cards";
    const templateButtonClassName =
      "!box-border !h-[32px] !min-w-[88px] !max-w-[200px] !rounded !border-[#c9c9c9] !bg-white !px-[16px] !py-[5px] !font-['HarmonyOS_Sans_SC',sans-serif] !text-[14px] !font-normal !leading-[20px] !tracking-normal !text-[#191919]";
    const menuItems: MenuProps["items"] = canManageListing
      ? [
          {
            key: "takeDown",
            label: t("repository.listingStatus.takeDown"),
            icon: <PackageX className="size-3.5" aria-hidden />,
            danger: true,
            disabled: isTakingDown,
            onClick: () => confirmTakeDown(listing),
          },
        ]
      : [];

    return (
      <ResourceCard
        actionsOnly={presentation?.layout === "list"}
        key={listing.agent_repository_id}
        className={presentation ? undefined : "h-full"}
        title={title}
        subtitle={presentation ? author : undefined}
        onClick={() => setDetailListing(listing)}
        icon={
          <div
            className={
              presentation
                ? "flex size-[56px] shrink-0 items-center justify-center rounded bg-[#f6f5f5]"
                : "flex size-11 items-center justify-center rounded-xl bg-primary/10 text-xl text-primary"
            }
          >
            <RepositoryAgentIcon
              agentId={listing.agent_id}
              iconUrl={listing.icon_url}
              size={presentation ? 56 : 44}
              iconSize={20}
              className={
                presentation
                  ? "!shrink-0 !rounded !bg-[#f6f5f5] !text-primary"
                  : undefined
              }
            />
          </div>
        }
        statusRow={
          presentation ? (
            <ResourcePublishedAt
              value={listing.published_at}
              className="block truncate font-['HarmonyOS_Sans_SC',sans-serif] text-xs font-normal leading-5 tracking-normal text-[#191919]/70"
            />
          ) : undefined
        }
        descriptionLabel={
          presentation ? t("resourceCenter.details") : undefined
        }
        description={
          listing.description?.trim() || t("agentRepository.card.noDescription")
        }
        descriptionLines={presentation ? 1 : undefined}
        badge={
          showBadge && !presentation ? (
            <>
              {isOfficialListing ? (
                <span className="inline-flex items-center gap-1 rounded-md bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium text-blue-700 dark:bg-blue-950/40 dark:text-blue-300">
                  <ShieldCheck className="size-3" aria-hidden />
                  {t("agentRepository.card.official")}
                </span>
              ) : null}
              {isMainAgent ? (
                <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                  <Bot className="size-3" aria-hidden />
                  {t("agentRepository.card.mainAgent")}
                </span>
              ) : null}
              {listing.version_label ? (
                <span className="flex min-w-0 max-w-full items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
                  <span
                    className="size-1.5 shrink-0 rounded-full bg-primary"
                    aria-hidden
                  />
                  <span className="min-w-0 truncate">
                    {t("agentRepository.mine.currentVersion", {
                      version: listing.version_label,
                    })}
                  </span>
                </span>
              ) : null}
            </>
          ) : undefined
        }
        tags={
          presentation || tags.length > 0 || toolCount > 0 ? (
            <div
              className={
                presentation
                  ? "flex h-6 w-full min-w-0 items-center gap-2"
                  : "flex w-full min-w-0 items-center gap-3"
              }
            >
              {presentation && (
                <span className="shrink-0 text-xs leading-5 text-[#191919]/70">
                  {t("resourceCenter.tags")}
                </span>
              )}
              {presentation && tags.length === 0 && (
                <span className="text-muted-foreground">—</span>
              )}
              {tags.length > 0 ? (
                <AgentCardTags
                  labels={tags.map((tag) => getAgentRepositoryTagLabel(tag, t))}
                />
              ) : null}
              {toolCount > 0 ? (
                <span className="shrink-0 whitespace-nowrap rounded-md border border-slate-200 px-2 py-0.5 text-slate-500 dark:border-slate-700 dark:text-slate-400">
                  {t("agentRepository.card.toolCount", { count: toolCount })}
                </span>
              ) : null}
            </div>
          ) : undefined
        }
        footerLayout="inline"
        meta={
          presentation ? (
            <div className="flex w-full min-w-0 items-center gap-2 leading-5 text-[#191919]/70">
              <span className="flex min-w-0 items-center gap-1">
                <Bot className="shrink-0" size={12} aria-hidden />
                <span className="truncate">
                  {t(
                    isMainAgent
                      ? "agentRepository.card.mainAgent"
                      : "space.detail.tabs.subAgents"
                  )}
                </span>
              </span>
              <span className="whitespace-nowrap">
                {t("resourceCenter.agentCardCopies", {
                  count: downloads,
                  formattedCount: downloads.toLocaleString(),
                })}
              </span>
              <span className="ml-auto flex min-w-0 items-center gap-1">
                <span className="shrink-0 whitespace-nowrap">
                  {t("resourceCenter.publishedVersion")}
                </span>
                <span
                  title={listing.version_label || undefined}
                  className="h-5 min-w-0 max-w-[60px] truncate rounded bg-blue-50 px-2 leading-5"
                >
                  {listing.version_label || "—"}
                </span>
              </span>
            </div>
          ) : author ? (
            <span className="block truncate" title={author}>
              {author}
            </span>
          ) : undefined
        }
        headerActions={
          <div className="flex items-center gap-1">
            {!presentation && (
              <span
                className="inline-flex shrink-0 items-center gap-1 text-xs font-normal text-slate-500 dark:text-slate-400"
                aria-label={t("agentRepository.detail.downloads", {
                  count: downloads.toLocaleString(),
                })}
              >
                <Download className="size-3.5" aria-hidden />
                {downloads.toLocaleString()}
              </span>
            )}
            {canManageListing && presentation?.layout === "list" ? (
              <Button
                type="link"
                className="!h-auto !px-0 !py-0 !text-sm !font-normal !leading-[22px] !text-[#0067D1]"
                loading={isTakingDown}
                onClick={() => confirmTakeDown(listing)}
              >
                {t("repository.listingStatus.takeDown")}
              </Button>
            ) : canManageListing && !showSplitAction ? (
              <Dropdown menu={{ items: menuItems }} trigger={["click"]}>
                <Button
                  type="text"
                  size="small"
                  className="size-8 shrink-0 text-slate-400 hover:text-slate-600"
                  icon={<MoreHorizontal className="size-4" aria-hidden />}
                  loading={isTakingDown}
                  aria-label={t("agentRepository.mine.menu.more")}
                />
              </Dropdown>
            ) : null}
          </div>
        }
        footer={
          showSplitAction ? (
            <Space.Compact>
              <Button
                className={`${templateButtonClassName} !rounded-r-none`}
                onClick={() => setCopyListing(listing)}
              >
                {t("resourceCenter.createFromTemplate")}
              </Button>
              <Dropdown menu={{ items: menuItems }} trigger={["click"]}>
                <Button
                  className="!size-[32px] !border-[#c9c9c9] !text-[#191919]"
                  icon={<ChevronDown className="size-4" aria-hidden />}
                  loading={isTakingDown}
                  aria-label={t("agentRepository.mine.menu.more")}
                />
              </Dropdown>
            </Space.Compact>
          ) : (
            <Button
              type={
                presentation?.layout === "list"
                  ? "link"
                  : presentation
                    ? "default"
                    : "text"
              }
              size={presentation ? "middle" : "small"}
              className={
                presentation?.layout === "list"
                  ? "!h-auto !min-w-0 !border-0 !bg-transparent !px-0 !py-0 !text-sm !font-normal !leading-[22px] !text-[#0067D1] !shadow-none"
                  : presentation
                    ? templateButtonClassName
                    : "!text-slate-600 hover:!text-blue-500"
              }
              icon={
                presentation ? undefined : (
                  <Copy className="size-3.5" aria-hidden />
                )
              }
              onClick={() => setCopyListing(listing)}
            >
              {t(
                presentation
                  ? "resourceCenter.createFromTemplate"
                  : "agentRepository.card.copy"
              )}
            </Button>
          )
        }
      />
    );
  };

  return (
    <div
      className={
        presentation?.layout === "cards"
          ? "repository-card-scroll flex min-h-0 flex-1 flex-col gap-4"
          : presentation
            ? "space-y-4"
            : "space-y-5"
      }
    >
      <div
        className={
          presentation
            ? "flex shrink-0 flex-wrap items-center gap-2"
            : "flex items-center gap-3"
        }
      >
        <div
          className={
            presentation
              ? presentation.layout === "list"
                ? "relative w-[349px] min-w-0 max-w-full"
                : "relative w-[440px] min-w-0 max-w-full"
              : "relative min-w-0 flex-1"
          }
        >
          <Input
            value={searchDraft ?? searchQuery}
            onCompositionStart={(event) => {
              composingSearch.current = true;
              setSearchDraft(event.currentTarget.value);
            }}
            onCompositionEnd={(event) => {
              composingSearch.current = false;
              onSearchChange(event.currentTarget.value);
              setSearchDraft(null);
            }}
            onChange={(event) => {
              if (composingSearch.current) {
                setSearchDraft(event.target.value);
              } else {
                onSearchChange(event.target.value);
              }
            }}
            placeholder={t("agentRepository.page.searchPlaceholder")}
            prefix={<Search className="size-4 text-[#777777]" aria-hidden />}
            className={
              presentation
                ? "h-8 gap-1 rounded border-[#C9C9C9] bg-white px-3 py-[5px] text-sm leading-[22px] [&_input::placeholder]:text-[#AEAEAE]"
                : "rounded-xl"
            }
            allowClear
          />
        </div>
        <TagFilterPopover
          appearance={presentation ? "select" : "button"}
          definitions={tagDefinitions ?? []}
          value={tagPredicates}
          onChange={onTagPredicatesChange}
          buttonClassName={
            presentation
              ? "!h-8 !w-[296px] max-w-full !justify-start !rounded !border-[#C9C9C9] !px-3 !text-sm"
              : undefined
          }
        />
        {!enhanced && (
          <Select<RepositorySortOrder>
            value={sortOrder}
            onChange={onSortOrderChange}
            className="w-44 shrink-0"
            aria-label={t("agentRepository.sort.label")}
            options={[
              { value: "default", label: t("agentRepository.sort.default") },
              { value: "latest", label: t("agentRepository.sort.latest") },
            ]}
          />
        )}
        {presentation && <AgentRepositorySort />}
        <RepositoryDisplayControls showSort={false} />
      </div>
      <div
        aria-busy={isPlaceholderData || undefined}
        className={
          presentation?.layout === "cards"
            ? "flex min-h-0 flex-1 flex-col"
            : "min-h-0"
        }
      >
        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Spin size="large" />
          </div>
        ) : isError ? (
          <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-200 py-16 text-center dark:border-slate-700">
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {t("agentRepository.page.loadError")}
            </p>
            <Button
              type="primary"
              onClick={() => refetch()}
              loading={isFetching}
            >
              {t("repository.common.retry")}
            </Button>
          </div>
        ) : (
          <ResourceCardGrid
            onListSelect={setDetailListing}
            items={listings}
            pageSize={pageSize}
            onPageSizeChange={presentation ? setPageSize : undefined}
            page={page}
            total={total}
            onPageChange={setPage}
            paginateItems={false}
            showToolbar={false}
            emptyState={
              <Empty
                className="py-16"
                description={t("agentRepository.page.empty")}
              />
            }
            renderItem={renderListing}
          />
        )}
      </div>
      <AgentDetail
        open={active && detailListing != null}
        onClose={() => setDetailListing(null)}
        detail={detail}
        agentIcon={
          detailListing ? (
            <RepositoryAgentIcon
              agentId={repositoryDetail?.agent_id ?? detailListing.agent_id}
              iconUrl={repositoryDetail?.icon_url ?? detailListing.icon_url}
              size={presentation ? 64 : 48}
              iconSize={24}
            />
          ) : undefined
        }
        published
        status={repositoryDetail?.status}
        showRepositoryInfo
        isLoading={isDetailLoading}
        isError={isDetailError}
        isFetching={isDetailFetching}
        onRetry={refetchDetail}
        footerActions={
          presentation && detailListing ? (
            <>
              {showAdminMenu && !detailListing.is_official ? (
                <Button
                  className="min-w-[88px] max-w-[200px]"
                  onClick={() => confirmTakeDown(detailListing)}
                  loading={
                    updatingRepositoryId === detailListing.agent_repository_id
                  }
                  disabled={isDetailLoading || isDetailError}
                >
                  {t("repository.listingStatus.takeDown")}
                </Button>
              ) : null}
              <Button
                type="primary"
                className="min-w-[88px] max-w-[200px]"
                disabled={isDetailLoading || isDetailError}
                onClick={() => {
                  setCopyListing(detailListing);
                  setDetailListing(null);
                }}
              >
                {t("resourceCenter.createFromTemplate")}
              </Button>
            </>
          ) : undefined
        }
      />
      <AgentRepositoryCopyDialog
        listing={copyListing}
        open={active && copyListing != null}
        onOpenChange={(open) => {
          if (!open) setCopyListing(null);
        }}
      />
    </div>
  );
}
