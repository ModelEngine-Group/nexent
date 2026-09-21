"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MenuProps } from "antd";
import { App, Button, Dropdown, Empty, Grid, Input, Modal, Spin } from "antd";
import {
  Bot,
  Copy,
  Download,
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

const CARD_GAP = 20;
const MIN_CARD_HEIGHT = 240;
const PAGINATION_HEIGHT = 60;

export function AgentSpace({ active }: { active: boolean }) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { user } = useAuthorizationContext();
  const showAdminMenu = user?.role === USER_ROLES.ADMIN;
  const screens = Grid.useBreakpoint();
  const gridRegionRef = useRef<HTMLDivElement>(null);
  const [availableGridHeight, setAvailableGridHeight] = useState<number | null>(
    null
  );
  const columns = screens.xxl
    ? 4
    : screens.xl
      ? 3
      : screens.lg || screens.md || screens.sm
        ? 2
        : screens.xs
          ? 1
          : 4;
  const pageBottomPadding = screens.sm ? 40 : 32;
  const rows = getRowCount(
    Math.max(0, (availableGridHeight ?? 0) - PAGINATION_HEIGHT)
  );
  const pageSize = columns * rows;
  const measureGridHeight = useCallback(() => {
    if (!active || !gridRegionRef.current) return;

    const viewportHeight = window.visualViewport?.height ?? window.innerHeight;
    const { top } = gridRegionRef.current.getBoundingClientRect();
    setAvailableGridHeight(
      Math.max(0, Math.floor(viewportHeight - top - pageBottomPadding - 8))
    );
  }, [active, pageBottomPadding]);

  useEffect(() => {
    if (!active) return;

    const frame = window.requestAnimationFrame(measureGridHeight);
    const observer = new ResizeObserver(measureGridHeight);
    const visualViewport = window.visualViewport;
    if (gridRegionRef.current) observer.observe(gridRegionRef.current);
    window.addEventListener("resize", measureGridHeight);
    visualViewport?.addEventListener("resize", measureGridHeight);

    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", measureGridHeight);
      visualViewport?.removeEventListener("resize", measureGridHeight);
    };
  }, [active, measureGridHeight]);
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
      page_size: pageSize,
      ...(searchQuery.trim() ? { search: searchQuery.trim() } : {}),
      ...(searchTagPredicates.length > 0
        ? { search_tag_predicates: searchTagPredicates }
        : {}),
      ...(tagPredicates.length > 0 ? { tag_predicates: tagPredicates } : {}),
    }),
    [page, pageSize, searchQuery, searchTagPredicates, tagPredicates]
  );
  const { data, isLoading, isError, isFetching, refetch } =
    useAgentRepositoryListings(listingParams, active);
  const updateStatusMutation = useUpdateAgentRepositoryStatus();
  const listings = data?.items ?? [];
  const total = data?.pagination?.total ?? 0;
  const gridHeight =
    availableGridHeight === null
      ? undefined
      : Math.max(0, availableGridHeight - (total > 0 ? PAGINATION_HEIGHT : 0));
  const cardHeight =
    gridHeight === undefined
      ? undefined
      : Math.max(0, (gridHeight - CARD_GAP * (rows - 1)) / rows);
  const descriptionLines =
    cardHeight === undefined || cardHeight >= 320
      ? 3
      : cardHeight >= 260
        ? 2
        : 1;
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
        className="h-full min-h-0"
        title={title}
        onClick={() => setDetailListingId(listing.agent_repository_id)}
        descriptionLines={descriptionLines}
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
        badge={
          listing.version_label ? (
            <span className="inline-flex items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
              <span
                className="size-1.5 shrink-0 rounded-full bg-primary"
                aria-hidden
              />
              {t("agentRepository.mine.currentVersion", {
                version: listing.version_label,
              })}
            </span>
          ) : undefined
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
        footerLayout="inline"
        meta={author ? <span className="truncate">{author}</span> : undefined}
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
            {showAdminMenu ? (
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
            className="h-8 px-3 text-xs font-medium text-primary !shadow-none hover:!bg-transparent hover:!text-primary/80"
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
      </div>
      <div ref={gridRegionRef} className="min-h-0">
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
            columns={columns}
            rows={rows}
            gridHeight={gridHeight}
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

function getRowCount(availableHeight: number) {
  if (availableHeight <= 0) return 3;
  return Math.min(
    3,
    Math.max(
      1,
      Math.floor((availableHeight + CARD_GAP) / (MIN_CARD_HEIGHT + CARD_GAP))
    )
  );
}
