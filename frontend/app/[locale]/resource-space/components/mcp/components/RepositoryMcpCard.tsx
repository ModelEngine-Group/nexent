// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";
import RepositoryCardActions from "@/app/resource-space/components/RepositoryCardActions";
import ResourcePublishedAt from "@/app/resource-space/components/ResourcePublishedAt";
import { Button, Dropdown, type MenuProps } from "antd";
import { Download, MoreHorizontal, Puzzle, Trash2 } from "lucide-react";
import { AgentCardTags } from "@/components/resource/AgentCardTags";
import { McpDeploymentType } from "@/const/mcpTools";
import { useUserDisplayName } from "@/hooks/auth/useUserDisplayName";
import { useTranslation } from "react-i18next";

import ResourceCard from "@/components/resource/ResourceCard";
import {
  getDeploymentTypeLabelKey,
  resolveDeploymentType,
} from "@/lib/mcpTools";
import type { CommunityMcpCard } from "@/types/mcpTools";
import TransportIcon from "./shared/TransportIcon";

interface RepositoryMcpCardProps {
  service: CommunityMcpCard;
  isAdmin: boolean;
  installed: boolean;
  onInstall: (service: CommunityMcpCard) => void;
  onSelect: (service: CommunityMcpCard) => void;
  onOffline: (service: CommunityMcpCard) => void;
}

