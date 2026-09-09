"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { App, Button, ConfigProvider, Empty, Modal, Popover, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import {
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  Clock,
  CloudUpload,
  Download,
  Eye,
  Inbox,
  Plus,
  Puzzle,
  ShieldCheck,
  Tag,
  User,
  XCircle,
} from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { parseMcpReviewDeepLinkParams } from "@/lib/notificationNavigation";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { useMcpServicesList } from "@/hooks/mcpTools/useMcpServicesList";
import { MCP_SERVERS_QUERY_KEY } from "@/hooks/mcp/useMcpServerList";
import { useMyCommunityMcp } from "@/hooks/mcpTools/useMyCommunityMcp";
import { useMcpCommunityBrowser } from "@/hooks/mcpTools/useMcpCommunityBrowser";
import { useMcpCommunityReview } from "@/hooks/mcpTools/useMcpCommunityReview";
import { useMcpCommunityQuickAdd } from "@/hooks/mcpTools/useMcpCommunityQuickAdd";
import { useMcpServiceToggle } from "@/hooks/mcpTools/useMcpServiceToggle";
import {
  approveCommunityMcpTool,
  cancelCommunityMcpReview,
  deleteCommunityMcpTool,
  deleteMcpToolService,
  publishCommunityMcpTool,
  rejectCommunityMcpTool,
  updateCommunityMcpTool,
} from "@/services/mcpToolsService";
import { checkMcpServerHealth } from "@/services/mcpService";
import type {
  CommunityMcpCard,
  McpContainerConfigPayload,
  McpServiceItem,
  McpTagStat,
} from "@/types/mcpTools";
import {
  FILTER_ALL,
  McpDeploymentType,
  McpServiceStatus,
  MCP_TOOLS_QUERY_KEYS,
  McpToolsServicesTab,
  McpTransportType,
} from "@/const/mcpTools";
import {
  filterByDeploymentType,
  formatRegistryDate,
  getDeploymentTypeLabelKey,
  matchesNameOrTag,
  paginateItems,
  resolveDeploymentType,
} from "@/lib/mcpTools";
import AddMcpServiceModal from "./components/add/AddMcpServiceModal";
import TagDefinitionManagementModal from "@/components/tag/TagDefinitionManagementModal";
import { useTagLibraries, useTagDefinitions } from "@/hooks/useTagManagement";
import TagFilterControls from "@/components/tag/TagFilterControls";
import RepositoryTagFilter from "@/components/tag/RepositoryTagFilter";
import { getTagSearchPredicates } from "@/lib/systemTagLabels";
import type { TagResourcePredicate } from "@/types/tagManagement";
import { tagManagementApi } from "@/services/tagManagementService";
import AddMcpServiceCard from "./components/AddMcpServiceCard";
import CommunityQuickAddModal from "./components/add/community/CommunityQuickAddModal";
import McpCommunityDetailModal from "./components/add/community/McpCommunityDetailModal";
import McpServiceDetailModal from "./components/McpServiceDetailModal";
import McpToolsPagination from "./components/McpToolsPagination";
import McpToolsSearchFilterBar from "./components/McpToolsSearchFilterBar";
import MineMcpServiceCard, {
  type MineMcpCardItem,
} from "./components/MineMcpServiceCard";
import MineApplyListingModal from "./components/MineApplyListingModal";
import MineMcpReviewStatusModal from "./components/MineMcpReviewStatusModal";
import McpRepositoryReviewConfirmModal, {
  type McpRepositoryReviewAction,
} from "./components/McpRepositoryReviewConfirmModal";
import PublishedServiceDetailModal from "./components/PublishedServiceDetailModal";
import RepositoryMcpCard from "./components/RepositoryMcpCard";
import RepositoryMcpDetailModal from "./components/RepositoryMcpDetailModal";
import TransportIcon from "./components/shared/TransportIcon";

const mcpToolsTheme = {
  token: { colorPrimary: "#2563eb", colorInfo: "#0284c7" },
};

const MINE_PAGE_SIZE = 6;
type DeploymentFilter = McpDeploymentType | typeof FILTER_ALL;

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

