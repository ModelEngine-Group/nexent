"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { App, Button, Empty, Grid, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { Tag } from "lucide-react";
import { parseMcpReviewDeepLinkParams } from "@/lib/notificationNavigation";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { FILTER_ALL, McpToolsServicesTab } from "@/const/mcpTools";
import { filterByDeploymentType, matchesNameOrTag } from "@/lib/mcpTools";
import type { CommunityMcpCard, McpServiceItem } from "@/types/mcpTools";
import { useMcpServicesList } from "@/hooks/mcpTools/useMcpServicesList";
import { useMcpCommunityBrowser } from "@/hooks/mcpTools/useMcpCommunityBrowser";
import { useMcpCommunityReview } from "@/hooks/mcpTools/useMcpCommunityReview";
import { useMcpCommunityQuickAdd } from "@/hooks/mcpTools/useMcpCommunityQuickAdd";
import { useMyCommunityMcp } from "@/hooks/mcpTools/useMyCommunityMcp";
import { useTagLibraries } from "@/hooks/useTagManagement";
import { deleteCommunityMcpTool } from "@/services/mcpToolsService";
import RepositoryTagFilter from "@/components/tag/RepositoryTagFilter";
import ResourceCardGrid from "@/components/resource/ResourceCardGrid";
import TagDefinitionManagementModal from "@/components/tag/TagDefinitionManagementModal";
import McpToolsSearchFilterBar from "./components/McpToolsSearchFilterBar";
import RepositoryMcpCard from "./components/RepositoryMcpCard";
import AddMcpServiceModal from "./components/add/AddMcpServiceModal";
import CommunityQuickAddModal from "./components/add/community/CommunityQuickAddModal";
import McpCommunityDetailModal from "./components/add/community/McpCommunityDetailModal";
import McpServiceDetailModal from "./components/McpServiceDetailModal";
import RepositoryMcpDetailModal from "./components/RepositoryMcpDetailModal";
import PublishedServiceDetailModal from "./components/PublishedServiceDetailModal";
import {
  type DeploymentFilter,
  getDeduplicatedMineItems,
  PlaceholderBox,
} from "./my-mcp";

const CARD_GAP = 20;
const MIN_CARD_HEIGHT = 240;
const PAGINATION_HEIGHT = 60;

