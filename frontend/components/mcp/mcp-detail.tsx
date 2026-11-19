// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useMemo, useState, type ReactNode } from "react";
import { App, Button } from "antd";
import {
  Download,
  ChevronDown,
  Server,
  Tag as TagIcon,
  UserRound,
  Wrench,
} from "lucide-react";
import { useUserDisplayName } from "@/hooks/auth/useUserDisplayName";
import { useTranslation } from "react-i18next";
import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";
import ResourceDetail from "@/components/resource/ResourceDetail";
import McpToolListModal from "@/components/mcp/McpToolListModal";
import {
  getDeploymentTypeLabelKey,
  resolveDeploymentType,
} from "@/lib/mcpTools";
import {
  resolveRepositoryMcpToolCount,
  resolveRepositoryMcpTools,
} from "@/lib/repositoryMcpDetail";
import { formatDateTimeLocale } from "@/lib/date";
import { listMcpRuntimeTools } from "@/services/mcpToolsService";
import type { McpTool } from "@/types/agentConfig";
import type { CommunityMcpCard } from "@/types/mcpTools";

interface McpDetailProps {
  open: boolean;
  service: CommunityMcpCard;
  installed: boolean;
  icon: ReactNode;
  onClose: () => void;
  onInstall: (service: CommunityMcpCard) => void;
}

