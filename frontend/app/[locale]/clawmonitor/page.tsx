"use client";

import React, { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Flex, Row, Col, Card, Segmented, Button, Tabs, Typography, Divider, Tag } from "antd";
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


/** Instance type: container or virtual machine */
export type InstanceType = "container" | "vm";

/** Instance status */
export type InstanceStatus = "running" | "waiting" | "stopped";

/** Single instance (container or VM) */
export interface ClawInstance {
  id: string;
  type: InstanceType;
  name: string;
  author: string;
  description: string;
  status: InstanceStatus;
  createdAt: string;
  /** Model configuration: model name, CPU cores, memory size */
  modelConfig?: {
    model: string;
    cpu: number;
    memory: string;
  };
  /** Skill configuration: list of skills and total count */
  skillConfig?: {
    skills: string[];
    totalCount: number;
  };
}

/** Global overview stats (mock) */
interface OverviewStats {
  runningCount: number;
  totalCount: number;
  tokenConsumptionToday: number; // e.g. 1250000
  tokenChangePercent: number; // e.g. 8.5
}

/** Mock overview data */
const MOCK_OVERVIEW: OverviewStats = {
  runningCount: 3,
  totalCount: 5,
  tokenConsumptionToday: 1250000,
  tokenChangePercent: 8.5,
};

/** Mock instance list: containers and VMs */
const MOCK_CONTAINERS: ClawInstance[] = [
  {
    id: "c1",
    type: "container",
    name: "openclaw-worker-01",
    author: "user01",
    description: "处理作业数据，生成数据集",
    status: "running",
    createdAt: "2024-03-15 09:00",
    modelConfig: {
      model: "gpt-4",
      cpu: 4,
      memory: "16GB",
    },
    skillConfig: {
      skills: ["web_search", "code_execute", "data_process"],
      totalCount: 3,
    },
  },
  {
    id: "c2",
    type: "container",
    name: "web-scraper-01",
    author: "user01",
    description: "网页抓取与数据解析",
    status: "running",
    createdAt: "2024-03-14 14:20",
    modelConfig: {
      model: "claude-3-opus",
      cpu: 2,
      memory: "8GB",
    },
    skillConfig: {
      skills: ["web_scraper", "html_parser"],
      totalCount: 2,
    },
  },
  {
    id: "c3",
    type: "container",
    name: "batch-processor-01",
    author: "user02",
    description: "批量任务处理",
    status: "waiting",
    createdAt: "2024-03-13 11:00",
    modelConfig: {
      model: "gpt-3.5-turbo",
      cpu: 8,
      memory: "32GB",
    },
    skillConfig: {
      skills: ["batch_process", "file_convert", "image_resize", "pdf_split"],
      totalCount: 4,
    },
  },
];

const MOCK_VMS: ClawInstance[] = [
  {
    id: "v1",
    type: "vm",
    name: "prod-db-01",
    author: "user01",
    description: "生产数据库服务器",
    status: "running",
    createdAt: "2024-03-10 08:00",
    modelConfig: {
      model: "gpt-4",
      cpu: 16,
      memory: "64GB",
    },
    skillConfig: {
      skills: ["sql_query", "data_backup", "performance_monitor"],
      totalCount: 3,
    },
  },
  {
    id: "v2",
    type: "vm",
    name: "dev-env-01",
    author: "user02",
    description: "开发环境",
    status: "stopped",
    createdAt: "2024-03-12 16:00",
    modelConfig: {
      model: "claude-3-sonnet",
      cpu: 4,
      memory: "16GB",
    },
    skillConfig: {
      skills: ["code_review", "unit_test"],
      totalCount: 2,
    },
  },
];

/**
 * Claw Monitor page: global overview + instance list (containers / VMs).
 * Clicking an instance shows its detail with Basic Info, Model Config, Skill Monitoring tabs.
 */
