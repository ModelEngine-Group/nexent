// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useMemo, useState } from "react";
import type { MenuProps } from "antd";
import { App, Button, Dropdown, Empty, Input, Modal, Select, Spin } from "antd";
import {
  Bot,
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
import { USER_ROLES } from "@/const/auth";
import { useTagLibraries, useTagDefinitions } from "@/hooks/useTagManagement";
import { getTagSearchPredicates } from "@/lib/systemTagLabels";

import { REPOSITORY_PAGE_SIZE } from "@/const/resource";
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

export function AgentSpace({ active }: { active: boolean }) {
  const { t } = useTranslation("common");
  const displayName = useUserDisplayName();
  const { message } = App.useApp();
  const { user } = useAuthorizationContext();
  const showAdminMenu = user?.role === USER_ROLES.ADMIN;
  const [searchQuery, setSearchQuery] = useState("");
  const [tagPredicates, setTagPredicates] = useState<TagResourcePredicate[]>(
    []
  );
  const [sortOrder, setSortOrder] = useState<RepositorySortOrder>("default");
  const [page, setPage] = useState(1);
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
      page_size: REPOSITORY_PAGE_SIZE,
      ...(searchQuery.trim() ? { search: searchQuery.trim() } : {}),
      ...(searchTagPredicates.length > 0
        ? { search_tag_predicates: searchTagPredicates }
        : {}),
      ...(tagPredicates.length > 0 ? { tag_predicates: tagPredicates } : {}),
      ...(sortOrder === "latest" ? { sort_by_update_time: true } : {}),
    }),
    [page, searchQuery, searchTagPredicates, tagPredicates, sortOrder]
  );
  const { data, isLoading, isError, isFetching, refetch } =
    useAgentRepositoryListings(listingParams, active);
  const updateStatusMutation = useUpdateAgentRepositoryStatus();
  const listings = data?.items ?? [];
  const total = data?.pagination?.total ?? 0;
  const updatingRepositoryId = updateStatusMutation.isPending
    ? (updateStatusMutation.variables?.agentRepositoryId ?? null)
    : null;
  const onSearchChange = (value: string) => {
    setSearchQuery(value);
    setPage(1);
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
        key={listing.agent_repository_id}
        className="h-full"
        title={title}
        onClick={() => setDetailListing(listing)}
        icon={
          <div className="flex size-11 items-center justify-center rounded-xl bg-primary/10 text-xl text-primary">
            <RepositoryAgentIcon
              agentId={listing.agent_id}
              iconUrl={listing.icon_url}
              size={44}
              iconSize={20}
            />
          </div>
        }
        description={
          listing.description?.trim() || t("agentRepository.card.noDescription")
        }
        badge={
          showBadge ? (
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
          tags.length > 0 || toolCount > 0 ? (
            <div className="flex w-full min-w-0 items-center gap-2">
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
          author ? (
            <span className="block truncate" title={author}>
              {author}
            </span>
          ) : undefined
        }
        headerActions={
          <div className="flex items-center gap-1">
            <span
              className="inline-flex shrink-0 items-center gap-1 text-xs font-normal text-slate-500 dark:text-slate-400"
              aria-label={t("agentRepository.detail.downloads", {
                count: downloads.toLocaleString(),
              })}
            >
              <Download className="size-3.5" aria-hidden />
              {downloads.toLocaleString()}
            </span>
            {canManageListing ? (
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
          <Button
            type="text"
            size="small"
            className="!text-slate-600 hover:!bg-transparent hover:!text-blue-500"
            icon={<Copy className="size-3.5" aria-hidden />}
            onClick={() => setCopyListing(listing)}
          >
            {t("agentRepository.card.copy")}
          </Button>
        }
      />
    );
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <div className="relative min-w-0 flex-1">
          <Input
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={t("agentRepository.page.searchPlaceholder")}
            prefix={<Search className="size-4 text-slate-400" aria-hidden />}
            className="rounded-xl"
            allowClear
          />
        </div>
        <TagFilterPopover
          definitions={tagDefinitions ?? []}
          value={tagPredicates}
          onChange={onTagPredicatesChange}
        />
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
      </div>
      <div className="min-h-0">
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
            items={listings}
            pageSize={REPOSITORY_PAGE_SIZE}
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
