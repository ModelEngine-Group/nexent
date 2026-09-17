import { Button, Dropdown, type MenuProps } from "antd";
import { Download, Eye, MoreHorizontal, Trash2 } from "lucide-react";
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
  const tags = service.tags || [];
  const deploymentType = resolveDeploymentType(service);
  const deploymentLabel = t(getDeploymentTypeLabelKey(deploymentType));
  const installCount = Number(service.installCount || 0);
  const toolCount = resolveToolCount(service);
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

  return (
    <ResourceCard
      className="h-full"
      title={service.name}
      icon={
        <TransportIcon
          transportType={service.transportType}
          deploymentType={deploymentType}
          label={deploymentLabel}
          seed={service.name}
          className="!size-10 rounded-xl"
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
      }
      meta={
        <span className="inline-flex items-center gap-1">
          <Download className="size-3.5 text-slate-400" />
          {installCount}
        </span>
      }
      headerActions={
        actionItems.length > 0 ? (
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
        ) : undefined
      }
      footer={
        <div className="flex items-center gap-2">
          <Button
            type={installed ? "default" : "primary"}
            disabled={installed}
            className="flex-1"
            icon={<Download className="size-3.5" />}
            onClick={() => onInstall(service)}
          >
            {installed
              ? t("mcpTools.repository.installed")
              : t("mcpTools.repository.install")}
          </Button>
          <Button
            className="flex-1"
            icon={<Eye className="size-3.5" />}
            onClick={() => onSelect(service)}
          >
            {t("mcpTools.repository.details")}
          </Button>
        </div>
      }
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
