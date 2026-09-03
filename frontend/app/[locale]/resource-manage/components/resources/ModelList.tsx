"use client";

import React, { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  Table,
  Button,
  message,
  Tag,
  Segmented,
  Tooltip,
} from "antd";
import {
  CheckCircle,
  CircleEllipsis,
  CircleHelp,
  CircleSlash,
  Edit,
  RefreshCw,
  Trash2,
  TriangleAlert,
  XCircle,
} from "lucide-react";
import { ColumnsType } from "antd/es/table";
import type { TablePaginationConfig } from "antd";
import { FilterValue, SorterResult } from "antd/es/table/interface";
import { useManageTenantModels } from "@/hooks/model/useManageTenantModels";
import { useCapacityCoverage } from "@/hooks/model/useCapacityCoverage";
import { useMonitoringData, type TimeRange } from "@/hooks/useMonitoringData";
import { modelService } from "@/services/modelService";
import { type ModelOption, type ModelType } from "@/types/modelConfig";
import type { ModelMonitoringItem } from "@/types/monitoring";
import { MODEL_TYPES } from "@/const/modelConfig";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { ModelAddDialog } from "../../../models/components/model/ModelAddDialog";
import { ModelEditDialog } from "../../../models/components/model/ModelEditDialog";
interface UnifiedModelRow extends ModelOption {
  request_count?: number;
  error_rate?: number;
  avg_duration?: number;
  avg_ttft?: number;
  token_generation_rate?: number;
  total_tokens?: number;
}

