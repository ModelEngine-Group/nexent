"use client";

import { useEffect, useState } from "react";
import { Button, List, Modal, Spin, message } from "antd";
import { Trash2 } from "lucide-react";
import {
  deleteOfficialAgent,
  fetchOfficialAgentManagement,
} from "@/services/agentRepositoryService";
import type { OfficialAgentManagementItem } from "@/types/agentRepository";

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function ManageOfficialAgentsModal({ open, onClose }: Props) {
  const [items, setItems] = useState<OfficialAgentManagementItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = async () => {
    setLoading(true);
    try { setItems(await fetchOfficialAgentManagement()); }
    catch { message.error("加载官方智能体失败"); }
    finally { setLoading(false); }
  };

  useEffect(() => { if (open) void load(); }, [open]);

  const remove = async (item: OfficialAgentManagementItem) => {
    setBusyId(item.agent_repository_id);
    try {
      await deleteOfficialAgent(item.agent_repository_id);
      setItems((current) => current.filter((entry) => entry.agent_repository_id !== item.agent_repository_id));
      message.success("官方智能体已删除；已复制的租户副本保留");
    } catch { message.error("删除官方智能体失败"); }
    finally { setBusyId(null); }
  };

  const confirmRemove = (item: OfficialAgentManagementItem) => {
    Modal.confirm({
      title: "确认删除官方智能体？",
      content:
        "删除后所有租户都无法再看到该官方智能体，同时会删除官方资源包文件；已经复制到租户中的智能体副本不受影响。",
      okText: "删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: () => remove(item),
    });
  };

  return (
    <Modal open={open} onCancel={onClose} footer={null} title="管理官方智能体" destroyOnHidden>
      {loading ? <div className="flex justify-center py-8"><Spin /></div> : (
        <List
          locale={{ emptyText: "暂无官方智能体" }}
          dataSource={items}
          renderItem={(item) => (
            <List.Item actions={[
              <Button
                key="delete"
                danger
                type="text"
                icon={<Trash2 className="h-4 w-4" />}
                loading={busyId === item.agent_repository_id}
                onClick={() => confirmRemove(item)}
              />,
            ]}>
              <List.Item.Meta title={item.display_name || item.name} description={item.name} />
            </List.Item>
          )}
        />
      )}
    </Modal>
  );
}
