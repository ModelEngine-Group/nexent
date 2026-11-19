// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useMemo, useState } from "react";
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
  Modal,
  Segmented,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
  Tooltip,
  type TableColumnsType,
} from "antd";
import { SearchOutlined, SettingOutlined } from "@ant-design/icons";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { useAidpOntologyDemoMode } from "@/ext_components/aidp/shared/hooks/useAidpOntologyDemoMode";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import {
  METADATA_FIELD_LIMIT,
  validateFieldName,
} from "@/ext_components/aidp/shared/utils/aidpOntologyValidation";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type {
  AidpMetadataFieldType,
  AidpOntologyMetadataField,
} from "@/ext_components/aidp/shared/types/ontology";
import AidpOntologyGapNote from "@/ext_components/aidp/shared/components/AidpOntologyGapNote";
import drawerStyles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import tableStyles from "@/ext_components/aidp/shared/styles/AidpOntologyTable.module.css";
import AidpOntologyAsyncTaskModal, {
  type AidpOntologyTaskState,
} from "./AidpOntologyAsyncTaskModal";
import styles from "./AidpOntologyMetadataFields.module.css";

interface AidpOntologyMetadataFieldsProps {
  domainId: string;
  /** Open the create-field dialog once for the list quick action. */
  autoOpenCreate?: boolean;
}

interface FieldFormValues {
  field_name: string;
  field_type: AidpMetadataFieldType;
  demo_candidates?: string[];
  demo_range_start?: string;
  demo_range_end?: string;
}

interface CreateFormValues {
  field_name: string;
  field_type: AidpMetadataFieldType;
}

interface AsyncTaskState {
  open: boolean;
  taskName: string;
  fieldNames: string[];
  taskId: string | null;
  initialState: AidpOntologyTaskState;
}

const MANAGER_ROLES = new Set(["SU", "ADMIN", "SPEED", "ASSET_OWNER"]);
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;
const DEFAULT_PAGE_SIZE = 10;

const TYPE_LABEL_KEYS: Record<AidpMetadataFieldType, string> = {
  string: "aidpKnowledge.ontologyMetadataTypeText",
  time: "aidpKnowledge.ontologyMetadataTypeDate",
  number: "aidpKnowledge.ontologyMetadataTypeNumber",
};

/** Format an AIDP metadata audit value with minutes, never inventing a time. */
const formatAuditTime = (value?: string | null): string => {
  if (!value) return "—";
  const text = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(text)) {
    return text.slice(0, 16).replace("T", " ");
  }
  return text || "—";
};

const nowText = () => new Date().toISOString().slice(0, 16).replace("T", " ");

const fieldKey = (field: AidpOntologyMetadataField): string =>
  String(field.id ?? field.field_name);

const buildDemoPatch = (
  values: FieldFormValues,
  created = false
): Partial<AidpOntologyMetadataField> => {
  const candidates = [...(values.demo_candidates ?? [])];
  if (
    values.field_type !== "string" &&
    (values.demo_range_start || values.demo_range_end)
  ) {
    candidates.push(
      `${values.demo_range_start || "—"} ~ ${values.demo_range_end || "—"}`
    );
  }
  const timestamp = nowText();
  return {
    candidates,
    extended_properties: [],
    associated_chunk_count: 0,
    ...(created ? { create_time: timestamp } : {}),
    update_time: timestamp,
  };
};

