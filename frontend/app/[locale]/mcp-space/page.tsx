"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { App, Button, ConfigProvider, Empty, Modal, Segmented, Spin, Steps, Tag, type StepsProps } from "antd";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import {
  CloudUploadOutlined,
  InboxOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { CheckCircle, Clock, Download, Eye, Plus, Puzzle, XCircle } from "lucide-react";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { useMcpServicesList } from "@/hooks/mcpTools/useMcpServicesList";
import { useMyCommunityMcp } from "@/hooks/mcpTools/useMyCommunityMcp";
import { useMcpCommunityBrowser } from "@/hooks/mcpTools/useMcpCommunityBrowser";
import { useMcpCommunityReview } from "@/hooks/mcpTools/useMcpCommunityReview";
import { useMcpCommunityQuickAdd } from "@/hooks/mcpTools/useMcpCommunityQuickAdd";
import { useMcpServiceToggle } from "@/hooks/mcpTools/useMcpServiceToggle";
import {
  approveCommunityMcpTool,
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
  McpSource,
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
import CommunityQuickAddModal from "./components/add/community/CommunityQuickAddModal";
import McpCommunityDetailModal from "./components/add/community/McpCommunityDetailModal";
import McpServiceDetailModal from "./components/McpServiceDetailModal";
import McpToolsPagination from "./components/McpToolsPagination";
import McpToolsSearchFilterBar from "./components/McpToolsSearchFilterBar";
import MineMcpServiceCard, {
  type MineMcpCardItem,
} from "./components/MineMcpServiceCard";
import PublishedServiceDetailModal from "./components/PublishedServiceDetailModal";
import RepositoryMcpCard from "./components/RepositoryMcpCard";
import RepositoryMcpDetailModal from "./components/RepositoryMcpDetailModal";
import TransportIcon from "./components/shared/TransportIcon";

const mcpToolsTheme = {
  token: { colorPrimary: "#2563eb", colorInfo: "#0284c7" },
};

const MINE_PAGE_SIZE = 12;
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
  const [addModalInitialTab, setAddModalInitialTab] = useState<McpSource>(
    McpSource.LOCAL
  );
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
  const reviewBrowser = useMcpCommunityReview(
    tab === McpToolsServicesTab.REVIEW && isAdmin
  );
  const quickAdd = useMcpCommunityQuickAdd({
    onSuccess: () => setShowAddModal(false),
  });
  const isRepositoryInstalled = useCallback((service: CommunityMcpCard) => {
    return localList.services.some((localService) => {
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
    setAddModalInitialTab(McpSource.LOCAL);
    setShowAddModal(true);
  };

  const openImportModal = () => {
    setAddModalInitialTab(McpSource.REGISTRY);
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
  const reviewCount = reviewBrowser.services.length;

  const searchActions = tab === McpToolsServicesTab.MINE ? (
    <>
      <Button
        icon={<Download className="h-4 w-4" />}
        onClick={openImportModal}
        className="h-10 rounded-xl px-4 font-medium"
      >
        {t("mcpTools.page.importService")}
      </Button>
      <Button
        type="primary"
        icon={<Plus className="h-4 w-4" />}
        onClick={openAddModal}
        className="h-10 rounded-xl px-4 font-semibold shadow-sm"
      >
        {t("mcpTools.page.addService")}
      </Button>
    </>
  ) : null;

  const userTabOptions = [
    {
      value: McpToolsServicesTab.REPOSITORY,
      label: (
        <span className="inline-flex h-full w-full items-center justify-center gap-1.5 text-sm">
          <InboxOutlined className="text-sm" aria-hidden />
          <span>{t("mcpTools.page.tab.repository")}</span>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            {repositoryCount}
          </span>
        </span>
      ),
    },
    {
      value: McpToolsServicesTab.MINE,
      label: (
        <span className="inline-flex h-full w-full items-center justify-center gap-1.5 text-sm">
          <CloudUploadOutlined className="text-sm" aria-hidden />
          <span>{t("mcpTools.page.tab.mine")}</span>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            {mineCount}
          </span>
        </span>
      ),
    },
  ];

  const adminTabOptions = [
    ...userTabOptions,
    {
      value: McpToolsServicesTab.REVIEW,
      label: (
        <span className="inline-flex h-full w-full items-center justify-center gap-1.5 text-sm">
          <SafetyCertificateOutlined className="text-sm" aria-hidden />
          <span>{t("mcpTools.page.tab.review")}</span>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            {reviewCount}
          </span>
        </span>
      ),
    },
  ];

  const tabOptions = isAdmin ? adminTabOptions : userTabOptions;

  return (
    <ConfigProvider theme={mcpToolsTheme}>
      <div className="flex h-full min-h-0 w-full min-w-0 flex-col bg-slate-50/40">
        <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]">
          <motion.div
            initial="initial"
            animate="in"
            exit="out"
            variants={pageVariants}
            transition={pageTransition}
            className="mx-auto w-full max-w-7xl px-6 py-8"
          >
            <div className="flex flex-col gap-6">
              <motion.div
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
                className="overflow-hidden rounded-3xl border border-blue-100 bg-gradient-to-br from-blue-50 via-white to-sky-50 p-6 shadow-sm"
              >
                <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                  <div className="flex min-w-0 items-center gap-4">
                    <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-sky-600 shadow-lg shadow-blue-900/10">
                      <Puzzle className="h-7 w-7 text-white" />
                    </div>
                    <div className="min-w-0">
                      <h1 className="text-3xl font-bold text-blue-800 dark:text-blue-400">
                        {t("mcpTools.page.title")}
                      </h1>
                      <p className="mt-1 max-w-2xl text-sm text-slate-600 dark:text-slate-300">
                        {t("mcpTools.page.subtitle")}
                      </p>
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-col items-start gap-2 sm:items-end">
                    <Tag
                      color="blue"
                      className="m-0 rounded-full px-3 py-1 text-sm"
                    >
                      {isAdmin
                        ? t("mcpTools.page.role.admin")
                        : t("mcpTools.page.role.user")}
                    </Tag>
                    <span className="text-xs text-slate-500">
                      {isAdmin
                        ? t("mcpTools.page.role.adminHint")
                        : t("mcpTools.page.role.userHint")}
                    </span>
                  </div>
                </div>
              </motion.div>

              <div className="rounded-2xl border border-slate-200 bg-white p-[3px] shadow-sm">
                <Segmented
                  block
                  value={tab}
                  onChange={(value) => setTab(value as McpToolsServicesTab)}
                  options={tabOptions}
                  className="h-11 w-full rounded-xl bg-transparent text-sm [&_.ant-segmented-group]:h-full [&_.ant-segmented-item]:flex-1 [&_.ant-segmented-item]:rounded-lg [&_.ant-segmented-item-label]:flex [&_.ant-segmented-item-label]:h-full [&_.ant-segmented-item-label]:items-center [&_.ant-segmented-item-label]:justify-center [&_.ant-segmented-item-label]:px-4 [&_.ant-segmented-item-label]:text-sm [&_.ant-segmented-item-selected]:text-blue-700 [&_.ant-segmented-thumb]:rounded-lg [&_.ant-segmented-thumb]:bg-blue-50 [&_.ant-segmented-thumb]:shadow-sm"
                />
              </div>

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
                initialTab={addModalInitialTab}
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

function MineView({
  localList,
  myPublished,
  actions,
  onEditLocal,
  onEditCommunity,
  onToggled,
}: {
  localList: ReturnType<typeof useMcpServicesList>;
  myPublished: ReturnType<typeof useMyCommunityMcp>;
  actions: React.ReactNode;
  onEditLocal: (service: McpServiceItem) => void;
  onEditCommunity: (service: CommunityMcpCard) => void;
  onToggled: (mcpId: number) => Promise<void>;
}) {
  const { t } = useTranslation("common");
  const { message, modal } = App.useApp();
  const toggle = useMcpServiceToggle();
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

  const pagedItems = paginateItems(filteredItems, page, MINE_PAGE_SIZE);
  const loading = localList.loading || myPublished.loading;

  const handleToggle = async (service: McpServiceItem) => {
    await toggle.toggle(service);
    await onToggled(service.mcpId);
  };

  const refreshMineData = async () => {
    await Promise.all([localList.refetch(), myPublished.refetch()]);
  };

  const handleSubmitVersionUpdate = async (
    item: MineMcpCardItem,
    onlineService?: CommunityMcpCard
  ) => {
    const key = getMineItemKey(item);
    setPublishingKey(key);
    try {
      if (item.kind === "community") {
        const service = item.service;
        if (!service.marketId && !service.communityId) return;
        await updateCommunityMcpTool({
          market_id: service.marketId || service.communityId!,
          name: service.name.trim(),
          description: (service.description || "").trim(),
          version: (service.version || "").trim(),
          tags: service.tags || [],
          registry_json: service.registryJson,
        });
      } else if (onlineService?.marketId || onlineService?.communityId) {
        const service = item.service;
        const configJson = toMcpContainerConfigPayload(service.configJson);
        await updateCommunityMcpTool({
          market_id: onlineService.marketId || onlineService.communityId!,
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
      await refreshMineData();
    } catch {
      message.error(t("mcpTools.mine.submitVersionUpdateFailed"));
    } finally {
      setPublishingKey(null);
    }
  };

  const handleUnpublishOnline = (
    item: MineMcpCardItem,
    onlineService: CommunityMcpCard
  ) => {
    if (!onlineService.communityId) return;
    modal.confirm({
      title: t("mcpTools.mine.unpublishOnlineVersionTitle"),
      content: t("mcpTools.mine.unpublishOnlineVersionDescription", {
        name: onlineService.name || item.service.name,
      }),
      okText: t("mcpTools.mine.unpublishOnlineVersion"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      centered: true,
      onOk: async () => {
        const key = getMineItemKey(item);
        setUnpublishingKey(key);
        try {
          await deleteCommunityMcpTool(onlineService.communityId!);
          message.success(t("mcpTools.mine.unpublishOnlineVersionSuccess"));
          await refreshMineData();
        } catch {
          message.error(t("mcpTools.mine.unpublishOnlineVersionFailed"));
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
        <PlaceholderBox>
          <Empty description={t("mcpTools.mine.empty")} />
        </PlaceholderBox>
      ) : (
        <ResponsiveCardGrid>
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

      <McpToolsPagination
        mode="offset"
        current={page}
        pageSize={MINE_PAGE_SIZE}
        total={filteredItems.length}
        onChange={setPage}
      />

      <ReviewProgressModal
        item={reviewProgressItem}
        onClose={() => setReviewProgressItem(null)}
        t={t}
      />
    </div>
  );
}

function ReviewProgressModal({
  item,
  onClose,
  t,
}: {
  item: { item: MineMcpCardItem; onlineService?: CommunityMcpCard } | null;
  onClose: () => void;
  t: (key: string) => string;
}) {
  if (!item) return null;

  const { item: cardItem, onlineService } = item;
  const service = cardItem.service;
  const communityRecord = cardItem.kind === "community" ? cardItem.service : onlineService;
  const reviewStatus = communityRecord?.reviewStatus || "pending";

  const isRejected = reviewStatus === "rejected";
  const isApproved = reviewStatus === "approved";

  const steps: StepsProps["items"] = [
    { title: t("mcpTools.mine.reviewProgressStepSubmitted"), status: "finish" },
    {
      title: isApproved
        ? t("mcpTools.mine.reviewProgressStepApproved")
        : isRejected
          ? t("mcpTools.mine.reviewProgressStepRejected")
          : t("mcpTools.mine.reviewProgressStepReviewing"),
      status: isApproved ? "finish" : isRejected ? "error" : "process",
    },
  ];

  return (
    <Modal
      open
      centered
      width={520}
      footer={null}
      onCancel={onClose}
      closable
    >
      <div className="py-4">
        <h3 className="text-lg font-bold text-slate-900">
          {t("mcpTools.mine.reviewProgressTitle")}
        </h3>

        <div className="mt-4 space-y-2 text-sm text-slate-600">
          <p>
            <span className="font-medium text-slate-700">
              {t("mcpTools.mine.reviewProgressService")}:
            </span>{" "}
            {service.name}
          </p>
        </div>

        <div className="mt-6">
          <Steps
            direction="vertical"
            status={isRejected ? "error" : isApproved ? "finish" : "process"}
            items={steps}
          />
        </div>
      </div>
    </Modal>
  );
}

function getDeduplicatedMineItems(
  localServices: McpServiceItem[],
  publishedServices: CommunityMcpCard[]
): MineMcpCardItem[] {
  const linkedCommunityIds = new Set<number>();
  const linkedSourceMcpIds = new Set<number>();
  const localNames = new Set<string>();

  for (const service of localServices) {
    if (service.communityId) linkedCommunityIds.add(service.communityId);
    linkedSourceMcpIds.add(service.mcpId);
    localNames.add(normalizeMcpName(service.name));
  }

  const visiblePublishedServices = publishedServices.filter((service) => {
    if (service.sourceMcpId != null && linkedSourceMcpIds.has(service.sourceMcpId)) {
      return false;
    }
    if (service.communityId && linkedCommunityIds.has(service.communityId)) {
      return false;
    }
    return !localNames.has(normalizeMcpName(service.name));
  });

  return [
    ...localServices.map((service) => ({
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
  const reviewType = service.reviewType || "initial_listing";
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
            <div className="mt-0.5 flex items-center gap-1.5 text-xs">
              {reviewType === "version_update" ? (
                <span className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-600">
                  {t("mcpTools.review.type.version_update")}
                </span>
              ) : (
                <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                  {t("mcpTools.review.type.initial_listing")}
                </span>
              )}
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
    <div
      className="grid gap-4"
      style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}
    >
      {children}
    </div>
  );
}

function PlaceholderBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-3xl border border-dashed border-slate-200 bg-white px-6 py-12 text-center text-slate-500 shadow-sm">
      {children}
    </div>
  );
}
