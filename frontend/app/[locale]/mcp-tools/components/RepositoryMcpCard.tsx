import { Button, Tag } from "antd";
import { Download, Eye, GitBranch, Star, Trash2, Wrench } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { CommunityMcpCard } from "@/types/mcpTools";
import {
  formatRegistryVersion,
  getDeploymentTypeLabelKey,
  resolveDeploymentType,
} from "@/lib/mcpTools";
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
  const tags = service.tags || [];
  const deploymentType = resolveDeploymentType(service);
  const deploymentLabel = t(getDeploymentTypeLabelKey(deploymentType));
  const author =
    service.authorDisplayName ||
    service.authorName ||
    t("mcpTools.repository.authorFallback", {
      name: service.communityId ? ` ${service.communityId}` : "",
    });
  const rating = Number(service.rating || 0);
  const installCount = Number(service.installCount || 0);
  const toolCount = resolveToolCount(service);

  return (
    <div className="group flex min-h-[292px] flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-blue-300 hover:shadow-md">
      <div className="flex items-start gap-3">
        <TransportIcon
          transportType={service.transportType}
          deploymentType={deploymentType}
          label={deploymentLabel}
          seed={service.name}
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
            {t("mcpTools.repository.source", { source: author })}
          </p>
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
            key={`${service.communityId || service.name}-${tag}`}
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

      <div className="mt-4 flex flex-wrap items-center justify-between gap-4 border-t border-slate-100 pt-3 text-xs font-medium text-slate-600">
        <span className="inline-flex items-center gap-1">
          <GitBranch className="h-3.5 w-3.5 text-slate-400" />
          {formatRegistryVersion(service.version || "")}
        </span>
        <div className="ml-auto flex items-center gap-4">
          <span className="inline-flex items-center gap-1">
            <Star className="h-3.5 w-3.5 fill-amber-400 text-amber-400" />
            {rating > 0 ? `${rating.toFixed(1)}/5` : t("mcpTools.repository.noRating")}
          </span>
          <span className="inline-flex items-center gap-1">
            <Download className="h-3.5 w-3.5 text-slate-400" />
            {installCount}
          </span>
        </div>
      </div>

      <div className="mt-auto grid grid-cols-2 gap-2 pt-4">
        <Button
          type={installed ? "default" : "primary"}
          disabled={installed}
          icon={<Download className="h-3.5 w-3.5" />}
          onClick={() => onInstall(service)}
        >
          {installed
            ? t("mcpTools.repository.installed")
            : t("mcpTools.repository.install")}
        </Button>
        <Button
          icon={<Eye className="h-3.5 w-3.5" />}
          onClick={() => onSelect(service)}
        >
          {t("mcpTools.repository.details")}
        </Button>
      </div>

      {isAdmin ? (
        <Button
          danger
          icon={<Trash2 className="h-3.5 w-3.5" />}
          onClick={() => onOffline(service)}
          className="mt-2 w-full"
        >
          {t("mcpTools.repository.offline")}
        </Button>
      ) : null}
    </div>
  );
}

function resolveToolCount(service: CommunityMcpCard): number {
  const registryTools = service.registryJson?.tools;
  if (Array.isArray(registryTools)) return registryTools.length;
  if (service.packages?.length) return service.packages.length;
  if (service.remotes?.length) return service.remotes.length;
  return 0;
}
