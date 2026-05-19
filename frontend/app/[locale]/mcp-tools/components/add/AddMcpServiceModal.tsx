import { useEffect, useState } from "react";
import { Modal, Segmented } from "antd";
import { useTranslation } from "react-i18next";
import {
  McpSource,
  MCP_ADD_SERVICE_MODAL_WIDTH_MARKETS,
} from "@/const/mcpTools";
import AddMcpServiceLocalSection from "./local/AddMcpServiceLocalSection";
import AddMcpServiceRegistrySection from "./registry/AddMcpServiceRegistrySection";
import AddMcpServiceCommunitySection from "./community/AddMcpServiceCommunitySection";

interface AddMcpServiceModalProps {
  open: boolean;
  onClose: () => void;
}

export default function AddMcpServiceModal({
  open,
  onClose,
}: AddMcpServiceModalProps) {
  const { t } = useTranslation("common");
  const [tab, setTab] = useState<McpSource>(McpSource.LOCAL);

  useEffect(() => {
    if (!open) setTab(McpSource.LOCAL);
  }, [open]);

  if (!open) return null;

  /** Fixed body height + inner scroll: avoids size jump on tab/transport change and prevents overflow. */
  const bodyFrame = "min(90vh, 700px)";

  const modalWidth = MCP_ADD_SERVICE_MODAL_WIDTH_MARKETS;

  return (
    <Modal
      open
      footer={null}
      closable
      centered
      width={modalWidth}
      onCancel={onClose}
      wrapClassName="[&_.ant-modal]:transition-[width] [&_.ant-modal]:duration-300 [&_.ant-modal]:ease-in-out"
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
        <div className="shrink-0 border-b border-slate-100 px-6 py-4">
          <h2 className="text-2xl font-semibold text-slate-900">
            {t("mcpTools.addModal.title")}
          </h2>
        </div>

        <div className="shrink-0 px-6 pt-4">
          <Segmented
            value={tab}
            onChange={(value) => setTab(value as McpSource)}
            options={[
              { label: t("mcpTools.addModal.tabLocal"), value: McpSource.LOCAL },
              {
                label: t("mcpTools.addModal.tabRegistry"),
                value: McpSource.REGISTRY,
              },
              {
                label: t("mcpTools.addModal.tabCommunity"),
                value: McpSource.COMMUNITY,
              },
            ]}
            className="h-9 rounded-md border border-slate-200 bg-slate-100 p-[2px] text-sm [&_.ant-segmented-group]:h-full [&_.ant-segmented-item]:rounded-md [&_.ant-segmented-item-label]:px-4 [&_.ant-segmented-item-label]:leading-[30px] [&_.ant-segmented-thumb]:rounded-md [&_.ant-segmented-thumb]:bg-white [&_.ant-segmented-thumb]:shadow-sm [&_.ant-segmented-thumb]:top-[2px] [&_.ant-segmented-thumb]:bottom-[2px]"
          />
        </div>

        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]">
          <AddMcpServiceLocalSection
            active={tab === McpSource.LOCAL}
            onAdded={onClose}
          />
          <AddMcpServiceRegistrySection
            active={tab === McpSource.REGISTRY}
            onAdded={onClose}
          />
          <AddMcpServiceCommunitySection
            active={tab === McpSource.COMMUNITY}
            onAdded={onClose}
          />
        </div>
      </div>
    </Modal>
  );
}
