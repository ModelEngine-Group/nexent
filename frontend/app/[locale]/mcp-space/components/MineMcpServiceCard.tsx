import { Button, Dropdown, type MenuProps } from "antd";
import { ArrowDownFromLine, Clock, Edit3, Hourglass, MoreHorizontal, Power, RefreshCw, Share2, Trash2, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import { McpServiceStatus, McpSource } from "@/const/mcpTools";
import type { CommunityMcpCard, McpServiceItem } from "@/types/mcpTools";
import {
  formatRegistryDate,
  getDeploymentTypeLabelKey,
  resolveDeploymentType,
} from "@/lib/mcpTools";
import TransportIcon from "./shared/TransportIcon";

export type MineMcpCardItem =
  | { kind: "local"; service: McpServiceItem }
  | { kind: "community"; service: CommunityMcpCard };

interface MineMcpServiceCardProps {
  item: MineMcpCardItem;
  onlineService?: CommunityMcpCard;
  toggling?: boolean;
  publishing?: boolean;
  unpublishing?: boolean;
  refreshingToolCount?: boolean;
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
  onViewReviewProgress?: (item: MineMcpCardItem, onlineService?: CommunityMcpCard) => void;
  onRefreshToolCount?: (item: MineMcpCardItem) => void;
}

export default function MineMcpServiceCard({
  item,
  onlineService,
  toggling,
  publishing,
  unpublishing,
  refreshingToolCount,
  onEditLocal,
  onEditCommunity,
  onToggle,
  onSubmitVersionUpdate,
  onUnpublishOnline,
  onDelete,
  onViewReviewProgress,
  onRefreshToolCount,
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
  const isInRepository = isLocal
    ? Boolean(localService?.isListedInRepository)
    : reviewStatus === "approved";
  const updatedAt = formatRegistryDate(service.updatedAt || "");
  const toolCount = resolveToolCount(item);

  // Owned = user-created MCP can be published/updated; community-installed
  // or registry-installed MCPs only permit deletion.
  const isOwned = item.kind === "community" || (
    localService?.permission === "EDIT" && localService?.source === McpSource.LOCAL
  );

  const actionItems: MenuProps["items"] = (() => {
    if (!isOwned) {
      return [
        {
          key: "delete",
          label: t("mcpTools.mine.delete"),
          icon: <Trash2 className="h-3.5 w-3.5" />,
          danger: true,
          onClick: () => onDelete(item),
        },
      ];
    }

    const items: MenuProps["items"] = [];

    if (reviewStatus === "pending") {
      items.push({
        key: "view-review-progress",
        label: t("mcpTools.mine.viewReviewProgress"),
        icon: <Clock className="h-3.5 w-3.5" />,
        onClick: () => onViewReviewProgress?.(item, onlineService),
      });
    } else if (reviewStatus === "approved") {
      items.push({
        key: "submit-version-update",
        label: t("mcpTools.mine.submitVersionUpdate"),
        icon: <RefreshCw className="h-3.5 w-3.5" />,
        disabled: publishing,
        onClick: () => onSubmitVersionUpdate(item, onlineService),
      });
    } else {
      // never submitted, rejected, or offline → apply for listing
      items.push({
        key: "apply-for-listing",
        label: t("mcpTools.mine.applyForListing"),
        icon: <Upload className="h-3.5 w-3.5" />,
        disabled: publishing,
        onClick: () => onSubmitVersionUpdate(item, onlineService),
      });
    }

    if (isInRepository) {
      items.push({
        key: "unpublish-online-version",
        label: t("mcpTools.mine.unpublishOnlineVersion"),
        icon: <ArrowDownFromLine className="h-3.5 w-3.5" />,
        danger: true,
        disabled: unpublishing,
        onClick: () => {
          if (onlineService) onUnpublishOnline(item, onlineService);
        },
      });
    }

    if (item.kind === "local") {
      items.push({
        key: "refresh-tool-count",
        label: t("mcpTools.mine.refreshToolCount"),
        icon: <RefreshCw className="h-3.5 w-3.5" />,
        disabled: refreshingToolCount,
        onClick: () => onRefreshToolCount?.(item),
      });
    }

    items.push({
      key: "delete",
      label: t("mcpTools.mine.delete"),
      icon: <Trash2 className="h-3.5 w-3.5" />,
      danger: true,
      onClick: () => onDelete(item),
    });

    return items;
  })();

  return (
    <div className="group flex flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-blue-300 hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <div className={`flex min-w-0 gap-3 ${isPending ? "items-center" : "items-start"}`}>
          <TransportIcon
            transportType={service.transportType}
            deploymentType={deploymentType}
            label={deploymentLabel}
            seed={service.name}
            className="!h-10 !w-10 rounded-xl"
          />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h3
                className="line-clamp-1 text-base font-semibold text-slate-900"
                title={service.name}
              >
                {service.name}
              </h3>
              {isInRepository ? (
                <span className="inline-flex items-center gap-0.5 rounded-md bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
                  <Share2 className="size-2.5" aria-hidden />
                  {t("mcpTools.mine.onHub")}
                </span>
              ) : null}
            </div>
            {isPending ? (
              <span className="mt-1.5 inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-600">
                <Hourglass className="h-3.5 w-3.5" />
                {t("mcpTools.mine.reviewPending")}
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex shrink-0 items-start gap-1.5">
          <Dropdown
            menu={{ items: actionItems }}
            trigger={["click"]}
            placement="bottomRight"
          >
            <Button
              type="text"
              size="small"
              icon={<MoreHorizontal className="h-4 w-4" />}
              loading={publishing || unpublishing}
              aria-label={t("mcpTools.mine.moreActions")}
              className="-mt-1 text-slate-500 hover:!text-slate-700"
            />
          </Dropdown>
        </div>
      </div>

      <p
        className="mt-4 line-clamp-2 min-h-[44px] text-sm leading-6 text-slate-600"
        title={service.description}
      >
        {service.description || t("mcpTools.detail.noDescription")}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
          {deploymentLabel}
        </span>
        {tags.slice(0, 3).map((tag) => (
          <span
            key={`${service.name}-${tag}`}
            className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700"
          >
            {tag}
          </span>
        ))}
        {tags.length > 3 ? (
          <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">+{tags.length - 3}</span>
        ) : null}
        <span className="rounded-md border border-slate-200 px-2 py-0.5 text-xs text-slate-500">
          {t("mcpTools.repository.toolCount", { count: toolCount })}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-end gap-4 border-t border-slate-100 pt-3 text-xs font-medium text-slate-600">
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3.5 w-3.5 text-slate-400" />
          {updatedAt}
        </span>
      </div>

      <div className="mt-auto flex items-center gap-2 pt-4">
        <Button
          className="flex-1"
          icon={<Edit3 className="h-3.5 w-3.5" />}
          onClick={() => {
            if (item.kind === "local") onEditLocal(item.service);
            else onEditCommunity(item.service);
          }}
        >
          {t("mcpTools.mine.edit")}
        </Button>
        {localService ? (
          <Button
            type={isEnabled ? "default" : "primary"}
            loading={toggling}
            icon={<Power className="h-3.5 w-3.5" />}
            onClick={() => onToggle(localService)}
            className={`flex-1 ${
              isEnabled
                ? "border-blue-200 bg-blue-50 text-blue-700 hover:!border-blue-300 hover:!text-blue-700"
                : ""
            }`}
          >
            {isEnabled ? t("mcpTools.mine.enabled") : t("mcpTools.mine.enable")}
          </Button>
        ) : (
          <Button className="flex-1" disabled>{t("mcpTools.mine.publishedService")}</Button>
        )}
      </div>
    </div>
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