function getDeploymentCategoryStats(
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

export default function McpToolsPage() {
  const { t } = useTranslation("common");
  const { message, modal } = App.useApp();
  const { user } = useAuthorizationContext();
  const { pageVariants, pageTransition } = useSetupFlow();
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
    if (tabParam === McpToolsServicesTab.MINE) {
      setTab(McpToolsServicesTab.MINE);
    } else if (tabParam === McpToolsServicesTab.REVIEW && isAdmin) {
      setTab(McpToolsServicesTab.REVIEW);
    } else if (tabParam === McpToolsServicesTab.REPOSITORY) {
      setTab(McpToolsServicesTab.REPOSITORY);
    }
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
    6
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
      setTab(McpToolsServicesTab.REPOSITORY);
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
      <>
        <Button
          type="primary"
          className="flex h-11 shrink-0 items-center gap-1.5"
          icon={<Plus className="size-4" />}
          onClick={openAddModal}
        >
          {t("mcpTools.addModal.title")}
        </Button>
        <Button
          className="flex h-11 shrink-0 items-center gap-1.5"
          icon={<Tag className="size-4" />}
          onClick={() => setTagManagementOpen(true)}
        >
          {t("mcpTools.tagManagement")}
        </Button>
      </>
    ) : null;

  return (
    <ConfigProvider theme={mcpToolsTheme}>
      <div className="flex h-full min-h-0 w-full min-w-0 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]">
          <motion.div
            initial="initial"
            animate="in"
            exit="out"
            variants={pageVariants}
            transition={pageTransition}
            className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 sm:py-10"
          >
            <div className="flex flex-col gap-6">
              <section className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex items-start gap-4">
                  <div className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary shadow-sm">
                    <Puzzle className="size-7" />
                  </div>
                  <div>
                    <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl dark:text-slate-100">
                      {t("mcpTools.page.title")}
                    </h1>
                    <p className="mt-1 max-w-xl text-sm leading-relaxed text-slate-600 dark:text-slate-300">
                      {t("mcpTools.page.subtitle")}
                    </p>
                  </div>
                </div>
              </section>

              <Tabs
                value={tab}
                onValueChange={(value) => setTab(value as McpToolsServicesTab)}
                className="w-full"
              >
                <TabsList
                  className={cn(
                    "mb-6 grid h-auto w-full gap-2 rounded-xl border border-border bg-secondary/60 px-2 py-2",
                    isAdmin ? "grid-cols-3" : "grid-cols-2"
                  )}
                >
                  <TabsTrigger
                    value={McpToolsServicesTab.REPOSITORY}
                    className="w-full justify-center gap-1.5 rounded-lg px-[5px] py-2 text-sm data-[state=active]:shadow-sm"
                  >
                    <Inbox className="size-4" aria-hidden />
                    {t("repository.page.tab.repository")}
                    <span className="ml-1 rounded-md bg-background/70 px-1.5 text-xs text-muted-foreground">
                      {repositoryCount}
                    </span>
                  </TabsTrigger>
                  <TabsTrigger
                    value={McpToolsServicesTab.MINE}
                    className="w-full justify-center gap-1.5 rounded-lg px-[5px] py-2 text-sm data-[state=active]:shadow-sm"
                  >
                    <User className="size-4" aria-hidden />
                    {t("mcpTools.page.tab.mine")}
                    <span className="ml-1 rounded-md bg-background/70 px-1.5 text-xs text-muted-foreground">
                      {mineCount}
                    </span>
                  </TabsTrigger>
                  {isAdmin ? (
                    <TabsTrigger
                      value={McpToolsServicesTab.REVIEW}
                      className="w-full justify-center gap-1.5 rounded-lg px-[5px] py-2 text-sm data-[state=active]:shadow-sm"
                    >
                      <ShieldCheck className="size-4" aria-hidden />
                      {t("repository.page.tab.review")}
                      {pendingReviewCount > 0 ? (
                        <span className="ml-1 inline-flex size-5 items-center justify-center rounded-full bg-red-500 text-[11px] font-bold text-white">
                          {pendingReviewCount}
                        </span>
                      ) : null}
                    </TabsTrigger>
                  ) : null}
                </TabsList>
              </Tabs>

              {tab === McpToolsServicesTab.REPOSITORY ? (
                <RepositoryView
                  browser={repositoryBrowser}
                  localServices={localList.services}
                  isAdmin={isAdmin}
                  actions={searchActions}
                  onSelect={setSelectedRepository}
                  onInstall={quickAdd.open}
                  onOffline={handleRepositoryOffline}
                />
              ) : null}

              {tab === McpToolsServicesTab.MINE ? (
                <MineView
                  localList={localList}
                  myPublished={myPublished}
                  actions={searchActions}
                  reviewDeepLink={reviewDeepLink}
                  onReviewDeepLinkConsumed={handleReviewDeepLinkConsumed}
                  onAdd={openAddModal}
                  onEditLocal={openLocalDetail}
                  onEditCommunity={setSelectedPublished}
                  onToggled={handleToggled}
                />
              ) : null}

              {tab === McpToolsServicesTab.REVIEW && isAdmin ? (
                <ReviewCenterView
                  browser={reviewBrowser}
                  actions={searchActions}
                  onSelect={setSelectedReview}
                  onReviewed={async () => {
                    await Promise.all([
                      reviewBrowser.refetch(),
                      repositoryBrowser.refetch(),
                      myPublished.refetch(),
                      localList.refetch(),
                    ]);
                  }}
                />
              ) : null}

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
            </div>
          </motion.div>
        </div>
      </div>
    </ConfigProvider>
  );
}

