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
  const { t } = useTranslation("common");
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
          <div className="flex min-h-0 flex-1 flex-col font-['HarmonyOS_Sans_SC',sans-serif] text-sm leading-[22px] text-[#191919]">
            <header className="shrink-0 space-y-2 pb-2">
              <div className="flex min-h-14 items-center gap-3 pr-6">
                <span className="shrink-0">{icon}</span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-x-2">
                    <h2 className="min-w-0 break-words text-xl font-medium leading-7">
                      {service.name}
                    </h2>
                    <span className="rounded bg-[#D0D8FD]/50 px-2 text-xs leading-5 text-[#1F55B5]">
                      {deploymentLabel}
                    </span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-2">
                    {tags.map((label, index) => (
                      <span
                        key={index}
                        className="max-w-full break-words rounded bg-[#191919]/5 px-2 text-xs leading-5 text-[#393939]"
                      >
                        {label}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs leading-[18px] text-[#191919]/70">
                <span className="break-all">
                  {t("resourceCenter.author")}：{author}
                </span>
                <span>
                  {t("resourceCenter.publishedAt")}：
                  {service.publishedAt?.slice(0, 10) ||
                    t("resourceCenter.notRecorded")}
                </span>
                <span>
                  {t("agentRepository.detail.downloads", {
                    count: downloadCount,
                  })}
                </span>
              </div>
            </header>
            <div className="flex min-h-0 flex-1 flex-col gap-8 overflow-hidden">
              <p className="shrink-0 whitespace-pre-wrap break-words">
                {service.description || t("mcpTools.detail.noDescription")}
              </p>
              <section className="flex min-h-0 flex-1 flex-col gap-2">
                <h3 className="shrink-0 font-medium">
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
                <div className="repository-detail-body min-h-0 space-y-2 overflow-y-auto">
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
            <footer className="flex shrink-0 justify-end gap-2 pt-8">
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