export default function ClawMonitorPage() {
  const { t } = useTranslation("common");

  const [instanceType, setInstanceType] = useState<InstanceType>("container");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const instanceList = useMemo(
    () => (instanceType === "container" ? MOCK_CONTAINERS : MOCK_VMS),
    [instanceType]
  );
  const selectedInstance = useMemo(
    () =>
      selectedId
        ? [...MOCK_CONTAINERS, ...MOCK_VMS].find((i) => i.id === selectedId)
        : null,
    [selectedId]
  );

  const handleBackToList = () => setSelectedId(null);

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
                    <div className="text-2xl font-semibold text-slate-900 dark:text-white mt-0.5">
                      {MOCK_OVERVIEW.runningCount} / {MOCK_OVERVIEW.totalCount}
                    </div>
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
                    <div className="text-2xl font-semibold text-slate-900 dark:text-white mt-0.5">
                      {(MOCK_OVERVIEW.tokenConsumptionToday / 10000).toFixed(1)} 万
                    </div>
                    <div className="text-xs text-orange-500 dark:text-orange-400 mt-1">
                      {t("clawmonitor.vsYesterday", {
                        change: `+${MOCK_OVERVIEW.tokenChangePercent}%`,
                      })}
                    </div>
                  </div>
                </div>
              </Card>
            </Col>
          </Row>
        </section>

        {/* Section 2: Instance list or detail */}
        <section className="flex-1 min-h-0">
          {selectedInstance ? (
            /* Detail view: header + tabs */
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
                  className="mb-4  text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white"
                >
                  {t("clawmonitor.backToList")}
                </Button>
                <div className="flex items-center gap-4 mx-4">
                  <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-emerald-100 dark:bg-emerald-900/30">
                    {selectedInstance.type === "container" ? (
                      <Box className="h- w-7 text-teal-600 dark:text-teal-400" />
                    ) : (
                      <Server className="h-7 w-7 text-teal-600 dark:text-teal-400" />
                    )}
                  </div>
                  <div>
                    <Typography.Title level={4} className="!mb-0">
                      {selectedInstance.name}
                    </Typography.Title>
                    <Typography.Text type="secondary" className="text-sm">
                      {t("clawmonitor.detailSubtitle")}
                    </Typography.Text>
                  </div>
                </div>
              </div>
              <Divider className="my-0" />
              {/* Tabs */}
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
                            {selectedInstance.id}
                          </span>
                        </div>
                        <div className="flex flex-col gap-1">
                          <span className="text-sm text-slate-500 dark:text-slate-400">
                            {t("clawmonitor.name")}
                          </span>
                          <span className="text-slate-900 dark:text-slate-100">
                            {selectedInstance.name}
                          </span>
                        </div>
                        <div className="flex flex-col gap-1">
                          <span className="text-sm text-slate-500 dark:text-slate-400">
                            {t("clawmonitor.author")}
                          </span>
                          <span className="text-slate-900 dark:text-slate-100">
                            {selectedInstance.author}
                          </span>
                        </div>
                        <div className="flex flex-col gap-1 sm:col-span-2">
                          <span className="text-sm text-slate-500 dark:text-slate-400">
                            {t("clawmonitor.description")}
                          </span>
                          <span className="text-slate-900 dark:text-slate-100">
                            {selectedInstance.description}
                          </span>
                        </div>
                        <div className="flex flex-col gap-1">
                          <span className="text-sm text-slate-500 dark:text-slate-400">
                            {t("clawmonitor.status")}
                          </span>
                          <StatusLabel status={selectedInstance.status} t={t} />
                        </div>
                        <div className="flex flex-col gap-1">
                          <span className="text-sm text-slate-500 dark:text-slate-400">
                            {t("clawmonitor.createdAt")}
                          </span>
                          <span className="text-slate-900 dark:text-slate-100">
                            {selectedInstance.createdAt}
                          </span>
                        </div>
                      </div>
                    ),
                  },
                  {
                    key: "model",
                    label: t("clawmonitor.tabModelConfig"),
                    children: (
                      <div className="py-4 grid grid-cols-1 sm:grid-cols-3 gap-6">
                        <div className="flex flex-col gap-2 p-4 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
                          <span className="text-sm text-slate-500 dark:text-slate-400">
                            {t("clawmonitor.modelName")}
                          </span>
                          <span className="text-lg font-medium text-slate-900 dark:text-slate-100">
                            {selectedInstance.modelConfig?.model || "-"}
                          </span>
                        </div>
                        <div className="flex flex-col gap-2 p-4 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
                          <span className="text-sm text-slate-500 dark:text-slate-400">
                            {t("clawmonitor.cpuCores")}
                          </span>
                          <span className="text-lg font-medium text-slate-900 dark:text-slate-100">
                            {selectedInstance.modelConfig?.cpu || "-"} {t("clawmonitor.cores")}
                          </span>
                        </div>
                        <div className="flex flex-col gap-2 p-4 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
                          <span className="text-sm text-slate-500 dark:text-slate-400">
                            {t("clawmonitor.memory")}
                          </span>
                          <span className="text-lg font-medium text-slate-900 dark:text-slate-100">
                            {selectedInstance.modelConfig?.memory || "-"}
                          </span>
                        </div>
                      </div>
                    ),
                  },
                  {
                    key: "skill",
                    label: t("clawmonitor.tabSkillMonitor"),
                    children: (
                      <div className="py-4">
                        <div className="mb-4">
                          <span className="text-sm text-slate-500 dark:text-slate-400">
                            {t("clawmonitor.totalSkills")}
                          </span>
                          <span className="ml-2 text-lg font-medium text-slate-900 dark:text-slate-100">
                            {selectedInstance.skillConfig?.totalCount || 0}
                          </span>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {selectedInstance.skillConfig?.skills?.map((skill) => (
                            <Tag key={skill} color="blue" className="px-3 py-1">
                              {skill}
                            </Tag>
                          )) || (
                            <span className="text-slate-500 dark:text-slate-400">
                              {t("clawmonitor.noSkills")}
                            </span>
                          )}
                        </div>
                      </div>
                    ),
                  },
                ]}
              />
            </Card>
          ) : (
            /* List view: type tabs + instance cards */
            <>
              <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
                <Segmented
                  value={instanceType}
                  onChange={(v) => setInstanceType(v as InstanceType)}
                  options={[
                    {
                      label: (
                        <span className="flex items-center gap-2">
                          <Box className="h-4 w-4" />
                          {t("clawmonitor.containers")} ({MOCK_CONTAINERS.length})
                        </span>
                      ),
                      value: "container",
                    },
                    {
                      label: (
                        <span className="flex items-center gap-2">
                          <Server className="h-4 w-4" />
                          {t("clawmonitor.virtualMachines")} ({MOCK_VMS.length})
                        </span>
                      ),
                      value: "vm",
                    },
                  ]}
                />
              </div>
              <Row gutter={[16, 16]}>
                {instanceList.map((inst) => (
                  <Col xs={24} sm={12} lg={8} key={inst.id}>
                    <Card
                      className="border border-slate-200 dark:border-slate-700 rounded-xl h-full transition-all hover:shadow-md hover:border-blue-300 dark:hover:border-blue-600 cursor-pointer"
                      styles={{ body: { padding: "20px" } }}
                      onClick={() => setSelectedId(inst.id)}
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
                            // TODO: delete
                          }}
                        >
                          {t("clawmonitor.delete")}
                        </Button>,
                      ]}
                    >
                      <div className="flex flex-col h-full">
                        <div className="flex items-start justify-between mb-3">
                          <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-emerald-100 dark:bg-emerald-900/30">
                            {inst.type === "container" ? (
                              <Box className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
                            ) : (
                              <Server className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
                            )}
                          </div>
                          <StatusLabel status={inst.status} t={t} compact />
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
  const config = {
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
  const { icon: Icon, text, className } = config[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 ${compact ? "text-xs" : "text-sm"} ${className}`}
    >
      <Icon className={compact ? "h-3.5 w-3.5" : "h-4 w-4"} />
      {text}
    </span>
  );
}