function RepositoryView({
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
  const [deploymentType, setDeploymentType] =
    useState<DeploymentFilter>(FILTER_ALL);

  const filteredServices = useMemo(() => {
    return filterByDeploymentType(browser.services, deploymentType).filter(
      (item) => matchesNameOrTag(item, browser.filters.search)
    );
  }, [browser.services, browser.filters.search, deploymentType]);

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
              browser.filters.tag === FILTER_ALL ? undefined : browser.filters.tag
            }
            tags={browser.tagStats}
            onChange={(value) =>
              browser.updateFilter("tag", value ?? FILTER_ALL)
            }
          />
        }
        onSearchChange={(value) => browser.updateFilter("search", value)}
      />

      <p className="text-sm text-slate-500">
        {t("mcpTools.repository.installHint")}
      </p>

      {browser.loading ? (
        <PlaceholderBox>
          <Spin />
        </PlaceholderBox>
      ) : filteredServices.length === 0 ? (
        <PlaceholderBox>
          <Empty description={t("mcpTools.repository.empty")} />
        </PlaceholderBox>
      ) : (
        <ResponsiveCardGrid>
          {filteredServices.map((service, index) => (
            <RepositoryMcpCard
              key={`${service.communityId || service.name}-${index}`}
              service={service}
              isAdmin={isAdmin}
              installed={isInstalled(service)}
              onInstall={onInstall}
              onSelect={onSelect}
              onOffline={onOffline}
            />
          ))}
        </ResponsiveCardGrid>
      )}

      {filteredServices.length > 0 ? (
        <McpToolsPagination
          mode="offset"
          current={browser.page}
          pageSize={browser.pageSize}
          total={browser.total}
          onChange={browser.setPage}
        />
      ) : null}
    </div>
  );
}

function MineView({
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
  const [tag, setTag] = useState(FILTER_ALL);
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
  const [matchedSearchTagIds, setMatchedSearchTagIds] = useState<
    Set<string> | null
  >(null);
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

  const tagStats = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of [...localList.services, ...myPublished.items]) {
      for (const raw of item.tags || []) {
        const next = String(raw || "").trim();
        if (!next) continue;
        counts.set(next, (counts.get(next) || 0) + 1);
      }
    }
    return Array.from(counts.entries())
      .map(([tagName, count]): McpTagStat => ({ tag: tagName, count }))
      .sort((a, b) => a.tag.localeCompare(b.tag));
  }, [localList.services, myPublished.items]);

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
  }, [tagPredicates, items]);

  useEffect(() => {
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
        tagManagementApi.filterResourceIds("mcp_service", localItems, [predicate])
      )
    )
      .then((results) => {
        if (cancelled) return;
        setMatchedSearchTagIds(
          new Set(results.flatMap((result) => result.matched_resource_ids ?? []))
        );
      })
      .catch(() => {
        if (cancelled) return;
        setMatchedSearchTagIds(new Set());
      });
    return () => {
      cancelled = true;
    };
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
    setPage(1);
  }, [search, tag, deploymentType, tagPredicates]);

  const firstPageSize = MINE_PAGE_SIZE - 1;

  const pagedItems = useMemo(() => {
    if (filteredItems.length === 0) return [];
    if (page === 1) {
      return filteredItems.slice(0, firstPageSize);
    }
    const start = firstPageSize + (page - 2) * MINE_PAGE_SIZE;
    return filteredItems.slice(start, start + MINE_PAGE_SIZE);
  }, [filteredItems, page]);

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

