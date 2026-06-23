import { Button, Modal, Tag } from "antd";
import { Download, Star } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  MCP_TOOLS_MODAL_WRAP_CLASS,
  mcpToolsModalChromeStyles,
} from "@/const/mcpTools";
import {
  formatRegistryVersion,
  getDeploymentTypeLabelKey,
  resolveDeploymentType,
} from "@/lib/mcpTools";
import type { CommunityMcpCard } from "@/types/mcpTools";
import TransportIcon from "./shared/TransportIcon";

interface RepositoryMcpDetailModalProps {
  service: CommunityMcpCard;
  installed: boolean;
  onClose: () => void;
  onInstall: (service: CommunityMcpCard) => void;
}

export default function RepositoryMcpDetailModal({
  service,
  installed,
  onClose,
  onInstall,
}: RepositoryMcpDetailModalProps) {
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
    <Modal
      open
      footer={null}
      closable
      centered
      width={620}
      style={{ top: 20 }}
      onCancel={onClose}
      wrapClassName={`${MCP_TOOLS_MODAL_WRAP_CLASS}`}
      styles={mcpToolsModalChromeStyles()}
    >
      <div className="bg-white">
        {/* Header */}
        <div className="border-b border-slate-100 px-6 pt-6 pb-4">
          <div className="flex items-start gap-3">
            <TransportIcon
              transportType={service.transportType}
              deploymentType={deploymentType}
              label={deploymentLabel}
              className="!h-10 !w-10 rounded-xl"
            />
            <div className="min-w-0 flex-1">
              <h2 className="text-xl font-bold text-slate-900 truncate">
                {service.name}
              </h2>
              <p className="mt-0.5 text-sm text-slate-500">
                {t("mcpTools.repository.source", { source: author })}
              </p>
            </div>
          </div>
        </div>

        {/* Tags */}
        <div className="px-6 pt-5 pb-3">
          <div className="flex flex-wrap gap-1.5">
            <Tag color="blue" className="m-0 rounded-full">
              {deploymentLabel}
            </Tag>
            {tags.map((tag) => (
              <Tag
                key={`${service.communityId || service.name}-${tag}`}
                className="m-0 rounded-full bg-slate-100"
              >
                {tag}
              </Tag>
            ))}
          </div>
        </div>

        {/* Description */}
        <div className="px-6 pt-5 pb-5">
          <p className="text-sm leading-6 text-slate-600">
            {service.description || t("mcpTools.detail.noDescription")}
          </p>
        </div>

        {/* Stats gray box */}
        <div className="mx-6 mb-5 rounded-xl bg-slate-50 border border-slate-200 px-6 py-5">
          <div className="grid grid-cols-3 gap-y-5">
            <StatItem
              label={t("mcpTools.deploymentType.label")}
              value={deploymentLabel}
            />
            <StatItem
              label={t("mcpTools.repository.version")}
              value={formatRegistryVersion(service.version || "")}
            />
            <StatItem
              label={t("mcpTools.detail.tools")}
              value={t("mcpTools.repository.toolCount", { count: toolCount })}
            />
          </div>
          <div className="grid grid-cols-3 gap-y-5 mt-5">
            <StatItem
              label={t("mcpTools.repository.rating")}
              value={
                <span className="inline-flex items-center gap-1">
                  <Star className="h-3.5 w-3.5 fill-amber-400 text-amber-400" />
                  {rating > 0 ? `${rating.toFixed(1)}/5` : t("mcpTools.repository.noRating")}
                </span>
              }
            />
            <StatItem
              label={t("mcpTools.repository.downloads")}
              value={t("mcpTools.repository.installCount", { count: installCount })}
            />
          </div>
        </div>

        {/* Footer buttons */}
        <div className="flex items-center justify-end gap-3 border-t border-slate-100 px-6 py-4">
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            type="primary"
            disabled={installed}
            icon={<Download className="h-4 w-4" />}
            onClick={() => onInstall(service)}
          >
            {installed
              ? t("mcpTools.repository.installed")
              : t("mcpTools.repository.install")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function StatItem({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-slate-500 mb-1">{label}</span>
      <span className="text-sm font-semibold text-slate-800">{value}</span>
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
