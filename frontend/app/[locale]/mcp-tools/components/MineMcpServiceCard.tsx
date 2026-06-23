import { Button, Dropdown, Tag, type MenuProps } from "antd";
import { Clock, Edit3, MoreHorizontal, Power } from "lucide-react";
import { useTranslation } from "react-i18next";
import { McpServiceStatus } from "@/const/mcpTools";
import type { CommunityMcpCard, McpServiceItem } from "@/types/mcpTools";
import {
  formatRegistryDate,
  formatRegistryVersion,
  getDeploymentTypeLabelKey,
  resolveDeploymentType,
} from "@/lib/mcpTools";
import StatusBadge from "./shared/StatusBadge";
import TransportIcon from "./shared/TransportIcon";

export type MineMcpCardItem =
  | { kind: "local"; service: McpServiceItem }
  | { kind: "community"; service: CommunityMcpCard };

interface MineMcpServiceCardProps {
  item: MineMcpCardItem;
  onlineService?: CommunityMcpCard;
  onlineVersion?: string;
  toggling?: boolean;
  publishing?: boolean;
  unpublishing?: boolean;
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
}

export default function MineMcpServiceCard({
  item,
  onlineService,
  onlineVersion,
  toggling,
  publishing,
  unpublishing,
  onEditLocal,
  onEditCommunity,
  onToggle,
  onSubmitVersionUpdate,
  onUnpublishOnline,
}: MineMcpServiceCardProps) {
  const { t } = useTranslation("common");
  const service = item.service;
  const tags = service.tags || [];
  const deploymentType = resolveDeploymentType(service);
  const deploymentLabel = t(getDeploymentTypeLabelKey(deploymentType));
  const isLocal = item.kind === "local";
  const localService = isLocal ? item.service : null;
  const isEnabled = localService?.enabled === McpServiceStatus.ENABLED;
  const showHub =
    item.kind === "community" ||
    Boolean(localService?.isListedInRepository || localService?.communityId);
  const reviewStatus = onlineService?.reviewStatus || service.reviewStatus;
  const sourceLabel = isLocal
    ? t("mcpTools.mine.localService")
    : t("mcpTools.mine.publishedService");
  const currentVersion = formatRegistryVersion(service.version || "");
  const syncedOnlineVersion = formatRegistryVersion(
    onlineVersion ||
      (item.kind === "community" ? item.service.version || "" : "")
  );
  const updatedAt = formatRegistryDate(service.updatedAt || "");
  const toolCount = resolveToolCount(item);
  const actionItems: MenuProps["items"] = [
    {
      key: "submit-version-update",
      label: t("mcpTools.mine.submitVersionUpdate"),
      disabled: publishing,
      onClick: () => onSubmitVersionUpdate(item, onlineService),
    },
    {
      key: "unpublish-online-version",
      label: t("mcpTools.mine.unpublishOnlineVersion"),
      danger: true,
      disabled: !onlineService || unpublishing,
      onClick: () => {
        if (onlineService) onUnpublishOnline(item, onlineService);
      },
    },
  ];

  return (
    <div className="group flex min-h-[292px] flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-blue-300 hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <TransportIcon
            transportType={service.transportType}
            deploymentType={deploymentType}
            label={deploymentLabel}
            className="!h-10 !w-10 rounded-xl"
          />
          <div className="min-w-0">
            <h3
              className="line-clamp-1 text-lg font-semibold text-slate-900"
              title={service.name}
            >
              {service.name}
            </h3>
            <p className="mt-1 text-xs text-slate-500">
              {t("mcpTools.repository.source", { source: sourceLabel })}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-start gap-1.5">
          <div className="flex flex-wrap justify-end gap-1.5">
            {showHub ? (
              <Tag color="processing" className="m-0 rounded-full">
                Hub
              </Tag>
            ) : null}
            {reviewStatus ? (
              <Tag color={getReviewStatusColor(reviewStatus)} className="m-0 rounded-full">
                {t(`mcpTools.review.status.${reviewStatus}`)}
              </Tag>
            ) : null}
            {localService ? (
              <StatusBadge status={localService.enabled} />
            ) : null}
          </div>
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
        <Tag color="blue" className="m-0 rounded-full">
          {deploymentLabel}
        </Tag>
        {tags.slice(0, 3).map((tag) => (
          <Tag
            key={`${service.name}-${tag}`}
            className="m-0 rounded-full bg-slate-50"
          >
            {tag}
          </Tag>
        ))}
        {tags.length > 3 ? (
          <Tag className="m-0 rounded-full bg-slate-50">+{tags.length - 3}</Tag>
        ) : null}
        <Tag className="m-0 rounded-full bg-blue-50 text-blue-700">
          {t("mcpTools.repository.toolCount", { count: toolCount })}
        </Tag>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 border-t border-slate-100 pt-3 text-xs font-medium text-slate-600">
        <span>{currentVersion}</span>
        <span>{syncedOnlineVersion}</span>
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3.5 w-3.5 text-slate-400" />
          {updatedAt}
        </span>
      </div>

      <div className="mt-auto grid grid-cols-2 gap-2 pt-4">
        <Button
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
            className={
              isEnabled
                ? "border-blue-200 bg-blue-50 text-blue-700 hover:!border-blue-300 hover:!text-blue-700"
                : ""
            }
          >
            {isEnabled ? t("mcpTools.mine.enabled") : t("mcpTools.mine.enable")}
          </Button>
        ) : (
          <Button disabled>{t("mcpTools.mine.publishedService")}</Button>
        )}
      </div>
    </div>
  );
}

function getReviewStatusColor(status: string) {
  if (status === "approved") return "green";
  if (status === "rejected") return "red";
  return "gold";
}

function resolveToolCount(item: MineMcpCardItem): number {
  if (item.kind === "local") return item.service.tools?.length || 0;
  const registryTools = item.service.registryJson?.tools;
  if (Array.isArray(registryTools)) return registryTools.length;
  if (item.service.packages?.length) return item.service.packages.length;
  if (item.service.remotes?.length) return item.service.remotes.length;
  return 0;
}