function getDeduplicatedMineItems(
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

function getMineItemKey(item: MineMcpCardItem): string {
  return item.kind === "local"
    ? `local-${item.service.mcpId}`
    : `community-${item.service.communityId || item.service.name}`;
}

function toMcpContainerConfigPayload(
  value?: Record<string, unknown>
): McpContainerConfigPayload | undefined {
  if (!value || typeof value.mcpServers !== "object" || !value.mcpServers) {
    return undefined;
  }
  return value as unknown as McpContainerConfigPayload;
}

function resolveOnlineService(
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

function ReviewCenterView({
  browser,
  actions,
  onSelect,
  onReviewed,
}: {
  browser: ReturnType<typeof useMcpCommunityReview>;
  actions: React.ReactNode;
  onSelect: (service: CommunityMcpCard) => void;
  onReviewed: () => Promise<void>;
}) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [reviewingId, setReviewingId] = useState<number | null>(null);
  const [confirmAction, setConfirmAction] =
    useState<McpRepositoryReviewAction | null>(null);
  const [confirmService, setConfirmService] = useState<CommunityMcpCard | null>(
    null
  );

  const openReviewConfirm = (
    service: CommunityMcpCard,
    action: McpRepositoryReviewAction
  ) => {
    setConfirmService(service);
    setConfirmAction(action);
  };

  const handleReviewConfirm = async (content?: string) => {
    if (!confirmService?.reviewId || !confirmAction) return;
    setReviewingId(confirmService.reviewId);
    try {
      if (confirmAction === "approve") {
        await approveCommunityMcpTool(confirmService.reviewId, content);
        message.success(
          t("repository.review.approveSuccess", { name: confirmService.name })
        );
      } else {
        await rejectCommunityMcpTool(confirmService.reviewId, content);
        message.success(
          t("repository.review.rejectSuccess", { name: confirmService.name })
        );
      }
      setConfirmAction(null);
      setConfirmService(null);
      await onReviewed();
    } catch {
      message.error(t("repository.review.actionFailed"));
      throw new Error("Review action failed");
    } finally {
      setReviewingId(null);
    }
  };

  return (
    <div className="space-y-4">
      {browser.loading ? (
        <PlaceholderBox>
          <Spin />
        </PlaceholderBox>
      ) : browser.services.length === 0 ? (
        <PlaceholderBox>
          <Empty description={t("repository.review.empty")} />
        </PlaceholderBox>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/80">
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("repository.review.column.name")}
                </th>
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("repository.review.column.deploymentType")}
                </th>
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("repository.review.column.submitter")}
                </th>
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("repository.review.column.listingNote")}
                </th>
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("repository.review.column.status")}
                </th>
                <th className="px-5 py-3.5 text-right text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("repository.review.column.actions")}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {browser.services.map((service) => (
                <ReviewTableRow
                  key={service.reviewId || service.communityId || service.name}
                  service={service}
                  reviewing={reviewingId === service.reviewId}
                  onSelect={() => onSelect(service)}
                  onApprove={() => openReviewConfirm(service, "approve")}
                  onReject={() => openReviewConfirm(service, "reject")}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <McpToolsPagination
        mode="cursor"
        page={browser.page}
        resultCount={browser.services.length}
        hasPrevPage={browser.hasPrevPage}
        hasNextPage={browser.hasNextPage}
        onPrevPage={browser.prevPage}
        onNextPage={browser.nextPage}
      />

      <McpRepositoryReviewConfirmModal
        open={Boolean(confirmAction && confirmService)}
        action={confirmAction}
        service={confirmService}
        loading={
          confirmService?.reviewId != null &&
          reviewingId === confirmService.reviewId
        }
        onClose={() => {
          setConfirmAction(null);
          setConfirmService(null);
        }}
        onConfirm={handleReviewConfirm}
      />
    </div>
  );
}

