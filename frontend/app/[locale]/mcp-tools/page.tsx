"use client";

import React, { useCallback } from "react";
import { App, Button, Input, Select } from "antd";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import log from "@/lib/logger";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import AddMcpServiceModal from "./components/AddMcpServiceModal";
import MyCommunityMcpModal from "./components/MyCommunityMcpModal";
import McpServiceCard from "./components/McpServiceCard";
import McpServiceDetailModal from "./components/McpServiceDetailModal";
import { useMcpToolsPage } from "../../../hooks/mcpTools/useMcpToolsPage";

export default function McpToolsPage() {
  const { message, modal } = App.useApp();
  const { t } = useTranslation("common");
  const { pageVariants, pageTransition } = useSetupFlow();
  const translate = useCallback((key: string) => String(t(key)), [t]);
  const [showMyPublishedModal, setShowMyPublishedModal] = React.useState(false);

  const {
    searchValue,
    setSearchValue,
    sourceFilter,
    setSourceFilter,
    transportTypeFilter,
    setTransportTypeFilter,
    tagFilter,
    setTagFilter,
    tagStats,
    loadingServices,
    selectedService,
    setSelectedService,
    showAddModal,
    setShowAddModal,
    loadServerList,
    filteredServices,
    toggleServiceStatus,
    togglingServiceId,
    detail,
  } = useMcpToolsPage({
    t: translate,
    message,
  });

  const handleDeleteConfirm = (mcpId: number, serviceName: string) => {
    modal.confirm({
      title: t("mcpTools.delete.confirmTitle"),
      content: (
        <div className="space-y-1">
          <p className="text-sm text-slate-600 break-all">{serviceName}</p>
          <p className="text-xs text-slate-400">{t("mcpTools.delete.confirmDesc")}</p>
        </div>
      ),
      okText: t("mcpTools.delete.confirmOk"),
      cancelText: t("mcpTools.delete.confirmCancel"),
      okButtonProps: { danger: true },
      onOk: () => detail.onDeleteService(mcpId, serviceName),
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
            <h1 className="text-3xl md:text-4xl font-semibold text-slate-900">{t("mcpTools.page.title")}</h1>
            <p className="text-slate-600 text-base">{t("mcpTools.page.subtitle")}</p>
          </div>

          <div className="flex flex-col md:flex-row gap-4 items-stretch">
            <div className="md:basis-2/3">
              <label className="sr-only" htmlFor="mcp-search">
                {t("mcpTools.page.searchLabel")}
              </label>
              <div className="relative mb-2">
                <Input
                  id="mcp-search"
                  value={searchValue}
                  onChange={(event) => setSearchValue(event.target.value)}
                  placeholder={String(t("mcpTools.page.searchPlaceholder"))}
                  size="large"
                  className="w-full h-10 rounded-2xl"
                />
                <div className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-xs font-medium text-amber-700">
                  {t("mcpTools.page.resultCount", { count: filteredServices.length })}
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                <Select
                  size="large"
                  value={sourceFilter}
                  onChange={setSourceFilter}
                  className="w-full"
                  options={[
                    { value: "all", label: t("mcpTools.page.sourceFilter.all") },
                    { value: "local", label: t("mcpTools.source.local") },
                    { value: "mcp_registry", label: t("mcpTools.source.registry") },
                    { value: "community", label: t("mcpTools.source.community") },
                  ]}
                />
                <Select
                  size="large"
                  value={transportTypeFilter}
                  onChange={setTransportTypeFilter}
                  className="w-full"
                  options={[
                    { value: "all", label: t("mcpTools.page.transportFilter.all") },
                    { value: "http", label: t("mcpTools.serverType.http") },
                    { value: "sse", label: t("mcpTools.serverType.sse") },
                    { value: "stdio", label: t("mcpTools.serverType.stdio") },
                  ]}
                />
                <Select
                  size="large"
                  value={tagFilter}
                  onChange={setTagFilter}
                  className="w-full"
                  options={[
                    { value: "all", label: t("mcpTools.page.tagFilter.all") },
                    ...tagStats.map((item) => ({
                      value: item.tag,
                      label: `${item.tag} (${item.count})`,
                    })),
                  ]}
                />
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

          {loadingServices ? (
            <div className="rounded-3xl border border-dashed border-slate-200 bg-white/60 px-6 py-10 text-center text-slate-500">
              {t("mcpTools.page.loading")}
            </div>
          ) : filteredServices.length === 0 ? (
            <div className="rounded-3xl border border-dashed border-slate-200 bg-white/60 px-6 py-10 text-center text-slate-500">
              {t("mcpTools.page.empty")}
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
              {filteredServices.map((service) => {
                return (
                  <McpServiceCard
                    key={`${service.mcpId}`}
                    service={service}
                    t={t}
                    onSelectService={setSelectedService}
                    toggleLoading={togglingServiceId === service.mcpId}
                    onToggleEnable={(item) => {
                      toggleServiceStatus(item).catch((error) => {
                        log.error("[McpToolsPage] Failed to toggle service status from card", {
                          error,
                          serviceName: item.name,
                          serverUrl: item.serverUrl,
                        });
                      });
                    }}
                  />
                );
              })}
            </div>
          )}

          {selectedService ? (
            <McpServiceDetailModal
              open={Boolean(detail.selectedService && detail.draftService)}
              selectedService={detail.selectedService}
              draftService={detail.draftService}
              tagDrafts={detail.tagDrafts}
              tagInputValue={detail.tagInputValue}
              healthCheckLoading={detail.healthCheckLoading}
              healthErrorModalVisible={detail.healthErrorModalVisible}
              healthErrorModalTitle={detail.healthErrorModalTitle}
              healthErrorModalDetail={detail.healthErrorModalDetail}
              loadingTools={detail.loadingTools}
              toolsModalVisible={detail.toolsModalVisible}
              currentServerTools={detail.currentServerTools}
              publishLoading={detail.publishLoading}
              toggleLoading={togglingServiceId === detail.selectedService?.mcpId}
              setDraftService={detail.setDraftService}
              setTagInputValue={detail.setTagInputValue}
              addDetailTag={detail.addDetailTag}
              removeTag={detail.removeTag}
              handleHealthCheck={detail.handleHealthCheck}
              handleViewTools={detail.handleViewTools}
              handleSaveUpdates={detail.handleSaveUpdates}
              closeToolsModal={detail.closeToolsModal}
              handleRefreshTools={detail.handleRefreshTools}
              closeHealthErrorModal={detail.closeHealthErrorModal}
              onDeleteConfirm={(serviceName) => handleDeleteConfirm(detail.selectedService!.mcpId, serviceName)}
              onPublishToCommunity={detail.handlePublishToCommunity}
              onToggleEnable={(item) => {
                toggleServiceStatus(item).catch((error) => {
                  log.error("[McpToolsPage] Failed to toggle service status from detail modal", {
                    error,
                    serviceName: item.name,
                    serverUrl: item.serverUrl,
                  });
                });
              }}
              onClose={detail.closeDetail}
            />
          ) : null}

          <AddMcpServiceModal
            open={showAddModal}
            onServiceAdded={loadServerList}
            onClose={() => setShowAddModal(false)}
          />

          <MyCommunityMcpModal
            open={showMyPublishedModal}
            onClose={() => setShowMyPublishedModal(false)}
            t={(key, params) => String(t(key, params))}
          />
        </div>
      </motion.div>
    </div>
  );
}