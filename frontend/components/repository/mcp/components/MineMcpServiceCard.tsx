// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import ResourceReviewLink from "@/components/repository/ResourceReviewLink";
import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";
import { CheckCircleFilled } from "@ant-design/icons";
import type { ReactNode } from "react";
import { Button, Dropdown, type MenuProps } from "antd";
import { Clock, MoreHorizontal, Puzzle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { McpServiceStatus, McpDeploymentType } from "@/const/mcpTools";
import type { CommunityMcpCard, McpServiceItem } from "@/types/mcpTools";
import {
  formatRegistryDate,
  getDeploymentTypeLabelKey,
  resolveDeploymentType,
} from "@/lib/mcpTools";
import { getMineCardReviewBadge } from "@/lib/mcpToolsMine";
import ResourceTagChips from "@/components/tag/ResourceTagChips";
import ResourceCard from "@/components/resource/ResourceCard";
import TransportIcon from "./shared/TransportIcon";

export type MineMcpCardItem =
  | { kind: "local"; service: McpServiceItem }
  | { kind: "community"; service: CommunityMcpCard };

export type McpConnectionStatus = "unchecked" | "success" | "failed";

interface MineMcpServiceCardProps {
  item: MineMcpCardItem;
  selection?: ReactNode;
  onlineService?: CommunityMcpCard;
  toggling?: boolean;
  publishing?: boolean;
  unpublishing?: boolean;
  healthChecking?: boolean;
  connectionStatus?: McpConnectionStatus;
  tagRefreshKey?: string | number;
  onEditLocal: (service: McpServiceItem) => void;
  onEditCommunity: (service: CommunityMcpCard) => void;
  onToggle: (service: McpServiceItem) => void;
  onSubmitVersionUpdate: (
    item: MineMcpCardItem,
    onlineService?: CommunityMcpCard
  ) => void;
  onUnpublishOnline: (
    item: MineMcpCardItem,
    onlineService: CommunityMcpCard
  ) => void;
  onDelete: (item: MineMcpCardItem) => void;
  onViewReviewProgress?: (
    item: MineMcpCardItem,
    onlineService?: CommunityMcpCard
  ) => void;
  onHealthCheck?: (item: MineMcpCardItem) => void;
}

export default function MineMcpServiceCard({
  item,
  selection,
  onlineService,
  toggling,
  publishing,
  unpublishing,
  healthChecking = false,
  connectionStatus = "unchecked",
  tagRefreshKey,
  onEditLocal,
  onEditCommunity,
  onToggle,
  onSubmitVersionUpdate,
  onUnpublishOnline,
  onDelete,
  onViewReviewProgress,
  onHealthCheck,
}: MineMcpServiceCardProps) {
  const { t } = useTranslation("common");
  const presentation = useRepositoryPresentation();
  const repositoryCard = presentation?.layout === "cards";
  const service = item.service;
  const tags = service.tags || [];
  const deploymentType = resolveDeploymentType(service);
  const deploymentLabel = t(getDeploymentTypeLabelKey(deploymentType));
  const isLocal = item.kind === "local";
  const localService = isLocal ? item.service : null;
  const isEnabled = localService?.enabled === McpServiceStatus.ENABLED;
  const localStatusLabel = !localService
    ? t("market.install.mcp.notInstalled")
    : t(isEnabled ? "mcpTools.mine.enabled" : "mcpTools.status.disabled");
  const reviewStatus = onlineService?.reviewStatus || service.reviewStatus;
  const isPending = reviewStatus === "pending";
  const isAlreadyListed = isLocal
    ? Boolean(localService?.isListedInRepository) ||
      localService?.latest_review?.status === "approved" ||
      reviewStatus === "approved"
    : reviewStatus === "approved";
  const hasVersionUpdateTarget =
    item.kind === "community"
      ? Boolean(item.service.marketId)
      : Boolean(onlineService?.marketId);
  const hasOnlineRecord = isLocal
    ? Boolean(onlineService) && onlineService?.reviewStatus === "approved"
    : reviewStatus === "approved";
  const reviewBadge =
    reviewStatus === "approved"
      ? getMineCardReviewBadge(item, onlineService)
      : null;
  const createDate = formatRegistryDate(
    item.kind === "local"
      ? item.service.createTime || ""
      : item.service.createdAt || ""
  );
  const updatedDate = formatRegistryDate(service.updatedAt || "");
  const installCount = onlineService?.installCount ?? 0;
  const iconTone =
    deploymentType === McpDeploymentType.REMOTE_LINK
      ? "bg-[#EEE0F7] text-[#743E9C]"
      : deploymentType === McpDeploymentType.API
        ? "bg-[#E0F2D2] text-[#316614]"
        : "bg-[#D0D8FD]/50 text-[#1F55B5]";
  const toolCount = resolveToolCount(item);

  // Owned = user-created MCP can be published/updated; community-installed
  // or registry-installed MCPs only permit deletion.
  const isOwned =
    item.kind === "community" || localService?.permission === "EDIT";

  const actionItems: MenuProps["items"] = (() => {
    const items: MenuProps["items"] = [];
    if (onHealthCheck && localService && isOwned) {
      items.push({
        key: "health-check",
        label: t("mcpConfig.serverList.button.healthCheck"),
        disabled: healthChecking,
        onClick: () => onHealthCheck(item),
      });
    }

    if (localService) {
      items.push({
        key: "toggle",
        label: t(isEnabled ? "mcpTools.mine.disable" : "mcpTools.mine.enable"),
        disabled: toggling,
        onClick: () => onToggle(localService),
      });
    }

    if (!isOwned) {
      return [
        ...items,
        {
          key: "delete",
          label: t("common.delete"),
          danger: true,
          onClick: () => onDelete(item),
        },
      ];
    }

    // Show "view review progress" for any submitted status (pending/approved/rejected)
    if (
      !localService?.latest_review &&
      (reviewStatus === "pending" ||
        reviewStatus === "approved" ||
        reviewStatus === "rejected")
    ) {
      items.push({
        key: "view-review-progress",
        label: t("mcpTools.mine.viewReviewProgress"),
        onClick: () => onViewReviewProgress?.(item, onlineService),
      });
    }

    const isPendingReview =
      localService?.latest_review?.status === "pending_review" || isPending;
    if (
      !isPendingReview &&
      (!isAlreadyListed || hasVersionUpdateTarget) &&
      (deploymentType === McpDeploymentType.REMOTE_LINK ||
        deploymentType === McpDeploymentType.CONTAINER)
    ) {
      // only remote link and container MCPs can be published to community
      items.push({
        key: isAlreadyListed ? "submit-version-update" : "apply-for-listing",
        label: isAlreadyListed
          ? t("mcpTools.mine.submitVersionUpdate")
          : t("repository.mine.applyForListing"),
        disabled: publishing,
        onClick: () => onSubmitVersionUpdate(item, onlineService),
      });
    }

    if (hasOnlineRecord) {
      items.push({
        key: "unpublish-online-version",
        label: isPending
          ? t("mcpTools.mine.reviewModal.cancelApply")
          : t("mcpTools.mine.unpublishOnlineVersion"),
        danger: true,
        disabled: unpublishing,
        onClick: () => {
          if (onlineService) onUnpublishOnline(item, onlineService);
        },
      });
    }

    items.push({
      key: "delete",
      label: t("common.delete"),
      danger: true,
      onClick: () => onDelete(item),
    });

    return items;
  })();

  const handleEdit = () => {
    if (item.kind === "local") onEditLocal(item.service);
    else onEditCommunity(item.service);
  };

  return (
    <ResourceCard
      actionsOnly={presentation?.layout === "list"}
      className="h-full"
      title={
        repositoryCard ? (
          <span className="flex min-w-0 items-center gap-2">
            <span className="truncate" title={service.name}>
              {service.name}
            </span>
            <span className="shrink-0 rounded bg-[#D0D8FD]/50 px-2 text-xs leading-5 font-normal text-[#1F55B5]">
              {deploymentLabel}
            </span>
            {reviewBadge && (
              <span className="shrink-0 rounded bg-emerald-50 px-2 text-xs leading-5 font-normal text-emerald-700">
                {t(reviewBadge.labelKey)}
              </span>
            )}
          </span>
        ) : (
          service.name
        )
      }
      subtitle={
        !repositoryCard && (
          <span
            className={`inline-flex items-center gap-1.5 ${
              connectionStatus === "success"
                ? "text-green-600 dark:text-green-400"
                : connectionStatus === "failed"
                  ? "text-red-600 dark:text-red-400"
                  : "text-slate-500 dark:text-slate-400"
            }`}
          >
            <span
              aria-hidden="true"
              className={`size-1.5 shrink-0 rounded-full ${
                connectionStatus === "success"
                  ? "bg-green-500"
                  : connectionStatus === "failed"
                    ? "bg-red-500"
                    : "bg-slate-400"
              }`}
            />
            {t(`mcpTools.mine.connectionStatus.${connectionStatus}`)}
          </span>
        )
      }
      onClick={handleEdit}
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
            className="!size-11 rounded-xl"
          />
        )
      }
      description={service.description || t("mcpTools.detail.noDescription")}
      descriptionLines={repositoryCard ? 1 : undefined}
      tagsPlacement={repositoryCard ? "header" : "body"}
      tags={
        <>
          {!repositoryCard && (
            <span className="rounded-md bg-slate-100 px-2 py-0.5 font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200">
              {deploymentLabel}
            </span>
          )}
          {tags.slice(0, 3).map((tag) => (
            <span
              key={`${service.name}-${tag}`}
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
          {item.kind === "local" ? (
            <ResourceTagChips
              resourceType="mcp_service"
              resourceId={String(item.service.mcpId)}
              max={3}
              refreshKey={tagRefreshKey}
            />
          ) : null}
          {!repositoryCard && (
            <span className="rounded-md border border-slate-200 px-2 py-0.5 text-slate-500 dark:border-slate-700 dark:text-slate-400">
              {t("mcpTools.repository.toolCount", { count: toolCount })}
            </span>
          )}
        </>
      }
      meta={
        repositoryCard ? (
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="inline-flex items-center gap-1">
              <span
                aria-hidden
                className={`size-1.5 rounded-full ${isEnabled ? "bg-blue-500" : "bg-[#777777]"}`}
              />
              {localStatusLabel}
            </span>
            <span>
              {t("agentRepository.detail.downloads", { count: installCount })}
            </span>
            {updatedDate && (
              <span className="inline-flex items-center gap-1">
                <Clock size={12} aria-hidden />
                {t("agentConfig.list.updatedAt", { date: updatedDate })}
              </span>
            )}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1">
            <Clock className="size-3.5 text-slate-400" />
            {createDate}
          </span>
        )
      }
      headerActions={
        selection ?? (
          <div className="flex flex-col items-start gap-1">
            <div className="flex items-center gap-1">
              <Dropdown
                menu={{ items: actionItems }}
                trigger={["click"]}
                placement="bottomRight"
              >
                <Button
                  type="text"
                  size="small"
                  icon={<MoreHorizontal className="size-4" />}
                  loading={publishing || unpublishing}
                  aria-label={t("mcpTools.mine.moreActions")}
                  className="-mt-1 text-slate-500 hover:!text-slate-700"
                />
              </Dropdown>
            </div>
            {presentation?.layout !== "list" ? (
              <ResourceReviewLink review={localService?.latest_review} />
            ) : null}
            {!repositoryCard && presentation?.layout !== "list" && reviewBadge ? (
              <span
                className={`self-end rounded-md px-1.5 py-0.5 text-[11px] font-medium ${
                  reviewBadge.variant === "pending"
                    ? "bg-orange-50 text-orange-700"
                    : reviewBadge.variant === "approved"
                      ? "bg-emerald-50 text-emerald-700"
                      : "bg-red-50 text-red-700"
                }`}
              >
                {t(reviewBadge.labelKey)}
              </span>
            ) : null}
          </div>
        )
      }
      footer={
        repositoryCard && onHealthCheck && isOwned && connectionStatus !== "unchecked" ? (
          <span
            className={`inline-flex items-center gap-1 text-xs ${
              connectionStatus === "success" ? "text-emerald-700" : "text-red-600"
            }`}
          >
            {connectionStatus === "success" ? (
              <CheckCircleFilled aria-hidden />
            ) : (
              <span aria-hidden className="size-1.5 rounded-full bg-red-500" />
            )}
            {t(`mcpTools.mine.connectionStatus.${connectionStatus}`)}
          </span>
        ) : null
      }
    />
  );
}

function resolveToolCount(item: MineMcpCardItem): number {
  if (item.kind === "local") {
    // For local MCPs installed from the community market, tools come from registryJson
    const registryTools = item.service.registryJson?.tools;
    if (Array.isArray(registryTools)) return registryTools.length;
    return item.service.tools?.length || 0;
  }
  const registryTools = item.service.registryJson?.tools;
  if (Array.isArray(registryTools)) return registryTools.length;
  if (item.service.packages?.length) return item.service.packages.length;
  if (item.service.remotes?.length) return item.service.remotes.length;
  return 0;
}
