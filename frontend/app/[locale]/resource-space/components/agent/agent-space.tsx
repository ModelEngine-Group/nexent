// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { hasRole } from "@/lib/roles";

import RepositoryDisplayControls from "@/app/resource-space/components/RepositoryDisplayControls";
import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";
import { useRepositoryTagPredicates } from "@/hooks/useRepositoryTagPredicates";

import {
  useRepositoryPageSize,
  useRepositoryQueryState,
} from "@/hooks/useRepositoryQueryState";
import { useMemo, useRef, useState } from "react";
import type { MenuProps } from "antd";
import { App, Button, Dropdown, Empty, Input, Modal, Spin } from "antd";
import {
  Bot,
  Copy,
  CopyPlus,
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

import RepositoryCardActions from "@/app/resource-space/components/RepositoryCardActions";
import ResourceCardGrid from "@/components/resource/ResourceCardGrid";
import { AgentCardTags } from "@/components/resource/AgentCardTags";
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

const REPOSITORY_AVATAR_CLASS =
  "!shrink-0 !rounded !bg-primary/10 !text-primary";

export function AgentSpace({ active }: { active: boolean }) {
  const { t } = useTranslation("common");
  const presentation = useRepositoryPresentation();
  const displayName = useUserDisplayName();
  const { message } = App.useApp();
  const { user } = useAuthorizationContext();
  const showAdminMenu = hasRole(user, "ADMIN");
  const isDeveloper = hasRole(user, "DEV");
  const canTakeDownListing = (listing: AgentRepositoryListingItem) =>
    !listing.is_official &&
    (showAdminMenu ||
      (isDeveloper &&
        listing.status === "shared" &&
        listing.is_publisher === true &&
        !!user?.tenantId &&
        user.tenantId === listing.publisher_tenant_id));
  const [searchQuery, setSearchQuery] = useRepositoryQueryState("search", "");
  const composingSearch = useRef(false);
  const [searchDraft, setSearchDraft] = useState<string | null>(null);
  const [tagPredicates, setTagPredicates] = useRepositoryTagPredicates();
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
    }),
    [page, pageSize, searchQuery, searchTagPredicates, tagPredicates]
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
    const toolCount = presentation ? 0 : (listing.tool_count ?? 0);
    const downloads = listing.downloads ?? 0;
    const isTakingDown = updatingRepositoryId === listing.agent_repository_id;
    const isOfficialListing = listing.is_official === true;
    const isMainAgent = listing.is_main_agent !== false;
    const showBadge =
      isOfficialListing || Boolean(listing.version_label) || isMainAgent;
    // Official templates are managed from the super-admin resource page.
    // The ordinary repository status menu must not expose take-down actions
    // for official listings to tenant administrators.
    const canManageListing = canTakeDownListing(listing);
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
    const tagChips = (
      <>
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
      </>
    );

    return (
      <ResourceCard
        actionsOnly={presentation?.layout === "list"}
        key={listing.agent_repository_id}
        className={presentation ? undefined : "h-full"}
        title={title}
        subtitle={presentation ? author : undefined}
        onClick={() => setDetailListing(listing)}
        icon={
          <RepositoryAgentIcon
            agentId={listing.agent_id}
            iconUrl={listing.icon_url}
            size={presentation ? 56 : 44}
            iconSize={20}
            className={presentation ? REPOSITORY_AVATAR_CLASS : undefined}
          />
        }
        description={
          listing.description?.trim() || t("agentRepository.card.noDescription")
        }
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
          presentation ? (
            // Always reserve the tag row so repository cards keep equal
            // heights regardless of whether the listing has tags.
            <div className="flex h-6 w-full min-w-0 items-center gap-2">
              {tagChips}
            </div>
          ) : tags.length > 0 || toolCount > 0 ? (
            <div className="flex w-full min-w-0 items-center gap-3">
              {tagChips}
            </div>
          ) : undefined
        }
        footerLayout="inline"
        meta={
          presentation ? (
            <div className="flex w-full min-w-0 flex-wrap items-center gap-x-2 gap-y-1 leading-5 text-[#191919]/70">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="inline-flex items-center gap-1 whitespace-nowrap">
                  <Bot className="shrink-0" size={12} aria-hidden />
                  {t(
                    isMainAgent
                      ? "agentRepository.card.mainAgent"
                      : "space.detail.tabs.subAgents"
                  )}
                </span>
                <span className="inline-flex items-center gap-1 whitespace-nowrap">
                  <Copy className="shrink-0" size={12} aria-hidden />
                  {t("resourceCenter.agentCardCopies", {
                    count: downloads,
                    formattedCount: downloads.toLocaleString(),
                  })}
                </span>
              </div>
              <span className="ml-auto flex w-[clamp(8rem,45%,12rem)] max-w-full shrink-0 items-center gap-1">
                <span className="shrink-0 whitespace-nowrap">
                  {t("resourceCenter.publishedVersion")}
                </span>
                <span
                  title={listing.version_label || undefined}
                  className="h-5 min-w-0 truncate rounded bg-blue-50 px-2 leading-5"
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
            {canManageListing && !presentation ? (
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
          presentation ? (
            <RepositoryCardActions
              primary={{
                label: t("resourceCenter.createFromTemplate"),
                onClick: () => setCopyListing(listing),
              }}
              takeDown={
                canManageListing
                  ? {
                      label: t("repository.listingStatus.takeDown"),
                      loading: isTakingDown,
                      onClick: () => confirmTakeDown(listing),
                    }
                  : undefined
              }
            />
          ) : (
            <Button
              type="text"
              size="small"
              className="!text-slate-600 hover:!text-blue-500"
              icon={<Copy className="size-3.5" aria-hidden />}
              onClick={() => setCopyListing(listing)}
            >
              {t("agentRepository.card.copy")}
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
              ? "relative min-w-0 max-w-[800px] flex-[1_1_320px]"
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
              size={48}
              iconSize={22}
              className={presentation ? REPOSITORY_AVATAR_CLASS : undefined}
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
              {canTakeDownListing(detailListing) ? (
                <Button
                  type="text"
                  icon={<PackageX size={16} aria-hidden />}
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
                className="ml-auto"
                icon={<CopyPlus size={16} aria-hidden />}
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
