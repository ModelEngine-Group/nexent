import { useEffect, useState } from "react";
import { App, Modal, Segmented } from "antd";
import { useTranslation } from "react-i18next";
import { MCP_TAB } from "@/const/mcpTools";
import type { McpTab } from "@/types/mcpTools";
import { useMcpToolsAddLocal } from "@/hooks/mcpTools/useMcpToolsAddLocal";
import { useMcpToolsAddMarket } from "@/hooks/mcpTools/useMcpToolsAddMarket";
import AddMcpServiceLocalSection from "./AddMcpServiceLocalSection";
import AddMcpServiceMarketSection from "./AddMcpServiceMarketSection";

interface AddMcpServiceModalProps {
  open: boolean;
  onServiceAdded: () => Promise<unknown>;
  onClose: () => void;
}

export default function AddMcpServiceModal({
  open,
  onServiceAdded,
  onClose,
}: AddMcpServiceModalProps) {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const [addModalTab, setAddModalTab] = useState<McpTab>(MCP_TAB.LOCAL);

  const local = useMcpToolsAddLocal({
    addModalTab,
    t: (key) => String(t(key)),
    message,
    onServiceAdded,
    onClose,
  });

  const market = useMcpToolsAddMarket({
    open,
    addModalTab,
    t: (key) => String(t(key)),
    message,
    onServiceAdded,
    onClose,
  });

  const { reset: resetLocal } = local;
  const { reset: resetMarket } = market;

  useEffect(() => {
    if (!open) {
      setAddModalTab(MCP_TAB.LOCAL);
      resetLocal();
      resetMarket();
    }
  }, [open, resetLocal, resetMarket]);

  if (!open) {
    return null;
  }

  return (
    <Modal
      open
      footer={null}
      closable
      maskClosable={false}
      centered
      width={addModalTab === MCP_TAB.MARKET ? 1200 : 900}
      onCancel={onClose}
      styles={{
        mask: { background: "rgba(15,23,42,0.6)", backdropFilter: "blur(2px)" },
        body: { padding: 0 },
      }}
    >
      <div>
        <div className="border-b border-slate-100 px-6 py-5">
          <div>
            <h2 className="text-2xl font-semibold text-slate-900">{t("mcpTools.addModal.title")}</h2>
          </div>
        </div>

        <div className="px-6 pt-4">
          <Segmented
            value={addModalTab}
            onChange={(value) => setAddModalTab(value as McpTab)}
            options={[
              { label: t("mcpTools.addModal.tabLocal"), value: MCP_TAB.LOCAL },
              { label: t("mcpTools.addModal.tabMarket"), value: MCP_TAB.MARKET },
            ]}
            className="h-9 rounded-full border border-slate-200 bg-slate-100 p-[2px] text-sm [&_.ant-segmented-group]:h-full [&_.ant-segmented-item]:rounded-full [&_.ant-segmented-item-label]:px-4 [&_.ant-segmented-item-label]:leading-[30px] [&_.ant-segmented-thumb]:rounded-full [&_.ant-segmented-thumb]:bg-white [&_.ant-segmented-thumb]:shadow-sm [&_.ant-segmented-thumb]:top-[2px] [&_.ant-segmented-thumb]:bottom-[2px]"
          />
        </div>

        {addModalTab === MCP_TAB.LOCAL ? (
          <AddMcpServiceLocalSection
            state={local.state}
            actions={local.actions}
            t={(key, params) => String(t(key, params))}
          />
        ) : (
          <AddMcpServiceMarketSection
            state={market.state}
            actions={market.actions}
            t={(key, params) => String(t(key, params))}
          />
        )}
      </div>
    </Modal>
  );
}