function ReviewTableRow({
  service,
  reviewing,
  onSelect,
  onApprove,
  onReject,
}: {
  service: CommunityMcpCard;
  reviewing: boolean;
  onSelect: () => void;
  onApprove: () => void;
  onReject: () => void;
}) {
  const { t } = useTranslation("common");
  const deploymentType = resolveDeploymentType(service);
  const deploymentLabel = t(getDeploymentTypeLabelKey(deploymentType));
  const reviewStatus = service.reviewStatus || "pending";
  const isPending = reviewStatus === "pending";
  const author = service.authorDisplayName || service.authorName || "-";
  const submitDate = formatRegistryDate(service.createdAt || "");
  const listingNote = service.content?.trim() || "—";

  const statusBadge = (() => {
    if (reviewStatus === "approved") {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2.5 py-0.5 text-xs font-medium text-green-700">
          <CheckCircle className="h-3 w-3" />
          {t("repository.review.status.approved")}
        </span>
      );
    }
    if (reviewStatus === "rejected") {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-medium text-red-700">
          <XCircle className="h-3 w-3" />
          {t("repository.review.status.rejected")}
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-700">
        <Clock className="h-3 w-3" />
        {t("repository.review.status.pending")}
      </span>
    );
  })();

  return (
    <tr className="group transition hover:bg-slate-50/60">
      {/* MCP Service */}
      <td className="px-5 py-4">
        <div className="flex items-center gap-3">
          <TransportIcon
            transportType={service.transportType}
            deploymentType={deploymentType}
            label={deploymentLabel}
            seed={service.name}
            className="!h-9 !w-9 rounded-lg"
          />
          <div className="min-w-0">
            <div className="text-sm font-medium text-slate-900">
              {service.name}
            </div>
          </div>
        </div>
      </td>

      {/* Deployment Type */}
      <td className="px-5 py-4">
        <span className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-600">
          {deploymentLabel}
        </span>
      </td>

      {/* Submitter */}
      <td className="px-5 py-4">
        <div className="text-sm text-slate-600">{author}</div>
        <div className="mt-0.5 text-xs text-slate-400">{submitDate}</div>
      </td>

      {/* Listing note */}
      <td className="px-5 py-4">
        <span
          className="line-clamp-2 max-w-[220px] text-sm text-slate-600"
          title={listingNote === "—" ? undefined : listingNote}
        >
          {listingNote}
        </span>
      </td>

      {/* Status */}
      <td className="px-5 py-4">{statusBadge}</td>

      {/* Actions */}
      <td className="px-5 py-4 text-right">
        {isPending ? (
          <div className="inline-flex items-center gap-2">
            <Button
              size="small"
              className="text-xs"
              icon={<Eye className="h-3.5 w-3.5" />}
              onClick={onSelect}
            >
              {t("repository.review.details")}
            </Button>
            <Button
              className="!border-green-600 !bg-green-600 text-white hover:!border-green-700 hover:!bg-green-700 !text-white"
              size="small"
              icon={<CheckCircle className="h-3.5 w-3.5" />}
              loading={reviewing}
              onClick={onApprove}
            >
              {t("repository.review.approve")}
            </Button>
            <Button
              danger
              size="small"
              className="text-xs"
              icon={<XCircle className="h-3.5 w-3.5" />}
              loading={reviewing}
              onClick={onReject}
            >
              {t("repository.review.reject")}
            </Button>
          </div>
        ) : (
          <Button
            size="small"
            className="text-xs"
            icon={<Eye className="h-3.5 w-3.5" />}
            onClick={onSelect}
          >
            {t("repository.review.details")}
          </Button>
        )}
      </td>
    </tr>
  );
}

function ResponsiveCardGrid({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {children}
    </div>
  );
}

function PlaceholderBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-center rounded-xl border border-dashed border-slate-200 px-6 py-16 text-center text-slate-500 dark:border-slate-700">
      {children}
    </div>
  );
}
