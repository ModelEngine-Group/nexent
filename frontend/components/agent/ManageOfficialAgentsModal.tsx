// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";

import { useCallback, useEffect, useState } from "react";
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
  const { t } = useTranslation();
  const [items, setItems] = useState<OfficialAgentManagementItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await fetchOfficialAgentManagement());
    } catch {
      message.error(t("ui.localization.officialAgentsLoadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const remove = async (item: OfficialAgentManagementItem) => {
    setBusyId(item.agent_repository_id);
    try {
      await deleteOfficialAgent(item.agent_repository_id);
      setItems((current) =>
        current.filter(
          (entry) => entry.agent_repository_id !== item.agent_repository_id
        )
      );
      message.success(t("ui.localization.officialAgentDeleted"));
    } catch {
      message.error(t("ui.localization.officialAgentDeleteFailed"));
    } finally {
      setBusyId(null);
    }
  };

  const confirmRemove = (item: OfficialAgentManagementItem) => {
    Modal.confirm({
      title: t("ui.localization.deleteOfficialAgentTitle"),
      content: t("ui.localization.deleteOfficialAgentBody"),
      okText: t("ui.localization.delete"),
      cancelText: t("ui.localization.cancel"),
      okButtonProps: { danger: true },
      onOk: () => remove(item),
    });
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      title={t("ui.localization.manageOfficialAgents")}
      destroyOnHidden
    >
      {loading ? (
        <div className="flex justify-center py-8">
          <Spin />
        </div>
      ) : (
        <List
          locale={{ emptyText: t("ui.localization.noOfficialAgents") }}
          dataSource={items}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button
                  key="delete"
                  danger
                  type="text"
                  icon={<Trash2 className="h-4 w-4" />}
                  loading={busyId === item.agent_repository_id}
                  onClick={() => confirmRemove(item)}
                />,
              ]}
            >
              <List.Item.Meta
                title={item.display_name || item.name}
                description={item.name}
              />
            </List.Item>
          )}
        />
      )}
    </Modal>
  );
}
