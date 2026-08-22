import { useMemo, useState } from "react";
import { App, Button, Modal, Tag } from "antd";
import { Download } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  MCP_TOOLS_MODAL_WRAP_CLASS,
  mcpToolsModalChromeStyles,
} from "@/const/mcpTools";
import {
  getDeploymentTypeLabelKey,
  resolveDeploymentType,
} from "@/lib/mcpTools";
import type { CommunityMcpCard } from "@/types/mcpTools";
import type { McpTool } from "@/types/agentConfig";
import McpToolListModal from "@/components/mcp/McpToolListModal";
import { listMcpRuntimeTools } from "@/services/mcpToolsService";
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
  const { message } = App.useApp();
  const [toolsOpen, setToolsOpen] = useState(false);
  const [loadingTools, setLoadingTools] = useState(false);
  const [tools, setTools] = useState<McpTool[]>(() => resolveTools(service));

  const tags = service.tags || [];
  const deploymentType = resolveDeploymentType(service);
  const deploymentLabel = t(getDeploymentTypeLabelKey(deploymentType));
  const author =
    service.authorDisplayName ||
    service.authorName ||
    t("mcpTools.repository.authorFallback", {
      name: service.communityId ? ` ${service.communityId}` : "",
    });
  const toolCount = resolveToolCount(service);
  const snapshotTools = useMemo(() => resolveTools(service), [service]);
  const downloadCount = Number(service.installCount || 0);

  const openTools = async () => {
    setToolsOpen(true);
    setTools(snapshotTools);
    if (!service.sourceMcpId) return;

    setLoadingTools(true);
    try {
      const result = await listMcpRuntimeTools(service.sourceMcpId);
      setTools(result.data || []);
    } catch {
      message.error(t("mcpTools.tools.loadFailed"));
    } finally {
      setLoadingTools(false);
    }
  };

  return (
    <>
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
            <div className="grid grid-cols-2 gap-y-5">
              <StatItem
                label={t("mcpTools.deploymentType.label")}
                value={deploymentLabel}
              />
              <StatItem
                label={t("mcpTools.detail.tools")}
                value={
                  <Button
                    type="link"
                    className="!h-auto !p-0 !text-sm !font-semibold"
                    onClick={openTools}
                  >
                    {t("mcpTools.repository.toolCount", { count: toolCount })}
                  </Button>
                }
              />
              <StatItem
                label={t("mcpTools.repository.downloadCount")}
                value={downloadCount.toLocaleString()}
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
      <McpToolListModal
        open={toolsOpen}
        onCancel={() => setToolsOpen(false)}
        loading={loadingTools}
        tools={tools}
        serverName={service.name}
        zIndex={1100}
      />
    </>
  );
}

function StatItem({ label, value }: { label: string; value: React.ReactNode }) {
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
  const toolNames = service.registryJson?._toolNames;
  if (Array.isArray(toolNames)) return toolNames.length;
  if (service.packages?.length) return service.packages.length;
  if (service.remotes?.length) return service.remotes.length;
  return 0;
}

function resolveTools(service: CommunityMcpCard): McpTool[] {
  const registryTools = service.registryJson?.tools;
  if (Array.isArray(registryTools)) {
    return registryTools
      .map((tool) => {
        if (typeof tool === "string") return { name: tool, description: "" };
        if (!tool || typeof tool !== "object") return null;
        const value = tool as Record<string, unknown>;
        const name = typeof value.name === "string" ? value.name : "";
        if (!name) return null;
        return {
          name,
          description:
            typeof value.description === "string" ? value.description : "",
        };
      })
      .filter((tool): tool is McpTool => tool !== null);
  }

  const toolNames = service.registryJson?._toolNames;
  if (!Array.isArray(toolNames)) return [];
  return toolNames
    .filter(
      (name): name is string => typeof name === "string" && name.length > 0
    )
    .map((name) => ({ name, description: "" }));
}
