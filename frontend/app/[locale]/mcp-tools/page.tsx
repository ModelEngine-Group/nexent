"use client";

import { useState } from "react";
import { Button, Empty, Input, Spin, Tabs } from "antd";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import { Puzzle } from "lucide-react";
import { useMcpServicesList } from "@/hooks/mcpTools/useMcpServicesList";
import { useMyCommunityMcp } from "@/hooks/mcpTools/useMyCommunityMcp";
import type { CommunityMcpCard, McpServiceItem } from "@/types/mcpTools";
import type { McpServiceStatus } from "@/const/mcpTools";
import AddMcpServiceModal from "./components/AddMcpServiceModal";
import McpServiceCard from "./components/McpServiceCard";
import McpServiceDetailModal from "./components/McpServiceDetailModal";
import McpServicesFilterBar from "./components/McpServicesFilterBar";
import PublishedServiceCard from "./components/PublishedServiceCard";
import PublishedServiceDetailModal from "./components/PublishedServiceDetailModal";

type ServicesTab = "imported" | "published";

export default function McpToolsPage() {
  const { t } = useTranslation("common");
  const { pageVariants, pageTransition } = useSetupFlow();

  const [tab, setTab] = useState<ServicesTab>("imported");
  const [showAddModal, setShowAddModal] = useState(false);
  const [selectedImported, setSelectedImported] =
    useState<McpServiceItem | null>(null);
  const [selectedPublished, setSelectedPublished] =
    useState<CommunityMcpCard | null>(null);

  const list = useMcpServicesList();
  const myPublished = useMyCommunityMcp(tab === "published");

  const handleStatusChanged = (mcpId: number, nextEnabled: McpServiceStatus) => {
    setSelectedImported((prev) =>
      prev && prev.mcpId === mcpId ? { ...prev, enabled: nextEnabled } : prev
    );
  };

  const handleSelectPublished = (item: CommunityMcpCard) => {
    setSelectedPublished(item);
  };

  const closePublished = () => {
    setSelectedPublished(null);
  };

  return (
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
            {/* Page header */}
            <motion.div
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="flex items-center gap-3 mb-6"
            >
              <div className="flex h-12 w-12 items-center justify-center rounded-md bg-gradient-to-br from-orange-400 to-amber-500">
                {/* Puzzle icon from lucide-react */}
                <Puzzle className="h-6 w-6 text-white" />
              </div>
              <div>
                <h1 className="text-3xl font-bold text-orange-600 dark:text-orange-400">
                  {t("mcpTools.page.title")}
                </h1>
                <p className="text-slate-600 dark:text-slate-300 mt-1">
                  {t("mcpTools.page.subtitle")}
                </p>
              </div>
            </motion.div>

            <div className="flex items-center justify-between gap-3">
              <Tabs
                activeKey={tab}
                onChange={(key) => setTab(key as ServicesTab)}
                className="m-0"
                items={[
                  { key: "imported", label: t("mcpTools.page.tab.imported") },
                  { key: "published", label: t("mcpTools.page.tab.published") },
                ]}
              />
              <Button
                type="primary"
                size="large"
                onClick={() => setShowAddModal(true)}
                className="rounded-md bg-gradient-to-r from-emerald-600 via-teal-600 to-cyan-600 px-5 font-semibold shadow-md shadow-emerald-200/50 transition hover:translate-y-[-1px] hover:shadow-emerald-300/70"
              >
                {t("mcpTools.page.addService")}
              </Button>
            </div>

            {tab === "imported" ? (
              <ImportedView list={list} onSelect={setSelectedImported} />
            ) : (
              <PublishedView
                myPublished={myPublished}
                onSelect={handleSelectPublished}
              />
            )}

            {selectedImported ? (
              <McpServiceDetailModal
                selectedService={selectedImported}
                onClose={() => setSelectedImported(null)}
                onStatusChanged={handleStatusChanged}
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
        resultCount={list.filteredServices.length}
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
        onSearchChange={myPublished.setSearch}
        resultCount={myPublished.filteredItems.length}
        searchPlaceholder={String(t("mcpTools.community.searchPlaceholder"))}
        filters={null}
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
  resultCount,
  searchPlaceholder,
  filters,
}: {
  searchValue: string;
  onSearchChange: (value: string) => void;
  resultCount: number;
  searchPlaceholder: string;
  filters: React.ReactNode;
}) {
  const { t } = useTranslation("common");
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <Input
          value={searchValue}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder={searchPlaceholder}
          size="large"
          allowClear
          className="w-full rounded-md lg:flex-1"
        />
        {filters ? (
          <div className="w-full lg:w-auto lg:shrink-0">{filters}</div>
        ) : null}
      </div>
      <span className="text-xs text-slate-400">
        {t("mcpTools.page.resultCount", { count: resultCount })}
      </span>
    </div>
  );
}

function ResponsiveCardGrid({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="grid h-56 gap-4"
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
