// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Checkbox,
  Descriptions,
  Drawer,
  Dropdown,
  Empty,
  Form,
  Input,
  Segmented,
  Select,
  Skeleton,
  Table,
  Tooltip,
  type TableColumnsType,
} from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  ReloadOutlined,
  SearchOutlined,
  SettingOutlined,
} from "@ant-design/icons";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { AIDP_ONTOLOGY_MANAGER_ROLES } from "@/ext_components/aidp/shared/utils/aidpOntologyRoles";
import AidpOntologyFieldLabel from "@/ext_components/aidp/shared/components/AidpOntologyFieldLabel";
import {
  METADATA_FIELD_LIMIT,
  validateFieldName,
} from "@/ext_components/aidp/shared/utils/aidpOntologyValidation";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import { formatAidpDateTime } from "@/ext_components/aidp/shared/utils/aidpTime";
import AidpResizableTitle, {
  type AidpResizableTitleProps,
} from "@/ext_components/aidp/pages/knowledge-list/AidpResizableTitle";
import { AIDP_MIN_COLUMN_WIDTH } from "@/ext_components/aidp/pages/knowledge-list/utils/aidpKnowledgeColumnWidths";
import { useAidpOntologyColumnWidths } from "@/ext_components/aidp/shared/hooks/useAidpOntologyColumnWidths";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type {
  AidpMetadataFieldType,
  AidpOntologyMetadataField,
} from "@/ext_components/aidp/shared/types/ontology";
import AidpOntologyGapNote from "@/ext_components/aidp/shared/components/AidpOntologyGapNote";
import drawerStyles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import tableStyles from "@/ext_components/aidp/shared/styles/AidpOntologyTable.module.css";
import styles from "./AidpOntologyMetadataFields.module.css";

interface AidpOntologyMetadataFieldsProps {
  domainId: string;
  /** Open the create-field dialog once for the list quick action. */
  autoOpenCreate?: boolean;
}

interface FieldFormValues {
  field_name: string;
  field_type: AidpMetadataFieldType;
}

interface CreateFormValues {
  field_name: string;
  field_type: AidpMetadataFieldType;
}

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;
const DEFAULT_PAGE_SIZE = 10;

const TYPE_LABEL_KEYS: Record<AidpMetadataFieldType, string> = {
  string: "aidpKnowledge.ontologyMetadataTypeText",
  date: "aidpKnowledge.ontologyMetadataTypeDate",
  number: "aidpKnowledge.ontologyMetadataTypeNumber",
};

const fieldKey = (field: AidpOntologyMetadataField): string =>
  String(field.id ?? field.field_name);

