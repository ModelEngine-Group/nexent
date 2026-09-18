"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { App, Button, Popover, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { ChevronLeft, ChevronRight, Tag } from "lucide-react";
import { MCP_SERVERS_QUERY_KEY } from "@/hooks/mcp/useMcpServerList";
import { useMcpServicesList } from "@/hooks/mcpTools/useMcpServicesList";
import { useMyCommunityMcp } from "@/hooks/mcpTools/useMyCommunityMcp";
import { useMcpServiceToggle } from "@/hooks/mcpTools/useMcpServiceToggle";
import { useTagLibraries, useTagDefinitions } from "@/hooks/useTagManagement";
import { checkMcpServerHealth } from "@/services/mcpService";
import {
  cancelCommunityMcpReview,
  deleteCommunityMcpTool,
  deleteMcpToolService,
  publishCommunityMcpTool,
  updateCommunityMcpTool,
} from "@/services/mcpToolsService";
import { tagManagementApi } from "@/services/tagManagementService";
import { getTagSearchPredicates } from "@/lib/systemTagLabels";
import { matchesNameOrTag, resolveDeploymentType } from "@/lib/mcpTools";
import type { CommunityMcpCard, McpServiceItem } from "@/types/mcpTools";
import type { TagResourcePredicate } from "@/types/tagManagement";
import {
  FILTER_ALL,
  McpServiceStatus,
  MCP_TOOLS_QUERY_KEYS,
  McpTransportType,
} from "@/const/mcpTools";
import TagFilterControls from "@/components/tag/TagFilterControls";
import AddMcpServiceCard from "./components/AddMcpServiceCard";
import McpToolsSearchFilterBar from "./components/McpToolsSearchFilterBar";
import MineMcpServiceCard, {
  type MineMcpCardItem,
} from "./components/MineMcpServiceCard";
import MineApplyListingModal from "./components/MineApplyListingModal";
import MineMcpReviewStatusModal from "./components/MineMcpReviewStatusModal";
import {
  type DeploymentFilter,
  getDeduplicatedMineItems,
  getDeploymentCategoryStats,
  getMineItemKey,
  PlaceholderBox,
  resolveOnlineService,
  ResponsiveCardGrid,
  toMcpContainerConfigPayload,
} from "./mcp-space-shared";

const MINE_PAGE_SIZE = 6;