export function McpDetail({
  open,
  service,
  installed,
  icon,
  onClose,
  onInstall,
}: McpDetailProps) {
  const { t, i18n } = useTranslation("common");
  const presentation = useRepositoryPresentation();
  const displayName = useUserDisplayName();
  const { message } = App.useApp();
  const [toolsOpen, setToolsOpen] = useState(false);
  const [loadingTools, setLoadingTools] = useState(false);
  const snapshotTools = useMemo(
    () => resolveRepositoryMcpTools(service),
    [service]
  );
  const [tools, setTools] = useState<McpTool[]>(snapshotTools);

  const deploymentLabel = t(
    getDeploymentTypeLabelKey(resolveDeploymentType(service))
  );
  const author = displayName(
    service.authorCasUsername,
    service.authorDisplayName ||
      service.authorName ||
      t("mcpTools.repository.authorFallback", {
        name: service.communityId ? ` ${service.communityId}` : "",
      })
  );
  const toolCount = resolveRepositoryMcpToolCount(service);
  const downloadCount = Number(service.installCount || 0);
  const tags = service.tags || [];

  const openTools = async () => {
    setToolsOpen(true);
    setTools(snapshotTools);
    if (!service.sourceMcpId) return;

    setLoadingTools(true);
    try {
      const result = await listMcpRuntimeTools(service.sourceMcpId);
      setTools(result.data || []);
    } catch {
      message.error(t("mcpTools.tools.loadFailed"));
    } finally {
      setLoadingTools(false);
    }
  };

  return (
    <>
      <ResourceDetail
        open={open}
        onClose={onClose}
        width={560}
        className="mcp-detail-modal [&_.ant-modal-close]:!z-20 [&_.ant-modal-content]:!overflow-hidden [&_.ant-modal-content]:!rounded-2xl [&_.ant-modal-content]:!p-0"
        bodyStyle={{ padding: 0 }}
      >
        {presentation?.resourceType === "mcp" ? (
          <div className="-mx-6 flex min-h-0 flex-1 flex-col text-sm leading-[22px] text-foreground">
            <header className="flex shrink-0 items-center gap-3 border-b border-border px-6 pb-4 pr-14">
              <div className="shrink-0">{icon}</div>
              <div className="min-w-0 flex-1">
                <h2 className="break-words text-xl font-medium leading-7">
                  {service.name}
                </h2>
                <span className="mt-1 inline-block rounded bg-primary/10 px-1.5 text-xs text-primary">
                  {deploymentLabel}
                </span>
              </div>
            </header>
            <div className="repository-detail-body min-h-0 flex-1 overflow-y-auto">
              <section className="space-y-3 border-b border-border px-6 py-5">
                <h3 className="font-semibold">
                  {t("resourceCenter.agentDetail.basicInfo")}
                </h3>
                <p
                  className={`whitespace-pre-wrap break-words ${service.description ? "" : "text-muted-foreground"}`}
                >
                  {service.description || t("mcpTools.detail.noDescription")}
                </p>
                {tags.length > 0 ? (
                  <ul
                    aria-label={t("agentRepository.mine.detail.tags")}
                    className="flex flex-wrap gap-1.5"
                  >
                    {tags.map((tag) => (
                      <li
                        key={tag}
                        className="max-w-full break-words rounded bg-primary/5 px-2 text-xs leading-5 text-muted-foreground"
                      >
                        {tag}
                      </li>
                    ))}
                  </ul>
                ) : null}
                <dl className="grid grid-cols-[minmax(5rem,max-content)_minmax(0,1fr)] gap-x-3 gap-y-1">
                  <div className="contents">
                    <dt className="text-muted-foreground">
                      {t("resourceCenter.author")}
                    </dt>
                    <dd className="min-w-0 [overflow-wrap:anywhere]">
                      {author}
                    </dd>
                  </div>
                  <div className="contents">
                    <dt className="text-muted-foreground">
                      {t("resourceCenter.publishedAt")}
                    </dt>
                    <dd className="min-w-0 [overflow-wrap:anywhere]">
                      {service.publishedAt ? (
                        <time dateTime={service.publishedAt}>
                          {formatDateTimeLocale(
                            service.publishedAt,
                            i18n?.language
                          )}
                        </time>
                      ) : (
                        t("resourceCenter.notRecorded")
                      )}
                    </dd>
                  </div>
                  <div className="contents">
                    <dt className="text-muted-foreground">
                      {t("skillRepository.detail.downloads")}
                    </dt>
                    <dd className="min-w-0 [overflow-wrap:anywhere]">
                      {downloadCount.toLocaleString()}
                    </dd>
                  </div>
                </dl>
              </section>
              <section className="space-y-3 px-6 py-5">
                <h3 className="font-semibold">
                  {t("mcpTools.detail.tools")}{" "}
                  <Button
                    type="link"
                    size="small"
                    className="!h-auto !px-1 !py-0 !text-xs"
                    onClick={() => void openTools()}
                  >
                    {t("mcpTools.repository.toolCount", { count: toolCount })}
                  </Button>
                </h3>
                <div className="space-y-2">
                  {snapshotTools.map((tool) => (
                    <details
                      key={tool.name}
                      className="group rounded bg-white px-4 py-[9px] text-xs leading-[18px] shadow-[inset_0_0_0_1px_#DFDFDF]"
                    >
                      <summary className="flex cursor-pointer list-none items-center gap-3">
                        <Wrench
                          className="size-[18px] shrink-0 rounded bg-[#E6F2FF] p-0.5 text-[#4285D7]"
                          aria-hidden
                        />
                        <span
                          className="max-w-full truncate font-medium"
                          title={tool.name}
                        >
                          {tool.name}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-[#191919]/70 group-open:invisible">
                          {tool.description}
                        </span>
                        <ChevronDown
                          className="size-3.5 shrink-0 group-open:rotate-180"
                          aria-hidden
                        />
                      </summary>
                      {tool.description && (
                        <p className="mt-2 whitespace-pre-wrap break-words font-['HarmonyHeiTi',sans-serif] text-[#191919]/70">
                          {tool.description}
                        </p>
                      )}
                    </details>
                  ))}
                </div>
              </section>
            </div>
            <footer className="-mx-6 flex shrink-0 items-center justify-end gap-2 border-t border-border bg-background px-6 py-3">
              <Button className="min-w-[88px]" onClick={onClose}>
                {t("common.close")}
              </Button>
              <Button
                type="primary"
                className="min-w-[88px] max-w-[200px]"
                disabled={installed}
                onClick={() => onInstall(service)}
              >
                {t(
                  installed
                    ? "mcpTools.repository.installed"
                    : "mcpTools.repository.install"
                )}
              </Button>
            </footer>
          </div>
        ) : (
          <div className="flex max-h-[min(740px,calc(100dvh-3rem))] flex-col overflow-hidden">
            <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4 pt-4 sm:px-4">
              <div className="flex items-start gap-3 pr-6">
                {icon}
                <div className="min-w-0 flex-1">
                  <h2 className="break-words text-lg font-semibold leading-7 text-slate-900 dark:text-slate-100">
                    {service.name}
                  </h2>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <span className="inline-flex items-center rounded-full border border-blue-100 bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 dark:border-blue-500/20 dark:bg-blue-500/10 dark:text-blue-300">
                      {deploymentLabel}
                    </span>
                  </div>
                </div>
              </div>

              <p className="mt-5 whitespace-pre-wrap text-sm leading-6 text-slate-600 dark:text-slate-300">
                {service.description || t("mcpTools.detail.noDescription")}
              </p>

              <div className="mt-3 flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
                <Download className="size-3.5" aria-hidden />
                <span className="shrink-0">
                  {t("mcpTools.repository.downloadCount")}
                </span>
                <span>{downloadCount.toLocaleString()}</span>
              </div>

              <div className="mt-4 space-y-2 rounded-xl bg-slate-50 px-3 py-3 text-sm dark:bg-slate-800/60">
                <div className="flex min-w-0 items-center gap-2 text-slate-500 dark:text-slate-400">
                  <UserRound className="size-4 shrink-0" aria-hidden />
                  <span className="shrink-0 whitespace-nowrap">
                    {t("mcpTools.repository.sourceLabel")}
                  </span>
                  <span
                    className="ml-auto min-w-0 flex-1 truncate text-right font-medium text-slate-900 dark:text-slate-100"
                    title={author}
                  >
                    {author}
                  </span>
                </div>
                <div className="flex min-w-0 items-center gap-2 text-slate-500 dark:text-slate-400">
                  <Server className="size-4 shrink-0" aria-hidden />
                  <span className="shrink-0 whitespace-nowrap">
                    {t("mcpTools.deploymentType.label")}
                  </span>
                  <span
                    className="ml-auto min-w-0 flex-1 truncate text-right font-medium text-slate-900 dark:text-slate-100"
                    title={deploymentLabel}
                  >
                    {deploymentLabel}
                  </span>
                </div>
              </div>

              <div className="mt-5 space-y-5">
                <section className="space-y-2">
                  <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800 dark:text-slate-100">
                    <Wrench
                      className="size-4 text-slate-500 dark:text-slate-400"
                      aria-hidden
                    />
                    {t("mcpTools.detail.tools")}
                    <Button
                      type="link"
                      size="small"
                      className="!h-auto !px-1 !py-0 !text-xs"
                      onClick={() => void openTools()}
                    >
                      {t("mcpTools.repository.toolCount", { count: toolCount })}
                    </Button>
                  </h3>
                  {snapshotTools.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {snapshotTools.map((tool) => (
                        <span
                          key={tool.name}
                          className="max-w-full break-all rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                        >
                          {tool.name}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </section>

                {tags.length > 0 ? (
                  <section className="space-y-2">
                    <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800 dark:text-slate-100">
                      <TagIcon
                        className="size-4 text-slate-500 dark:text-slate-400"
                        aria-hidden
                      />
                      {t("agentRepository.mine.detail.tags")}
                      <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium leading-none text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                        {tags.length}
                      </span>
                    </h3>
                    <div className="flex flex-wrap gap-1.5">
                      {tags.map((tag) => (
                        <span
                          key={tag}
                          className="rounded-md bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 dark:bg-blue-500/10 dark:text-blue-300"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  </section>
                ) : null}
              </div>
            </div>

            <div className="flex shrink-0 items-center justify-end gap-2 border-t border-slate-200 bg-slate-50/60 px-3 py-3 dark:border-slate-700 dark:bg-slate-900/60 sm:px-4">
              <Button onClick={onClose}>{t("common.close")}</Button>
              <Button
                type="primary"
                disabled={installed}
                icon={<Download className="size-4" />}
                onClick={() => onInstall(service)}
              >
                {installed
                  ? t("mcpTools.repository.installed")
                  : t("mcpTools.repository.install")}
              </Button>
            </div>
          </div>
        )}
      </ResourceDetail>
      <McpToolListModal
        open={toolsOpen}
        onCancel={() => setToolsOpen(false)}
        loading={loadingTools}
        tools={tools}
        serverName={service.name}
        zIndex={1100}
      />
    </>
  );
}
