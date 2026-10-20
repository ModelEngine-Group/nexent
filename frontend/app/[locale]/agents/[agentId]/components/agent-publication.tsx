// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Alert, App, Button, Collapse, Spin, Table, Tag, Tooltip } from "antd";
import {
  Copy,
  ExternalLink,
  Info,
  Link,
  Send,
  Share2,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { StandardButton } from "@/components/common/StandardButton";
import { StandardInput } from "@/components/common/StandardInput";
import {
  buildAgentShareUrl,
  buildCopyAriaLabel,
  buildNorthboundCurl,
  buildNorthboundDocsUrl,
  buildNorthboundRunUrl,
  buildUserApiKeyPath,
  getA2AGuideState,
} from "@/lib/agentUsageGuide";
import { a2aClientService } from "@/services/a2aService";
import { configService } from "@/services/configService";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";

interface AgentPublicationProps {
  agentId: number;
  agentName: string;
}

export function AgentPublication({
  agentId,
  agentName,
}: AgentPublicationProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { locale } = useParams<{ locale: string }>();
  const [showA2AHelp, setShowA2AHelp] = useState(false);
  const frontendConfig = useQuery({
    queryKey: ["frontend-config"],
    queryFn: () => configService.fetchRuntimeFrontendConfig(),
  });
  const publishedAgents = usePublishedAgentList();
  const a2a = useQuery({
    queryKey: ["a2aServerSettings", agentId],
    queryFn: async () => {
      const result = await a2aClientService.getServerSettings(agentId);
      if ((!result.success || !result.data) && result.statusCode !== 404) {
        throw new Error(result.message);
      }
      return result;
    },
  });
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const shareUrl = buildAgentShareUrl(origin, locale, agentId);
  const northboundUrl = buildNorthboundRunUrl(
    frontendConfig.data?.northboundBaseUrl,
    origin
  );
  const publishedName = publishedAgents.data?.find(
    (agent) => agent.id === String(agentId)
  )?.name;
  const curl = buildNorthboundCurl(
    publishedName?.trim() || agentName,
    northboundUrl
  );
  const settings = a2a.data?.data;
  const a2aGuideState = getA2AGuideState({
    isLoading: a2a.isPending,
    isError: a2a.isError,
    isEnabled: Boolean(a2a.data?.success && settings?.is_enabled),
  });
  const interfaces = settings?.supported_interfaces ?? [];
  const rest = interfaces.find((entry) =>
    ["http+json", "httprest"].includes(
      String(entry.protocolBinding).toLowerCase()
    )
  );
  const rpc = interfaces.find((entry) =>
    ["jsonrpc", "json-rpc"].includes(
      String(entry.protocolBinding).toLowerCase()
    )
  );
  const restUrl =
    typeof rest?.url === "string" ? rest.url.replace(/\/$/, "") : "";
  const rpcUrl = typeof rpc?.url === "string" ? rpc.url : "";
  const rows = [
    ...(restUrl
      ? [
          {
            key: "send",
            protocol: "HTTP+JSON (REST)",
            method: "POST",
            endpoint: `${restUrl}/message:send`,
            description: "—",
          },
          {
            key: "stream",
            protocol: "HTTP+JSON (REST)",
            method: "POST",
            endpoint: `${restUrl}/message:stream`,
            description: "—",
          },
          {
            key: "task",
            protocol: "HTTP+JSON (REST)",
            method: "GET",
            endpoint: `${restUrl}/tasks/{task_id}`,
            description: "—",
          },
        ]
      : []),
    ...(rpcUrl
      ? [
          {
            key: "rpc",
            protocol: "JSON-RPC",
            method: "POST",
            endpoint: rpcUrl,
            description: [
              'SendMessage: method="SendMessage"',
              'SendStreamingMessage: method="SendStreamingMessage"',
              'GetTask: method="GetTask"',
            ].join("\n"),
          },
        ]
      : []),
  ];

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      message.success(t("common.copied"));
    } catch {
      message.error(t("agentUsageGuide.copyFailed"));
    }
  };
  const copyField = (
    label: string,
    value: string,
    options: { hint?: string; prefix?: string; hideLabel?: boolean } = {}
  ) => (
    <div className="flex w-[564px] max-w-full flex-col gap-2">
      {!options.hideLabel && (
        <span className="inline-flex items-center gap-1 text-sm text-[#191919]">
          {label}
          {options.hint && (
            <Tooltip title={options.hint}>
              <button
                type="button"
                aria-label={options.hint}
                className="inline-flex text-[#808080]"
              >
                <Info size={14} aria-hidden />
              </button>
            </Tooltip>
          )}
        </span>
      )}
      <StandardInput
        readOnly
        aria-label={label}
        value={value}
        prefix={
          options.prefix ? (
            <Tag color="blue" className="!m-0">
              {options.prefix}
            </Tag>
          ) : undefined
        }
        className="!bg-[#f5f5f5] !border-transparent"
        suffix={
          <Tooltip title={t("common.copy")}>
            <Button
              type="text"
              size="small"
              aria-label={buildCopyAriaLabel(t("common.copy"), label)}
              icon={<Copy size={14} />}
              onClick={() => copy(value)}
            />
          </Tooltip>
        }
      />
    </div>
  );

  return (
    <div
      data-testid="agent-publication-content"
      className="mx-4 mb-5 min-h-0 flex-1 overflow-y-auto rounded-lg bg-white px-6 py-8"
    >
      <Collapse
        ghost
        defaultActiveKey={["share", "api", "a2a"]}
        expandIconPlacement="end"
        className="flex flex-col gap-8 [&_.ant-collapse-title]:!flex-none [&_.ant-collapse-title]:!me-0 [&_.ant-collapse-extra]:!order-2 [&_.ant-collapse-extra]:!ms-3 [&_.ant-collapse-header]:!p-0 [&_.ant-collapse-header]:!bg-transparent [&_.ant-collapse-header]:!shadow-none [&_.ant-collapse-body]:!px-0 [&_.ant-collapse-body]:!pt-4 [&_.ant-collapse-body]:!pb-0 [&_.ant-collapse-content-box]:!px-0 [&_.ant-collapse-content-box]:!pt-4 [&_.ant-collapse-content-box]:!pb-0"
        items={[
          {
            key: "share",
            label: (
              <span className="flex items-center gap-2 font-medium">
                <Link size={18} />
                {t("agentUsageGuide.tabs.share")}
              </span>
            ),
            children: (
              <div className="flex flex-col gap-4">
                <p className="text-xs text-[#808080]">
                  {t("agent.publication.shareDescription")}
                </p>
                <Alert
                  className="!rounded-lg"
                  type="info"
                  showIcon
                  closable
                  title={t("agentUsageGuide.share.notice")}
                />
                <div className="flex flex-wrap items-end gap-3">
                  {copyField(t("agent.publication.agentLink"), shareUrl)}
                  <StandardButton icon={<Send size={14} />} href={shareUrl}>
                    {t("agent.publication.preview")}
                  </StandardButton>
                  <StandardButton
                    icon={<Share2 size={14} />}
                    onClick={() => copy(shareUrl)}
                  >
                    {t("agent.publication.share")}
                  </StandardButton>
                </div>
              </div>
            ),
          },
          {
            key: "api",
            label: (
              <span className="flex flex-wrap items-center gap-2 font-medium">
                <ShieldCheck size={18} />
                {t("agent.publication.apiTitle")}
              </span>
            ),
            extra: (
              <a
                href={buildNorthboundDocsUrl(locale)}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(event) => event.stopPropagation()}
                className="inline-flex items-center gap-1 text-xs font-normal text-primary"
              >
                {t("agent.publication.docs")}
                <ExternalLink size={12} />
              </a>
            ),
            children: (
              <div className="flex flex-col gap-4">
                <p className="text-xs text-[#808080]">
                  {t("agent.publication.apiDescription")}
                </p>
                <p className="text-sm">{t("agent.publication.apiProcess")}</p>
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                  {["key", "call", "response"].map((step, index) => (
                    <div
                      key={step}
                      className="min-w-0 rounded-lg bg-gradient-to-br from-[#eef3ff] to-[#f8fbff] p-5 flex flex-col gap-3"
                    >
                      <h3 className="text-sm font-medium">
                        {t(`agent.publication.steps.${step}.title`, {
                          step: index + 1,
                        })}
                      </h3>
                      <p className="text-xs leading-5 text-[#808080]">
                        {t(`agent.publication.steps.${step}.description`)}
                      </p>
                      {step === "key" && (
                        <a
                          href={buildUserApiKeyPath(locale)}
                          className="inline-block text-xs text-primary"
                        >
                          API Key: {t("agent.publication.getKey")}
                        </a>
                      )}
                    </div>
                  ))}
                </div>
                {frontendConfig.isPending || publishedAgents.isPending ? (
                  <Spin size="small" />
                ) : frontendConfig.isError || publishedAgents.isError ? (
                  <Alert
                    className="!rounded-lg"
                    type="error"
                    showIcon
                    title={t("agent.publication.loadFailed")}
                    action={
                      <Button
                        size="small"
                        onClick={() => {
                          void frontendConfig.refetch();
                          void publishedAgents.refetch();
                        }}
                      >
                        {t("common.retry")}
                      </Button>
                    }
                  />
                ) : (
                  <details open className="text-xs">
                    <summary className="w-fit cursor-pointer text-primary">
                      {t("agent.publication.example")}
                    </summary>
                    <div className="relative mt-4 rounded-lg bg-[#f5f5f5] p-4">
                      <Button
                        type="text"
                        icon={<Copy size={14} />}
                        aria-label={buildCopyAriaLabel(
                          t("common.copy"),
                          t("agent.publication.example")
                        )}
                        className="!absolute right-3 top-3"
                        onClick={() => copy(curl)}
                      />
                      <pre className="overflow-x-auto whitespace-pre-wrap break-all pr-10 leading-6">
                        <code>{curl}</code>
                      </pre>
                    </div>
                  </details>
                )}
              </div>
            ),
          },
          {
            key: "a2a",
            label: (
              <span className="flex items-center gap-2 font-medium">
                <Workflow size={18} />
                {t("agent.publication.a2aTitle")}
              </span>
            ),
            children: (
              <div className="flex flex-col gap-4">
                <p className="text-xs text-[#808080]">
                  {t("agent.publication.a2aDescription")}
                </p>
                <Alert
                  className="!rounded-lg"
                  type="info"
                  showIcon
                  closable
                  title={
                    <span className="inline-flex flex-wrap items-center gap-2">
                      {t("a2a.server.usageTitle")}
                      <Button
                        type="link"
                        size="small"
                        aria-expanded={showA2AHelp}
                        onClick={() => setShowA2AHelp((shown) => !shown)}
                      >
                        {t(
                          showA2AHelp
                            ? "agent.publication.hideHelp"
                            : "agent.publication.showHelp"
                        )}
                      </Button>
                    </span>
                  }
                  description={
                    showA2AHelp ? (
                      <div className="flex flex-col gap-2">
                        <p>{t("a2a.server.localDevHint")}</p>
                        <p>{t("a2a.server.productionHint")}</p>
                      </div>
                    ) : undefined
                  }
                />
                {a2aGuideState === "loading" ? (
                  <Spin size="small" />
                ) : a2aGuideState === "error" ? (
                  <Alert
                    className="!rounded-lg"
                    type="error"
                    showIcon
                    title={t("agent.publication.loadFailed")}
                    action={
                      <Button size="small" onClick={() => void a2a.refetch()}>
                        {t("common.retry")}
                      </Button>
                    }
                  />
                ) : a2aGuideState === "disabled" || !settings ? (
                  <Alert
                    className="!rounded-lg"
                    type="info"
                    showIcon
                    title={t("agentUsageGuide.a2a.notEnabled")}
                  />
                ) : (
                  <>
                    {settings.endpoint_id &&
                      copyField(
                        t("a2a.server.endpointId"),
                        settings.endpoint_id
                      )}
                    {settings.endpoint_id &&
                      copyField(
                        t("a2a.server.agentCardUrl"),
                        `/nb/a2a/${settings.endpoint_id}/.well-known/agent-card.json`,
                        { hint: t("a2a.server.urlHint") }
                      )}
                    <div className="flex w-[564px] max-w-full flex-col gap-3">
                      <span className="text-sm text-[#191919]">
                        {t("agent.publication.localDevelopment")}
                      </span>
                      {copyField(
                        `${t("agent.publication.localDevelopment")} Docker`,
                        "http://localhost:5013/api",
                        { prefix: "Docker", hideLabel: true }
                      )}
                      {copyField(
                        `${t("agent.publication.localDevelopment")} K8s`,
                        "http://localhost:30013/api",
                        { prefix: "K8s", hideLabel: true }
                      )}
                    </div>
                    <div className="flex flex-col gap-3 text-sm">
                      <span>{t("a2a.server.protocolVersion")}</span>
                      <p>
                        {interfaces
                          .map((entry) => entry.protocolVersion)
                          .filter(
                            (value): value is string =>
                              typeof value === "string"
                          )
                          .filter(
                            (value, index, values) =>
                              values.indexOf(value) === index
                          )
                          .join(" / ") || "—"}
                      </p>
                    </div>
                    <div className="flex flex-col gap-3 text-sm">
                      <span className="inline-flex items-center gap-1">
                        {t("agent.publication.interfaces")}
                        <Tooltip title={t("agent.publication.a2aHelp")}>
                          <Info size={14} />
                        </Tooltip>
                      </span>
                      <Table
                        size="small"
                        pagination={false}
                        dataSource={rows}
                        tableLayout="fixed"
                        scroll={{ x: 860 }}
                        columns={[
                          {
                            title: t("agent.publication.protocol"),
                            dataIndex: "protocol",
                            width: 180,
                          },
                          {
                            title: t("agent.publication.endpoint"),
                            dataIndex: "endpoint",
                            width: 380,
                            render: (endpoint: string, row) => (
                              <span className="break-all font-mono text-xs">
                                <Tag
                                  color={
                                    row.method === "GET" ? "purple" : "cyan"
                                  }
                                >
                                  {row.method}
                                </Tag>
                                {endpoint}
                              </span>
                            ),
                          },
                          {
                            title: t("agent.publication.description"),
                            dataIndex: "description",
                            render: (description: string) => (
                              <span className="whitespace-pre-wrap break-words text-xs leading-6">
                                {description}
                              </span>
                            ),
                          },
                        ]}
                      />
                    </div>
                  </>
                )}
              </div>
            ),
          },
        ]}
      />
    </div>
  );
}
