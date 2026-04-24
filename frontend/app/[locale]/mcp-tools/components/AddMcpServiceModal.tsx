import { useEffect, useState } from "react";
import { Modal, Segmented } from "antd";
import { useTranslation } from "react-i18next";
import { MCP_TAB } from "@/const/mcpTools";
import { McpTab } from "@/types/mcpTools";
import AddMcpServiceLocalSection from "./AddMcpServiceLocalSection";
import AddMcpServiceRegistrySection from "./AddMcpServiceRegistrySection";
import AddMcpServiceCommunitySection from "./AddMcpServiceCommunitySection";

interface AddMcpServiceModalProps {
  open: boolean;
  onClose: () => void;
}

export default function AddMcpServiceModal({
  open,
  onClose,
}: AddMcpServiceModalProps) {
  const { t } = useTranslation("common");
  const [tab, setTab] = useState<McpTab>(McpTab.LOCAL);

  useEffect(() => {
    if (!open) setTab(McpTab.LOCAL);
  }, [open]);

  if (!open) return null;

  return (
    <Modal
      open
      footer={null}
      closable
      centered
      width={tab === MCP_TAB.LOCAL ? 900 : 1200}
      onCancel={onClose}
      styles={{
        mask: { background: "rgba(15,23,42,0.6)", backdropFilter: "blur(2px)" },
        body: { padding: 0 },
      }}
    >
      <div>
        <div className="border-b border-slate-100 px-6 py-5">
          <h2 className="text-2xl font-semibold text-slate-900">
            {t("mcpTools.addModal.title")}
          </h2>
        </div>

        <div className="px-6 pt-4">
          <Segmented
            value={tab}
            onChange={(value) => setTab(value as McpTab)}
            options={[
              { label: t("mcpTools.addModal.tabLocal"), value: MCP_TAB.LOCAL },
              {
                label: t("mcpTools.addModal.tabRegistry"),
                value: MCP_TAB.MCP_REGISTRY,
              },
              {
                label: t("mcpTools.addModal.tabCommunity"),
                value: MCP_TAB.COMMUNITY,
              },
            ]}
            className="h-9 rounded-full border border-slate-200 bg-slate-100 p-[2px] text-sm [&_.ant-segmented-group]:h-full [&_.ant-segmented-item]:rounded-full [&_.ant-segmented-item-label]:px-4 [&_.ant-segmented-item-label]:leading-[30px] [&_.ant-segmented-thumb]:rounded-full [&_.ant-segmented-thumb]:bg-white [&_.ant-segmented-thumb]:shadow-sm [&_.ant-segmented-thumb]:top-[2px] [&_.ant-segmented-thumb]:bottom-[2px]"
          />
        </div>

        <AddMcpServiceLocalSection
          active={tab === MCP_TAB.LOCAL}
          onAdded={onClose}
        />
        <AddMcpServiceRegistrySection
          active={tab === MCP_TAB.MCP_REGISTRY}
          onAdded={onClose}
        />
        <AddMcpServiceCommunitySection
          active={tab === MCP_TAB.COMMUNITY}
          onAdded={onClose}
        />
      </div>
    </Modal>
  );
}
