"use client";

import { useRef, useState } from "react";
import { InboxOutlined, CloudUploadOutlined } from "@ant-design/icons";
import { Button, ConfigProvider, Empty, Input, Segmented, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import { Puzzle } from "lucide-react";
import { useMcpServicesList } from "@/hooks/mcpTools/useMcpServicesList";
import { useMyCommunityMcp } from "@/hooks/mcpTools/useMyCommunityMcp";
import type { CommunityMcpCard, McpServiceItem } from "@/types/mcpTools";
import {
  McpServiceStatus,
  McpToolsServicesTab,
} from "@/const/mcpTools";
import AddMcpServiceModal from "./components/add/AddMcpServiceModal";
import McpServiceCard from "./components/McpServiceCard";
import McpServiceDetailModal from "./components/McpServiceDetailModal";
import McpServicesFilterBar from "./components/McpServicesFilterBar";
import PublishedServiceCard from "./components/PublishedServiceCard";
import PublishedServiceDetailModal from "./components/PublishedServiceDetailModal";

/** Scoped Ant Design theme for MCP tools (primary buttons, etc.). Segmented uses default styling. */
const mcpToolsTheme = {
  token: { colorPrimary: "#059669", colorInfo: "#0d9488" },
};

export default function McpToolsPage() {
  const { t } = useTranslation("common");
  const { pageVariants, pageTransition } = useSetupFlow();

  const [tab, setTab] = useState<McpToolsServicesTab>(McpToolsServicesTab.IMPORTED);
  const [showAddModal, setShowAddModal] = useState(false);
  const [selectedImported, setSelectedImported] =
    useState<McpServiceItem | null>(null);
  const [selectedPublished, setSelectedPublished] =
    useState<CommunityMcpCard | null>(null);

  const list = useMcpServicesList();
  const myPublished = useMyCommunityMcp(tab === McpToolsServicesTab.PUBLISHED);

  const handleToggled = async (mcpId: number) => {
    const result = await list.refetch();
    const updated = result.data?.find((s) => s.mcpId === mcpId);
    if (updated && detailMcpIdRef.current === mcpId) {
      setSelectedImported(updated);
    }
  };

  const detailMcpIdRef = useRef<number | null>(null);
  const openDetail = (service: McpServiceItem) => {
    detailMcpIdRef.current = service.mcpId;
    setSelectedImported(service);
  };
  const closeDetail = () => {
    detailMcpIdRef.current = null;
    setSelectedImported(null);
  };

  const handleSelectPublished = (item: CommunityMcpCard) => {
    setSelectedPublished(item);
  };

  const closePublished = () => {
    setSelectedPublished(null);
  };

  const resultCount =
    tab === McpToolsServicesTab.IMPORTED
      ? list.filteredServices.length
      : myPublished.filteredItems.length;

  return (
    <ConfigProvider theme={mcpToolsTheme}>
    <div className="flex h-full min-h-0 w-full min-w-0 flex-col">
      {/*
        Own scroll + scrollbar-gutter on this page only: avoids layout shift when
        tabs change height, without changing global ClientLayout.
      */}
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]">
        <motion.div
          initial="initial"
          animate="in"
          exit="out"
          variants={pageVariants}
          transition={pageTransition}
          className="mx-auto w-full max-w-7xl px-6 py-10"
        >
          <div className="flex flex-col gap-6">
            {/* Title + add service (same row on sm+) */}
            <motion.div
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="mb-1 flex flex-col gap-3 sm:mb-0 sm:flex-row sm:items-end sm:justify-between"
            >
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-emerald-500 to-teal-600 shadow-sm shadow-emerald-900/10">
                  <Puzzle className="h-6 w-6 text-white" />
                </div>
                <div className="min-w-0">
                  <h1 className="text-3xl font-bold text-emerald-700 dark:text-emerald-400">
                    {t("mcpTools.page.title")}
                  </h1>
                  <p className="mt-1 text-slate-600 dark:text-slate-300">
                    {t("mcpTools.page.subtitle")}
                  </p>
                </div>
              </div>
              <Button
                type="primary"
                size="middle"
                onClick={() => setShowAddModal(true)}
                className="w-full shrink-0 rounded-md px-4 font-semibold shadow-sm transition hover:translate-y-[-1px] hover:shadow-md sm:ml-auto sm:w-auto"
              >
                {t("mcpTools.page.addService")}
              </Button>
            </motion.div>

            {/* Tab switch + result count (same row) */}
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
              <Segmented
                value={tab}
                onChange={(value) => setTab(value as McpToolsServicesTab)}
                options={[
                  {
                    value: McpToolsServicesTab.IMPORTED,
                    label: (
                      <span className="inline-flex h-full w-full items-center justify-center gap-1.5 text-sm">
                        <InboxOutlined className="text-sm" aria-hidden />
                        <span>{t("mcpTools.page.tab.imported")}</span>
                      </span>
                    ),
                  },
                  {
                    value: McpToolsServicesTab.PUBLISHED,
                    label: (
                      <span className="inline-flex h-full w-full items-center justify-center gap-1.5 text-sm">
                        <CloudUploadOutlined className="text-sm" aria-hidden />
                        <span>{t("mcpTools.page.tab.published")}</span>
                      </span>
                    ),
                  },
                ]}
                className="h-9 w-full max-w-xs rounded-md border border-slate-200 bg-slate-100 p-[2px] text-sm shadow-sm sm:w-auto [&_.ant-segmented-group]:h-full [&_.ant-segmented-item]:rounded-md [&_.ant-segmented-item-label]:flex [&_.ant-segmented-item-label]:h-full [&_.ant-segmented-item-label]:items-center [&_.ant-segmented-item-label]:px-3 [&_.ant-segmented-item-label]:text-sm [&_.ant-segmented-thumb]:rounded-md [&_.ant-segmented-thumb]:bg-white [&_.ant-segmented-thumb]:shadow-sm [&_.ant-segmented-thumb]:top-[2px] [&_.ant-segmented-thumb]:bottom-[2px]"
              />
              <span className="pb-0.5 text-xs text-slate-400 sm:shrink-0 sm:text-right">
                {t("mcpTools.page.resultCount", { count: resultCount })}
              </span>
            </div>

            {tab === McpToolsServicesTab.IMPORTED ? (
              <ImportedView list={list} onSelect={openDetail} />
            ) : (
              <PublishedView
                myPublished={myPublished}
                onSelect={handleSelectPublished}
              />
            )}

            {selectedImported ? (
              <McpServiceDetailModal
                selectedService={selectedImported}
                onClose={closeDetail}
                onToggled={handleToggled}
              />
            ) : null}

            <PublishedServiceDetailModal
              open={Boolean(selectedPublished)}
              service={selectedPublished}
              onClose={closePublished}
            />

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

type ServicesListController = ReturnType<typeof useMcpServicesList>;

function ImportedView({
  list,
  onSelect,
}: {
  list: ServicesListController;
  onSelect: (service: McpServiceItem) => void;
}) {
  const { t } = useTranslation("common");

  return (
    <>
      <SearchAndFilterRow
        searchValue={list.filters.search}
        onSearchChange={(value) => list.updateFilter("search", value)}
        searchPlaceholder={String(t("mcpTools.page.searchPlaceholder"))}
        filters={
          <McpServicesFilterBar
            source={list.filters.source}
            transport={list.filters.transport}
            tag={list.filters.tag}
            tagStats={list.tagStats}
            onSourceChange={(value) => list.updateFilter("source", value)}
            onTransportChange={(value) => list.updateFilter("transport", value)}
            onTagChange={(value) => list.updateFilter("tag", value)}
          />
        }
      />

      {list.loading ? (
        <PlaceholderBox>{t("mcpTools.page.loading")}</PlaceholderBox>
      ) : list.filteredServices.length === 0 ? (
        <PlaceholderBox>{t("mcpTools.page.empty")}</PlaceholderBox>
      ) : (
        <ResponsiveCardGrid>
          {list.filteredServices.map((service) => (
            <McpServiceCard
              key={`${service.mcpId}`}
              service={service}
              onSelect={onSelect}
            />
          ))}
        </ResponsiveCardGrid>
      )}
    </>
  );
}

function PublishedView({
  myPublished,
  onSelect,
}: {
  myPublished: ReturnType<typeof useMyCommunityMcp>;
  onSelect: (item: CommunityMcpCard) => void;
}) {
  const { t } = useTranslation("common");

  return (
    <>
      <SearchAndFilterRow
        searchValue={myPublished.search}
        onSearchChange={(value) => myPublished.updateFilter("search", value)}
        searchPlaceholder={String(t("mcpTools.community.searchPlaceholder"))}
        filters={
          <McpServicesFilterBar
            transport={myPublished.filters.transport}
            tag={myPublished.filters.tag}
            tagStats={myPublished.tagStats}
            onTransportChange={(value) =>
              myPublished.updateFilter("transport", value)
            }
            onTagChange={(value) => myPublished.updateFilter("tag", value)}
          />
        }
      />

      {myPublished.loading ? (
        <PlaceholderBox>
          <Spin />
        </PlaceholderBox>
      ) : myPublished.filteredItems.length === 0 ? (
        <PlaceholderBox>
          <Empty description={t("mcpTools.community.mine.empty")} />
        </PlaceholderBox>
      ) : (
        <ResponsiveCardGrid>
          {myPublished.filteredItems.map((item) => (
            <PublishedServiceCard
              key={`${item.communityId}-${item.name}`}
              service={item}
              onSelect={onSelect}
            />
          ))}
        </ResponsiveCardGrid>
      )}
    </>
  );
}

function SearchAndFilterRow({
  searchValue,
  onSearchChange,
  searchPlaceholder,
  filters,
}: {
  searchValue: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder: string;
  filters: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
      <Input
        value={searchValue}
        onChange={(event) => onSearchChange(event.target.value)}
        placeholder={searchPlaceholder}
        size="middle"
        allowClear
        className="w-full rounded-md text-sm lg:flex-1"
      />
      {filters ? (
        <div className="w-full lg:w-auto lg:shrink-0">{filters}</div>
      ) : null}
    </div>
  );
}

function ResponsiveCardGrid({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="grid gap-4"
      style={{
        gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
      }}
    >
      {children}
    </div>
  );
}

function PlaceholderBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-slate-200 bg-white/60 px-6 py-12 text-center text-slate-500">
      {children}
    </div>
  );
}
