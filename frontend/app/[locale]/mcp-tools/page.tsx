"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { App, Button, Input } from "antd";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import log from "@/lib/logger";
import { filterServiceCards } from "@/lib/mcpTools";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import type { McpTool } from "@/types/agentConfig";
import type { McpServiceItem } from "@/types/mcpTools";
import { listMcpTools } from "@/services/mcpToolsService";
import AddMcpServiceModal from "./components/AddMcpServiceModal";
import McpServiceCard from "./components/McpServiceCard";
import McpServiceDetailModal from "./components/McpServiceDetailModal";
import { useMcpToolsDetail } from "../../../hooks/mcpTools/useMcpToolsDetail";
import { useMcpToolsToggle } from "../../../hooks/mcpTools/useMcpToolsToggle";

export default function McpToolsPage() {
  const { message, modal } = App.useApp();
  const { t } = useTranslation("common");
  const { pageVariants, pageTransition } = useSetupFlow();

  const [searchValue, setSearchValue] = useState("");
  const [services, setServices] = useState<McpServiceItem[]>([]);
  const [loadingServices, setLoadingServices] = useState(false);
  const [selectedService, setSelectedService] = useState<McpServiceItem | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);

  const loadServerList = async () => {
    setLoadingServices(true);
    try {
      const result = await listMcpTools();
      if (!result.success) {
        throw new Error(result.message || t("mcpTools.list.loadFailed"));
      }
      setServices(result.data);
      return { success: true };
    } catch (error) {
      log.error("[McpToolsPage] Failed to load managed MCP service list", { error });
      message.error(error instanceof Error ? error.message : t("mcpTools.list.loadFailed"));
      return { success: false };
    } finally {
      setLoadingServices(false);
    }
  };

  useEffect(() => {
    loadServerList().catch(() => undefined);
  }, []);

  const filteredServices = useMemo(() => {
    return filterServiceCards(services, searchValue);
  }, [searchValue, services]);

  const isSameToolNames = (left: string[] = [], right: string[] = []) => {
    if (left.length !== right.length) return false;
    return left.every((item, index) => item === right[index]);
  };

  const syncToolNamesToCards = useCallback((service: Pick<McpServiceItem, "name" | "serverUrl">, tools: McpTool[]) => {
    const nextToolNames = tools.map((item) => item.name);
    setSelectedService((prev) => {
      if (!prev || prev.name !== service.name || prev.serverUrl !== service.serverUrl) {
        return prev;
      }
      if (isSameToolNames(prev.tools, nextToolNames)) {
        return prev;
      }
      return { ...prev, tools: nextToolNames };
    });
    setServices((prev) => {
      let changed = false;
      const next = prev.map((item) => {
        if (item.name !== service.name || item.serverUrl !== service.serverUrl) {
          return item;
        }
        if (isSameToolNames(item.tools, nextToolNames)) {
          return item;
        }
        changed = true;
        return { ...item, tools: nextToolNames };
      });
      return changed ? next : prev;
    });
  }, []);

  const { toggleServiceStatus } = useMcpToolsToggle({
    loadServerList,
    setSelectedService,
    t: (key: string) => String(t(key)),
    message,
  });

  const { state: detailState, actions: detailActions } = useMcpToolsDetail({
    selectedService,
    onSelectedServiceChange: setSelectedService,
    onServicesReload: loadServerList,
    onSyncToolNames: syncToolNamesToCards,
    t: (key: string) => String(t(key)),
    message,
  });

  const handleDeleteConfirm = (serviceName: string) => {
    modal.confirm({
      title: t("mcpTools.delete.confirmTitle"),
      content: (
        <div className="space-y-1">
          <p className="text-sm text-slate-600 break-all">{serviceName}</p>
          <p className="text-xs text-slate-400">{t("mcpTools.delete.confirmDesc")}</p>
        </div>
      ),
      okButtonProps: { danger: true },
      onOk: () => detailActions.onDeleteService(serviceName),
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
              <div className="relative">
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
            </div>
            <div className="md:basis-1/3">
              <Button
                type="primary"
                size="large"
                block
                onClick={() => setShowAddModal(true)}
                className="w-full h-10 rounded-full bg-gradient-to-r from-emerald-600 via-teal-600 to-cyan-600 px-6 text-white font-semibold shadow-lg shadow-emerald-200/50 transition hover:translate-y-[-1px] hover:shadow-emerald-300/70"
              >
                {t("mcpTools.page.addService")}
              </Button>
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
                const isSelected =
                  selectedService?.name === service.name &&
                  selectedService?.serverUrl === service.serverUrl;

                return (
                  <McpServiceCard
                    key={`${service.name}-${service.source}`}
                    service={service}
                    t={t}
                    onSelectService={setSelectedService}
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
              open={Boolean(detailState.selectedService && detailState.draftService)}
              detailState={detailState}
              detailActions={detailActions}
              onDeleteConfirm={handleDeleteConfirm}
              onToggleEnable={(item) => {
                toggleServiceStatus(item).catch((error) => {
                  log.error("[McpToolsPage] Failed to toggle service status from detail modal", {
                    error,
                    serviceName: item.name,
                    serverUrl: item.serverUrl,
                  });
                });
              }}
              onClose={detailActions.onCloseDetail}
            />
          ) : null}

          <AddMcpServiceModal
            open={showAddModal}
            onServiceAdded={loadServerList}
            onClose={() => setShowAddModal(false)}
          />
        </div>
      </motion.div>
    </div>
  );
}