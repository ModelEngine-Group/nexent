"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Table, Button, Popconfirm, message, Tag, Pagination } from "antd";
import { Edit, Trash2, RefreshCw } from "lucide-react";
import { Tooltip } from "@/components/ui/tooltip";
import { ColumnsType } from "antd/es/table";
import { useManageTenantModels } from "@/hooks/model/useManageTenantModels";
import { modelService } from "@/services/modelService";
import { type ModelOption, type ModelType } from "@/types/modelConfig";
import { ModelAddDialog } from "../../../models/components/model/ModelAddDialog";
import { ModelEditDialog } from "../../../models/components/model/ModelEditDialog";
import { CheckCircle, CircleSlash, XCircle, CircleEllipsis, CircleHelp } from "lucide-react";

export default function ModelList({ tenantId }: { tenantId: string | null }) {
  const { t } = useTranslation("common");

  // Pagination state
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  // Use manage API to get models for the specified tenant
  const {
    models = [],
    total = 0,
    isLoading,
    refetch,
  } = useManageTenantModels({
    tenantId: tenantId || "",
    page,
    pageSize,
  });

  const [editingModel, setEditingModel] = useState<ModelOption | null>(null);
  const [addDialogVisible, setAddDialogVisible] = useState(false);
  const [editDialogVisible, setEditDialogVisible] = useState(false);

  // Track which models are being checked for connectivity
  const [checkingConnectivity, setCheckingConnectivity] = useState<Set<string>>(new Set());

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

  const handleDelete = async (displayName: string, _provider?: string) => {
    if (!tenantId) {
      message.error("Tenant ID is required");
      return;
    }
    try {
      await modelService.deleteManageTenantModel({
        tenantId,
        displayName,
      });
      message.success(t("tenantResources.models.deleteSuccess"));
      refetch();
    } catch (error: any) {
      if (error.response?.data?.message) {
        message.error(error.response.data.message);
      } else {
        message.error(t("tenantResources.models.deleteFailed"));
      }
    }
  };

  // Handle checking model connectivity
  const handleCheckConnectivity = async (displayName: string) => {
    if (!tenantId) {
      message.error("Tenant ID is required");
      return;
    }

    setCheckingConnectivity((prev) => new Set(prev).add(displayName));
    try {
      const isConnected = await modelService.checkManageTenantModelConnectivity(
        tenantId,
        displayName
      );
      if (isConnected) {
        message.success(t("tenantResources.models.connectivitySuccess"));
      } else {
        message.warning(t("tenantResources.models.connectivityFailed"));
      }
      // Refresh the model list to get updated connectivity status
      refetch();
    } catch (error) {
      message.error(t("tenantResources.models.connectivityError"));
    } finally {
      setCheckingConnectivity((prev) => {
        const next = new Set(prev);
        next.delete(displayName);
        return next;
      });
    }
  };

  // Handle pagination change
  const handlePageChange = (newPage: number, newPageSize: number) => {
    setPage(newPage);
    if (newPageSize !== pageSize) {
      setPageSize(newPageSize);
      setPage(1);
    }
  };


  const columns: ColumnsType<ModelOption> = [
    {
      title: t("common.name"),
      dataIndex: "displayName",
      key: "displayName",
      width: 170,
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
      width: 100,
      render: (type: ModelType) => <Tag>{t(`tenantResources.models.type.${type}`)}</Tag>,
    },
    {
      title: t("common.status"),
      dataIndex: "connect_status",
      key: "connect_status",
      width: 100,
      render: (status: string) => {
        const color =
                status === "available" ? "#229954" :
                status === "unavailable" ? "#E74C3C" :
                status === "detecting" ? "#5499C7" :
                status === "not_detected" ? "#AEB6BF" : "#2E4053";

        const icon = status === "available" ? <CheckCircle className="w-3 h-3 mr-1" /> :
                status === "unavailable" ? <CircleSlash className="w-3 h-3 mr-1" /> :
                status === "detecting" ? <CircleEllipsis className="w-3 h-3 mr-1" /> :
                status === "not_detected" ? <CircleHelp className="w-3.5 h-3.5 mr-1" /> :
                <XCircle className="w-3 h-3 mr-1" />;
        return (
          <Tag
            color={color}
            className="inline-flex items-center"
            variant="solid">
            {icon}
            {t(`tenantResources.models.status.${status}`)}
          </Tag>
        );
      },
    },
    {
      title: t("common.source"),
      dataIndex: "source",
      key: "source",
      width: 100,
      render: (source: string) => <Tag color="default">{source}</Tag>,
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 300,
      render: (_, record: ModelOption) => (
        <div className="flex items-center space-x-2">
          <Tooltip title={t("tenantResources.models.checkConnectivity")}>
            <Button
              type="text"
              icon={checkingConnectivity.has(record.displayName) ? <RefreshCw className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              onClick={() => handleCheckConnectivity(record.displayName)}
              size="small"
              loading={checkingConnectivity.has(record.displayName)}
            />
          </Tooltip>
          <Tooltip title={t("tenantResources.models.editModel")}>
            <Button
              type="text"
              icon={<Edit className="h-4 w-4" />}
              onClick={() => openEdit(record)}
              size="small"
            />
          </Tooltip>
          <Popconfirm
            title={t("tenantResources.models.confirmDelete")}
            description={t("common.cannotBeUndone")}
            onConfirm={() => handleDelete(record.displayName, record.source)}
            okText={t("common.confirm")}
            cancelText={t("common.cancel")}
          >
            <Tooltip title={t("tenantResources.models.deleteModel")}>
              <Button
                type="text"
                danger
                icon={<Trash2 className="h-4 w-4" />}
                size="small"
              />
            </Tooltip>
          </Popconfirm>
        </div>
      ),
    },
  ];

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
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
        scroll={{ x: true }}
        className="flex-1"
      />

      <ModelAddDialog
        isOpen={addDialogVisible}
        onClose={handleAddDialogClose}
        onSuccess={handleAddDialogSuccess}
        tenantId={tenantId || undefined}
      />

      <ModelEditDialog
        isOpen={editDialogVisible}
        model={editingModel}
        onClose={handleEditDialogClose}
        onSuccess={handleEditDialogSuccess}
        tenantId={tenantId || undefined}
      />
    </div>
  );
}
