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

  /** Fixed body height + inner scroll: avoids size jump on tab/transport change and prevents overflow. */
  const bodyFrame = "min(95vh, 900px)";

  return (
    <Modal
      open
      footer={null}
      closable
      centered
      width={1100}
      onCancel={onClose}
      styles={{
        mask: { background: "rgba(4, 4, 4, 0.6)", backdropFilter: "blur(2px)" },
        body: {
          padding: 0,
          display: "flex",
          flexDirection: "column",
          height: bodyFrame,
          maxHeight: bodyFrame,
          overflow: "hidden",
        },
      }}
    >
      <div className="flex h-full min-h-0 min-w-0 flex-col">
        <div className="shrink-0 border-b border-slate-100 px-6 py-5">
          <h2 className="text-2xl font-semibold text-slate-900">
            {t("mcpTools.addModal.title")}
          </h2>
        </div>

        <div className="shrink-0 px-6 pt-4">
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
            className="h-9 rounded-md border border-slate-200 bg-slate-100 p-[2px] text-sm [&_.ant-segmented-group]:h-full [&_.ant-segmented-item]:rounded-md [&_.ant-segmented-item-label]:px-4 [&_.ant-segmented-item-label]:leading-[30px] [&_.ant-segmented-thumb]:rounded-md [&_.ant-segmented-thumb]:bg-white [&_.ant-segmented-thumb]:shadow-sm [&_.ant-segmented-thumb]:top-[2px] [&_.ant-segmented-thumb]:bottom-[2px]"
          />
        </div>

        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]">
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
      </div>
    </Modal>
  );
}