const AidpOntologyMetadataFields: React.FC<AidpOntologyMetadataFieldsProps> = ({
  domainId,
  autoOpenCreate = false,
}) => {
  const { t } = useTranslation();
  const { message, modal } = App.useApp();
  const scope = useAidpQueryScope();
  const queryClient = useQueryClient();
  const { user, isAuthzReady } = useAuthorizationContext();
  const canManage = !!user && AIDP_ONTOLOGY_MANAGER_ROLES.has(user.role) && isAuthzReady;
  const [editForm] = Form.useForm<FieldFormValues>();
  const [createForm] = Form.useForm<CreateFormValues>();
  const [createOpen, setCreateOpen] = useState(autoOpenCreate);
  const [editing, setEditing] = useState<AidpOntologyMetadataField | null>(
    null
  );
  const [detailField, setDetailField] =
    useState<AidpOntologyMetadataField | null>(null);
  const [saving, setSaving] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [visibleColumns, setVisibleColumns] = useState({
    createTime: true,
    updateTime: true,
  });
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const next = searchInput.trim();
      setSearch((current) => (current === next ? current : next));
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const query = useQuery({
    queryKey: [
      ...scope.key,
      "ontology-metadata-fields",
      domainId,
      { page, pageSize, search },
    ],
    queryFn: () =>
      aidpOntologyService.listMetadataFields(
        domainId,
        page,
        pageSize,
        search || undefined
      ),
    enabled: scope.enabled && !!domainId,
    staleTime: 0,
    retry: false,
  });

  const fields = useMemo(() => query.data?.value ?? [], [query.data?.value]);
  const limit = query.data?.limit ?? METADATA_FIELD_LIMIT;
  const total = query.data?.total_count ?? 0;
  const allCount = query.data?.all_count ?? total;
  const hasMore = query.data?.has_more ?? false;
  const totalReliable = query.data?.total_reliable !== false;
  const atLimit = allCount >= limit;
  const selectedFields = fields.filter((field) =>
    selectedKeys.includes(fieldKey(field))
  );
  const errorMessageFromQuery = query.error
    ? getAidpErrorMessage(
        query.error,
        t,
        t("aidpKnowledge.ontologyMetadataFieldsLoadFailed")
      )
    : undefined;

  const refresh = () => {
    void queryClient.invalidateQueries({
      queryKey: [...scope.key, "ontology-metadata-fields", domainId],
    });
    void queryClient.invalidateQueries({
      queryKey: [...scope.key, "ontology-chunks"],
    });
    void queryClient.invalidateQueries({
      queryKey: [...scope.key, "ontology-chunk"],
    });
  };

  const openCreate = () => {
    setCreateError(null);
    createForm.resetFields();
    createForm.setFieldsValue({ field_type: "string" });
    setCreateOpen(true);
  };

  const openEdit = (field: AidpOntologyMetadataField) => {
    setEditing(field);
    setErrorMessage(null);
    editForm.setFieldsValue({
      field_name: field.field_name,
      field_type: field.field_type,
    });
  };

  const closeEdit = () => {
    setErrorMessage(null);
    setSaving(false);
    setEditing(null);
  };

  const handleCreate = async () => {
    let values: CreateFormValues;
    try {
      values = await createForm.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    setCreateError(null);
    try {
      await aidpOntologyService.createMetadataField(domainId, {
        field_name: values.field_name.trim(),
        field_type: values.field_type,
      });
      message.success(t("aidpKnowledge.ontologyMetadataFieldCreated"));
      setCreateOpen(false);
      setPage(1);
      refresh();
    } catch (error) {
      setCreateError(
        getAidpErrorMessage(
          error,
          t,
          t("aidpKnowledge.ontologyMetadataFieldCreateFailed")
        )
      );
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = async () => {
    if (!editing) return;
    let values: FieldFormValues;
    try {
      values = await editForm.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    setErrorMessage(null);
    try {
      if (values.field_name.trim() !== editing.field_name) {
        const renamed = await aidpOntologyService.renameMetadataField(
          domainId,
          editing.id ?? editing.field_name,
          values.field_name.trim()
        );
        if (renamed.accepted) {
          message.info(
            t("aidpKnowledge.ontologyMetadataFieldRenameAccepted", {
              taskId: renamed.task_id ?? "",
            }),
            8
          );
        } else {
          message.success(t("aidpKnowledge.ontologyMetadataFieldRenamed"));
        }
      }
      message.success(t("aidpKnowledge.ontologyMetadataUpdated"));
      closeEdit();
      refresh();
    } catch (error) {
      setErrorMessage(
        getAidpErrorMessage(
          error,
          t,
          t("aidpKnowledge.ontologyMetadataFieldRenameFailed")
        )
      );
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = (field: AidpOntologyMetadataField) => {
    modal.confirm({
      title: t("aidpKnowledge.ontologyMetadataDeleteConfirmTitle", {
        name: field.field_name,
      }),
      width: 520,
      content: (
        <div className={styles.confirmBody}>
          <p>{t("aidpKnowledge.ontologyMetadataDeleteConfirmContent")}</p>
        </div>
      ),
      okText: t("aidpKnowledge.ontologyMetadataDeleteSubmit"),
      cancelText: t("common.cancel"),
      centered: true,
      onOk: async () => {
        try {
          const result = await aidpOntologyService.deleteMetadataField(
            domainId,
            field.id ?? field.field_name
          );
          if (result.accepted) {
            message.info(
              t("aidpKnowledge.ontologyMetadataFieldDeleteAccepted", {
                taskId: result.task_id ?? "",
              }),
              8
            );
          } else if ((result.failed_kbs ?? []).length > 0) {
            message.warning(
              t("aidpKnowledge.ontologyMetadataDeletePartial", {
                count: result.failed_kbs?.length ?? 0,
                kbs: (result.failed_kbs ?? []).join(", "),
              }),
              8
            );
          } else {
            message.success(t("aidpKnowledge.ontologyMetadataFieldDeleted"));
          }
          refresh();
        } catch (error) {
          message.error(
            getAidpErrorMessage(
              error,
              t,
              t("aidpKnowledge.ontologyMetadataFieldDeleteFailed")
            )
          );
          throw error;
        }
      },
    });
  };

  const handleBatchUnbind = () => {
    if (selectedFields.length === 0) {
      message.warning(t("aidpKnowledge.ontologyMetadataSelectDeleteRequired"));
      return;
    }
    modal.confirm({
      title: t("aidpKnowledge.ontologyMetadataBatchUnbindTitle"),
      width: 520,
      content: (
        <div className={styles.confirmBody}>
          <p>{t("aidpKnowledge.ontologyMetadataBatchUnbindContent")}</p>
        </div>
      ),
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
      centered: true,
      onOk: async () => {
        setSaving(true);
        try {
          const result = await aidpOntologyService.batchUnbindMetadata(
            domainId,
            selectedFields.map((field) => field.id ?? field.field_name)
          );
          if (result.accepted) {
            message.info(
              t("aidpKnowledge.ontologyMetadataUnbindAccepted", {
                taskId: result.task_id ?? "",
              }),
              8
            );
          } else {
            message.success(t("aidpKnowledge.ontologyMetadataUnbindDone"));
          }
          setSelectedKeys([]);
          refresh();
        } catch (error) {
          message.error(
            getAidpErrorMessage(
              error,
              t,
              t("aidpKnowledge.ontologyMetadataUnbindFailed")
            )
          );
          throw error;
        } finally {
          setSaving(false);
        }
      },
    });
  };

  const handleBatchDelete = () => {
    if (selectedFields.length === 0) {
      message.warning(t("aidpKnowledge.ontologyMetadataSelectDeleteRequired"));
      return;
    }
    modal.confirm({
      title: t("aidpKnowledge.ontologyMetadataBatchDeleteTitle", {
        count: selectedFields.length,
      }),
      width: 520,
      content: (
        <div className={styles.confirmBody}>
          <p>{t("aidpKnowledge.ontologyMetadataDeleteConfirmContent")}</p>
        </div>
      ),
      okText: t("aidpKnowledge.ontologyMetadataDeleteSubmit"),
      cancelText: t("common.cancel"),
      centered: true,
      onOk: async () => {
        setSaving(true);
        try {
          const outcomes = await Promise.allSettled(
            selectedFields.map((field) =>
              aidpOntologyService.deleteMetadataField(
                domainId,
                field.id ?? field.field_name
              )
            )
          );
          const acceptedNames: string[] = [];
          let taskId: string | null = null;
          let failed = 0;
          const failedKbs = new Set<string>();
          outcomes.forEach((outcome, index) => {
            if (outcome.status === "rejected") {
              failed += 1;
              return;
            }
            for (const kbs of outcome.value.failed_kbs ?? []) {
              failedKbs.add(kbs);
            }
            if (outcome.value.accepted) {
              acceptedNames.push(selectedFields[index].field_name);
              taskId = taskId ?? outcome.value.task_id ?? null;
            }
          });
          if (acceptedNames.length > 0) {
            message.info(
              t("aidpKnowledge.ontologyMetadataFieldDeleteAccepted", {
                taskId: taskId ?? "",
              }),
              8
            );
          } else if (failed === 0) {
            message.success(t("aidpKnowledge.ontologyMetadataFieldDeleted"));
          }
          if (failed > 0) {
            message.warning(
              t("aidpKnowledge.ontologyMetadataBatchDeletePartial", {
                count: failed,
              })
            );
          }
          if (failedKbs.size > 0) {
            message.warning(
              t("aidpKnowledge.ontologyMetadataDeletePartial", {
                count: failedKbs.size,
                kbs: Array.from(failedKbs).join(", "),
              }),
              8
            );
          }
          setSelectedKeys([]);
          refresh();
        } finally {
          setSaving(false);
        }
      },
    });
  };

  const typeLabel = (value: AidpMetadataFieldType) =>
    t(TYPE_LABEL_KEYS[value]);

  const columns: TableColumnsType<AidpOntologyMetadataField> = [
    {
      title: t("aidpKnowledge.ontologyMetadataFieldName"),
      dataIndex: "field_name",
      key: "field_name",
      width: 220,
      render: (value: string, record) => (
        <button
          type="button"
          className={styles.nameLink}
          onClick={() => setDetailField(record)}
        >
          {value}
        </button>
      ),
    },
    {
      title: t("aidpKnowledge.ontologyMetadataFieldType"),
      dataIndex: "field_type",
      key: "field_type",
      width: 160,
      render: (value: AidpMetadataFieldType) => typeLabel(value),
    },
    ...(visibleColumns.createTime
      ? [
          {
            title: t("aidpKnowledge.ontologyMetadataColumnCreateTime"),
            key: "create_time",
            width: 200,
            render: (_value: unknown, record: AidpOntologyMetadataField) => (
              <span>{formatAidpDateTime(record.create_time)}</span>
            ),
          },
        ]
      : []),
    ...(visibleColumns.updateTime
      ? [
          {
            title: t("aidpKnowledge.ontologyMetadataColumnUpdateTime"),
            key: "update_time",
            width: 200,
            render: (_value: unknown, record: AidpOntologyMetadataField) => (
              <span>{formatAidpDateTime(record.update_time)}</span>
            ),
          },
        ]
      : []),
    {
      title: t("aidpKnowledge.ontologyColumnActions"),
      key: "actions",
      width: 140,
      fixed: "right",
      render: (_value, record) => (
        <div className={tableStyles.rowActions}>
          <Button
            type="link"
            size="small"
            disabled={!canManage}
            onClick={() => openEdit(record)}
          >
            {t("aidpKnowledge.ontologyMetadataEdit")}
          </Button>
          <Button
            type="link"
            size="small"
            disabled={!canManage}
            onClick={() => handleDelete(record)}
          >
            {t("aidpKnowledge.ontologyMetadataDelete")}
          </Button>
        </div>
      ),
    },
  ];

  const columnKeys = columns.map((column) => String(column.key));
  const { tableContainer, columnWidths, totalWidth, handleResize } =
    useAidpOntologyColumnWidths(columnKeys, {
      field_name: 1.4,
      field_type: 1,
      create_time: 1.2,
      update_time: 1.2,
      actions: 0.9,
    });
  const resizableColumns = columns.map((column, index) => {
    const key = columnKeys[index];
    const nextKey = columnKeys[index + 1];
    return {
      ...column,
      width: columnWidths[key],
      onHeaderCell: () =>
        ({
          width: columnWidths[key],
          maxWidth: nextKey
            ? columnWidths[key] + columnWidths[nextKey] - AIDP_MIN_COLUMN_WIDTH
            : undefined,
          "data-column-key": key,
          onResize: nextKey
            ? (delta: number, rendered: Record<string, number>) =>
                handleResize(key, nextKey, delta, rendered)
            : undefined,
        }) as AidpResizableTitleProps,
    };
  });

  const detailItems = detailField
    ? [
        {
          key: "name",
          label: t("aidpKnowledge.ontologyMetadataFieldName"),
          children: detailField.field_name,
        },
        {
          key: "id",
          label: t("aidpKnowledge.ontologyMetadataColumnId"),
          children: detailField.id ?? t("aidpKnowledge.ontologyDash"),
        },
        {
          key: "type",
          label: t("aidpKnowledge.ontologyMetadataFieldType"),
          children: typeLabel(detailField.field_type),
        },
        {
          key: "column",
          label: t("aidpKnowledge.ontologyMetadataColumnIndex"),
          children: detailField.column_index ?? t("aidpKnowledge.ontologyDash"),
        },
      ]
    : [];

  const emptyTable = (
    <Empty
      image={Empty.PRESENTED_IMAGE_DEFAULT}
      description={t("aidpKnowledge.ontologyMetadataTableEmpty")}
    />
  );

  return (
    <div className={tableStyles.tab}>
      <div className={tableStyles.toolbar}>
        <Input
          allowClear
          className={tableStyles.searchInput}
          prefix={<SearchOutlined />}
          placeholder={t("aidpKnowledge.ontologyMetadataSearchPlaceholder")}
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
        />
        <div className={tableStyles.toolbarActions}>
          <Button
            type="text"
            aria-label={t("aidpKnowledge.refresh")}
            icon={<ReloadOutlined spin={query.isFetching} />}
            onClick={() => void query.refetch()}
          />
          <Button
            loading={saving}
            disabled={!canManage || selectedFields.length === 0}
            onClick={handleBatchUnbind}
          >
            {t("aidpKnowledge.ontologyMetadataUnbind")}
          </Button>
          <Button
            loading={saving}
            disabled={!canManage || selectedFields.length === 0}
            onClick={handleBatchDelete}
          >
            {t("aidpKnowledge.ontologyMetadataDelete")}
          </Button>
          <Tooltip
            title={
              atLimit
                ? t("aidpKnowledge.ontologyMetadataFieldLimitReached")
                : undefined
            }
          >
            <Button
              type="primary"
              disabled={!canManage || atLimit}
              onClick={openCreate}
            >
              {t("aidpKnowledge.ontologyMetadataFieldCreate")}
            </Button>
          </Tooltip>
          <Dropdown
            trigger={["click"]}
            menu={{
              items: [
                {
                  key: "createTime",
                  label: (
                    <Checkbox
                      checked={visibleColumns.createTime}
                      onChange={(event) =>
                        setVisibleColumns((previous) => ({
                          ...previous,
                          createTime: event.target.checked,
                        }))
                      }
                    >
                      {t("aidpKnowledge.ontologyMetadataColumnCreateTime")}
                    </Checkbox>
                  ),
                },
                {
                  key: "updateTime",
                  label: (
                    <Checkbox
                      checked={visibleColumns.updateTime}
                      onChange={(event) =>
                        setVisibleColumns((previous) => ({
                          ...previous,
                          updateTime: event.target.checked,
                        }))
                      }
                    >
                      {t("aidpKnowledge.ontologyMetadataColumnUpdateTime")}
                    </Checkbox>
                  ),
                },
              ],
            }}
          >
            <Tooltip title={t("aidpKnowledge.ontologyMetadataColumnSettings")}>
              <Button
                aria-label={t("aidpKnowledge.ontologyMetadataColumnSettings")}
                icon={<SettingOutlined />}
              />
            </Tooltip>
          </Dropdown>
        </div>
      </div>

      <AidpOntologyGapNote
        title={t("aidpKnowledge.ontologyMetadataLengthGapTitle")}
      >
        {t("aidpKnowledge.ontologyMetadataLengthGap")}
      </AidpOntologyGapNote>
      <div className={tableStyles.tableArea} ref={tableContainer}>
        {query.isLoading ? (
          <div className={tableStyles.stateBlock}>
            <Skeleton active title={false} paragraph={{ rows: 4 }} />
          </div>
        ) : query.isError ? (
          <div className={tableStyles.stateBlock}>
            <div className={tableStyles.errorText} role="alert">
              {errorMessageFromQuery}
            </div>
            <Button onClick={() => void query.refetch()}>
              {t("aidpKnowledge.retry")}
            </Button>
          </div>
        ) : (
          <Table<AidpOntologyMetadataField>
            rowKey={fieldKey}
            size="middle"
            className={tableStyles.table}
            columns={resizableColumns}
            dataSource={fields}
            pagination={false}
            tableLayout="fixed"
            components={{ header: { cell: AidpResizableTitle } }}
            scroll={{ x: totalWidth }}
            rowSelection={
              canManage
                ? {
                    selectedRowKeys: selectedKeys,
                    onChange: setSelectedKeys,
                    getCheckboxProps: (record) => ({
                      disabled: record.id === undefined || record.id === null,
                    }),
                  }
                : undefined
            }
            locale={{
              emptyText: emptyTable,
            }}
          />
        )}
      </div>
      {fields.length > 0 && (
        <div className={tableStyles.paginationRow}>
          <AidpPagination
            currentPage={page}
            pageSize={pageSize}
            pageSizeOptions={PAGE_SIZE_OPTIONS}
            total={total}
            totalReliable={totalReliable}
            hasMore={hasMore}
            selectionHint={
              selectedKeys.length
                ? t("aidpKnowledge.selectedCount", {
                    count: selectedKeys.length,
                  })
                : undefined
            }
            onPageChange={setPage}
            onPageSizeChange={(nextSize) => {
              setPageSize(nextSize);
              setPage(1);
            }}
          />
        </div>
      )}

      <Drawer
        rootClassName={drawerStyles.drawer}
        open={createOpen}
        width={560}
        title={t("aidpKnowledge.ontologyMetadataCreateModalTitle")}
        onClose={() => setCreateOpen(false)}
        destroyOnHidden
        footer={
          <div className={drawerStyles.footer}>
            <Button onClick={() => setCreateOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              type="primary"
              loading={saving}
              onClick={() => void handleCreate()}
            >
              {t("common.confirm")}
            </Button>
          </div>
        }
      >
        <Form
          form={createForm}
          layout="vertical"
          className={drawerStyles.form}
          initialValues={{ field_type: "string" }}
        >
          <Form.Item
            name="field_name"
            label={
              <AidpOntologyFieldLabel
                label={t("aidpKnowledge.ontologyMetadataFieldName")}
                help={t("aidpKnowledge.ontologyMetadataFieldNameHelp")}
              />
            }
            required
            rules={[
              {
                validator: async (_rule, value: string) => {
                  if (!(value ?? "").trim()) {
                    throw new Error(
                      t("aidpKnowledge.ontologyMetadataNameRequired")
                    );
                  }
                  const error = validateFieldName(value ?? "", t);
                  if (error) throw new Error(error);
                },
              },
            ]}
          >
            <Input maxLength={63} showCount />
          </Form.Item>
          <Form.Item
            name="field_type"
            label={
              <AidpOntologyFieldLabel
                label={t("aidpKnowledge.ontologyMetadataValueType")}
                help={t("aidpKnowledge.ontologyMetadataFieldTypeHelp")}
              />
            }
            required
            rules={[{ required: true }]}
          >
            <Segmented<AidpMetadataFieldType>
              block
              className={styles.typeSegmented}
              options={[
                { value: "string", label: typeLabel("string") },
                { value: "number", label: typeLabel("number") },
                { value: "date", label: typeLabel("date") },
              ]}
            />
          </Form.Item>
          {createError && (
            <div className={drawerStyles.error} role="alert">
              {createError}
            </div>
          )}
        </Form>
      </Drawer>

      <Drawer
        rootClassName={drawerStyles.drawer}
        open={!!editing}
        width={560}
        onClose={closeEdit}
        destroyOnHidden
        title={t("aidpKnowledge.ontologyMetadataEditTitle")}
        footer={
          <div className={drawerStyles.footer}>
            <Button onClick={closeEdit}>{t("common.cancel")}</Button>
            <Button
              type="primary"
              loading={saving}
              onClick={() => void handleEdit()}
            >
              {t("aidpKnowledge.ontologyMetadataSave")}
            </Button>
          </div>
        }
      >
        <Form
          key={editing ? `edit-${editing.id ?? editing.field_name}` : "closed"}
          form={editForm}
          layout="vertical"
          className={drawerStyles.form}
          initialValues={{
            field_name: editing?.field_name ?? "",
            field_type: editing?.field_type ?? "string",
          }}
        >
          <Form.Item
            name="field_name"
            label={
              <AidpOntologyFieldLabel
                label={t("aidpKnowledge.ontologyMetadataFieldName")}
                help={t("aidpKnowledge.ontologyMetadataFieldNameHelp")}
              />
            }
            rules={[
              {
                validator: async (_rule, value: string) => {
                  if (!(value ?? "").trim()) {
                    throw new Error(
                      t("aidpKnowledge.ontologyMetadataNameRequired")
                    );
                  }
                  const error = validateFieldName(value ?? "", t);
                  if (error) throw new Error(error);
                },
              },
            ]}
          >
            <Input maxLength={63} />
          </Form.Item>
          <Form.Item
            name="field_type"
            label={
              <AidpOntologyFieldLabel
                label={t("aidpKnowledge.ontologyMetadataFieldType")}
                help={t("aidpKnowledge.ontologyMetadataFieldTypeHelp")}
              />
            }
            rules={[{ required: true }]}
          >
            <Select
              disabled
              options={[
                { value: "string", label: typeLabel("string") },
                { value: "number", label: typeLabel("number") },
                { value: "date", label: typeLabel("date") },
              ]}
            />
          </Form.Item>

          {errorMessage && (
            <div className={drawerStyles.error} role="alert">
              {errorMessage}
            </div>
          )}
        </Form>
      </Drawer>

      <Drawer
        rootClassName={drawerStyles.drawer}
        open={!!detailField}
        width={560}
        mask={false}
        onClose={() => setDetailField(null)}
        destroyOnHidden
        title={
          detailField?.field_name ??
          t("aidpKnowledge.ontologyMetadataDetailTitle")
        }
        extra={
          detailField ? (
            <div className={styles.headerActions}>
              <Tooltip title={t("aidpKnowledge.ontologyMetadataEdit")}>
                <Button
                  type="text"
                  size="small"
                  aria-label={t("aidpKnowledge.ontologyMetadataEdit")}
                  icon={<EditOutlined />}
                  onClick={() => {
                    const target = detailField;
                    setDetailField(null);
                    openEdit(target);
                  }}
                />
              </Tooltip>
              <Tooltip title={t("aidpKnowledge.ontologyMetadataDelete")}>
                <Button
                  type="text"
                  size="small"
                  aria-label={t("aidpKnowledge.ontologyMetadataDelete")}
                  icon={<DeleteOutlined />}
                  onClick={() => {
                    const target = detailField;
                    setDetailField(null);
                    handleDelete(target);
                  }}
                />
              </Tooltip>
            </div>
          ) : null
        }
      >
        {detailField && (
          <div className={styles.detailBody}>
            <Descriptions
              size="small"
              column={1}
              bordered
              items={detailItems}
            />
          </div>
        )}
      </Drawer>
    </div>
  );
};

export default AidpOntologyMetadataFields;
