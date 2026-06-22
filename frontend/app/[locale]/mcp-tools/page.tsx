"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { App, Button, ConfigProvider, Empty, Segmented, Spin, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { CloudUploadOutlined, InboxOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { ClipboardCheck, Download, Plus, Puzzle } from "lucide-react";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { useMcpServicesList } from "@/hooks/mcpTools/useMcpServicesList";
import { useMyCommunityMcp } from "@/hooks/mcpTools/useMyCommunityMcp";
import { useMcpCommunityBrowser } from "@/hooks/mcpTools/useMcpCommunityBrowser";
import { useMcpCommunityQuickAdd } from "@/hooks/mcpTools/useMcpCommunityQuickAdd";
import { useMcpServiceToggle } from "@/hooks/mcpTools/useMcpServiceToggle";
import type { CommunityMcpCard, McpServiceItem, McpTagStat } from "@/types/mcpTools";
import {
  FILTER_ALL,
  McpDeploymentType,
  McpSource,
  McpToolsServicesTab,
} from "@/const/mcpTools";
import {
  filterByDeploymentType,
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
import MineMcpServiceCard, { type MineMcpCardItem } from "./components/MineMcpServiceCard";
import PublishedServiceDetailModal from "./components/PublishedServiceDetailModal";
import RepositoryMcpCard from "./components/RepositoryMcpCard";

const mcpToolsTheme = {
  token: { colorPrimary: "#059669", colorInfo: "#0d9488" },
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
      count: items.filter((item) => resolveDeploymentType(item) === deploymentType).length,
    })),
  ];
}

