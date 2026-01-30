import { useState } from "react";
import { Modal, Button, Table } from "antd";
import { Maximize, Minimize } from "lucide-react";
import { useTranslation } from "react-i18next";
import { McpTool } from "@/types/agentConfig";

interface McpToolListModalProps {
  open: boolean;
  onCancel: () => void;
  loading: boolean;
  tools: McpTool[];
  serverName: string;
}

export default function McpToolListModal({
  open,
  onCancel,
  loading,
  tools,
  serverName,
}: McpToolListModalProps) {
  const { t } = useTranslation("common");
  const [expandedDescriptions, setExpandedDescriptions] = useState<Set<string>>(new Set());

  const toggleDescription = (toolName: string) => {
    const newExpanded = new Set(expandedDescriptions);
    if (newExpanded.has(toolName)) {
      newExpanded.delete(toolName);
    } else {
      newExpanded.add(toolName);
    }
    setExpandedDescriptions(newExpanded);
  };

  const toolColumns = [
    { title: t("mcpConfig.toolsList.column.name"), dataIndex: "name", key: "name", width: "30%" },
    {
      title: t("mcpConfig.toolsList.column.description"),
      dataIndex: "description",
      key: "description",
      width: "70%",
      render: (text: string, record: McpTool) => {
        const isExpanded = expandedDescriptions.has(record.name);
        const maxLength = 100;
        const needsExpansion = text && text.length > maxLength;
        return (
          <div>
            <div style={{ marginBottom: needsExpansion ? 8 : 0 }}>
              {needsExpansion && !isExpanded ? `${text.substring(0, maxLength)}...` : text}
            </div>
            {needsExpansion && (
              <Button
                type="link"
                size="small"
                icon={isExpanded ? <Minimize size={16} /> : <Maximize size={16} />}
                onClick={() => toggleDescription(record.name)}
                style={{ padding: 0, height: "auto" }}
              >
                {isExpanded ? t("mcpConfig.toolsList.button.collapse") : t("mcpConfig.toolsList.button.expand")}
              </Button>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <Modal
      title={`${serverName} - ${t("mcpConfig.toolsList.title")}`}
      open={open}
      onCancel={onCancel}
      width={800}
      footer={[<Button key="close" onClick={onCancel}>{t("mcpConfig.modal.close")}</Button>]}
    >
      <Table
        loading={{ spinning: loading, tip: t("mcpConfig.toolsList.loading") }}
        columns={toolColumns}
        dataSource={tools}
        rowKey="name"
        size="small"
        pagination={false}
        locale={{ emptyText: t("mcpConfig.toolsList.empty") }}
        scroll={{ y: 500 }}
      />
    </Modal>
  );
}

