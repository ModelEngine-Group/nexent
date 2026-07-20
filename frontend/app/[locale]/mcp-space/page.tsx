"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { App, Button, ConfigProvider, Empty, Modal, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { CheckCircle, ChevronLeft, ChevronRight, Clock, CloudUpload, Download, Eye, Inbox, Plus, Puzzle, ShieldCheck, User, XCircle } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
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
  refreshMcpToolCount,
  rejectCommunityMcpTool,
  updateCommunityMcpTool,
} from "@/services/mcpToolsService";
import type {
  CommunityMcpCard,
  McpContainerConfigPayload,
  McpServiceItem,
  McpTagStat,
} from "@/types/mcpTools";
import {
  FILTER_ALL,
  McpDeploymentType,
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
import AddMcpServiceCard from "./components/AddMcpServiceCard";
import CommunityQuickAddModal from "./components/add/community/CommunityQuickAddModal";
import McpCommunityDetailModal from "./components/add/community/McpCommunityDetailModal";
import McpServiceDetailModal from "./components/McpServiceDetailModal";
import McpToolsPagination from "./components/McpToolsPagination";
import McpToolsSearchFilterBar from "./components/McpToolsSearchFilterBar";
import MineMcpServiceCard, {
  type MineMcpCardItem,
} from "./components/MineMcpServiceCard";
import MineMcpReviewStatusModal from "./components/MineMcpReviewStatusModal";
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
  return [
    {
      value: FILTER_ALL,
      label: t("mcpTools.deploymentType.all"),
      count: items.length,
    },
    ...deploymentCategories.map((deploymentType) => ({
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
  const isAdmin = useMemo(
    () => user?.role === USER_ROLES.ADMIN || user?.role === USER_ROLES.SU,
    [user?.role]
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
  const [selectedReview, setSelectedReview] =
    useState<CommunityMcpCard | null>(null);
  const [selectedPublished, setSelectedPublished] =
    useState<CommunityMcpCard | null>(null);

  const localList = useMcpServicesList();
  const myPublished = useMyCommunityMcp(tab === McpToolsServicesTab.MINE);
  const repositoryBrowser = useMcpCommunityBrowser(
    tab === McpToolsServicesTab.REPOSITORY
  );
  const reviewBrowser = useMcpCommunityReview(isAdmin);
  const quickAdd = useMcpCommunityQuickAdd({
    onSuccess: () => setShowAddModal(false),
  });
  const isRepositoryInstalled = useCallback((service: CommunityMcpCard) => {
    return localList.services.some((localService) => {
      if (localService.permission !== "EDIT") return false;
      if (
        service.communityId &&
        localService.communityId === service.communityId
      )
        return true;
      return localService.name === service.name;
    });
  }, [localList.services]);
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

  const searchActions = tab === McpToolsServicesTab.MINE ? (
    <Button
      type="primary"
      className="flex h-11 shrink-0 items-center gap-1.5"
      icon={<Plus className="size-4" />}
      onClick={openAddModal}
    >
      添加 MCP
    </Button>
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

              <Tabs value={tab} onValueChange={(value) => setTab(value as McpToolsServicesTab)} className="w-full">
                <TabsList className={cn("mb-6 grid h-auto w-full gap-2 rounded-xl border border-border bg-secondary/60 px-2 py-2", isAdmin ? "grid-cols-3" : "grid-cols-2")}>
                  <TabsTrigger value={McpToolsServicesTab.REPOSITORY} className="w-full justify-center gap-1.5 rounded-lg px-[5px] py-2 text-sm data-[state=active]:shadow-sm">
                    <Inbox className="size-4" aria-hidden />
                    {t("mcpTools.page.tab.repository")}
                    <span className="ml-1 rounded-md bg-background/70 px-1.5 text-xs text-muted-foreground">{repositoryCount}</span>
                  </TabsTrigger>
                  <TabsTrigger value={McpToolsServicesTab.MINE} className="w-full justify-center gap-1.5 rounded-lg px-[5px] py-2 text-sm data-[state=active]:shadow-sm">
                    <User className="size-4" aria-hidden />
                    {t("mcpTools.page.tab.mine")}
                    <span className="ml-1 rounded-md bg-background/70 px-1.5 text-xs text-muted-foreground">{mineCount}</span>
                  </TabsTrigger>
                  {isAdmin ? (
                    <TabsTrigger value={McpToolsServicesTab.REVIEW} className="w-full justify-center gap-1.5 rounded-lg px-[5px] py-2 text-sm data-[state=active]:shadow-sm">
                      <ShieldCheck className="size-4" aria-hidden />
                      {t("mcpTools.page.tab.review")}
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

  const categoryStats = useMemo(
    () => getDeploymentCategoryStats(browser.services, t),
    [browser.services, t]
  );

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
        deploymentType={deploymentType}
        categoryStats={categoryStats}
        actions={actions}
        onSearchChange={(value) => browser.updateFilter("search", value)}
        onDeploymentTypeChange={setDeploymentType}
      />

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
          mode="cursor"
          page={browser.page}
          resultCount={filteredServices.length}
          hasPrevPage={browser.hasPrevPage}
          hasNextPage={browser.hasNextPage}
          onPrevPage={browser.prevPage}
          onNextPage={browser.nextPage}
        />
      ) : null}
    </div>
  );
}

function MineView({
  localList,
  myPublished,
  actions,
  onAdd,
  onEditLocal,
  onEditCommunity,
  onToggled,
}: {
  localList: ReturnType<typeof useMcpServicesList>;
  myPublished: ReturnType<typeof useMyCommunityMcp>;
  actions: React.ReactNode;
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
  const [page, setPage] = useState(1);
  const [publishingKey, setPublishingKey] = useState<string | null>(null);
  const [unpublishingKey, setUnpublishingKey] = useState<string | null>(null);
  const [refreshingMineKey, setRefreshingMineKey] = useState<string | null>(null);
  const [reviewProgressItem, setReviewProgressItem] = useState<{
    item: MineMcpCardItem;
    onlineService?: CommunityMcpCard;
  } | null>(null);

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

  const categoryStats = useMemo(
    () =>
      getDeploymentCategoryStats(
        items.map((item) => item.service),
        t
      ),
    [items, t]
  );

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      const service = item.service;
      if (!matchesNameOrTag(service, search)) return false;
      if (tag !== FILTER_ALL && !(service.tags || []).includes(tag))
        return false;
      if (
        deploymentType !== FILTER_ALL &&
        resolveDeploymentType(service) !== deploymentType
      )
        return false;
      return true;
    });
  }, [items, search, tag, deploymentType]);

  useEffect(() => {
    setPage(1);
  }, [search, tag, deploymentType]);

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
    await Promise.all([localList.refetch(), myPublished.refetch()]);
  };

  const handleSubmitVersionUpdate = (
    item: MineMcpCardItem,
    onlineService?: CommunityMcpCard
  ) => {
    if (item.kind === "community") {
      // Community items: submit directly
      doSubmitVersionUpdate(item, onlineService);
      return;
    }
    // Local items: confirm first
    modal.confirm({
      title: t("mcpTools.mine.applyForListing"),
      content: t("mcpTools.mine.confirmApplyListing", {
        name: item.service.name,
      }),
      okText: t("mcpTools.mine.applyForListing"),
      cancelText: t("common.cancel"),
      centered: true,
      onOk: () => doSubmitVersionUpdate(item, onlineService),
    });
  };

  const doSubmitVersionUpdate = async (
    item: MineMcpCardItem,
    onlineService?: CommunityMcpCard
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
        });
      }
      message.success(t("mcpTools.mine.submitVersionUpdateSuccess"));
      // Optimistically update local cache to show pending status
      updateLocalReviewStatus(item, "pending");
      await refreshMineData();
    } catch {
      message.error(t("mcpTools.mine.submitVersionUpdateFailed"));
    } finally {
      setPublishingKey(null);
    }
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
      title: isPendingReview ? "确认撤回审核？" : t("mcpTools.mine.unpublishOnlineVersionTitle"),
      content: isPendingReview
        ? t("mcpTools.mine.reviewModal.cancelApply")
        : t("mcpTools.mine.unpublishOnlineVersionDescription", {
            name: onlineService.name || item.service.name,
          }),
      okText: isPendingReview ? t("mcpTools.mine.reviewModal.cancelApply") : t("mcpTools.mine.unpublishOnlineVersion"),
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
              ? t("mcpTools.mine.cancelApplySuccess")
              : t("mcpTools.mine.unpublishOnlineVersionSuccess")
          );
          await refreshMineData();
        } catch {
          message.error(
            isPendingReview
              ? t("mcpTools.mine.cancelApplyFailed")
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
      okText: t("mcpTools.mine.delete"),
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
          message.success(t("mcpTools.mine.deleteSuccess"));
          await refreshMineData();
          // Force-refresh all caches the agent config page relies on
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: MCP_SERVERS_QUERY_KEY }),
            queryClient.invalidateQueries({ queryKey: ["tools"] }),
            queryClient.invalidateQueries({ queryKey: ["agents"] }),
            queryClient.refetchQueries({ queryKey: MCP_SERVERS_QUERY_KEY, type: 'all' }),
          ]);
        } catch {
          message.error(t("mcpTools.mine.deleteFailed"));
        }
      },
    });
  };

  const handleRefreshToolCount = async (item: MineMcpCardItem) => {
    if (item.kind !== "local") return;
    const key = getMineItemKey(item);
    setRefreshingMineKey(key);
    try {
      await refreshMcpToolCount(item.service.mcpId);
      message.success(t("mcpTools.mine.refreshToolCountSuccess"));
      await refreshMineData();
    } catch {
      message.error(t("mcpTools.mine.refreshToolCountFailed"));
    } finally {
      setRefreshingMineKey(null);
    }
  };

  const handleCancelApply = async (
    item: MineMcpCardItem,
    onlineService?: CommunityMcpCard
  ) => {
    const communityRecord = item.kind === "community" ? item.service : onlineService;
    const reviewId = communityRecord?.reviewId;
    if (!reviewId) return;
    try {
      await cancelCommunityMcpReview(reviewId);
      message.success(t("mcpTools.mine.cancelApplySuccess"));
      setReviewProgressItem(null);
      await refreshMineData();
    } catch {
      message.error(t("mcpTools.mine.cancelApplyFailed"));
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
        onSearchChange={setSearch}
        onDeploymentTypeChange={setDeploymentType}
      />

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
                refreshingToolCount={refreshingMineKey === key}
                onEditLocal={onEditLocal}
                onEditCommunity={onEditCommunity}
                onToggle={handleToggle}
                onSubmitVersionUpdate={handleSubmitVersionUpdate}
                onUnpublishOnline={handleUnpublishOnline}
                onDelete={handleDelete}
                onViewReviewProgress={(item, os) =>
                  setReviewProgressItem({ item, onlineService: os })
                }
                onRefreshToolCount={handleRefreshToolCount}
              />
            );
          })}
        </ResponsiveCardGrid>
      )}

      {(() => {
        const remainingItems = Math.max(0, filteredItems.length - firstPageSize);
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
    if (marketService?.sourceMcpId == null || marketService.sourceMcpId === service.mcpId) {
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
  const [statusFilter, setStatusFilter] = useState<string>(FILTER_ALL);
  const [reviewingId, setReviewingId] = useState<number | null>(null);

  const statusTabs = useMemo(() => {
    const items = browser.services;
    const counts: Record<string, number> = {};
    for (const s of items) {
      const st = s.reviewStatus || "pending";
      counts[st] = (counts[st] || 0) + 1;
    }
    return [
      { value: FILTER_ALL, label: t("mcpTools.review.status.all"), count: items.length },
      { value: "pending", label: t("mcpTools.review.status.pending"), count: counts.pending || 0 },
      { value: "approved", label: t("mcpTools.review.status.approved"), count: counts.approved || 0 },
      { value: "rejected", label: t("mcpTools.review.status.rejected"), count: counts.rejected || 0 },
    ];
  }, [browser.services, t]);

  const filteredServices = useMemo(() => {
    if (statusFilter === FILTER_ALL) return browser.services;
    return browser.services.filter((s) => (s.reviewStatus || "pending") === statusFilter);
  }, [browser.services, statusFilter]);

  const handleReview = async (
    service: CommunityMcpCard,
    action: "approve" | "reject"
  ) => {
    if (!service.reviewId) return;
    setReviewingId(service.reviewId);
    try {
      if (action === "approve") {
        await approveCommunityMcpTool(service.reviewId);
        message.success(t("mcpTools.review.approveSuccess"));
      } else {
        await rejectCommunityMcpTool(service.reviewId);
        message.success(t("mcpTools.review.rejectSuccess"));
      }
      await onReviewed();
    } catch {
      message.error(t("mcpTools.review.actionFailed"));
    } finally {
      setReviewingId(null);
    }
  };

  return (
    <div className="space-y-4">
      <McpToolsSearchFilterBar
        search={browser.filters.search}
        actions={actions}
        onSearchChange={(value) => browser.updateFilter("search", value)}
        filterTabs={statusTabs}
        activeFilterTab={statusFilter}
        onFilterTabChange={(value) => setStatusFilter(value)}
      />

      {browser.loading ? (
        <PlaceholderBox>
          <Spin />
        </PlaceholderBox>
      ) : filteredServices.length === 0 ? (
        <PlaceholderBox>
          <Empty description={t("mcpTools.review.emptyTitle")} />
        </PlaceholderBox>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/80">
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("mcpTools.review.table.mcpService")}
                </th>
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("mcpTools.review.table.deploymentType")}
                </th>
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("mcpTools.review.table.submitter")}
                </th>
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("mcpTools.review.table.status")}
                </th>
                <th className="px-5 py-3.5 text-right text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {t("mcpTools.review.table.actions")}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filteredServices.map((service) => (
                <ReviewTableRow
                  key={service.reviewId || service.communityId || service.name}
                  service={service}
                  reviewing={reviewingId === service.reviewId}
                  onSelect={() => onSelect(service)}
                  onApprove={() => handleReview(service, "approve")}
                  onReject={() => handleReview(service, "reject")}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <McpToolsPagination
        mode="cursor"
        page={browser.page}
        resultCount={filteredServices.length}
        hasPrevPage={browser.hasPrevPage}
        hasNextPage={browser.hasNextPage}
        onPrevPage={browser.prevPage}
        onNextPage={browser.nextPage}
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
  const author =
    service.authorDisplayName || service.authorName || "-";
  const submitDate = formatRegistryDate(service.createdAt || "");

  const statusBadge = (() => {
    if (reviewStatus === "approved") {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2.5 py-0.5 text-xs font-medium text-green-700">
          <CheckCircle className="h-3 w-3" />
          {t("mcpTools.review.status.approved")}
        </span>
      );
    }
    if (reviewStatus === "rejected") {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-medium text-red-700">
          <XCircle className="h-3 w-3" />
          {t("mcpTools.review.status.rejected")}
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-700">
        <Clock className="h-3 w-3" />
        {t("mcpTools.review.status.pending")}
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
              {t("mcpTools.review.details")}
            </Button>
            <Button
              className="!border-green-600 !bg-green-600 text-white hover:!border-green-700 hover:!bg-green-700 !text-white"
              size="small"
              icon={<CheckCircle className="h-3.5 w-3.5" />}
              loading={reviewing}
              onClick={onApprove}
            >
              {t("mcpTools.review.approve")}
            </Button>
            <Button
              danger
              size="small"
              className="text-xs"
              icon={<XCircle className="h-3.5 w-3.5" />}
              loading={reviewing}
              onClick={onReject}
            >
              {t("mcpTools.review.reject")}
            </Button>
          </div>
        ) : (
          <Button
            size="small"
            className="text-xs"
            icon={<Eye className="h-3.5 w-3.5" />}
            onClick={onSelect}
          >
            {t("mcpTools.review.details")}
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
