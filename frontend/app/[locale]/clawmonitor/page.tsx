"use client";

import React, { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import {
  Flex,
  Row,
  Col,
  Card,
  Button,
  Tabs,
  Typography,
  Divider,
  Tag,
  Skeleton,
  Spin,
} from "antd";
import {
  getMeclawOverview,
  getMeclawInstances,
  getMeclawInstanceDetail,
} from "@/services/meclawService";
import type {
  MeclawInstance,
  MeclawInstanceDetail,
} from "@/services/meclawService";
import {
  Box,
  Server,
  MessageCircle,
  Trash2,
  ArrowLeft,
  Coins,
  CheckCircle2,
  Clock,
  Square,
} from "lucide-react";

/** Instance status */
export type InstanceStatus = "running" | "waiting" | "stopped";

/** Global overview stats */
interface OverviewStats {
  runningCount: number;
  totalCount: number;
  tokenConsumptionToday: number;
}

/**
 * Claw Monitor page: global overview + instance list.
 * Clicking an instance lazily fetches and shows its full detail.
 */
export default function ClawMonitorPage() {
  const { t } = useTranslation("common");

  const [overview, setOverview] = useState<OverviewStats | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);

  const [instances, setInstances] = useState<MeclawInstance[]>([]);
  const [instancesLoading, setInstancesLoading] = useState(true);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [instanceDetail, setInstanceDetail] = useState<MeclawInstanceDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    setOverviewLoading(true);
    getMeclawOverview()
      .then(({ success, data }) => {
        if (success && data) {
          setOverview({
            runningCount: data.running_count,
            totalCount: data.total_count,
            tokenConsumptionToday: data.total_token_usage,
          });
        }
      })
      .finally(() => setOverviewLoading(false));
  }, []);

  useEffect(() => {
    setInstancesLoading(true);
    getMeclawInstances()
      .then(({ success, data }) => {
        if (success) setInstances(data);
      })
      .finally(() => setInstancesLoading(false));
  }, []);

  const handleSelectInstance = (id: string) => {
    setSelectedId(id);
    setInstanceDetail(null);
    setDetailLoading(true);
    getMeclawInstanceDetail(id)
      .then(({ success, data }) => {
        if (success && data) setInstanceDetail(data);
      })
      .finally(() => setDetailLoading(false));
  };

  const handleBackToList = () => {
    setSelectedId(null);
    setInstanceDetail(null);
  };

  return (
    <div className="w-full h-full overflow-auto">
      <Flex
        vertical
        gap={24}
        className="w-full max-w-6xl mx-auto p-4 md:p-6"
        style={{ minHeight: "100%" }}
      >
        {/* Section 1: Global Overview */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-100 mb-4">
            {t("clawmonitor.globalOverview")}
          </h2>
          <Row gutter={[16, 16]}>
            <Col xs={24} sm={12}>
              <Card
                className="h-full border border-slate-200 dark:border-slate-700 rounded-xl"
                styles={{ body: { padding: "20px 24px" } }}
              >
                <div className="flex items-center gap-4">
                  <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-emerald-100 dark:bg-emerald-900/30">
                    <Server className="h-6 w-6 text-emerald-600 dark:text-emerald-400" />
                  </div>
                  <div>
                    <div className="text-sm text-slate-500 dark:text-slate-400">
                      {t("clawmonitor.runningInstances")}
                    </div>
                    {overviewLoading ? (
                      <Skeleton.Input active size="small" className="mt-1" />
                    ) : (
                      <div className="text-2xl font-semibold text-slate-900 dark:text-white mt-0.5">
                        {overview?.runningCount ?? "-"} / {overview?.totalCount ?? "-"}
                      </div>
                    )}
                  </div>
                </div>
              </Card>
            </Col>
            <Col xs={24} sm={12}>
              <Card
                className="h-full border border-slate-200 dark:border-slate-700 rounded-xl"
                styles={{ body: { padding: "20px 24px" } }}
              >
                <div className="flex items-center gap-4">
                  <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-amber-100 dark:bg-amber-900/30">
                    <Coins className="h-6 w-6 text-amber-600 dark:text-amber-400" />
                  </div>
                  <div>
                    <div className="text-sm text-slate-500 dark:text-slate-400">
                      {t("clawmonitor.todayTokenConsumption")}
                    </div>
                    {overviewLoading ? (
                      <Skeleton.Input active size="small" className="mt-1" />
                    ) : (
                      <div className="text-2xl font-semibold text-slate-900 dark:text-white mt-0.5">
                        {overview != null
                          ? (overview.tokenConsumptionToday / 10000).toFixed(1)
                          : "-"}{" "}
                        万
                      </div>
                    )}
                  </div>
                </div>
              </Card>
            </Col>
          </Row>
        </section>

        {/* Section 2: Instance list or detail */}
        <section className="flex-1 min-h-0">
          {selectedId ? (
            /* Detail view */
            <Card
              className="w-full border border-slate-200 dark:border-slate-700 rounded-xl"
              styles={{ body: { padding: 0 } }}
            >
              {/* Header */}
              <div className="px-2 pt-4 pb-4">
                <Button
                  type="text"
                  icon={<ArrowLeft className="h-4 w-4" />}
                  onClick={handleBackToList}
                  className="mb-4 text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white"
                >
                  {t("clawmonitor.backToList")}
                </Button>
                <div className="flex items-center gap-4 mx-4">
                  <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-emerald-100 dark:bg-emerald-900/30">
                    <Box className="h-7 w-7 text-teal-600 dark:text-teal-400" />
                  </div>
                  <div>
                    <Typography.Title level={4} className="!mb-0">
                      {instanceDetail?.name ??
                        instances.find((i) => i.id === selectedId)?.name ??
                        selectedId}
                    </Typography.Title>
                    <Typography.Text type="secondary" className="text-sm">
                      {t("clawmonitor.detailSubtitle")}
                    </Typography.Text>
                  </div>
                </div>
              </div>
              <Divider className="my-0" />

              {detailLoading ? (
                <div className="flex items-center justify-center py-16">
                  <Spin size="large" />
                </div>
              ) : (
                <Tabs
                  defaultActiveKey="basic"
                  className="clawmonitor-detail-tabs px-6"
                  items={[
                    {
                      key: "basic",
                      label: t("clawmonitor.tabBasicInfo"),
                      children: (
                        <div className="py-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
                          <div className="flex flex-col gap-1">
                            <span className="text-sm text-slate-500 dark:text-slate-400">
                              {t("clawmonitor.instanceId")}
                            </span>
                            <span className="text-slate-900 dark:text-slate-100">
                              {instanceDetail?.id ?? "-"}
                            </span>
                          </div>
                          <div className="flex flex-col gap-1">
                            <span className="text-sm text-slate-500 dark:text-slate-400">
                              {t("clawmonitor.name")}
                            </span>
                            <span className="text-slate-900 dark:text-slate-100">
                              {instanceDetail?.name ?? "-"}
                            </span>
                          </div>
                          <div className="flex flex-col gap-1">
                            <span className="text-sm text-slate-500 dark:text-slate-400">
                              {t("clawmonitor.author")}
                            </span>
                            <span className="text-slate-900 dark:text-slate-100">
                              {instanceDetail?.author ?? "-"}
                            </span>
                          </div>
                          <div className="flex flex-col gap-1 sm:col-span-2">
                            <span className="text-sm text-slate-500 dark:text-slate-400">
                              {t("clawmonitor.description")}
                            </span>
                            <span className="text-slate-900 dark:text-slate-100">
                              {instanceDetail?.description ?? "-"}
                            </span>
                          </div>
                          <div className="flex flex-col gap-1">
                            <span className="text-sm text-slate-500 dark:text-slate-400">
                              {t("clawmonitor.status")}
                            </span>
                            {instanceDetail ? (
                              <StatusLabel
                                status={instanceDetail.status as InstanceStatus}
                                t={t}
                              />
                            ) : (
                              <span>-</span>
                            )}
                          </div>
                          <div className="flex flex-col gap-1">
                            <span className="text-sm text-slate-500 dark:text-slate-400">
                              {t("clawmonitor.createdAt")}
                            </span>
                            <span className="text-slate-900 dark:text-slate-100">
                              {instanceDetail?.created_at ?? "-"}
                            </span>
                          </div>
                        </div>
                      ),
                    },
                    {
                      key: "model",
                      label: t("clawmonitor.tabModelConfig"),
                      children: (
                        <div className="py-4 grid grid-cols-1 sm:grid-cols-2 gap-6">
                          <div className="flex flex-col gap-2 p-4 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
                            <span className="text-sm text-slate-500 dark:text-slate-400">
                              {t("clawmonitor.modelName")}
                            </span>
                            <span className="text-lg font-medium text-slate-900 dark:text-slate-100">
                              {instanceDetail?.model || "-"}
                            </span>
                          </div>
                          <div className="flex flex-col gap-2 p-4 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
                            <span className="text-sm text-slate-500 dark:text-slate-400">
                              {t("clawmonitor.tokenUsage")}
                            </span>
                            <span className="text-lg font-medium text-slate-900 dark:text-slate-100">
                              {instanceDetail?.token_usage?.toLocaleString() ?? "-"}
                            </span>
                          </div>
                        </div>
                      ),
                    },
                    {
                      key: "skill",
                      label: t("clawmonitor.tabSkillMonitor"),
                      children: (
                        <div className="py-4 space-y-6">
                          <div>
                            <div className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-300">
                              {t("clawmonitor.totalSkills")}
                              <span className="ml-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
                                {instanceDetail?.skills?.length ?? 0}
                              </span>
                            </div>
                            <div className="flex flex-wrap gap-2">
                              {instanceDetail?.skills?.length ? (
                                instanceDetail.skills.map((skill) => (
                                  <Tag key={skill} color="blue" className="px-3 py-1">
                                    {skill}
                                  </Tag>
                                ))
                              ) : (
                                <span className="text-slate-500 dark:text-slate-400">
                                  {t("clawmonitor.noSkills")}
                                </span>
                              )}
                            </div>
                          </div>
                          <div>
                            <div className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-300">
                              {t("clawmonitor.plugins")}
                              <span className="ml-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
                                {instanceDetail?.plugins?.length ?? 0}
                              </span>
                            </div>
                            <div className="flex flex-wrap gap-2">
                              {instanceDetail?.plugins?.length ? (
                                instanceDetail.plugins.map((plugin) => (
                                  <Tag key={plugin} color="purple" className="px-3 py-1">
                                    {plugin}
                                  </Tag>
                                ))
                              ) : (
                                <span className="text-slate-500 dark:text-slate-400">
                                  {t("clawmonitor.noPlugins")}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      ),
                    },
                  ]}
                />
              )}
            </Card>
          ) : (
            /* List view */
            <>
              <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-100 mb-4">
                {t("clawmonitor.instanceList")}
              </h2>
              {instancesLoading ? (
                <Row gutter={[16, 16]}>
                  {[1, 2, 3].map((n) => (
                    <Col xs={24} sm={12} lg={8} key={n}>
                      <Card
                        className="border border-slate-200 dark:border-slate-700 rounded-xl"
                        styles={{ body: { padding: "20px" } }}
                      >
                        <Skeleton active paragraph={{ rows: 3 }} />
                      </Card>
                    </Col>
                  ))}
                </Row>
              ) : (
                <Row gutter={[16, 16]}>
                  {instances.map((inst) => (
                    <Col xs={24} sm={12} lg={8} key={inst.id}>
                      <Card
                        className="border border-slate-200 dark:border-slate-700 rounded-xl h-full transition-all hover:shadow-md hover:border-blue-300 dark:hover:border-blue-600 cursor-pointer"
                        styles={{ body: { padding: "20px" } }}
                        onClick={() => handleSelectInstance(inst.id)}
                        actions={[
                          <Button
                            key="enter"
                            type="link"
                            size="small"
                            icon={<MessageCircle className="h-4 w-4" />}
                            className="text-slate-600 dark:text-slate-300"
                            onClick={(e) => {
                              e.stopPropagation();
                              // TODO: navigate to conversation
                            }}
                          >
                            {t("clawmonitor.enterConversation")}
                          </Button>,
                          <Button
                            key="delete"
                            type="link"
                            size="small"
                            danger
                            icon={<Trash2 className="h-4 w-4" />}
                            onClick={(e) => {
                              e.stopPropagation();
                              // TODO: delete instance
                            }}
                          >
                            {t("clawmonitor.delete")}
                          </Button>,
                        ]}
                      >
                        <div className="flex flex-col h-full">
                          <div className="flex items-start justify-between mb-3">
                            <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-emerald-100 dark:bg-emerald-900/30">
                              <Box className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
                            </div>
                            <StatusLabel
                              status={inst.status as InstanceStatus}
                              t={t}
                              compact
                            />
                          </div>
                          <Typography.Title level={5} className="!mt-0 !mb-1">
                            {inst.name}
                          </Typography.Title>
                          <div className="text-sm text-slate-500 dark:text-slate-400 mb-1">
                            {t("clawmonitor.author")}: {inst.author}
                          </div>
                          <p className="text-sm text-slate-600 dark:text-slate-300 flex-1 line-clamp-2">
                            {inst.description}
                          </p>
                        </div>
                      </Card>
                    </Col>
                  ))}
                </Row>
              )}
            </>
          )}
        </section>
      </Flex>
    </div>
  );
}

/** Status label with icon */
function StatusLabel({
  status,
  t,
  compact,
}: {
  status: InstanceStatus;
  t: (key: string) => string;
  compact?: boolean;
}) {
  const config: Record<
    InstanceStatus,
    { icon: React.ElementType; text: string; className: string }
  > = {
    running: {
      icon: CheckCircle2,
      text: t("clawmonitor.running"),
      className: "text-teal-600 dark:text-teal-400",
    },
    waiting: {
      icon: Clock,
      text: t("clawmonitor.waiting"),
      className: "text-amber-600 dark:text-amber-400",
    },
    stopped: {
      icon: Square,
      text: t("clawmonitor.stopped"),
      className: "text-slate-500 dark:text-slate-400",
    },
  };
  const cfg = config[status] ?? config.stopped;
  const Icon = cfg.icon;
  return (
    <span
      className={`inline-flex items-center gap-1.5 ${compact ? "text-xs" : "text-sm"} ${cfg.className}`}
    >
      <Icon className={compact ? "h-3.5 w-3.5" : "h-4 w-4"} />
      {cfg.text}
    </span>
  );
}