export function McpSpace({
  browser,
  localServices,
  isAdmin,
  actions,
  onSelect,
  onInstall,
  onOffline,
  onPageSizeChange,
}: {
  browser: ReturnType<typeof useMcpCommunityBrowser>;
  localServices: McpServiceItem[];
  isAdmin: boolean;
  actions: React.ReactNode;
  onSelect: (service: CommunityMcpCard) => void;
  onInstall: (service: CommunityMcpCard) => void;
  onOffline: (service: CommunityMcpCard) => void;
  onPageSizeChange: (pageSize: number) => void;
}) {
  const { t } = useTranslation("common");
  const [deploymentType] = useState<DeploymentFilter>(FILTER_ALL);
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
    if (!gridRegionRef.current) return;

    const viewportHeight = window.visualViewport?.height ?? window.innerHeight;
    const { top } = gridRegionRef.current.getBoundingClientRect();
    setAvailableGridHeight(
      Math.max(0, Math.floor(viewportHeight - top - pageBottomPadding - 8))
    );
  }, [pageBottomPadding]);

  useEffect(() => {
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
  }, [measureGridHeight]);

  useEffect(() => {
    onPageSizeChange(pageSize);
  }, [onPageSizeChange, pageSize]);

  const filteredServices = useMemo(() => {
    return filterByDeploymentType(browser.services, deploymentType).filter(
      (item) => matchesNameOrTag(item, browser.filters.search)
    );
  }, [browser.services, browser.filters.search, deploymentType]);
  const gridHeight =
    availableGridHeight === null
      ? undefined
      : Math.max(
          0,
          availableGridHeight - (browser.total > 0 ? PAGINATION_HEIGHT : 0)
        );

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
    <div className="space-y-4">
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

      <div ref={gridRegionRef} className="min-h-0">
        {browser.loading ? (
          <PlaceholderBox>
            <Spin />
          </PlaceholderBox>
        ) : filteredServices.length === 0 ? (
          <PlaceholderBox>
            <Empty description={t("mcpTools.repository.empty")} />
          </PlaceholderBox>
        ) : (
          <ResourceCardGrid
            items={filteredServices}
            page={browser.page}
            total={browser.total}
            onPageChange={browser.setPage}
            columns={columns}
            rows={rows}
            gridHeight={gridHeight}
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

export function useMcpSpaceController() {
  const { t } = useTranslation("common");
  const { message, modal } = App.useApp();
  const { user } = useAuthorizationContext();
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const locale = params.locale || "en";
  const searchParams = useSearchParams();
  const isAdmin = useMemo(
    () => user?.role === USER_ROLES.ADMIN || user?.role === USER_ROLES.SU,
    [user?.role]
  );

  const [tab, setTab] = useState<McpToolsServicesTab>(
    McpToolsServicesTab.REPOSITORY
  );
  const [repositoryPageSize, setRepositoryPageSize] = useState(12);
  const [showAddModal, setShowAddModal] = useState(false);
  const [tagManagementOpen, setTagManagementOpen] = useState(false);
  const { data: tagLibraries } = useTagLibraries();
  const defaultLibrary =
    tagLibraries?.find((lib) => lib.bucket_key === "default_resource") ?? null;
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
    const tabParam = searchParams.get("tab");
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
    router.replace(`/${locale}/mcp-space?tab=mine`);
  }, [locale, router]);

  const localList = useMcpServicesList();
  const myPublished = useMyCommunityMcp(
    tab === McpToolsServicesTab.MINE || Boolean(reviewDeepLink)
  );
  const repositoryBrowser = useMcpCommunityBrowser(
    tab === McpToolsServicesTab.REPOSITORY,
    repositoryPageSize
  );
  const reviewBrowser = useMcpCommunityReview(isAdmin);
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

  const handleToggled = async (mcpId: number) => {
    const result = await localList.refetch();
    const updated = result.data?.find((s) => s.mcpId === mcpId);
    if (updated && detailMcpIdRef.current === mcpId) {
      setSelectedLocal(updated);
    }
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
          await deleteCommunityMcpTool(service.communityId!);
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

  const searchActions =
    tab === McpToolsServicesTab.MINE ? (
      <Button
        className="flex h-11 shrink-0 items-center gap-1.5"
        icon={<Tag className="size-4" />}
        onClick={() => setTagManagementOpen(true)}
      >
        {t("mcpTools.tagManagement")}
      </Button>
    ) : null;

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
        />
      ) : null}

      {selectedRepository ? (
        <RepositoryMcpDetailModal
          service={selectedRepository}
          installed={isRepositoryInstalled(selectedRepository)}
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
        <CommunityQuickAddModal controller={quickAdd} />
      ) : null}

      <AddMcpServiceModal
        open={showAddModal}
        onClose={() => setShowAddModal(false)}
      />

      <TagDefinitionManagementModal
        open={tagManagementOpen}
        onClose={() => setTagManagementOpen(false)}
        bucketId={defaultLibrary?.bucket_id ?? 0}
        bucketName={defaultLibrary?.bucket_name ?? ""}
        canManage={true}
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
      actions: searchActions,
      onSelect: setSelectedRepository,
      onInstall: quickAdd.open,
      onOffline: handleRepositoryOffline,
      onPageSizeChange: setRepositoryPageSize,
    },
    mineProps: {
      localList,
      myPublished,
      actions: searchActions,
      reviewDeepLink,
      onReviewDeepLinkConsumed: handleReviewDeepLinkConsumed,
      onAdd: openAddModal,
      onEditLocal: openLocalDetail,
      onEditCommunity: setSelectedPublished,
      onToggled: handleToggled,
    },
    reviewProps: {
      browser: reviewBrowser,
      onSelect: setSelectedReview,
      onReviewed,
    },
    dialogs,
  };
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