export default function ModelList({ tenantId }: { tenantId: string | null }) {
  const { t } = useTranslation("common");
  const { confirm } = useConfirmModal();

  const { bareModelIds } = useCapacityCoverage();

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

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

  const {
    models: monitoringModels,
    loading: monitoringLoading,
    refresh: refreshMonitoring,
    timeRange: monitoringTimeRange,
    setTimeRange: setMonitoringTimeRange,
  } = useMonitoringData();

  const [editingModel, setEditingModel] = useState<ModelOption | null>(null);
  const [addDialogVisible, setAddDialogVisible] = useState(false);
  const [editDialogVisible, setEditDialogVisible] = useState(false);

  const [checkingConnectivity, setCheckingConnectivity] = useState<Set<string>>(
    new Set()
  );

  const monitoringMap = useMemo(() => {
    const map = new Map<string, ModelMonitoringItem>();
    for (const m of monitoringModels) {
      map.set(m.display_name, m);
    }
    return map;
  }, [monitoringModels]);

  const unifiedData: UnifiedModelRow[] = useMemo(() => {
    return models.map((m) => {
      const mon = monitoringMap.get(m.displayName);
      return {
        ...m,
        request_count: mon?.request_count,
        error_rate: mon?.error_rate,
        avg_duration: mon?.avg_duration,
        avg_ttft: mon?.avg_ttft,
        token_generation_rate: mon?.token_generation_rate,
        total_tokens: mon?.total_tokens,
      };
    });
  }, [models, monitoringMap]);

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
      message.error(t("tenantResources.tenants.tenantIdRequired"));
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
  const handleCheckConnectivity = async (
    displayName: string,
    modelType: string
  ) => {
    if (!tenantId) {
      message.error(t("tenantResources.tenants.tenantIdRequired"));
      return;
    }

    setCheckingConnectivity((prev) => new Set(prev).add(displayName));
    try {
      const isConnected = await modelService.checkManageTenantModelConnectivity(
        tenantId,
        displayName,
        modelType
      );
      if (isConnected) {
        message.success(t("tenantResources.models.connectivitySuccess"));
      } else {
        message.error(t("tenantResources.models.connectivityFailed"));
      }
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

  const handlePageChange = (
    pagination: TablePaginationConfig,
    _filters: Record<string, FilterValue | null>,
    _sorter: SorterResult<UnifiedModelRow> | SorterResult<UnifiedModelRow>[]
  ) => {
    const newPage = pagination.current || 1;
    const newPageSize = pagination.pageSize || 10;
    setPage(newPage);
    if (newPageSize !== pageSize) {
      setPageSize(newPageSize);
    }
  };

  const getErrorRateColor = (rate: number | undefined) => {
    if (rate === undefined) return "default";
    if (rate < 1.5) return "#52c41a";
    if (rate < 3) return "#faad14";
    return "#ff4d4f";
  };

  const getModelTypeName = (type: ModelType) => {
    switch (type) {
      case MODEL_TYPES.LLM:
        return t("model.type.llm");
      case MODEL_TYPES.EMBEDDING:
        return t("model.type.embedding");
      case MODEL_TYPES.MULTI_EMBEDDING:
        return t("model.type.multiEmbedding");
      case MODEL_TYPES.RERANK:
        return t("model.type.rerank");
      case MODEL_TYPES.STT:
        return t("model.type.stt");
      case MODEL_TYPES.TTS:
        return t("model.type.tts");
      case MODEL_TYPES.VLM:
        return t("model.type.imageUnderstanding");
      case MODEL_TYPES.VLM2:
        return t("model.type.imageGeneration");
      case MODEL_TYPES.VLM3:
        return t("model.type.videoUnderstanding");
      case MODEL_TYPES.VLM4: {
        return t("model.type.audioUnderstanding");
      }
      default:
        return t("model.type.unknown");
    }
  };

  const TEXT_MODEL_TYPES = ["llm", "vlm", "long_context"];

  const renderTextModelMetric = (
    value: number | undefined,
    record: UnifiedModelRow,
    formatter: (v: number) => string
  ) => {
    if (!TEXT_MODEL_TYPES.includes(record.type)) return "--";
    if (value === undefined) return "--";
    return formatter(value);
  };

  const columns: ColumnsType<UnifiedModelRow> = [
    {
      title: t("common.name"),
      dataIndex: "displayName",
      key: "displayName",
      width: 180,
      ellipsis: true,
      render: (displayName: string, record: UnifiedModelRow) => {
        // bareModelIds comes from /capacity-coverage which already filters
        // by CAPACITY_COVERAGE_MODEL_TYPES on the backend (llm/vlm/vlm2/vlm3).
        // The earlier `type === 'llm' || 'vlm'` guard was a duplicated
        // type list that drifted -- it silently hid the badge on vlm2
        // (image-gen) and vlm3 (video-und) rows even when backend marked
        // them bare. Drop the guard and trust the authoritative set.
        const isBareCapacity = Boolean(
          record.id && bareModelIds.has(record.id)
        );

        return (
          <div className="flex items-center">
            <span className="truncate">{displayName}</span>
            {isBareCapacity && (
              <Tooltip title={t("model.list.capacityWarning.badgeTooltip")}>
                <TriangleAlert
                  size={14}
                  className="text-yellow-500 cursor-pointer ml-1.5 shrink-0"
                  onClick={(e) => {
                    e.stopPropagation();
                    openEdit(record);
                  }}
                />
              </Tooltip>
            )}
          </div>
        );
      },
    },
    {
      title: t("common.type"),
      dataIndex: "type",
      key: "type",
      width: 220,
      ellipsis: {
        showTitle: false,
      },
      render: (type: ModelType) => {
        const typeName = getModelTypeName(type);
        return (
          <Tooltip title={typeName} placement="topLeft">
            <Tag
              color="default"
              className="max-w-full"
              style={{ display: "inline-flex", verticalAlign: "middle" }}
            >
              <span className="truncate">{typeName}</span>
            </Tag>
          </Tooltip>
        );
      },
    },
    {
      title: t("common.status"),
      dataIndex: "connect_status",
      key: "connect_status",
      width: 120,
      render: (status: string) => {
        const color =
          status === "available"
            ? "#229954"
            : status === "unavailable"
              ? "#E74C3C"
              : status === "detecting"
                ? "#5499C7"
                : status === "not_detected"
                  ? "#AEB6BF"
                  : "#2E4053";

        const icon =
          status === "available" ? (
            <CheckCircle className="w-3 h-3" />
          ) : status === "unavailable" ? (
            <CircleSlash className="w-3 h-3" />
          ) : status === "detecting" ? (
            <CircleEllipsis className="w-3 h-3" />
          ) : status === "not_detected" ? (
            <CircleHelp className="w-3.5 h-3.5" />
          ) : (
            <XCircle className="w-3 h-3" />
          );
        return (
          <Tag
            color={color}
            style={{
              display: "inline-flex",
              alignItems: "center",
              whiteSpace: "nowrap",
              flexShrink: 0,
            }}
            variant="solid"
          >
            <span className="inline-flex items-center mr-1">{icon}</span>
            {t(`tenantResources.models.status.${status}`)}
          </Tag>
        );
      },
    },
    {
      title: t("common.source"),
      dataIndex: "source",
      key: "source",
      width: 180,
      ellipsis: {
        showTitle: false,
      },
      render: (source: string) => (
        <Tooltip title={source} placement="topLeft">
          <Tag
            color="default"
            className="max-w-full"
            style={{ display: "inline-flex", verticalAlign: "middle" }}
          >
            <span className="truncate">{source}</span>
          </Tag>
        </Tooltip>
      ),
    },
    {
      title: t("monitoring.table.requests"),
      dataIndex: "request_count",
      key: "request_count",
      width: 120,
      sorter: (a: UnifiedModelRow, b: UnifiedModelRow) =>
        (a.request_count ?? 0) - (b.request_count ?? 0),
      render: (v: number | undefined) =>
        v !== undefined ? v.toLocaleString() : "--",
    },
    {
      title: t("monitoring.table.errorRate"),
      dataIndex: "error_rate",
      key: "error_rate",
      width: 130,
      sorter: (a: UnifiedModelRow, b: UnifiedModelRow) =>
        (a.error_rate ?? 0) - (b.error_rate ?? 0),
      render: (v: number | undefined) =>
        v !== undefined ? (
          <Tag color={getErrorRateColor(v)}>{v.toFixed(2)}%</Tag>
        ) : (
          "--"
        ),
    },
    {
      title: t("monitoring.table.avgDuration"),
      dataIndex: "avg_duration",
      key: "avg_duration",
      width: 150,
      sorter: (a: UnifiedModelRow, b: UnifiedModelRow) =>
        (a.avg_duration ?? 0) - (b.avg_duration ?? 0),
      render: (v: number | undefined) =>
        v !== undefined ? `${v.toFixed(0)} ${t("monitoring.time.ms")}` : "--",
    },
    {
      title: t("monitoring.table.avgTTFT"),
      dataIndex: "avg_ttft",
      key: "avg_ttft",
      width: 170,
      sorter: (a: UnifiedModelRow, b: UnifiedModelRow) =>
        (a.avg_ttft ?? 0) - (b.avg_ttft ?? 0),
      render: (v: number | undefined, record: UnifiedModelRow) =>
        renderTextModelMetric(
          v,
          record,
          (val) => `${val.toFixed(0)} ${t("monitoring.time.ms")}`
        ),
    },
    {
      title: t("monitoring.table.tokens"),
      dataIndex: "total_tokens",
      key: "total_tokens",
      width: 110,
      sorter: (a: UnifiedModelRow, b: UnifiedModelRow) =>
        (a.total_tokens ?? 0) - (b.total_tokens ?? 0),
      render: (v: number | undefined, record: UnifiedModelRow) =>
        renderTextModelMetric(v, record, (val) => val.toLocaleString()),
    },
    {
      title: t("monitoring.table.tokenGenerationRate"),
      dataIndex: "token_generation_rate",
      key: "token_generation_rate",
      width: 150,
      sorter: (a: UnifiedModelRow, b: UnifiedModelRow) =>
        (a.token_generation_rate ?? 0) - (b.token_generation_rate ?? 0),
      render: (v: number | undefined, record: UnifiedModelRow) =>
        renderTextModelMetric(
          v,
          record,
          (val) => `${val.toFixed(1)} ${t("monitoring.unit.tokensPerSec")}`
        ),
    },
    {
      key: "actions",
      width: 120,
      render: (_, record: UnifiedModelRow) => (
        <div className="flex items-center space-x-2">
          <Tooltip title={t("tenantResources.models.checkConnectivity")}>
            <Button
              type="text"
              icon={
                checkingConnectivity.has(record.displayName) ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )
              }
              onClick={() =>
                handleCheckConnectivity(record.displayName, record.type)
              }
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
          <Tooltip title={t("tenantResources.models.deleteModel")}>
            <Button
              type="text"
              danger
              icon={<Trash2 className="h-4 w-4" />}
              size="small"
              onClick={() =>
                confirm({
                  title: t("tenantResources.models.confirmDelete"),
                  content: t("common.cannotBeUndone"),
                  okText: t("common.confirm"),
                  cancelText: t("common.cancel"),
                  onOk: () => handleDelete(record.displayName, record.source),
                })
              }
            />
          </Tooltip>
        </div>
      ),
    },
  ];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <div className="flex items-center gap-3">
          <Segmented
            size="small"
            value={monitoringTimeRange}
            onChange={(v) => setMonitoringTimeRange(v as TimeRange)}
            options={[
              { label: t("monitoring.dashboard.timeRange.24h"), value: "24h" },
              { label: t("monitoring.dashboard.timeRange.7d"), value: "7d" },
              { label: t("monitoring.dashboard.timeRange.30d"), value: "30d" },
            ]}
          />
          <Button
            icon={<RefreshCw className="h-3 w-3" />}
            size="small"
            onClick={refreshMonitoring}
          >
            {t("monitoring.dashboard.refresh")}
          </Button>
        </div>
        <Button type="primary" onClick={openCreate}>
          + {t("modelConfig.button.addCustomModel")}
        </Button>
      </div>

      <Table
        columns={columns}
        dataSource={unifiedData}
        loading={isLoading || monitoringLoading}
        rowKey="id"
        pagination={{
          current: page,
          pageSize: pageSize,
          total: total,
        }}
        onChange={handlePageChange}
        scroll={{ y: "calc(100vh - 580px)" }}
        className="flex-1 [&_.ant-table]:h-full [&_.ant-table-thead>tr>th]:whitespace-nowrap [&_.ant-table-thead>tr>th.ant-table-column-has-sorters_.ant-table-column-title]:mr-3 [&_.ant-table-thead>tr>th.ant-table-column-has-sorters_.ant-table-column-sorter]:shrink-0"
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
