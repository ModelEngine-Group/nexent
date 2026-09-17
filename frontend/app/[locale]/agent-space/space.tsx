"use client";

import { useMemo, useState } from "react";
import type { MenuProps } from "antd";
import { App, Button, Dropdown, Empty, Input, Modal, Spin } from "antd";
import {
  Bot,
  Copy,
  Download,
  Eye,
  MoreHorizontal,
  PackageX,
  Search,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { useTagLibraries, useTagDefinitions } from "@/hooks/useTagManagement";
import { getTagSearchPredicates } from "@/lib/systemTagLabels";

import ResourceCardGrid from "@/components/resource/ResourceCardGrid";
import ResourceCard from "@/components/resource/ResourceCard";
import TagFilterPopover from "@/components/tag/TagFilterPopover";
import { getAgentRepositoryTagLabel } from "@/lib/agentRepositoryLabels";
import type { TagResourcePredicate } from "@/types/tagManagement";
import type { AgentRepositoryListingItem } from "@/types/agentRepository";
import { AgentRepositoryCopyDialog } from "./components/AgentRepositoryCopyDialog";
import { AgentRepositoryDetailModal } from "./components/AgentRepositoryDetailModal";
import {
  useAgentRepositoryListingDetail,
  useAgentRepositoryListings,
  useUpdateAgentRepositoryStatus,
} from "@/hooks/agentRepository/useAgentRepositoryListings";
import { mapRepositoryListingDetail } from "@/lib/agentRepositoryDetail";

const REPOSITORY_PAGE_SIZE = 12;

export function AgentSpace({ active }: { active: boolean }) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { user } = useAuthorizationContext();
  const showAdminMenu = user?.role === USER_ROLES.ADMIN;
  const [searchQuery, setSearchQuery] = useState("");
  const [tagPredicates, setTagPredicates] = useState<TagResourcePredicate[]>(
    []
  );
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
    }),
    [page, searchQuery, searchTagPredicates, tagPredicates]
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
  const onTakeDown = (listing: AgentRepositoryListingItem) =>
    updateStatusMutation.mutateAsync({
      agentRepositoryId: listing.agent_repository_id,
      status: "not_shared",
    });
  const [copyListing, setCopyListing] =
    useState<AgentRepositoryListingItem | null>(null);
  const [detailListingId, setDetailListingId] = useState<number | null>(null);
  const {
    data: repositoryDetail,
    isLoading: isDetailLoading,
    isError: isDetailError,
    isFetching: isDetailFetching,
    refetch: refetchDetail,
  } = useAgentRepositoryListingDetail(
    detailListingId,
    active && detailListingId != null
  );
  const detail = useMemo(
    () =>
      repositoryDetail
        ? mapRepositoryListingDetail(repositoryDetail)
        : detailListingId != null
          ? undefined
          : null,
    [detailListingId, repositoryDetail]
  );
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
    const author = listing.author?.trim();
    const tags = listing.tags?.filter((tag) => tag.trim()) ?? [];
    const toolCount = listing.tool_count ?? 0;
    const downloads = listing.downloads ?? 0;
    const isTakingDown = updatingRepositoryId === listing.agent_repository_id;
    const menuItems: MenuProps["items"] = showAdminMenu
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
        subtitle={author}
        icon={
          <div className="flex size-11 items-center justify-center rounded-xl bg-primary/10 text-xl text-primary">
            {listing.icon?.trim() ? (
              <span aria-hidden>{listing.icon.trim()}</span>
            ) : (
              <Bot className="size-5" aria-hidden />
            )}
          </div>
        }
        description={
          listing.description?.trim() || t("agentRepository.card.noDescription")
        }
        tags={
          tags.length > 0 || toolCount > 0 ? (
            <>
              {tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded-md bg-slate-100 px-2 py-0.5 font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200"
                >
                  {getAgentRepositoryTagLabel(tag, t)}
                </span>
              ))}
              {toolCount > 0 ? (
                <span className="rounded-md border border-slate-200 px-2 py-0.5 text-slate-500 dark:border-slate-700 dark:text-slate-400">
                  {t("agentRepository.card.toolCount", { count: toolCount })}
                </span>
              ) : null}
            </>
          ) : undefined
        }
        meta={
          <>
            {listing.version_label ? (
              <span className="inline-flex min-w-0 items-center gap-1.5">
                <span
                  className="size-1.5 rounded-full bg-primary"
                  aria-hidden
                />
                {listing.version_label}
              </span>
            ) : null}
            <span
              className="inline-flex items-center gap-1"
              aria-label={t("agentRepository.detail.downloads", {
                count: downloads.toLocaleString(),
              })}
            >
              <Download className="size-3.5" aria-hidden />
              {downloads.toLocaleString()}
            </span>
          </>
        }
        headerActions={
          showAdminMenu ? (
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
          ) : undefined
        }
        footer={
          <div className="flex items-center gap-2">
            <Button
              type="primary"
              className="min-w-0 flex-1"
              icon={<Copy className="size-3.5" />}
              onClick={() => setCopyListing(listing)}
            >
              {t("agentRepository.card.copy")}
            </Button>
            <Button
              type="default"
              className="min-w-0 flex-1"
              icon={<Eye className="size-3.5" />}
              onClick={() => setDetailListingId(listing.agent_repository_id)}
            >
              {t("agentRepository.card.detail")}
            </Button>
          </div>
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
            className="h-11 rounded-xl"
            allowClear
          />
        </div>
        <TagFilterPopover
          definitions={tagDefinitions ?? []}
          value={tagPredicates}
          onChange={onTagPredicatesChange}
        />
      </div>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        {t("agentRepository.page.repositoryHint")}
      </p>
      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Spin size="large" />
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-200 py-16 text-center dark:border-slate-700">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("agentRepository.page.loadError")}
          </p>
          <Button type="primary" onClick={() => refetch()} loading={isFetching}>
            {t("repository.common.retry")}
          </Button>
        </div>
      ) : (
        <ResourceCardGrid
          items={listings}
          columns={4}
          rows={3}
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
      <AgentRepositoryDetailModal
        open={active && detailListingId != null}
        onClose={() => setDetailListingId(null)}
        detail={detail}
        isLoading={isDetailLoading}
        isError={isDetailError}
        isFetching={isDetailFetching}
        onRetry={() => refetchDetail()}
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