const AidpOntologyMetadataFields: React.FC<AidpOntologyMetadataFieldsProps> = ({
  domainId,
  autoOpenCreate = false,
}) => {
  const { t } = useTranslation();
  const { message, modal } = App.useApp();
  const scope = useAidpQueryScope();
  const queryClient = useQueryClient();
  const demo = useAidpOntologyDemoMode();
  const { user, isAuthzReady } = useAuthorizationContext();
  const canManage = !!user && MANAGER_ROLES.has(user.role) && isAuthzReady;
  const [editForm] = Form.useForm<FieldFormValues>();
  const [createForm] = Form.useForm<CreateFormValues>();
  const editFieldType =
    (Form.useWatch("field_type", editForm) as
      AidpMetadataFieldType | undefined) ?? "string";
  const [createOpen, setCreateOpen] = useState(autoOpenCreate);
  const [editing, setEditing] = useState<AidpOntologyMetadataField | null>(
    null
  );
  const [detailField, setDetailField] =
    useState<AidpOntologyMetadataField | null>(null);
  const [saving, setSaving] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [demoExtras, setDemoExtras] = useState<
    Record<string, Partial<AidpOntologyMetadataField>>
  >({});
  const [visibleColumns, setVisibleColumns] = useState({
    createTime: true,
    updateTime: true,
  });
  const [task, setTask] = useState<AsyncTaskState>({
    open: false,
    taskName: "",
    fieldNames: [],
    taskId: null,
    initialState: "running",
  });

  const query = useQuery({
    queryKey: [...scope.key, "ontology-metadata-fields", domainId],
    queryFn: () => aidpOntologyService.listMetadataFields(domainId),
    enabled: scope.enabled && !!domainId,
    staleTime: 0,
    retry: false,
  });

  const fields = useMemo(
    () =>
      (query.data?.value ?? []).map((field) => ({
        ...field,
        ...(demoExtras[fieldKey(field)] ?? {}),
      })),
    [demoExtras, query.data?.value]
  );
  const limit = query.data?.limit ?? METADATA_FIELD_LIMIT;
  const atLimit = fields.length >= limit;
  const filteredFields = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return fields;
    return fields.filter((field) =>
      field.field_name.toLowerCase().includes(needle)
    );
  }, [fields, search]);
  const pagedFields = useMemo(
    () => filteredFields.slice((page - 1) * pageSize, page * pageSize),
    [filteredFields, page, pageSize]
  );
  const missingIds = fields.filter(
    (field) => field.id === undefined || field.id === null
  );
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
      demo_candidates: field.candidates ?? [],
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
      const created = await aidpOntologyService.createMetadataField(domainId, {
        field_name: values.field_name.trim(),
        field_type: values.field_type,
      });
      if (demo) {
        setDemoExtras((previous) => ({
          ...previous,
          [fieldKey(created)]: {
            ...buildDemoPatch(
              { field_name: values.field_name, field_type: values.field_type },
              true
            ),
            ...(previous[fieldKey(created)] ?? {}),
          },
        }));
      }
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
      if (demo) {
        setDemoExtras((previous) => ({
          ...previous,
          [fieldKey(editing)]: {
            ...(previous[fieldKey(editing)] ?? {}),
            ...buildDemoPatch(values),
          },
        }));
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

  const openTask = (
    taskName: string,
    fieldNames: string[],
    taskId: string | null
  ) => {
    setTask({
      open: true,
      taskName,
      fieldNames,
      taskId,
      initialState: "running",
    });
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
          <AidpOntologyGapNote>
            {t("aidpKnowledge.ontologyMetadataDeleteGap")}
          </AidpOntologyGapNote>
        </div>
      ),
      okText: t("aidpKnowledge.ontologyMetadataDeleteSubmit"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
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
            openTask(
              t("aidpKnowledge.ontologyAsyncTaskDeleteName"),
              [field.field_name],
              result.task_id ?? null
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
          <AidpOntologyGapNote>
            {t("aidpKnowledge.ontologyMetadataDeleteGap")}
          </AidpOntologyGapNote>
        </div>
      ),
      okText: t("aidpKnowledge.ontologyMetadataDeleteSubmit"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
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
          outcomes.forEach((outcome, index) => {
            if (outcome.status === "rejected") {
              failed += 1;
              return;
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
            openTask(
              t("aidpKnowledge.ontologyAsyncTaskDeleteName"),
              acceptedNames,
              taskId
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
          setSelectedKeys([]);
          refresh();
        } finally {
          setSaving(false);
        }
      },
    });
  };

  const typeLabel = (value: AidpMetadataFieldType) =>
    t(TYPE_LABEL_KEYS[value] ?? "aidpKnowledge.ontologyMetadataFieldType");

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
              <span>{formatAuditTime(record.create_time)}</span>
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
              <span>{formatAuditTime(record.update_time)}</span>
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
            danger
            disabled={!canManage}
            onClick={() => handleDelete(record)}
          >
            {t("aidpKnowledge.ontologyMetadataDelete")}
          </Button>
        </div>
      ),
    },
  ];

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
        {
          key: "chunks",
          label: t("aidpKnowledge.ontologyMetadataColumnChunkCount"),
          children:
            demo && detailField.associated_chunk_count != null
              ? t("aidpKnowledge.ontologyMetadataChunkCountValue", {
                  count: detailField.associated_chunk_count,
                })
              : t("aidpKnowledge.ontologyDash"),
        },
        {
          key: "created",
          label: t("aidpKnowledge.ontologyMetadataColumnCreateTime"),
          children: formatAuditTime(detailField.create_time),
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
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setPage(1);
          }}
        />
        <div className={tableStyles.toolbarActions}>
          <Button
            danger
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
            <Button
              aria-label={t("aidpKnowledge.ontologyMetadataColumnSettings")}
              icon={<SettingOutlined />}
            />
          </Dropdown>
        </div>
      </div>

      <AidpOntologyGapNote title={t("aidpKnowledge.ontologyMetadataGapTitle")}>
        {demo
          ? t("aidpKnowledge.ontologyMetadataDemoColumnsGap")
          : t("aidpKnowledge.ontologyMetadataRealColumnsGap")}
      </AidpOntologyGapNote>
      {missingIds.length > 0 && (
        <AidpOntologyGapNote>
          {t("aidpKnowledge.ontologyMetadataMissingIdGap", {
            count: missingIds.length,
          })}
        </AidpOntologyGapNote>
      )}
      {!canManage && (
        <AidpOntologyGapNote
          title={t("aidpKnowledge.ontologyMetadataNoPermission")}
        >
          {t("aidpKnowledge.ontologyMetadataNoPermissionHint")}
        </AidpOntologyGapNote>
      )}
      <div className={tableStyles.tableArea}>
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
            columns={columns}
            dataSource={pagedFields}
            pagination={false}
            tableLayout="fixed"
            scroll={{ x: 920 }}
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
            total={filteredFields.length}
            totalReliable
            hasMore={page * pageSize < filteredFields.length}
            selectedCount={selectedKeys.length}
            onPageChange={setPage}
            onPageSizeChange={(nextSize) => {
              setPageSize(nextSize);
              setPage(1);
            }}
          />
        </div>
      )}

      <Modal
        open={createOpen}
        width={520}
        title={t("aidpKnowledge.ontologyMetadataCreateModalTitle")}
        onCancel={() => setCreateOpen(false)}
        destroyOnHidden
        centered
        footer={
          <Space>
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
          </Space>
        }
      >
        <Form
          form={createForm}
          layout="vertical"
          initialValues={{ field_type: "string" }}
        >
          <Form.Item
            name="field_name"
            label={t("aidpKnowledge.ontologyMetadataFieldName")}
            required
            rules={[
              {
                validator: async (_rule, value: string) => {
                  if (!(value ?? "").trim()) {
                    throw new Error(
                      t("aidpKnowledge.ontologyMetadataNameRequired")
                    );
                  }
                  const error = validateFieldName(value ?? "");
                  if (error) throw new Error(error);
                },
              },
            ]}
          >
            <Input maxLength={63} />
          </Form.Item>
          <Form.Item
            name="field_type"
            label={t("aidpKnowledge.ontologyMetadataValueType")}
            required
            rules={[{ required: true }]}
          >
            <Segmented<AidpMetadataFieldType>
              block
              className={styles.typeSegmented}
              options={[
                { value: "string", label: typeLabel("string") },
                { value: "time", label: typeLabel("time") },
                { value: "number", label: typeLabel("number") },
              ]}
            />
          </Form.Item>
          {createError && (
            <div className={drawerStyles.error} role="alert">
              {createError}
            </div>
          )}
        </Form>
      </Modal>

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
            demo_candidates: editing?.candidates ?? [],
          }}
        >
          <Form.Item
            name="field_name"
            label={t("aidpKnowledge.ontologyMetadataFieldName")}
            extra={t("aidpKnowledge.ontologyMetadataFieldNameHint")}
            rules={[
              {
                validator: async (_rule, value: string) => {
                  if (!(value ?? "").trim()) {
                    throw new Error(
                      t("aidpKnowledge.ontologyMetadataNameRequired")
                    );
                  }
                  const error = validateFieldName(value ?? "");
                  if (error) throw new Error(error);
                },
              },
            ]}
          >
            <Input maxLength={63} />
          </Form.Item>
          <Form.Item
            name="field_type"
            label={t("aidpKnowledge.ontologyMetadataFieldType")}
            extra={t("aidpKnowledge.ontologyMetadataTypeLocked")}
            rules={[{ required: true }]}
          >
            <Select
              disabled
              options={[
                { value: "string", label: typeLabel("string") },
                { value: "number", label: typeLabel("number") },
                { value: "time", label: typeLabel("time") },
              ]}
            />
          </Form.Item>

          <div className={styles.candidatePanel}>
            <AidpOntologyGapNote>
              {t("aidpKnowledge.ontologyMetadataDemoConfigGap")}
            </AidpOntologyGapNote>
            {editFieldType === "string" ? (
              <Form.Item
                name="demo_candidates"
                label={t("aidpKnowledge.ontologyMetadataCandidates")}
              >
                <Select
                  mode="tags"
                  tokenSeparators={[",", "，"]}
                  placeholder={t(
                    "aidpKnowledge.ontologyMetadataCandidatesTagPlaceholder"
                  )}
                />
              </Form.Item>
            ) : (
              <Space.Compact block>
                <Form.Item
                  name="demo_range_start"
                  label={t("aidpKnowledge.ontologyMetadataRangeStart")}
                  className={styles.rangeItem}
                >
                  <Input placeholder="2020-01-01" />
                </Form.Item>
                <Form.Item
                  name="demo_range_end"
                  label={t("aidpKnowledge.ontologyMetadataRangeEnd")}
                  className={styles.rangeItem}
                >
                  <Input placeholder="2026-12-31" />
                </Form.Item>
              </Space.Compact>
            )}
          </div>
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
        width={520}
        onClose={() => setDetailField(null)}
        destroyOnHidden
        title={
          detailField?.field_name ??
          t("aidpKnowledge.ontologyMetadataDetailTitle")
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
            <div>
              <div className={styles.detailSectionTitle}>
                {t("aidpKnowledge.ontologyMetadataCandidates")}
              </div>
              {demo && (detailField.candidates ?? []).length > 0 ? (
                <div className={tableStyles.metadataTags}>
                  {(detailField.candidates ?? []).map((item) => (
                    <Tag key={item} className={tableStyles.metadataTag}>
                      {item}
                    </Tag>
                  ))}
                </div>
              ) : (
                <span className={styles.muted}>—</span>
              )}
            </div>
            <AidpOntologyGapNote>
              {t("aidpKnowledge.ontologyMetadataDetailGap")}
            </AidpOntologyGapNote>
          </div>
        )}
      </Drawer>

      <AidpOntologyAsyncTaskModal
        open={task.open}
        taskName={task.taskName}
        taskId={task.taskId}
        demo={demo}
        initialState={task.initialState}
        onClose={() => setTask((previous) => ({ ...previous, open: false }))}
      />
    </div>
  );
};

export default AidpOntologyMetadataFields;
