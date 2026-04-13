"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";
import { Tabs, Button, Drawer, Segmented } from "antd";
import { ArrowLeftOutlined, ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import { useMonitoringData, useModelDetail, useAlerts } from "@/hooks/useMonitoringData";
import OverviewCards from "@/components/monitoring/OverviewCards";
import ModelComparisonTable from "@/components/monitoring/ModelComparisonTable";
import MonitoringTrendChart from "@/components/monitoring/MonitoringTrendChart";
import AlertList from "@/components/monitoring/AlertList";
import PerformanceCharts from "@/components/monitoring/PerformanceCharts";
import FailureDetailPanel from "@/components/monitoring/FailureDetailPanel";
import CostAnalysisCharts from "@/components/monitoring/CostAnalysisCharts";
import type { ModelMonitoringItem } from "@/types/monitoring";

export default function MonitoringPage() {
  const { t } = useTranslation("common");
  const { pageVariants, pageTransition } = useSetupFlow();

  const [activeTab, setActiveTab] = useState("models");
  const [selectedModel, setSelectedModel] = useState<ModelMonitoringItem | null>(null);

  const { models, trend, loading, timeRange, setTimeRange, trendModelId, setTrendModelId, refresh } = useMonitoringData();
  const alertsHook = useAlerts();

  const handleModelClick = (model: ModelMonitoringItem) => {
    setSelectedModel(model);
  };

  const timeOptions = [
    { label: t("monitoring.dashboard.timeRange.24h"), value: "24h" },
    { label: t("monitoring.dashboard.timeRange.7d"), value: "7d" },
    { label: t("monitoring.dashboard.timeRange.30d"), value: "30d" },
  ];

  const tabItems = [
    {
      key: "models",
      label: t("monitoring.dashboard.models"),
      children: (
        <div className="space-y-4">
          <OverviewCards models={models} loading={loading} />
          <MonitoringTrendChart
            trend={trend}
            models={models}
            loading={loading}
            selectedModelId={trendModelId}
            onModelChange={setTrendModelId}
          />
          <ModelComparisonTable
            models={models}
            loading={loading}
            onModelClick={handleModelClick}
          />
        </div>
      ),
    },
    {
      key: "alerts",
      label: t("monitoring.dashboard.alerts"),
      children: (
        <AlertList
          alerts={alertsHook.alerts.items}
          total={alertsHook.alerts.total}
          loading={alertsHook.loading}
          onAcknowledge={alertsHook.acknowledge}
          onResolve={alertsHook.resolve}
        />
      ),
    },
  ];

  return (
    <div className="w-full h-full">
      <motion.div
        initial="initial"
        animate="in"
        exit="out"
        variants={pageVariants}
        transition={pageTransition}
        className="w-full h-full p-6 overflow-auto"
      >
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-100">
              {t("monitoring.dashboard.title")}
            </h2>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {t("monitoring.dashboard.subtitle")}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Segmented
              options={timeOptions}
              value={timeRange}
              onChange={(v) => setTimeRange(v as string)}
              size="small"
            />
            <Button
              icon={<ReloadOutlined />}
              size="small"
              onClick={refresh}
            >
              {t("monitoring.dashboard.refresh")}
            </Button>
          </div>
        </div>

        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={tabItems}
        />
      </motion.div>

      <ModelDetailDrawer
        model={selectedModel}
        onClose={() => setSelectedModel(null)}
      />
    </div>
  );
}

function ModelDetailDrawer({
  model,
  onClose,
}: {
  model: ModelMonitoringItem | null;
  onClose: () => void;
}) {
  const { t } = useTranslation("common");
  const { summary, trend: modelTrend, failures, loading } = useModelDetail(model?.model_id ?? "");

  if (!model) return null;

  const detailTabs = [
    {
      key: "overview",
      label: t("monitoring.detail.overview"),
      children: (
        <div className="space-y-4">
          <MonitoringTrendChart
            trend={modelTrend}
            models={[model]}
            loading={loading}
            selectedModelId={model.model_id}
            onModelChange={() => {}}
          />
          <PerformanceCharts summary={summary} loading={loading} />
        </div>
      ),
    },
    {
      key: "failures",
      label: t("monitoring.detail.failures"),
      children: <FailureDetailPanel failures={failures} loading={loading} />,
    },
    {
      key: "cost",
      label: t("monitoring.detail.cost"),
      children: <CostAnalysisCharts summary={summary} loading={loading} />,
    },
  ];

  return (
    <Drawer
      title={
        <div className="flex items-center gap-2">
          <span className="font-semibold">{model.display_name}</span>
          <span className="text-sm text-slate-400">{model.model_name}</span>
        </div>
      }
      placement="right"
      width={720}
      open={!!model}
      onClose={onClose}
      styles={{ body: { padding: "0 16px 16px" } }}
    >
      <Tabs items={detailTabs} />
    </Drawer>
  );
}
