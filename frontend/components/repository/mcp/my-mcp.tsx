// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useRepositoryTagPredicates } from "@/hooks/useRepositoryTagPredicates";

import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";
import {
  useRepositoryPageSize,
  useRepositoryQueryState,
} from "@/hooks/useRepositoryQueryState";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { App, Button, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { ChevronUp } from "lucide-react";
import { MCP_SERVERS_QUERY_KEY } from "@/hooks/mcp/useMcpServerList";
import { useMcpServicesList } from "@/hooks/mcpTools/useMcpServicesList";
import { useMyCommunityMcp } from "@/hooks/mcpTools/useMyCommunityMcp";
import { useMcpServiceToggle } from "@/hooks/mcpTools/useMcpServiceToggle";
import { useTagLibraries, useTagDefinitions } from "@/hooks/useTagManagement";
import { checkMcpServerHealth } from "@/services/mcpService";
import {
  cancelCommunityMcpReview,
  batchDeleteMcpTools,
  deleteCommunityMcpTool,
  unpublishCommunityMcpTool,
  deleteMcpToolService,
  publishCommunityMcpTool,
  updateCommunityMcpTool,
} from "@/services/mcpToolsService";
import { tagManagementApi } from "@/services/tagManagementService";
import { getTagSearchPredicates } from "@/lib/systemTagLabels";
import { matchesNameOrTag, resolveDeploymentType } from "@/lib/mcpTools";
import type {
  CommunityMcpCard,
  McpContainerConfigPayload,
  McpServiceItem,
} from "@/types/mcpTools";
import type { TagResourcePredicate } from "@/types/tagManagement";
import {
  FILTER_ALL,
  McpDeploymentType,
  McpServiceStatus,
  MCP_TOOLS_QUERY_KEYS,
  McpTransportType,
} from "@/const/mcpTools";
import TagFilterPopover from "@/components/tag/TagFilterPopover";
import ResourceCardGrid from "@/components/resource/ResourceCardGrid";
import ResourceReviewLink from "@/components/repository/ResourceReviewLink";
import AddMcpServiceCard from "./components/AddMcpServiceCard";
import McpToolsSearchFilterBar from "./components/McpToolsSearchFilterBar";
import MineMcpServiceCard, {
  type MineMcpCardItem,
  type McpConnectionStatus,
} from "./components/MineMcpServiceCard";
import MineApplyListingModal from "./components/MineApplyListingModal";
import MineMcpReviewStatusModal from "./components/MineMcpReviewStatusModal";
import { getDeploymentTypeLabelKey } from "@/lib/mcpTools";

export function MyMcp({
  localList,
  myPublished,
  actions,
  reviewDeepLink,
  onReviewDeepLinkConsumed,
  onAdd,
  onEditLocal,
  onEditCommunity,
  onToggled,
  tagRefreshKeys,
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
  tagRefreshKeys?: Record<number, number>;
}) {
  const { t } = useTranslation("common");
  const { message, modal } = App.useApp();
  const toggle = useMcpServiceToggle();
  const queryClient = useQueryClient();
  const presentation = useRepositoryPresentation();
  const cardLayout = presentation?.layout === "cards";
  const [batchMode, setBatchMode] = useState(false);
  const [search, setSearch] = useRepositoryQueryState("search", "");
  const [deploymentType, setDeploymentType] =
    useRepositoryQueryState<DeploymentFilter>("deployment", FILTER_ALL, [
      FILTER_ALL,
      ...Object.values(McpDeploymentType),
    ]);
  const tag = FILTER_ALL;
  const { data: mineTagLibraries } = useTagLibraries();
  const mineDefaultLibrary =
    mineTagLibraries?.find((lib) => lib.bucket_key === "default_resource") ??
    null;
  const { data: mineTagDefinitions } = useTagDefinitions(
    mineDefaultLibrary?.bucket_id ?? null
  );
  const [tagPredicates, setTagPredicates] = useRepositoryTagPredicates();
  const [matchedTagIds, setMatchedTagIds] = useState<Set<string> | null>(null);
  const [matchedSearchTagIds, setMatchedSearchTagIds] =
    useState<Set<string> | null>(null);
  const [pageSize, setPageSize] = useRepositoryPageSize();
  const [page, setPage] = useRepositoryQueryState("page", 1);
  const [publishingKey, setPublishingKey] = useState<string | null>(null);
  const [unpublishingKey, setUnpublishingKey] = useState<string | null>(null);
  const [refreshingMineKey, setRefreshingMineKey] = useState<string | null>(
    null
  );
  const [connectionStatuses, setConnectionStatuses] = useState<
    Record<string, McpConnectionStatus>
  >({});
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
    if (!presentation) setPage(1);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [search, tag, deploymentType, tagPredicates]);

  const itemsPerPage = presentation ? pageSize : pageSize - 1;
  const totalPages = Math.max(
    1,
    Math.ceil(filteredItems.length / itemsPerPage)
  );
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- Filtering or deleting items can reduce the last page. */
    if (!localList.loading && !myPublished.loading && page > totalPages)
      setPage(totalPages);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [page, totalPages, localList.loading, myPublished.loading, setPage]);

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
          await unpublishCommunityMcpTool(onlineService.communityId!);
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

  const refreshAfterDelete = async () => {
    await refreshMineData();
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: MCP_SERVERS_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: ["tools"] }),
      queryClient.invalidateQueries({ queryKey: ["agents"] }),
      queryClient.refetchQueries({
        queryKey: MCP_SERVERS_QUERY_KEY,
        type: "all",
      }),
    ]);
  };

  const deleteSelectedItems = async (items: MineMcpCardItem[]) => {
    const targets = items.map((item) => {
      const id =
        item.kind === "local" ? item.service.mcpId : item.service.communityId;
      if (!id) throw new Error(t("repository.mine.deleteFailed"));
      return { kind: item.kind, id };
    });
    const results = await batchDeleteMcpTools(targets);
    const byTarget = new Map(
      results.map((result) => [`${result.kind}:${result.id}`, result])
    );
    const failures = new Map<string, string>();
    targets.forEach(({ kind, id }, index) => {
      const result = byTarget.get(`${kind}:${id}`);
      if (!result?.success) {
        failures.set(
          getMineItemKey(items[index]),
          result?.message || t("repository.mine.deleteFailed")
        );
      }
    });
    if (failures.size < items.length) {
      await Promise.allSettled([refreshAfterDelete()]);
    }
    return failures;
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
          } else {
            const marketId = item.service.communityId;
            if (!marketId) throw new Error(t("repository.mine.deleteFailed"));
            await deleteCommunityMcpTool(marketId);
          }
          await refreshAfterDelete();
          message.success(t("repository.mine.deleteSuccess"));
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
      setConnectionStatuses((current) => ({
        ...current,
        [key]: result.success ? "success" : "failed",
      }));
      if (result.success) {
        message.success(
          result.message || t("mcpService.message.healthCheckSuccess")
        );
      } else {
        message.error(
          result.message || t("mcpService.message.healthCheckFailed")
        );
      }
      if (!result.success) {
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
      setConnectionStatuses((current) => ({ ...current, [key]: "failed" }));
      message.error(t("mcpService.message.healthCheckFailed"));
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

  const renderBatchToolbar = (batchControls?: React.ReactNode) => (
    <div className="mb-4 shrink-0">
      <McpToolsSearchFilterBar
        search={search}
        deploymentType={deploymentType}
        categoryStats={categoryStats}
        actions={
          presentation ? (
            <>
              {actions}
              {batchControls}
              <Button onClick={() => setBatchMode(!batchMode)}>
                {t(batchMode ? "common.cancel" : "mcpTools.mine.batchActions")}
              </Button>
              {!batchMode && (
                <Button
                  type="primary"
                  className="!gap-1 !px-3"
                  icon={<ChevronUp size={16} aria-hidden />}
                  iconPlacement="end"
                  onClick={onAdd}
                >
                  {t("mcpTools.mine.addMcp")}
                </Button>
              )}
            </>
          ) : (
            actions
          )
        }
        searchActions={
          <TagFilterPopover
            definitions={mineTagDefinitions ?? []}
            value={tagPredicates}
            onChange={setTagPredicates}
            appearance={presentation ? "select" : "button"}
            buttonClassName={presentation ? "w-full min-w-0" : undefined}
          />
        }
        onSearchChange={setSearch}
        onDeploymentTypeChange={setDeploymentType}
      />
    </div>
  );

  return (
    <div
      className={
        cardLayout
          ? "mcp-mine repository-card-scroll flex min-h-0 flex-1 flex-col bg-white"
          : "mcp-mine space-y-4 rounded-2xl bg-white"
      }
    >
      {loading && renderBatchToolbar()}
      <div className={cardLayout ? "flex min-h-0 flex-1 flex-col" : "min-h-0"}>
        {loading ? (
          <PlaceholderBox>
            <Spin />
          </PlaceholderBox>
        ) : (
          <ResourceCardGrid
            onListSelect={(item) =>
              item.kind === "local"
                ? onEditLocal(item.service)
                : onEditCommunity(item.service)
            }
            renderListStatus={(item) => {
              const localService = item.kind === "local" ? item.service : null;
              const onlineService = localService
                ? resolveOnlineService(
                    localService,
                    onlineServiceByCommunityId,
                    onlineServiceBySourceMcpId
                  )
                : item.service;
              const reviewStatus =
                onlineService?.reviewStatus ||
                item.service.reviewStatus ||
                (localService?.isListedInRepository ||
                (item.kind === "community" && item.service.status === "active")
                  ? "approved"
                  : undefined);
              const isEnabled =
                localService?.enabled === McpServiceStatus.ENABLED;
              const listingState =
                reviewStatus === "approved"
                  ? {
                      label: t("mcpTools.mine.status.listed"),
                      className: "bg-emerald-50 text-emerald-700",
                    }
                  : reviewStatus === "pending"
                    ? {
                        label: t("mcpTools.mine.status.reviewing"),
                        className: "bg-orange-50 text-orange-700",
                      }
                    : reviewStatus === "rejected"
                      ? {
                          label: t("mcpTools.mine.status.rejected"),
                          className: "bg-red-50 text-red-700",
                        }
                      : {
                          label: t("repository.status.notListed"),
                          className: "bg-slate-100 text-slate-600",
                        };
              const latestReview = localService?.latest_review;

              return (
                <div className="flex flex-wrap items-center gap-1.5">
                  {localService ? (
                    <span
                      className={`rounded px-1.5 py-0.5 text-xs ${
                        isEnabled
                          ? "bg-blue-50 text-blue-700"
                          : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {t(
                        isEnabled
                          ? "mcpTools.mine.enabled"
                          : "mcpTools.status.disabled"
                      )}
                    </span>
                  ) : (
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                      {t("market.install.mcp.notInstalled")}
                    </span>
                  )}
                  <span
                    className={`rounded px-1.5 py-0.5 text-xs ${listingState.className}`}
                  >
                    {listingState.label}
                  </span>
                  {latestReview ? (
                    <ResourceReviewLink review={latestReview} />
                  ) : null}
                </div>
              );
            }}
            getItemKey={getMineItemKey}
            selectionKey={JSON.stringify([
              search,
              deploymentType,
              tagPredicates,
            ])}
            canBatchDelete={(item) =>
              item.kind === "local"
                ? item.service.permission === "EDIT"
                : Boolean(item.service.communityId)
            }
            batchDeleteItems={batchMode ? deleteSelectedItems : undefined}
            renderBatchToolbar={renderBatchToolbar}
            cardSelectionInHeader
            items={filteredItems}
            page={page}
            total={filteredItems.length}
            onPageChange={setPage}
            pageSize={pageSize}
            onPageSizeChange={presentation ? setPageSize : undefined}
            createCard={
              presentation ? undefined : <AddMcpServiceCard onClick={onAdd} />
            }
            paginateItems
            showToolbar={false}
            emptyState={presentation ? undefined : null}
            renderItem={(item, _index, selection) => {
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
                  selection={selection}
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
                  connectionStatus={connectionStatuses[key] ?? "unchecked"}
                  tagRefreshKey={
                    item.kind === "local"
                      ? tagRefreshKeys?.[item.service.mcpId]
                      : undefined
                  }
                />
              );
            }}
          />
        )}
      </div>

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

export type DeploymentFilter = McpDeploymentType | typeof FILTER_ALL;

type DeploymentCountable = {
  transportType: CommunityMcpCard["transportType"];
  deploymentType?: McpDeploymentType;
  configJson?: Record<string, unknown>;
  serverUrl?: string;
};

const deploymentCategories = [
  McpDeploymentType.REMOTE_LINK,
  McpDeploymentType.CONTAINER,
  McpDeploymentType.API,
  McpDeploymentType.LOCAL_IMAGE,
];

export function getDeploymentCategoryStats(
  items: DeploymentCountable[],
  t: (key: string) => string
): Array<{ value: DeploymentFilter; label: string; count: number }> {
  const hasLocalImage = items.some(
    (item) => resolveDeploymentType(item) === McpDeploymentType.LOCAL_IMAGE
  );
  return [
    {
      value: FILTER_ALL,
      label: t("mcpTools.deploymentType.all"),
      count: items.length,
    },
    ...deploymentCategories
      .filter((dt) => dt !== McpDeploymentType.LOCAL_IMAGE || hasLocalImage)
      .map((deploymentType) => ({
        value: deploymentType,
        label: t(getDeploymentTypeLabelKey(deploymentType)),
        count: items.filter(
          (item) => resolveDeploymentType(item) === deploymentType
        ).length,
      })),
  ];
}

export function getDeduplicatedMineItems(
  localServices: McpServiceItem[],
  publishedServices: CommunityMcpCard[]
): MineMcpCardItem[] {
  // Only show local MCPs that belong to the current user or are shared via groups
  const myLocalServices = localServices.filter(
    (s) => s.permission === "EDIT" || s.groupIds
  );
  const linkedCommunityIds = new Set<number>();
  const localNames = new Set<string>();

  for (const service of myLocalServices) {
    if (service.communityId) linkedCommunityIds.add(service.communityId);
    localNames.add(normalizeMcpName(service.name));
  }

  const visiblePublishedServices = publishedServices.filter((service) => {
    // Published-by-me items (have sourceMcpId) are hidden from "我的" tab.
    // They are managed via the repository tab. This prevents them from
    // reappearing after the local copy is deleted.
    if (service.sourceMcpId != null) return false;
    if (service.communityId && linkedCommunityIds.has(service.communityId)) {
      return false;
    }
    return !localNames.has(normalizeMcpName(service.name));
  });

  return [
    ...myLocalServices.map((service) => ({
      kind: "local" as const,
      service,
    })),
    ...visiblePublishedServices.map((service) => ({
      kind: "community" as const,
      service,
    })),
  ];
}

function normalizeMcpName(name: string): string {
  return name.trim().toLowerCase();
}

export function getMineItemKey(item: MineMcpCardItem): string {
  return item.kind === "local"
    ? `local-${item.service.mcpId}`
    : `community-${item.service.communityId || item.service.name}`;
}

export function toMcpContainerConfigPayload(
  value?: Record<string, unknown>
): McpContainerConfigPayload | undefined {
  if (!value || typeof value.mcpServers !== "object" || !value.mcpServers) {
    return undefined;
  }
  return value as unknown as McpContainerConfigPayload;
}

export function resolveOnlineService(
  service: McpServiceItem,
  serviceByCommunityId: Map<number, CommunityMcpCard>,
  serviceBySourceMcpId: Map<number, CommunityMcpCard>
): CommunityMcpCard | undefined {
  const reviewService = serviceBySourceMcpId.get(service.mcpId);
  if (reviewService) return reviewService;
  if (service.communityId) {
    const marketService = serviceByCommunityId.get(service.communityId);
    if (
      marketService?.sourceMcpId == null ||
      marketService.sourceMcpId === service.mcpId
    ) {
      return marketService;
    }
  }
  return undefined;
}

export function PlaceholderBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-center rounded-xl border border-dashed border-slate-200 px-6 py-16 text-center text-slate-500 dark:border-slate-700">
      {children}
    </div>
  );
}
