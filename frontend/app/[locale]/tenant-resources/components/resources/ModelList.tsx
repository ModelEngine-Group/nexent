"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Table, Button, Popconfirm, message, Tag } from "antd";
import { EditOutlined, DeleteOutlined } from "@ant-design/icons";
import { ColumnsType } from "antd/es/table";
import { useModelList } from "@/hooks/model/useModelList";
import { modelService } from "@/services/modelService";
import { type ModelOption, type ModelType } from "@/types/modelConfig";
import { ModelAddDialog } from "../../../models/components/model/ModelAddDialog";
import { ModelEditDialog } from "../../../models/components/model/ModelEditDialog";

export default function ModelList({ tenantId }: { tenantId: string | null }) {
  const { t } = useTranslation("common");
  const { data: models = [], isLoading, refetch } = useModelList();
  const [editingModel, setEditingModel] = useState<ModelOption | null>(null);
  const [addDialogVisible, setAddDialogVisible] = useState(false);
  const [editDialogVisible, setEditDialogVisible] = useState(false);

  const openCreate = () => {
    setAddDialogVisible(true);
  };

  const handleAddDialogClose = () => {
    setAddDialogVisible(false);
  };

  const handleAddDialogSuccess = async () => {
    await refetch();
    setAddDialogVisible(false);
  };

  const handleEditDialogClose = () => {
    setEditDialogVisible(false);
    setEditingModel(null);
  };

  const handleEditDialogSuccess = async () => {
    await refetch();
    setEditDialogVisible(false);
    setEditingModel(null);
  };

  const openEdit = (model: ModelOption) => {
    setEditingModel(model);
    setEditDialogVisible(true);
  };

  const handleDelete = async (modelId: string, provider?: string) => {
    try {
      await modelService.deleteCustomModel(modelId, provider);
      message.success("Model deleted");
      refetch();
    } catch (error: any) {
      if (error.response?.data?.message) {
        message.error(error.response.data.message);
      } else {
        message.error("Delete failed");
      }
    }
  };


  const columns: ColumnsType<ModelOption> = [
    {
      title: t("common.name"),
      dataIndex: "displayName",
      key: "displayName",
      render: (text: string, record: ModelOption) => (
        <div>
          <div className="font-medium">{text || record.name}</div>
          <div className="text-sm text-gray-500">{record.name}</div>
        </div>
      ),
    },
    {
      title: t("common.type"),
      dataIndex: "type",
      key: "type",
      render: (type: ModelType) => <Tag>{type}</Tag>,
    },
    {
      title: t("common.source"),
      dataIndex: "source",
      key: "source",
      render: (source: string) => <Tag color="blue">{source}</Tag>,
    },
    {
      title: t("common.status"),
      dataIndex: "connect_status",
      key: "connect_status",
      render: (status: string) => {
        const color = status === "available" ? "green" : status === "unavailable" ? "red" : "orange";
        return <Tag color={color}>{status}</Tag>;
      },
    },
    {
      title: t("common.actions"),
      key: "actions",
      render: (_, record: ModelOption) => (
        <div className="space-x-2">
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          <Popconfirm
            title={t("tenantResources.models.confirmDelete")}
            description="This action cannot be undone."
            onConfirm={() => handleDelete(record.displayName, record.source)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </div>
      ),
    },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div />
        <div>
          <Button type="primary" onClick={openCreate}>
            + {t("modelConfig.button.addCustomModel")}
          </Button>
        </div>
      </div>

      <Table
        columns={columns}
        dataSource={models}
        loading={isLoading}
        rowKey="id"
        pagination={{ pageSize: 10 }}
      />

      <ModelAddDialog
        isOpen={addDialogVisible}
        onClose={handleAddDialogClose}
        onSuccess={handleAddDialogSuccess}
      />

      <ModelEditDialog
        isOpen={editDialogVisible}
        model={editingModel}
        onClose={handleEditDialogClose}
        onSuccess={handleEditDialogSuccess}
      />
    </div>
  );
}
