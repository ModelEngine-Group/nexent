// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { hasRole } from "@/lib/roles";

import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { App, Empty, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { parseMcpReviewDeepLinkParams } from "@/lib/notificationNavigation";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";

import { FILTER_ALL, McpToolsServicesTab } from "@/const/mcpTools";
import {
  filterByDeploymentType,
  getDeploymentTypeLabelKey,
  matchesNameOrTag,
  resolveDeploymentType,
} from "@/lib/mcpTools";
import { McpDetail } from "@/components/mcp/mcp-detail";
import type { CommunityMcpCard, McpServiceItem } from "@/types/mcpTools";
import { useMcpServicesList } from "@/hooks/mcpTools/useMcpServicesList";
import { useMcpCommunityBrowser } from "@/hooks/mcpTools/useMcpCommunityBrowser";
import { useMcpCommunityReview } from "@/hooks/mcpTools/useMcpCommunityReview";
import { useMcpCommunityQuickAdd } from "@/hooks/mcpTools/useMcpCommunityQuickAdd";
import { useMyCommunityMcp } from "@/hooks/mcpTools/useMyCommunityMcp";
import { unpublishCommunityMcpTool } from "@/services/mcpToolsService";
import RepositoryTagFilter from "@/components/tag/RepositoryTagFilter";
import { useRepositoryPageSize } from "@/hooks/useRepositoryQueryState";
import ResourceCardGrid from "@/components/resource/ResourceCardGrid";
import McpCommunityRequestError from "./components/add/community/McpCommunityRequestError";
import McpToolsSearchFilterBar from "./components/McpToolsSearchFilterBar";
import RepositoryMcpCard from "./components/RepositoryMcpCard";
import AddMcpServiceModal from "./components/add/AddMcpServiceModal";
import CommunityQuickAddModal from "./components/add/community/CommunityQuickAddModal";
import McpCommunityDetailModal from "./components/add/community/McpCommunityDetailModal";
import McpServiceDetailModal from "./components/McpServiceDetailModal";
import TransportIcon from "./components/shared/TransportIcon";
import PublishedServiceDetailModal from "./components/PublishedServiceDetailModal";
import {
  type DeploymentFilter,
  getDeduplicatedMineItems,
  PlaceholderBox,
} from "./my-mcp";

export function McpSpace({
  browser,
  localServices,
  isAdmin,
  actions,
  onSelect,
  onInstall,
  onOffline,
}: {
  browser: ReturnType<typeof useMcpCommunityBrowser>;
  localServices: McpServiceItem[];
  isAdmin: boolean;
  actions: React.ReactNode;
  onSelect: (service: CommunityMcpCard) => void;
  onInstall: (service: CommunityMcpCard) => void;
  onOffline: (service: CommunityMcpCard) => void;
}) {
  const { t } = useTranslation("common");
  const presentation = useRepositoryPresentation();
  const scrollCards = presentation?.layout === "cards";
  const [pageSize, setPageSize] = useRepositoryPageSize();
  const [deploymentType] = useState<DeploymentFilter>(FILTER_ALL);
  const filteredServices = useMemo(() => {
    if (presentation) return browser.services;
    return filterByDeploymentType(browser.services, deploymentType).filter(
      (item) => matchesNameOrTag(item, browser.filters.search)
    );
  }, [browser.services, browser.filters.search, deploymentType, presentation]);
  const isInstalled = (service: CommunityMcpCard) => {
    return localServices.some((localService) => {
      if (localService.permission !== "EDIT") return false;
      if (
        service.communityId &&
        localService.communityId === service.communityId
      )
        return true;
      return localService.name === service.name;
    });
  };

  return (
    <div
      className={
        scrollCards
          ? "repository-card-scroll flex min-h-0 flex-1 flex-col gap-4"
          : "space-y-4"
      }
    >
      <McpToolsSearchFilterBar
        search={browser.filters.search}
        actions={actions}
        searchActions={
          <RepositoryTagFilter
            value={
              browser.filters.tag === FILTER_ALL
                ? undefined
                : browser.filters.tag
            }
            tags={browser.tagStats}
            onChange={(value) =>
              browser.updateFilter("tag", value ?? FILTER_ALL)
            }
          />
        }
        onSearchChange={(value) => browser.updateFilter("search", value)}
      />

      <div className={scrollCards ? "flex min-h-0 flex-1 flex-col" : "min-h-0"}>
        {browser.loading ? (
          <PlaceholderBox>
            <Spin />
          </PlaceholderBox>
        ) : browser.error ? (
          <PlaceholderBox>
            <McpCommunityRequestError onRetry={() => void browser.refetch()} />
          </PlaceholderBox>
        ) : filteredServices.length === 0 ? (
          <PlaceholderBox>
            <Empty description={t("mcpTools.repository.empty")} />
          </PlaceholderBox>
        ) : (
          <ResourceCardGrid
            onListSelect={onSelect}
            items={filteredServices}
            page={browser.page}
            total={browser.total}
            onPageChange={browser.setPage}
            pageSize={pageSize}
            onPageSizeChange={presentation ? setPageSize : undefined}
            paginateItems={false}
            showToolbar={false}
            renderItem={(service, index) => (
              <RepositoryMcpCard
                key={`${service.communityId || service.name}-${index}`}
                service={service}
                isAdmin={isAdmin}
                installed={isInstalled(service)}
                onInstall={onInstall}
                onSelect={onSelect}
                onOffline={onOffline}
              />
            )}
          />
        )}
      </div>
    </div>
  );
}

export function useMcpSpaceController(sortByPublished = false) {
  const { t } = useTranslation("common");
  const presentation = useRepositoryPresentation();
  const { message, modal } = App.useApp();
  const { user } = useAuthorizationContext();
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const locale = params.locale || "en";
  const searchParams = useSearchParams();
  const isAdmin = useMemo(
    () => hasRole(user, "ADMIN") || hasRole(user, "SU"),
    [user?.role, user?.roles]
  );

  const [tab, setTab] = useState<McpToolsServicesTab>(
    McpToolsServicesTab.REPOSITORY
  );
  const [showAddModal, setShowAddModal] = useState(false);
  const [selectedLocal, setSelectedLocal] = useState<McpServiceItem | null>(
    null
  );
  const [selectedRepository, setSelectedRepository] =
    useState<CommunityMcpCard | null>(null);
  const [selectedReview, setSelectedReview] = useState<CommunityMcpCard | null>(
    null
  );
  const [selectedPublished, setSelectedPublished] =
    useState<CommunityMcpCard | null>(null);

  const reviewDeepLink = useMemo(
    () => parseMcpReviewDeepLinkParams(searchParams),
    [searchParams]
  );

  useEffect(() => {
    const tabParam =
      searchParams.get("tab") === "mcp"
        ? searchParams.get("view") || "repository"
        : searchParams.get("tab");
    /* eslint-disable react-hooks/set-state-in-effect -- URL changes select the requested tab. */
    if (tabParam === McpToolsServicesTab.MINE) {
      setTab(McpToolsServicesTab.MINE);
    } else if (tabParam === McpToolsServicesTab.REVIEW && isAdmin) {
      setTab(McpToolsServicesTab.REVIEW);
    } else if (tabParam === McpToolsServicesTab.REPOSITORY) {
      setTab(McpToolsServicesTab.REPOSITORY);
    }
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [searchParams, isAdmin]);

  const handleReviewDeepLinkConsumed = useCallback(() => {
    router.replace(
      searchParams.get("tab") === "mcp"
        ? `/${locale}/resource-space?tab=mcp&view=mine`
        : `/${locale}/mcp-space?tab=mine`
    );
  }, [locale, router, searchParams]);

  const localList = useMcpServicesList();
  const consumedLocalTarget = useRef<string | null>(null);
  useEffect(() => {
    const value = searchParams.get("source_mcp_id");
    if (
      searchParams.get("tab") !== "mcp" ||
      !value ||
      value === consumedLocalTarget.current
    )
      return;
    const id = Number(value);
    if (!Number.isSafeInteger(id) || id <= 0) return;
    const service = localList.services.find((item) => item.mcpId === id);
    if (service) {
      consumedLocalTarget.current = value;
      // eslint-disable-next-line react-hooks/set-state-in-effect -- External links open the requested local record.
      setSelectedLocal(service);
    }
  }, [localList.services, searchParams]);

  const myPublished = useMyCommunityMcp(
    tab === McpToolsServicesTab.MINE || Boolean(reviewDeepLink)
  );
  const [repositoryPageSize] = useRepositoryPageSize();
  const repositoryBrowser = useMcpCommunityBrowser(
    tab === McpToolsServicesTab.REPOSITORY,
    repositoryPageSize,
    sortByPublished
  );
  const reviewBrowser = useMcpCommunityReview(
    isAdmin && searchParams.get("tab") !== "mcp"
  );
  const quickAdd = useMcpCommunityQuickAdd({
    onSuccess: () => setShowAddModal(false),
  });
  const isRepositoryInstalled = useCallback(
    (service: CommunityMcpCard) => {
      return localList.services.some((localService) => {
        if (localService.permission !== "EDIT") return false;
        if (
          service.communityId &&
          localService.communityId === service.communityId
        )
          return true;
        return localService.name === service.name;
      });
    },
    [localList.services]
  );
  const detailMcpIdRef = useRef<number | null>(null);

  useEffect(() => {
    if (!isAdmin && tab === McpToolsServicesTab.REVIEW) {
      /* eslint-disable react-hooks/set-state-in-effect -- Hide the admin tab when access changes. */
      setTab(McpToolsServicesTab.REPOSITORY);
      /* eslint-enable react-hooks/set-state-in-effect */
    }
  }, [isAdmin, tab]);

  const openAddModal = () => {
    setShowAddModal(true);
  };

  const openLocalDetail = (service: McpServiceItem) => {
    detailMcpIdRef.current = service.mcpId;
    setSelectedLocal(service);
  };

  const closeLocalDetail = () => {
    detailMcpIdRef.current = null;
    setSelectedLocal(null);
  };

  const [mineTagRefreshKeys, setMineTagRefreshKeys] = useState<
    Record<number, number>
  >({});

  const handleToggled = async (mcpId: number) => {
    const result = await localList.refetch();
    const updated = result.data?.find((s) => s.mcpId === mcpId);
    if (updated && detailMcpIdRef.current === mcpId) {
      setSelectedLocal(updated);
    }
  };

  const handleTagsChanged = (mcpId: number) => {
    setMineTagRefreshKeys((prev) => ({
      ...prev,
      [mcpId]: (prev[mcpId] ?? 0) + 1,
    }));
  };

  const handleRepositoryOffline = (service: CommunityMcpCard) => {
    if (!service.communityId) return;
    modal.confirm({
      title: t("mcpTools.mine.unpublishOnlineVersionTitle"),
      content: t("mcpTools.mine.unpublishOnlineVersionDescription", {
        name: service.name,
      }),
      okText: t("mcpTools.repository.offline"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      centered: true,
      onOk: async () => {
        try {
          await unpublishCommunityMcpTool(service.communityId!);
          message.success(t("mcpTools.mine.unpublishOnlineVersionSuccess"));
          await Promise.all([
            repositoryBrowser.refetch(),
            myPublished.refetch(),
            localList.refetch(),
          ]);
        } catch {
          message.error(t("mcpTools.mine.unpublishOnlineVersionFailed"));
        }
      },
    });
  };

  const repositoryCount = repositoryBrowser.services.length;
  const mineCount = getDeduplicatedMineItems(
    localList.services,
    myPublished.items
  ).length;
  const pendingReviewCount = reviewBrowser.services.filter(
    (s) => (s.reviewStatus || "pending") === "pending"
  ).length;

  const onReviewed = async () => {
    await Promise.all([
      reviewBrowser.refetch(),
      repositoryBrowser.refetch(),
      myPublished.refetch(),
      localList.refetch(),
    ]);
  };

  const dialogs = (
    <>
      {selectedLocal ? (
        <McpServiceDetailModal
          selectedService={selectedLocal}
          onClose={closeLocalDetail}
          onToggled={handleToggled}
          onTagsChanged={handleTagsChanged}
        />
      ) : null}

      {selectedRepository ? (
        <McpDetail
          open
          service={selectedRepository}
          installed={isRepositoryInstalled(selectedRepository)}
          icon={
            <TransportIcon
              transportType={selectedRepository.transportType}
              deploymentType={resolveDeploymentType(selectedRepository)}
              label={t(
                getDeploymentTypeLabelKey(
                  resolveDeploymentType(selectedRepository)
                )
              )}
              seed={selectedRepository.name}
              className={
                presentation
                  ? "!size-14 !rounded"
                  : "!size-12 shrink-0 rounded-xl"
              }
            />
          }
          onClose={() => setSelectedRepository(null)}
          onInstall={quickAdd.open}
        />
      ) : null}

      {selectedReview ? (
        <McpCommunityDetailModal
          service={selectedReview}
          onClose={() => setSelectedReview(null)}
        />
      ) : null}

      <PublishedServiceDetailModal
        open={Boolean(selectedPublished)}
        service={selectedPublished}
        onClose={() => setSelectedPublished(null)}
      />

      {quickAdd.visible ? (
        <CommunityQuickAddModal controller={quickAdd} mode="repository" />
      ) : null}

      <AddMcpServiceModal
        open={showAddModal}
        onClose={() => setShowAddModal(false)}
      />
    </>
  );

  return {
    tab,
    setTab,
    isAdmin,
    repositoryCount,
    mineCount,
    pendingReviewCount,
    repositoryProps: {
      browser: repositoryBrowser,
      localServices: localList.services,
      isAdmin,
      actions: null,
      onSelect: setSelectedRepository,
      onInstall: quickAdd.open,
      onOffline: handleRepositoryOffline,
    },
    mineProps: {
      localList,
      myPublished,
      actions: null,
      reviewDeepLink,
      onReviewDeepLinkConsumed: handleReviewDeepLinkConsumed,
      onAdd: openAddModal,
      onEditLocal: openLocalDetail,
      onEditCommunity: setSelectedPublished,
      onToggled: handleToggled,
      tagRefreshKeys: mineTagRefreshKeys,
    },
    reviewProps: {
      browser: reviewBrowser,
      onSelect: setSelectedReview,
      onReviewed,
    },
    dialogs,
  };
}
