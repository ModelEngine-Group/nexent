import { Button, Dropdown, Tooltip, type MenuProps } from "antd";
import {
  ArrowDownFromLine,
  Clock,
  MoreHorizontal,
  Power,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";
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
  onlineService?: CommunityMcpCard;
  toggling?: boolean;
  publishing?: boolean;
  unpublishing?: boolean;
  healthChecking?: boolean;
  connectionStatus?: McpConnectionStatus;
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
  onlineService,
  toggling,
  publishing,
  unpublishing,
  healthChecking = false,
  connectionStatus = "unchecked",
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
  const service = item.service;
  const tags = service.tags || [];
  const deploymentType = resolveDeploymentType(service);
  const deploymentLabel = t(getDeploymentTypeLabelKey(deploymentType));
  const isLocal = item.kind === "local";
  const localService = isLocal ? item.service : null;
  const isEnabled = localService?.enabled === McpServiceStatus.ENABLED;
  const reviewStatus = onlineService?.reviewStatus || service.reviewStatus;
  const isPending = reviewStatus === "pending";
  const hasOnlineRecord = isLocal
    ? Boolean(onlineService) &&
      (onlineService?.reviewStatus === "approved" ||
        onlineService?.reviewStatus === "pending")
    : reviewStatus === "approved";
  const reviewBadge = getMineCardReviewBadge(item, onlineService);
  const createDate = formatRegistryDate(
    item.kind === "local"
      ? item.service.createTime || ""
      : item.service.createdAt || ""
  );
  const toolCount = resolveToolCount(item);

  // Owned = user-created MCP can be published/updated; community-installed
  // or registry-installed MCPs only permit deletion.
  const isOwned =
    item.kind === "community" || localService?.permission === "EDIT";

  const actionItems: MenuProps["items"] = (() => {
    if (!isOwned) {
      return [
        {
          key: "delete",
          label: t("common.delete"),
          icon: <Trash2 className="h-3.5 w-3.5" />,
          danger: true,
          onClick: () => onDelete(item),
        },
      ];
    }

    const items: MenuProps["items"] = [];

    // Show "view review progress" for any submitted status (pending/approved/rejected)
    if (
      reviewStatus === "pending" ||
      reviewStatus === "approved" ||
      reviewStatus === "rejected"
    ) {
      items.push({
        key: "view-review-progress",
        label: t("mcpTools.mine.viewReviewProgress"),
        icon: <Clock className="h-3.5 w-3.5" />,
        onClick: () => onViewReviewProgress?.(item, onlineService),
      });
    }

    if (
      reviewStatus !== "approved" &&
      reviewStatus !== "pending" &&
      (deploymentType === McpDeploymentType.REMOTE_LINK ||
        deploymentType === McpDeploymentType.CONTAINER)
    ) {
      // only remote link and container MCPs can be published to community
      items.push({
        key: "apply-for-listing",
        label: t("repository.mine.applyForListing"),
        icon: <Upload className="h-3.5 w-3.5" />,
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
        icon: <ArrowDownFromLine className="h-3.5 w-3.5" />,
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
      icon: <Trash2 className="h-3.5 w-3.5" />,
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
      className="h-full"
      title={service.name}
      subtitle={
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
      }
      onClick={handleEdit}
      footerLayout="inline"
      icon={
        <TransportIcon
          transportType={service.transportType}
          deploymentType={deploymentType}
          label={deploymentLabel}
          seed={service.name}
          className="!size-11 rounded-xl"
        />
      }
      description={service.description || t("mcpTools.detail.noDescription")}
      tags={
        <>
          <span className="rounded-md bg-slate-100 px-2 py-0.5 font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200">
            {deploymentLabel}
          </span>
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
            />
          ) : null}
          <span className="rounded-md border border-slate-200 px-2 py-0.5 text-slate-500 dark:border-slate-700 dark:text-slate-400">
            {t("mcpTools.repository.toolCount", { count: toolCount })}
          </span>
        </>
      }
      meta={
        <span className="inline-flex items-center gap-1">
          <Clock className="size-3.5 text-slate-400" />
          {createDate}
        </span>
      }
      headerActions={
        <div className="flex flex-col items-start gap-1">
          <div className="flex items-center gap-1">
            {onHealthCheck && isOwned ? (
              <Tooltip
                title={t("mcpConfig.serverList.button.healthCheck")}
                placement="top"
              >
                <Button
                  type="text"
                  size="small"
                  icon={<RefreshCw className="size-4" />}
                  loading={healthChecking}
                  aria-label={t("mcpConfig.serverList.button.healthCheck")}
                  className="-mt-1 text-slate-500 hover:!text-slate-700"
                  onClick={() => onHealthCheck(item)}
                />
              </Tooltip>
            ) : null}
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
          {reviewBadge ? (
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
      }
      footer={
        localService ? (
          <Button
            type="text"
            size="small"
            className="!text-slate-600 hover:!bg-transparent hover:!text-blue-500"
            loading={toggling}
            icon={<Power className="size-3.5" />}
            onClick={() => onToggle(localService)}
          >
            {isEnabled ? t("mcpTools.mine.enabled") : t("mcpTools.mine.enable")}
          </Button>
        ) : (
          <Button disabled>{t("mcpTools.mine.publishedService")}</Button>
        )
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