export function MyMcpServices({
  localList,
  myPublished,
  actions,
  reviewDeepLink,
  onReviewDeepLinkConsumed,
  onAdd,
  onEditLocal,
  onEditCommunity,
  onToggled,
}: {
  localList: ReturnType<typeof useMcpServicesList>;
  myPublished: ReturnType<typeof useMyCommunityMcp>;
  actions: React.ReactNode;
  reviewDeepLink: { marketId: number; sourceMcpId: number } | null;
  onReviewDeepLinkConsumed: () => void;
  onAdd: () => void;
  onEditLocal: (service: McpServiceItem) => void;
  onEditCommunity: (service: CommunityMcpCard) => void;
  onToggled: (mcpId: number) => Promise<void>;
}) {
  const { t } = useTranslation("common");
  const { message, modal } = App.useApp();
  const toggle = useMcpServiceToggle();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [deploymentType, setDeploymentType] =
    useState<DeploymentFilter>(FILTER_ALL);
  const tag = FILTER_ALL;
  const { data: mineTagLibraries } = useTagLibraries();
  const mineDefaultLibrary =
    mineTagLibraries?.find((lib) => lib.bucket_key === "default_resource") ??
    null;
  const { data: mineTagDefinitions } = useTagDefinitions(
    mineDefaultLibrary?.bucket_id ?? null
  );
  const [tagPredicates, setTagPredicates] = useState<TagResourcePredicate[]>(
    []
  );
  const [matchedTagIds, setMatchedTagIds] = useState<Set<string> | null>(null);
  const [matchedSearchTagIds, setMatchedSearchTagIds] =
    useState<Set<string> | null>(null);
  const [page, setPage] = useState(1);
  const [publishingKey, setPublishingKey] = useState<string | null>(null);
  const [unpublishingKey, setUnpublishingKey] = useState<string | null>(null);
  const [refreshingMineKey, setRefreshingMineKey] = useState<string | null>(
    null
  );
  const [reviewProgressItem, setReviewProgressItem] = useState<{
    item: MineMcpCardItem;
    onlineService?: CommunityMcpCard;
  } | null>(null);
  const [applyListingItem, setApplyListingItem] = useState<{
    item: MineMcpCardItem;
    onlineService?: CommunityMcpCard;
  } | null>(null);
  const deepLinkHandledRef = useRef<string | null>(null);

  const items = useMemo<MineMcpCardItem[]>(() => {
    return getDeduplicatedMineItems(localList.services, myPublished.items);
  }, [localList.services, myPublished.items]);

  const onlineServiceByCommunityId = useMemo(() => {
    const services = new Map<number, CommunityMcpCard>();
    for (const service of myPublished.items) {
      if (service.communityId) services.set(service.communityId, service);
    }
    return services;
  }, [myPublished.items]);

  const onlineServiceBySourceMcpId = useMemo(() => {
    const services = new Map<number, CommunityMcpCard>();
    for (const item of myPublished.items) {
      if (item.sourceMcpId != null) services.set(item.sourceMcpId, item);
    }
    return services;
  }, [myPublished.items]);

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- The deep link opens the matching review item after data loads. */
    if (!reviewDeepLink) {
      deepLinkHandledRef.current = null;
      return;
    }
    if (localList.loading || myPublished.loading) {
      return;
    }

    const deepLinkKey = `${reviewDeepLink.marketId}:${reviewDeepLink.sourceMcpId}`;
    if (deepLinkHandledRef.current === deepLinkKey) {
      return;
    }

    const onlineService =
      myPublished.items.find(
        (service) =>
          service.marketId === reviewDeepLink.marketId ||
          service.communityId === reviewDeepLink.marketId
      ) || onlineServiceBySourceMcpId.get(reviewDeepLink.sourceMcpId);

    const localService = localList.services.find(
      (service) => service.mcpId === reviewDeepLink.sourceMcpId
    );

    if (localService) {
      const item: MineMcpCardItem = { kind: "local", service: localService };
      setReviewProgressItem({
        item,
        onlineService: onlineService || undefined,
      });
      deepLinkHandledRef.current = deepLinkKey;
      onReviewDeepLinkConsumed();
      return;
    }

    if (onlineService) {
      setReviewProgressItem({
        item: { kind: "community", service: onlineService },
        onlineService,
      });
      deepLinkHandledRef.current = deepLinkKey;
      onReviewDeepLinkConsumed();
      return;
    }

    deepLinkHandledRef.current = deepLinkKey;
    message.error(t("notifications.deepLink.mcpNotFound"));
    onReviewDeepLinkConsumed();
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [
    localList.loading,
    localList.services,
    message,
    myPublished.items,
    myPublished.loading,
    onReviewDeepLinkConsumed,
    onlineServiceBySourceMcpId,
    reviewDeepLink,
    t,
  ]);

  const categoryStats = useMemo(
    () =>
      getDeploymentCategoryStats(
        items.map((item) => item.service),
        t
      ),
    [items, t]
  );

  const searchTagPredicates = useMemo(
    () => getTagSearchPredicates(mineTagDefinitions, search, t),
    [mineTagDefinitions, search, t]
  );

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- Reset matches when the selected filters change. */
    if (tagPredicates.length === 0) {
      setMatchedTagIds(null);
      return;
    }
    const localItems = items
      .filter((item) => item.kind === "local")
      .map((item) => String(item.service.mcpId))
      .filter(Boolean);
    if (localItems.length === 0) {
      setMatchedTagIds(new Set());
      return;
    }
    let cancelled = false;
    tagManagementApi
      .filterResourceIds("mcp_service", localItems, tagPredicates)
      .then((result) => {
        if (cancelled) return;
        setMatchedTagIds(new Set(result.matched_resource_ids ?? []));
      })
      .catch(() => {
        if (cancelled) return;
        setMatchedTagIds(new Set());
      });
    return () => {
      cancelled = true;
    };
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [tagPredicates, items]);

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- Reset matches when the search predicates change. */
    if (searchTagPredicates.length === 0) {
      setMatchedSearchTagIds(null);
      return;
    }
    const localItems = items
      .filter((item) => item.kind === "local")
      .map((item) => String(item.service.mcpId))
      .filter(Boolean);
    if (localItems.length === 0) {
      setMatchedSearchTagIds(new Set());
      return;
    }
    let cancelled = false;
    Promise.all(
      searchTagPredicates.map((predicate) =>
        tagManagementApi.filterResourceIds("mcp_service", localItems, [
          predicate,
        ])
      )
    )
      .then((results) => {
        if (cancelled) return;
        setMatchedSearchTagIds(
          new Set(
            results.flatMap((result) => result.matched_resource_ids ?? [])
          )
        );
      })
      .catch(() => {
        if (cancelled) return;
        setMatchedSearchTagIds(new Set());
      });
    return () => {
      cancelled = true;
    };
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [items, searchTagPredicates]);
  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      const service = item.service;
      const matchesStructuredTag =
        item.kind === "local" &&
        matchedSearchTagIds?.has(String(item.service.mcpId));
      if (!matchesNameOrTag(service, search) && !matchesStructuredTag)
        return false;
      if (tag !== FILTER_ALL && !(service.tags || []).includes(tag))
        return false;
      if (
        deploymentType !== FILTER_ALL &&
        resolveDeploymentType(service) !== deploymentType
      )
        return false;
      if (matchedTagIds !== null) {
        if (item.kind !== "local") return false;
        if (!matchedTagIds.has(String(item.service.mcpId))) return false;
      }
      return true;
    });
  }, [items, search, tag, deploymentType, matchedTagIds, matchedSearchTagIds]);

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- Filter changes restart pagination. */
    setPage(1);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [search, tag, deploymentType, tagPredicates]);

  const firstPageSize = MINE_PAGE_SIZE - 1;

  const pagedItems = useMemo(() => {
    if (filteredItems.length === 0) return [];
    if (page === 1) {
      return filteredItems.slice(0, firstPageSize);
    }
    const start = firstPageSize + (page - 2) * MINE_PAGE_SIZE;
    return filteredItems.slice(start, start + MINE_PAGE_SIZE);
  }, [filteredItems, page, firstPageSize]);

  const loading = localList.loading || myPublished.loading;

  const handleToggle = async (service: McpServiceItem) => {
    await toggle.toggle(service);
    await onToggled(service.mcpId);
  };

  const refreshMineData = async () => {
    // Refetch the review query immediately so the admin tab badge updates
    // without requiring a full page reload.
    await queryClient.refetchQueries({
      queryKey: MCP_TOOLS_QUERY_KEYS.communityReview,
      type: "all",
    });
    await Promise.all([localList.refetch(), myPublished.refetch()]);
  };

  const handleSubmitVersionUpdate = (
    item: MineMcpCardItem,
    onlineService?: CommunityMcpCard
  ) => {
    setApplyListingItem({ item, onlineService });
  };

  const doSubmitVersionUpdate = async (
    item: MineMcpCardItem,
    onlineService: CommunityMcpCard | undefined,
    content?: string,
    sharedFields?: Record<string, boolean>
  ) => {
    const key = getMineItemKey(item);
    setPublishingKey(key);
    try {
      if (item.kind === "community") {
        const service = item.service;
        if (!service.marketId) return;
        await updateCommunityMcpTool({
          market_id: service.marketId,
          name: service.name.trim(),
          description: (service.description || "").trim(),
          version: (service.version || "").trim(),
          tags: service.tags || [],
          registry_json: service.registryJson,
          shared_fields: sharedFields,
          content,
        });
      } else if (onlineService?.marketId) {
        const service = item.service;
        const configJson = toMcpContainerConfigPayload(service.configJson);
        await updateCommunityMcpTool({
          market_id: onlineService.marketId,
          name: service.name.trim(),
          description: (service.description || "").trim(),
          version: (service.version || "").trim(),
          tags: service.tags || [],
          registry_json: service.registryJson || onlineService.registryJson,
          mcp_server: configJson ? undefined : service.serverUrl,
          transport_type: configJson
            ? McpTransportType.CONTAINER
            : McpTransportType.URL,
          config_json: configJson,
          shared_fields: sharedFields,
          content,
        });
      } else if (item.kind === "local") {
        const service = item.service;
        const configJson = toMcpContainerConfigPayload(service.configJson);
        await publishCommunityMcpTool({
          mcp_id: service.mcpId,
          name: service.name.trim(),
          description: service.description,
          version: (service.version || "").trim(),
          tags: service.tags || [],
          mcp_server: configJson ? undefined : service.serverUrl,
          config_json: configJson,
          shared_fields: sharedFields,
          content,
        });
      }
      const isInitialPublish =
        item.kind === "local" && !onlineService?.marketId;
      message.success(
        isInitialPublish
          ? t("mcpTools.mine.publishApplySuccess")
          : t("mcpTools.mine.submitVersionUpdateSuccess")
      );
      // Optimistically update local cache to show pending status
      updateLocalReviewStatus(item, "pending");
    } catch {
      message.error(t("mcpTools.mine.publishApplyFailed"));
      return;
    } finally {
      setPublishingKey(null);
    }
    // Refresh caches after successful submission; never fail the submission
    // when a cache refresh has a transient error.
    try {
      await refreshMineData();
    } catch {
      // cache refresh errors are non-fatal
    }
    setPublishingKey(null);
  };

  const updateLocalReviewStatus = (
    item: MineMcpCardItem,
    status: "pending" | "approved" | "rejected"
  ) => {
    if (item.kind !== "local") return;
    queryClient.setQueryData(
      [...MCP_TOOLS_QUERY_KEYS.services],
      (old: McpServiceItem[] | undefined) => {
        if (!old) return old;
        return old.map((s) =>
          s.mcpId === item.service.mcpId ? { ...s, reviewStatus: status } : s
        );
      }
    );
  };

  const handleUnpublishOnline = (
    item: MineMcpCardItem,
    onlineService: CommunityMcpCard
  ) => {
    if (!onlineService.communityId) return;
    const isPendingReview = onlineService.reviewStatus === "pending";
    modal.confirm({
      title: isPendingReview
        ? t("mcpTools.mine.reviewModal.confirmCancelApplyTitle")
        : t("mcpTools.mine.unpublishOnlineVersionTitle"),
      content: isPendingReview
        ? t("repository.listingStatus.cancelApply")
        : t("mcpTools.mine.unpublishOnlineVersionDescription", {
            name: onlineService.name || item.service.name,
          }),
      okText: isPendingReview
        ? t("repository.listingStatus.cancelApply")
        : t("mcpTools.mine.unpublishOnlineVersion"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      centered: true,
      onOk: async () => {
        const key = getMineItemKey(item);
        setUnpublishingKey(key);
        try {
          await deleteCommunityMcpTool(onlineService.communityId!);
          message.success(
            isPendingReview
              ? t("repository.mine.cancelApplySuccess")
              : t("mcpTools.mine.unpublishOnlineVersionSuccess")
          );
          await refreshMineData();
        } catch {
          message.error(
            isPendingReview
              ? t("repository.mine.cancelApplyError")
              : t("mcpTools.mine.unpublishOnlineVersionFailed")
          );
        } finally {
          setUnpublishingKey(null);
        }
      },
    });
  };

  const handleDelete = (item: MineMcpCardItem) => {
    modal.confirm({
      title: t("mcpTools.mine.deleteConfirmTitle"),
      content: t("mcpTools.mine.deleteConfirmDescription", {
        name: item.service.name,
      }),
      okText: t("common.delete"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      centered: true,
      onOk: async () => {
        try {
          if (item.kind === "local") {
            await deleteMcpToolService(item.service.mcpId);
          } else if (item.service.communityId) {
            await deleteCommunityMcpTool(item.service.communityId);
          }
          message.success(t("repository.mine.deleteSuccess"));
          await refreshMineData();
          // Force-refresh all caches the agent config page relies on
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: MCP_SERVERS_QUERY_KEY }),
            queryClient.invalidateQueries({ queryKey: ["tools"] }),
            queryClient.invalidateQueries({ queryKey: ["agents"] }),
            queryClient.refetchQueries({
              queryKey: MCP_SERVERS_QUERY_KEY,
              type: "all",
            }),
          ]);
        } catch {
          message.error(t("repository.mine.deleteFailed"));
        }
      },
    });
  };

  const handleHealthCheck = async (item: MineMcpCardItem) => {
    const mcpId =
      item.kind === "local" ? item.service.mcpId : item.service.sourceMcpId;
    if (!mcpId) return;
    const key = getMineItemKey(item);
    setRefreshingMineKey(key);
    try {
      const result = await checkMcpServerHealth(mcpId);
      if (result.success) {
        message.success(t("mcpConfig.message.healthCheckSuccess"));
      } else {
        message.error(t("mcpConfig.message.healthCheckFailed"));
        // If MCP is enabled and health check fails, auto-disable it
        if (
          item.kind === "local" &&
          item.service.enabled === McpServiceStatus.ENABLED
        ) {
          await toggle.toggle(item.service);
        }
      }
      await refreshMineData();
    } catch {
      message.error(t("mcpConfig.message.healthCheckFailed"));
    } finally {
      setRefreshingMineKey(null);
    }
  };

  const handleCancelApply = async (
    item: MineMcpCardItem,
    onlineService?: CommunityMcpCard
  ) => {
    const communityRecord =
      item.kind === "community" ? item.service : onlineService;
    const reviewId = communityRecord?.reviewId;
    if (!reviewId) return;
    try {
      await cancelCommunityMcpReview(reviewId);
      message.success(t("repository.mine.cancelApplySuccess"));
      setReviewProgressItem(null);
      await refreshMineData();
    } catch {
      message.error(t("repository.mine.cancelApplyError"));
    }
  };

  const handleTakeDown = async (
    item: MineMcpCardItem,
    onlineService: CommunityMcpCard
  ) => {
    handleUnpublishOnline(item, onlineService);
  };

  return (
    <div className="space-y-4">
      <McpToolsSearchFilterBar
        search={search}
        deploymentType={deploymentType}
        categoryStats={categoryStats}
        actions={actions}
        filterActions={
          <Popover
            trigger="click"
            placement="bottomRight"
            content={
              <div className="w-72">
                <TagFilterControls
                  definitions={mineTagDefinitions ?? []}
                  value={tagPredicates}
                  onChange={setTagPredicates}
                />
                {tagPredicates.length > 0 ? (
                  <button
                    type="button"
                    className="mt-2 text-xs text-blue-600 hover:underline"
                    onClick={() => setTagPredicates([])}
                  >
                    {t("mcpTools.tagFilter.clear")}
                  </button>
                ) : null}
              </div>
            }
          >
            <Button
              type={tagPredicates.length > 0 ? "primary" : "default"}
              icon={<Tag className="size-3.5" aria-hidden />}
              aria-label={t("mcpTools.tagFilter.button")}
            >
              {t("mcpTools.tagFilter.button")}
            </Button>
          </Popover>
        }
        onSearchChange={setSearch}
        onDeploymentTypeChange={setDeploymentType}
      />

      <p className="text-sm text-slate-500">{t("mcpTools.mine.publishHint")}</p>

      {loading ? (
        <PlaceholderBox>
          <Spin />
        </PlaceholderBox>
      ) : filteredItems.length === 0 ? (
        <ResponsiveCardGrid>
          <AddMcpServiceCard onClick={onAdd} />
        </ResponsiveCardGrid>
      ) : (
        <ResponsiveCardGrid>
          {page === 1 ? <AddMcpServiceCard onClick={onAdd} /> : null}
          {pagedItems.map((item) => {
            const key = getMineItemKey(item);
            const onlineService =
              item.kind === "local"
                ? resolveOnlineService(
                    item.service,
                    onlineServiceByCommunityId,
                    onlineServiceBySourceMcpId
                  )
                : item.service;
            return (
              <MineMcpServiceCard
                key={key}
                item={item}
                onlineService={onlineService}
                toggling={
                  item.kind === "local"
                    ? toggle.isToggling(item.service.mcpId)
                    : false
                }
                publishing={publishingKey === key}
                unpublishing={unpublishingKey === key}
                onEditLocal={onEditLocal}
                onEditCommunity={onEditCommunity}
                onToggle={handleToggle}
                onSubmitVersionUpdate={handleSubmitVersionUpdate}
                onUnpublishOnline={handleUnpublishOnline}
                onDelete={handleDelete}
                onViewReviewProgress={(item, os) =>
                  setReviewProgressItem({ item, onlineService: os })
                }
                onHealthCheck={handleHealthCheck}
                healthChecking={refreshingMineKey === getMineItemKey(item)}
              />
            );
          })}
        </ResponsiveCardGrid>
      )}

      {(() => {
        const remainingItems = Math.max(
          0,
          filteredItems.length - firstPageSize
        );
        const totalPages = 1 + Math.ceil(remainingItems / MINE_PAGE_SIZE);
        if (totalPages <= 1) return null;
        return (
          <div className="flex items-center justify-center gap-1.5 pt-4">
            <Button
              type="default"
              className="flex size-9 items-center justify-center rounded-lg p-0"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
              aria-label="Previous page"
            >
              <ChevronLeft className="size-4" />
            </Button>
            {Array.from({ length: totalPages }, (_, index) => index + 1).map(
              (pageNumber) => (
                <Button
                  key={pageNumber}
                  type={pageNumber === page ? "primary" : "default"}
                  className="flex size-9 items-center justify-center rounded-lg p-0"
                  onClick={() => setPage(pageNumber)}
                  aria-current={pageNumber === page ? "page" : undefined}
                >
                  {pageNumber}
                </Button>
              )
            )}
            <Button
              type="default"
              className="flex size-9 items-center justify-center rounded-lg p-0"
              disabled={page >= totalPages}
              onClick={() => setPage(page + 1)}
              aria-label="Next page"
            >
              <ChevronRight className="size-4" />
            </Button>
          </div>
        );
      })()}

      <MineMcpReviewStatusModal
        open={Boolean(reviewProgressItem)}
        item={reviewProgressItem?.item ?? null}
        onlineService={reviewProgressItem?.onlineService}
        onClose={() => setReviewProgressItem(null)}
        onCancelApply={handleCancelApply}
        onTakeDown={handleTakeDown}
      />

      <MineApplyListingModal
        open={Boolean(applyListingItem)}
        item={applyListingItem?.item ?? null}
        loading={
          applyListingItem
            ? publishingKey === getMineItemKey(applyListingItem.item)
            : false
        }
        onClose={() => setApplyListingItem(null)}
        onConfirm={async (content, sharedFields) => {
          if (!applyListingItem) return;
          await doSubmitVersionUpdate(
            applyListingItem.item,
            applyListingItem.onlineService,
            content,
            sharedFields
          );
        }}
      />
    </div>
  );
}
