import { Button, Dropdown, type MenuProps } from "antd";
import { Download, Eye, MoreHorizontal, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { CommunityMcpCard } from "@/types/mcpTools";
import {
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
  const installCount = Number(service.installCount || 0);
  const toolCount = resolveToolCount(service);

  const actionItems: MenuProps["items"] = [];
  if (isAdmin) {
    actionItems.push({
      key: "offline",
      label: t("mcpTools.repository.offline"),
      icon: <Trash2 className="h-3.5 w-3.5" />,
      danger: true,
      onClick: () => onOffline(service),
    });
  }

  return (
    <div className="group flex flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-blue-300 hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
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
              className="line-clamp-1 text-base font-semibold text-slate-900"
              title={service.name}
            >
              {service.name}
            </h3>
          </div>
        </div>
        {actionItems.length > 0 ? (
          <Dropdown menu={{ items: actionItems }} trigger={["click"]} placement="bottomRight">
            <Button
              type="text"
              size="small"
              icon={<MoreHorizontal className="h-4 w-4" />}
              aria-label={t("mcpTools.mine.moreActions")}
              className="-mt-1 text-slate-500 hover:!text-slate-700"
            />
          </Dropdown>
        ) : null}
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
            key={`${service.communityId || service.name}-${tag}`}
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
          <Download className="h-3.5 w-3.5 text-slate-400" />
          {installCount}
        </span>
      </div>

      <div className="mt-auto flex items-center gap-2 pt-4">
        <Button
          type={installed ? "default" : "primary"}
          disabled={installed}
          className="flex-1"
          icon={<Download className="h-3.5 w-3.5" />}
          onClick={() => onInstall(service)}
        >
          {installed
            ? t("mcpTools.repository.installed")
            : t("mcpTools.repository.install")}
        </Button>
        <Button
          className="flex-1"
          icon={<Eye className="h-3.5 w-3.5" />}
          onClick={() => onSelect(service)}
        >
          {t("mcpTools.repository.details")}
        </Button>
      </div>
    </div>
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