export default function RepositoryMcpCard({
  service,
  isAdmin,
  installed,
  onInstall,
  onSelect,
  onOffline,
}: RepositoryMcpCardProps) {
  const { t } = useTranslation("common");
  const presentation = useRepositoryPresentation();
  const repositoryCard = presentation?.layout === "cards";
  const repositoryList = presentation?.layout === "list";
  const displayName = useUserDisplayName();
  const tags = service.tags || [];
  const deploymentType = resolveDeploymentType(service);
  const deploymentLabel = t(getDeploymentTypeLabelKey(deploymentType));
  const installCount = Number(service.installCount || 0);
  const toolCount = resolveToolCount(service);
  const author = displayName(
    service.authorCasUsername,
    service.authorDisplayName ||
      service.authorName ||
      t("mcpTools.repository.authorFallback")
  );
  const actionItems: MenuProps["items"] = isAdmin
    ? [
        {
          key: "offline",
          label: t("mcpTools.repository.offline"),
          icon: <Trash2 className="size-3.5" />,
          danger: true,
          onClick: () => onOffline(service),
        },
      ]
    : [];
  const installLabel = t(
    installed ? "mcpTools.repository.installed" : "mcpTools.repository.install"
  );
  const iconTone =
    deploymentType === McpDeploymentType.REMOTE_LINK
      ? "bg-[#EEE0F7] text-[#743E9C]"
      : deploymentType === McpDeploymentType.API
        ? "bg-[#E0F2D2] text-[#346522]"
        : "bg-[rgba(208,216,253,0.5)] text-[#1F55B5]";

  return (
    <ResourceCard
      actionsOnly={repositoryList}
      className="h-full"
      title={
        presentation ? (
          <span className="flex min-w-0 items-center gap-2">
            <span className="truncate" title={service.name}>
              {service.name}
            </span>
            <span className="h-5 shrink-0 rounded bg-[rgba(208,216,253,0.5)] px-2 text-xs leading-5 font-normal text-[#1F55B5]">
              {deploymentLabel}
            </span>
          </span>
        ) : (
          service.name
        )
      }
      subtitle={presentation ? <span title={author}>{author}</span> : undefined}
      footerLayout="inline"
      icon={
        repositoryCard ? (
          <span
            className={`flex size-12 items-center justify-center rounded ${iconTone}`}
          >
            <Puzzle size={24} aria-hidden />
          </span>
        ) : (
          <TransportIcon
            transportType={service.transportType}
            deploymentType={deploymentType}
            label={deploymentLabel}
            seed={service.name}
            className={
              presentation
                ? "!size-12 !rounded !bg-[rgba(208,216,253,0.5)] !text-[#1F55B5]"
                : "!size-11 rounded-xl"
            }
          />
        )
      }
      description={service.description || t("mcpTools.detail.noDescription")}
      tags={
        repositoryCard ? (
          // Always reserve the tag row so repository cards keep equal heights
          // regardless of whether the service has tags.
          <div className="h-6">
            {tags.length > 0 ? (
              <AgentCardTags labels={tags} maxVisible={5} />
            ) : null}
          </div>
        ) : (
          <>
            {!presentation && (
              <span className="rounded-md bg-slate-100 px-2 py-0.5 font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                {deploymentLabel}
              </span>
            )}
            {tags.slice(0, 3).map((tag) => (
              <span
                key={`${service.communityId || service.name}-${tag}`}
                className="rounded-md bg-slate-100 px-2 py-0.5 font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200"
              >
                {tag}
              </span>
            ))}
            {tags.length > 3 ? (
              <span className="rounded-md bg-slate-100 px-2 py-0.5 text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                +{tags.length - 3}
              </span>
            ) : null}
            <span className="rounded-md border border-slate-200 px-2 py-0.5 text-slate-500 dark:border-slate-700 dark:text-slate-400">
              {t("mcpTools.repository.toolCount", { count: toolCount })}
            </span>
          </>
        )
      }
      meta={
        repositoryCard ? (
          <>
            <span className="shrink-0">
              {t("agentRepository.detail.downloads", { count: installCount })}
            </span>
          </>
        ) : (
          <>
            {" "}
            {!presentation && (
              <span className="block truncate" title={author}>
                {author}
              </span>
            )}{" "}
            <ResourcePublishedAt value={service.publishedAt} />
            {presentation && (
              <span>
                {t("mcpTools.repository.downloadCount", {
                  count: installCount,
                })}
              </span>
            )}
          </>
        )
      }
      headerActions={
        <>
          {!presentation && (
            <span
              className="inline-flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400"
              aria-label={t("mcpTools.repository.downloadCount", {
                count: installCount,
              })}
            >
              <Download className="size-3.5" />
              {installCount}
            </span>
          )}
          {!presentation && actionItems.length > 0 ? (
            <Dropdown
              menu={{ items: actionItems }}
              trigger={["click"]}
              placement="bottomRight"
            >
              <Button
                type="text"
                size="small"
                icon={<MoreHorizontal className="size-4" />}
                aria-label={t("mcpTools.mine.moreActions")}
                className="-mt-1 text-slate-500 hover:!text-slate-700"
              />
            </Dropdown>
          ) : null}
        </>
      }
      footer={
        presentation ? (
          <RepositoryCardActions
            primary={
              installed
                ? undefined
                : { label: installLabel, onClick: () => onInstall(service) }
            }
            takeDown={
              isAdmin
                ? {
                    label: t("mcpTools.repository.offline"),
                    onClick: () => onOffline(service),
                  }
                : undefined
            }
          />
        ) : (
          <Button
            type="text"
            size="small"
            className={
              installed
                ? undefined
                : "!text-slate-600 hover:!bg-transparent hover:!text-blue-500"
            }
            disabled={installed}
            icon={<Download className="size-3.5" />}
            onClick={() => onInstall(service)}
          >
            {installed
              ? t("mcpTools.repository.installed")
              : t("mcpTools.repository.install")}
          </Button>
        )
      }
      onClick={() => onSelect(service)}
    />
  );
}

function resolveToolCount(service: CommunityMcpCard): number {
  const registryTools = service.registryJson?.tools;
  if (Array.isArray(registryTools)) return registryTools.length;
  const toolNames = service.registryJson?._toolNames;
  if (Array.isArray(toolNames)) return toolNames.length;
  if (service.packages?.length) return service.packages.length;
  if (service.remotes?.length) return service.remotes.length;
  return 0;
}
