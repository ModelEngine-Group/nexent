"use client";

import { useState } from "react";
import { Button, Input } from "antd";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import log from "@/lib/logger";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import { useMcpServicesList } from "@/hooks/mcpTools/useMcpServicesList";
import { useMcpServiceToggle } from "@/hooks/mcpTools/useMcpServiceToggle";
import type { McpServiceItem } from "@/types/mcpTools";
import AddMcpServiceModal from "./components/AddMcpServiceModal";
import MyCommunityMcpModal from "./components/MyCommunityMcpModal";
import McpServiceCard from "./components/McpServiceCard";
import McpServiceDetailModal from "./components/McpServiceDetailModal";
import McpServicesFilterBar from "./components/McpServicesFilterBar";

export default function McpToolsPage() {
  const { t } = useTranslation("common");
  const { pageVariants, pageTransition } = useSetupFlow();

  const [showAddModal, setShowAddModal] = useState(false);
  const [showMyPublishedModal, setShowMyPublishedModal] = useState(false);
  const [selected, setSelected] = useState<McpServiceItem | null>(null);

  const list = useMcpServicesList();
  const toggle = useMcpServiceToggle();

  const handleToggle = (service: McpServiceItem) => {
    toggle.toggle(service).catch((error) => {
      log.error("[McpToolsPage] Failed to toggle service status", {
        error,
        serviceName: service.name,
        serverUrl: service.serverUrl,
      });
    });
  };

  return (
    <div className="w-full h-full">
      <motion.div
        initial="initial"
        animate="in"
        exit="out"
        variants={pageVariants}
        transition={pageTransition}
        className="w-full max-w-6xl mx-auto px-6 py-10"
      >
        <div className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <h1 className="text-3xl md:text-4xl font-semibold text-slate-900">
              {t("mcpTools.page.title")}
            </h1>
            <p className="text-slate-600 text-base">
              {t("mcpTools.page.subtitle")}
            </p>
          </div>

          <div className="flex flex-col md:flex-row gap-4 items-stretch">
            <div className="md:basis-2/3">
              <label className="sr-only" htmlFor="mcp-search">
                {t("mcpTools.page.searchLabel")}
              </label>
              <div className="relative">
                <Input
                  id="mcp-search"
                  value={list.filters.search}
                  onChange={(event) =>
                    list.updateFilter("search", event.target.value)
                  }
                  placeholder={String(t("mcpTools.page.searchPlaceholder"))}
                  size="large"
                  className="w-full h-10 rounded-2xl"
                />
                <div className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-xs font-medium text-amber-700">
                  {t("mcpTools.page.resultCount", {
                    count: list.filteredServices.length,
                  })}
                </div>
              </div>
            </div>
            <div className="md:basis-1/3">
              <div className="grid grid-cols-2 gap-2">
                <Button
                  type="primary"
                  size="large"
                  block
                  onClick={() => setShowAddModal(true)}
                  className="w-full h-10 rounded-full bg-gradient-to-r from-emerald-600 via-teal-600 to-cyan-600 px-4 text-white font-semibold shadow-lg shadow-emerald-200/50 transition hover:translate-y-[-1px] hover:shadow-emerald-300/70"
                >
                  {t("mcpTools.page.addService")}
                </Button>
                <Button
                  size="large"
                  block
                  onClick={() => setShowMyPublishedModal(true)}
                  className="w-full h-10 rounded-full border-slate-300 px-4 font-semibold text-slate-700"
                >
                  {t("mcpTools.page.myPublished")}
                </Button>
              </div>
            </div>
          </div>

          <McpServicesFilterBar
            source={list.filters.source}
            transport={list.filters.transport}
            tag={list.filters.tag}
            tagStats={list.tagStats}
            onSourceChange={(value) => list.updateFilter("source", value)}
            onTransportChange={(value) => list.updateFilter("transport", value)}
            onTagChange={(value) => list.updateFilter("tag", value)}
          />

          {list.loading ? (
            <div className="rounded-3xl border border-dashed border-slate-200 bg-white/60 px-6 py-10 text-center text-slate-500">
              {t("mcpTools.page.loading")}
            </div>
          ) : list.filteredServices.length === 0 ? (
            <div className="rounded-3xl border border-dashed border-slate-200 bg-white/60 px-6 py-10 text-center text-slate-500">
              {t("mcpTools.page.empty")}
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
              {list.filteredServices.map((service) => (
                <McpServiceCard
                  key={`${service.mcpId}`}
                  service={service}
                  onSelect={setSelected}
                  onToggleEnable={handleToggle}
                  toggleLoading={toggle.isToggling(service.mcpId)}
                />
              ))}
            </div>
          )}

          {selected ? (
            <McpServiceDetailModal
              selectedService={selected}
              onClose={() => setSelected(null)}
              onToggleEnable={handleToggle}
              isToggleLoading={toggle.isToggling}
            />
          ) : null}

          <AddMcpServiceModal
            open={showAddModal}
            onClose={() => setShowAddModal(false)}
          />

          <MyCommunityMcpModal
            open={showMyPublishedModal}
            onClose={() => setShowMyPublishedModal(false)}
          />
        </div>
      </motion.div>
    </div>
  );
}