export default function McpToolsPage() {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { user } = useAuthorizationContext();
  const { pageVariants, pageTransition } = useSetupFlow();
  const isAdmin = useMemo(
    () => user?.role === USER_ROLES.ADMIN || user?.role === USER_ROLES.SU,
    [user?.role]
  );

  const [tab, setTab] = useState<McpToolsServicesTab>(McpToolsServicesTab.REPOSITORY);
  const [showAddModal, setShowAddModal] = useState(false);
  const [addModalInitialTab, setAddModalInitialTab] = useState<McpSource>(McpSource.LOCAL);
  const [selectedLocal, setSelectedLocal] = useState<McpServiceItem | null>(null);
  const [selectedRepository, setSelectedRepository] = useState<CommunityMcpCard | null>(null);
  const [selectedPublished, setSelectedPublished] = useState<CommunityMcpCard | null>(null);

  const localList = useMcpServicesList();
  const myPublished = useMyCommunityMcp(tab === McpToolsServicesTab.MINE);
  const repositoryBrowser = useMcpCommunityBrowser(tab === McpToolsServicesTab.REPOSITORY);
  const quickAdd = useMcpCommunityQuickAdd({ onSuccess: () => setShowAddModal(false) });
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

  const repositoryCount = repositoryBrowser.services.length;
  const mineCount = localList.services.length + myPublished.items.length;
  const reviewCount = 0;

  const searchActions = (
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
  );

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
                className="overflow-hidden rounded-3xl border border-emerald-100 bg-gradient-to-br from-emerald-50 via-white to-cyan-50 p-6 shadow-sm"
              >
                <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                  <div className="flex min-w-0 items-center gap-4">
                    <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 shadow-lg shadow-emerald-900/10">
                      <Puzzle className="h-7 w-7 text-white" />
                    </div>
                    <div className="min-w-0">
                      <h1 className="text-3xl font-bold text-emerald-800 dark:text-emerald-400">
                        {t("mcpTools.page.title")}
                      </h1>
                      <p className="mt-1 max-w-2xl text-sm text-slate-600 dark:text-slate-300">
                        {t("mcpTools.page.subtitle")}
                      </p>
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-col items-start gap-2 sm:items-end">
                    <Tag color={isAdmin ? "green" : "blue"} className="m-0 rounded-full px-3 py-1 text-sm">
                      {isAdmin ? t("mcpTools.page.role.admin") : t("mcpTools.page.role.user")}
                    </Tag>
                    <span className="text-xs text-slate-500">
                      {isAdmin ? t("mcpTools.page.role.adminHint") : t("mcpTools.page.role.userHint")}
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
                  className="h-11 w-full rounded-xl bg-transparent text-sm [&_.ant-segmented-group]:h-full [&_.ant-segmented-item]:flex-1 [&_.ant-segmented-item]:rounded-lg [&_.ant-segmented-item-label]:flex [&_.ant-segmented-item-label]:h-full [&_.ant-segmented-item-label]:items-center [&_.ant-segmented-item-label]:justify-center [&_.ant-segmented-item-label]:px-4 [&_.ant-segmented-item-label]:text-sm [&_.ant-segmented-item-selected]:text-emerald-700 [&_.ant-segmented-thumb]:rounded-lg [&_.ant-segmented-thumb]:bg-emerald-50 [&_.ant-segmented-thumb]:shadow-sm"
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
                  onOffline={() => message.info(t("mcpTools.repository.offlinePending"))}
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
                <ReviewCenterView actions={searchActions} />
              ) : null}

              {selectedLocal ? (
                <McpServiceDetailModal
                  selectedService={selectedLocal}
                  onClose={closeLocalDetail}
                  onToggled={handleToggled}
                />
              ) : null}

              {selectedRepository ? (
                <McpCommunityDetailModal
                  service={selectedRepository}
                  onClose={() => setSelectedRepository(null)}
                  onQuickAdd={quickAdd.open}
                />
              ) : null}

              <PublishedServiceDetailModal
                open={Boolean(selectedPublished)}
                service={selectedPublished}
                onClose={() => setSelectedPublished(null)}
              />

              {quickAdd.visible ? <CommunityQuickAddModal controller={quickAdd} /> : null}

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
  const [deploymentType, setDeploymentType] = useState<DeploymentFilter>(FILTER_ALL);

  const categoryStats = useMemo(
    () => getDeploymentCategoryStats(browser.services, t),
    [browser.services, t]
  );

  const filteredServices = useMemo(() => {
    return filterByDeploymentType(browser.services, deploymentType).filter((item) =>
      matchesNameOrTag(item, browser.filters.search)
    );
  }, [browser.services, browser.filters.search, deploymentType]);

  const isInstalled = (service: CommunityMcpCard) => {
    return localServices.some((localService) => {
      if (service.communityId && localService.communityId === service.communityId) return true;
      return localService.name === service.name;
    });
  };

  return (
    <div className="space-y-4">
      <McpToolsSearchFilterBar
        search={browser.filters.search}
        deploymentType={deploymentType}
        categoryStats={categoryStats}
        actions={(
          <>
            <span className="flex h-10 items-center text-xs text-slate-400">
              {t("mcpTools.page.resultCount", { count: filteredServices.length })}
            </span>
            {actions}
          </>
        )}
        onSearchChange={(value) => browser.updateFilter("search", value)}
        onDeploymentTypeChange={setDeploymentType}
      />

      {browser.loading ? (
        <PlaceholderBox><Spin /></PlaceholderBox>
      ) : filteredServices.length === 0 ? (
        <PlaceholderBox><Empty description={t("mcpTools.repository.empty")} /></PlaceholderBox>
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
  const toggle = useMcpServiceToggle();
  const [search, setSearch] = useState("");
  const [deploymentType, setDeploymentType] = useState<DeploymentFilter>(FILTER_ALL);
  const [tag, setTag] = useState(FILTER_ALL);
  const [page, setPage] = useState(1);

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
    return [
      ...localList.services.map((service) => ({ kind: "local" as const, service })),
      ...myPublished.items.map((service) => ({ kind: "community" as const, service })),
    ];
  }, [localList.services, myPublished.items]);

  const categoryStats = useMemo(
    () => getDeploymentCategoryStats(items.map((item) => item.service), t),
    [items, t]
  );

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      const service = item.service;
      if (!matchesNameOrTag(service, search)) return false;
      if (tag !== FILTER_ALL && !(service.tags || []).includes(tag)) return false;
      if (deploymentType !== FILTER_ALL && resolveDeploymentType(service) !== deploymentType) return false;
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

  return (
    <div className="space-y-4">
      <McpToolsSearchFilterBar
        search={search}
        deploymentType={deploymentType}
        categoryStats={categoryStats}
        actions={(
          <>
            <span className="flex h-10 items-center text-xs text-slate-400">
              {t("mcpTools.page.resultCount", { count: filteredItems.length })}
            </span>
            {actions}
          </>
        )}
        onSearchChange={setSearch}
        onDeploymentTypeChange={setDeploymentType}
      />

      {loading ? (
        <PlaceholderBox><Spin /></PlaceholderBox>
      ) : filteredItems.length === 0 ? (
        <PlaceholderBox><Empty description={t("mcpTools.mine.empty")} /></PlaceholderBox>
      ) : (
        <ResponsiveCardGrid>
          {pagedItems.map((item) => {
            const key = item.kind === "local"
              ? `local-${item.service.mcpId}`
              : `community-${item.service.communityId || item.service.name}`;
            return (
              <MineMcpServiceCard
                key={key}
                item={item}
                toggling={item.kind === "local" ? toggle.isToggling(item.service.mcpId) : false}
                onEditLocal={onEditLocal}
                onEditCommunity={onEditCommunity}
                onToggle={handleToggle}
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
    </div>
  );
}

function ReviewCenterView({ actions }: { actions: React.ReactNode }) {
  const { t } = useTranslation("common");
  const [search, setSearch] = useState("");
  const [deploymentType, setDeploymentType] = useState<DeploymentFilter>(FILTER_ALL);
  const [tag, setTag] = useState(FILTER_ALL);
  const [status, setStatus] = useState(FILTER_ALL);

  return (
    <div className="space-y-4">
      <McpToolsSearchFilterBar
        search={search}
        deploymentType={deploymentType}
        status={status}
        statusOptions={[
          { value: FILTER_ALL, label: t("mcpTools.review.status.all") },
          { value: "pending", label: t("mcpTools.review.status.pending") },
          { value: "approved", label: t("mcpTools.review.status.approved") },
          { value: "rejected", label: t("mcpTools.review.status.rejected") },
        ]}
        actions={actions}
        onSearchChange={setSearch}
        onDeploymentTypeChange={setDeploymentType}
        onStatusChange={setStatus}
      />

      <div className="rounded-3xl border border-dashed border-emerald-200 bg-white p-10 text-center shadow-sm">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-600">
          <ClipboardCheck className="h-7 w-7" />
        </div>
        <h3 className="mt-4 text-lg font-semibold text-slate-900">
          {t("mcpTools.review.emptyTitle")}
        </h3>
        <p className="mx-auto mt-2 max-w-xl text-sm text-slate-500">
          {t("mcpTools.review.pendingIntegration")}
        </p>
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          <Tag color="green" className="rounded-full">{t("mcpTools.review.approve")}</Tag>
          <Tag color="red" className="rounded-full">{t("mcpTools.review.reject")}</Tag>
          <Tag color="blue" className="rounded-full">{t("mcpTools.review.details")}</Tag>
        </div>
      </div>
    </div>
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
