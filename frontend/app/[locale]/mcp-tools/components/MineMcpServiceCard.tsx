import { Button, Tag } from "antd";
import { Download, Edit3, Power, Star } from "lucide-react";
import { useTranslation } from "react-i18next";
import { McpServiceStatus } from "@/const/mcpTools";
import type { CommunityMcpCard, McpServiceItem } from "@/types/mcpTools";
import { getDeploymentTypeLabelKey, resolveDeploymentType } from "@/lib/mcpTools";
import StatusBadge from "./shared/StatusBadge";
import TransportIcon from "./shared/TransportIcon";

export type MineMcpCardItem =
  | { kind: "local"; service: McpServiceItem }
  | { kind: "community"; service: CommunityMcpCard };

interface MineMcpServiceCardProps {
  item: MineMcpCardItem;
  toggling?: boolean;
  onEditLocal: (service: McpServiceItem) => void;
  onEditCommunity: (service: CommunityMcpCard) => void;
  onToggle: (service: McpServiceItem) => void;
}

export default function MineMcpServiceCard({
  item,
  toggling,
  onEditLocal,
  onEditCommunity,
  onToggle,
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
  const sourceLabel = isLocal
    ? t("mcpTools.mine.localService")
    : t("mcpTools.mine.publishedService");
  const rating = item.kind === "community" ? Number(item.service.rating || 0) : 0;
  const installCount = item.kind === "community" ? Number(item.service.installCount || 0) : 0;
  const toolCount = resolveToolCount(item);

  return (
    <div className="group flex min-h-[292px] flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-emerald-300 hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <TransportIcon
            transportType={service.transportType}
            label={deploymentLabel}
            className="!h-10 !w-10 rounded-xl"
          />
          <div className="min-w-0">
            <h3 className="line-clamp-1 text-lg font-semibold text-slate-900" title={service.name}>
              {service.name}
            </h3>
            <p className="mt-1 text-xs text-slate-500">
              {t("mcpTools.repository.source", { source: sourceLabel })}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
          {showHub ? (
            <Tag color="processing" className="m-0 rounded-full">
              Hub
            </Tag>
          ) : null}
          {localService ? <StatusBadge status={localService.enabled} /> : null}
        </div>
      </div>

      <p
        className="mt-4 line-clamp-2 min-h-[44px] text-sm leading-6 text-slate-600"
        title={service.description}
      >
        {service.description || t("mcpTools.detail.noDescription")}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <Tag color="cyan" className="m-0 rounded-full">
          {deploymentLabel}
        </Tag>
        {tags.slice(0, 3).map((tag) => (
          <Tag key={`${service.name}-${tag}`} className="m-0 rounded-full bg-slate-50">
            {tag}
          </Tag>
        ))}
        {tags.length > 3 ? (
          <Tag className="m-0 rounded-full bg-slate-50">+{tags.length - 3}</Tag>
        ) : null}
        <Tag className="m-0 rounded-full bg-emerald-50 text-emerald-700">
          {t("mcpTools.repository.toolCount", { count: toolCount })}
        </Tag>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 border-t border-slate-100 pt-3 text-xs font-medium text-slate-600">
        <span>{service.version ? `v${service.version.replace(/^v/i, "")}` : "v-"}</span>
        <span className="inline-flex items-center gap-1">
          <Star className="h-3.5 w-3.5 fill-amber-400 text-amber-400" />
          {rating.toFixed(1)}
        </span>
        <span className="inline-flex items-center gap-1">
          <Download className="h-3.5 w-3.5 text-slate-400" />
          {installCount}
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
            className={isEnabled ? "border-emerald-200 bg-emerald-50 text-emerald-700 hover:!border-emerald-300 hover:!text-emerald-700" : ""}
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

function resolveToolCount(item: MineMcpCardItem): number {
  if (item.kind === "local") return item.service.tools?.length || 0;
  const registryTools = item.service.registryJson?.tools;
  if (Array.isArray(registryTools)) return registryTools.length;
  if (item.service.packages?.length) return item.service.packages.length;
  if (item.service.remotes?.length) return item.service.remotes.length;
  return 0;
}
