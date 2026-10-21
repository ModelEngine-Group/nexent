// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useMemo, useState } from "react";

import {
  Alert,
  App,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Progress,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";

import { useTagDefinitions } from "@/hooks/useTagManagement";
import {
  getMatchingTagDefinitionIds,
  getTagDefinitionDisplayName,
  getTagValueDisplayName,
} from "@/lib/systemTagLabels";
import { tagManagementApi } from "@/services/tagManagementService";
import type {
  TagDefinition,
  TagSelectionMode,
  TagValue,
} from "@/types/tagManagement";

interface TagDefinitionManagementPanelProps {
  bucketId: number;
  canManage: boolean;
}

interface DefinitionFormValues {
  definition_name: string;
  selection_mode: TagSelectionMode;
  initial_values?: string[];
}

interface ValueFormValues {
  display_value: string;
}

export default function TagDefinitionManagementPanel({
  bucketId,
  canManage,
}: TagDefinitionManagementPanelProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const {
    data: definitions,
    loading,
    error,
    refresh,
  } = useTagDefinitions(bucketId);
  const [definitionModalOpen, setDefinitionModalOpen] = useState(false);
  const [editingDefinition, setEditingDefinition] =
    useState<TagDefinition | null>(null);
  const [valueModal, setValueModal] = useState<{
    open: boolean;
    definition: TagDefinition | null;
    editingValue: TagValue | null;
  }>({ open: false, definition: null, editingValue: null });
  const [definitionPage, setDefinitionPage] = useState(1);
  const [definitionSearch, setDefinitionSearch] = useState("");
  const [hasValues, setHasValues] = useState(true);
  const [definitionForm] = Form.useForm<DefinitionFormValues>();
  const [valueForm] = Form.useForm<ValueFormValues>();

  const handleCreateDefinition = useCallback(async () => {
    const values = await definitionForm.validateFields();
    const initialValues = (values.initial_values ?? [])
      .map((item) => item.trim())
      .filter(Boolean);
    try {
      await tagManagementApi.createDefinition(bucketId, {
        definition_name: values.definition_name,
        selection_mode: hasValues ? values.selection_mode : "no_value",
        initial_values: initialValues,
      });
      message.success(t("tagManagement.message.definitionSaved"));
      setDefinitionModalOpen(false);
      definitionForm.resetFields();
      void refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    }
  }, [bucketId, definitionForm, hasValues, message, refresh, t]);

  const handleUpdateDefinition = useCallback(async () => {
    if (!editingDefinition) return;
    const values = await definitionForm.validateFields();
    try {
      await tagManagementApi.updateDefinition(
        bucketId,
        editingDefinition.definition_id,
        {
          definition_name: values.definition_name,
          selection_mode: values.selection_mode,
        }
      );
      message.success(t("tagManagement.message.definitionSaved"));
      setDefinitionModalOpen(false);
      setEditingDefinition(null);
      definitionForm.resetFields();
      void refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    }
  }, [bucketId, definitionForm, editingDefinition, message, refresh, t]);

  const openCreateDefinition = useCallback(() => {
    setEditingDefinition(null);
    definitionForm.resetFields();
    setHasValues(true);
    definitionForm.setFieldValue("selection_mode", "multi_select");
    setDefinitionModalOpen(true);
  }, [definitionForm]);

  const openEditDefinition = useCallback(
    (definition: TagDefinition) => {
      setEditingDefinition(definition);
      definitionForm.setFieldsValue({
        definition_name: definition.definition_name,
        selection_mode: definition.selection_mode,
      });
      setHasValues(definition.selection_mode !== "no_value");
      setDefinitionModalOpen(true);
    },
    [definitionForm]
  );
  const toggleDefinitionStatus = useCallback(
    async (definition: TagDefinition) => {
      try {
        await tagManagementApi.updateDefinitionStatus(
          bucketId,
          definition.definition_id,
          {
            status: definition.status === "active" ? "disabled" : "active",
          }
        );
        void refresh();
      } catch (error) {
        message.error(error instanceof Error ? error.message : String(error));
      }
    },
    [bucketId, message, refresh]
  );

  const moveDefinitionToTop = useCallback(
    async (definition: TagDefinition) => {
      try {
        await tagManagementApi.moveDefinitionToTop(
          bucketId,
          definition.definition_id
        );
        setDefinitionPage(1);
        void refresh();
      } catch (error) {
        message.error(error instanceof Error ? error.message : String(error));
      }
    },
    [bucketId, message, refresh]
  );

  const deleteDefinition = useCallback(
    async (definition: TagDefinition) => {
      try {
        await tagManagementApi.deleteDefinition(
          bucketId,
          definition.definition_id
        );
        message.success(t("tagManagement.message.definitionDeleted"));
        void refresh();
      } catch (error) {
        message.error(error instanceof Error ? error.message : String(error));
      }
    },
    [bucketId, message, refresh, t]
  );

  const handleSaveValue = useCallback(async () => {
    const definition = valueModal.definition;
    if (!definition) return;
    const values = await valueForm.validateFields();
    try {
      if (valueModal.editingValue) {
        await tagManagementApi.updateValue(
          bucketId,
          definition.definition_id,
          valueModal.editingValue.value_id,
          { display_value: values.display_value }
        );
      } else {
        await tagManagementApi.createValue(bucketId, definition.definition_id, {
          display_value: values.display_value,
        });
      }
      message.success(t("tagManagement.message.valueSaved"));
      setValueModal({ open: false, definition: null, editingValue: null });
      valueForm.resetFields();
      void refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    }
  }, [bucketId, message, refresh, t, valueForm, valueModal]);

  const toggleValueStatus = useCallback(
    async (definition: TagDefinition, tagValue: TagValue) => {
      try {
        await tagManagementApi.updateValueStatus(
          bucketId,
          definition.definition_id,
          tagValue.value_id,
          { status: tagValue.status === "active" ? "disabled" : "active" }
        );
        void refresh();
      } catch (error) {
        message.error(error instanceof Error ? error.message : String(error));
      }
    },
    [bucketId, message, refresh]
  );

  const deleteValue = useCallback(
    async (definition: TagDefinition, tagValue: TagValue) => {
      try {
        await tagManagementApi.deleteValue(
          bucketId,
          definition.definition_id,
          tagValue.value_id
        );
        message.success(t("tagManagement.message.valueDeleted"));
        void refresh();
      } catch (error) {
        message.error(error instanceof Error ? error.message : String(error));
      }
    },
    [bucketId, message, refresh, t]
  );
  const valueColumns = useCallback(
    (definition: TagDefinition): ColumnsType<TagValue> => [
      {
        title: t("tagManagement.column.displayValue"),
        dataIndex: "display_value",
        key: "display_value",
        render: (_, tagValue) =>
          getTagValueDisplayName(
            definition.definition_key,
            tagValue.display_value,
            t
          ),
      },
      {
        title: t("tagManagement.column.status"),
        dataIndex: "status",
        key: "status",
        width: 100,
        render: (status: string) => (
          <Tag color={status === "active" ? "green" : "default"}>{status}</Tag>
        ),
      },
      {
        title: t("tagManagement.column.actions"),
        key: "actions",
        width: 240,
        render: (_, tagValue) => (
          <Space size="small">
            <Button
              size="small"
              disabled={!canManage}
              onClick={() => {
                valueForm.setFieldsValue({
                  display_value: tagValue.display_value,
                });
                setValueModal({
                  open: true,
                  definition,
                  editingValue: tagValue,
                });
              }}
            >
              {t("tagManagement.action.edit")}
            </Button>
            <Button
              size="small"
              disabled={!canManage}
              onClick={() => toggleValueStatus(definition, tagValue)}
            >
              {tagValue.status === "active"
                ? t("tagManagement.action.disable")
                : t("tagManagement.action.enable")}
            </Button>
            <Popconfirm
              title={t("tagManagement.confirm.deleteValue")}
              okText={t("tagManagement.action.confirm")}
              cancelText={t("common.cancel")}
              onConfirm={() => deleteValue(definition, tagValue)}
            >
              <Button size="small" danger disabled={!canManage}>
                {t("tagManagement.action.delete")}
              </Button>
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [canManage, deleteValue, t, toggleValueStatus, valueForm]
  );

  const columns: ColumnsType<TagDefinition> = [
    {
      title: t("tagManagement.column.name"),
      dataIndex: "definition_name",
      key: "definition_name",
      render: (_, definition) =>
        getTagDefinitionDisplayName(
          definition.definition_key,
          definition.definition_name,
          t
        ),
    },
    {
      title: t("tagManagement.column.key"),
      dataIndex: "definition_key",
      key: "definition_key",
      width: 180,
    },
    {
      title: t("tagManagement.column.mode"),
      dataIndex: "selection_mode",
      key: "selection_mode",
      width: 140,
      render: (mode: TagSelectionMode) => (
        <Tag>
          {mode === "no_value"
            ? t("tagManagement.form.noValue")
            : mode === "single_select"
              ? t("tagManagement.form.singleSelect")
              : t("tagManagement.form.multiSelect")}
        </Tag>
      ),
    },
    {
      title: t("tagManagement.column.status"),
      dataIndex: "status",
      key: "status",
      width: 100,
      render: (status: string) => (
        <Tag color={status === "active" ? "green" : "default"}>{status}</Tag>
      ),
    },
    {
      title: t("tagManagement.column.valueCapacity"),
      key: "capacity",
      width: 180,
      render: (_, definition) => (
        <Progress
          percent={
            definition.selection_mode === "no_value"
              ? 0
              : Math.min(
                  100,
                  Math.round(
                    (definition.active_value_count /
                      definition.value_capacity) *
                      100
                  )
                )
          }
          size="small"
          format={() =>
            definition.selection_mode === "no_value"
              ? "—"
              : `${definition.active_value_count}/${definition.value_capacity}`
          }
        />
      ),
    },
    {
      title: t("tagManagement.column.actions"),
      key: "actions",
      width: 260,
      render: (_, definition) => (
        <Space size="small">
          <Button
            size="small"
            disabled={!canManage}
            onClick={() => openEditDefinition(definition)}
          >
            {t("tagManagement.action.edit")}
          </Button>
          <Button
            size="small"
            disabled={!canManage}
            onClick={() => toggleDefinitionStatus(definition)}
          >
            {definition.status === "active"
              ? t("tagManagement.action.disable")
              : t("tagManagement.action.enable")}
          </Button>
          <Button
            size="small"
            disabled={
              !canManage ||
              definitions?.[0]?.definition_id === definition.definition_id
            }
            onClick={() => moveDefinitionToTop(definition)}
          >
            {t("tagManagement.action.moveToTop")}
          </Button>
          <Popconfirm
            title={t("tagManagement.confirm.deleteDefinition")}
            okText={t("tagManagement.action.confirm")}
            cancelText={t("common.cancel")}
            onConfirm={() => deleteDefinition(definition)}
          >
            <Button size="small" danger disabled={!canManage}>
              {t("tagManagement.action.delete")}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // The table renders localized names and expands into per-value rows, so the
  // search has to run over the same localized texts plus each value. Matching on
  // the raw definition_name/definition_key fields alone hides rows the user can
  // see, for example the translated "关键词" name or a value such as "Cache".
  const hasDefinitionSearch = definitionSearch.trim().length > 0;
  const filteredDefinitions = useMemo(() => {
    const allDefinitions = definitions ?? [];
    const matchedIds = getMatchingTagDefinitionIds(
      allDefinitions,
      definitionSearch,
      t
    );
    if (!matchedIds) return allDefinitions;
    return allDefinitions.filter((definition) =>
      matchedIds.has(definition.definition_id)
    );
  }, [definitions, definitionSearch, t]);

  return (
    <div className="min-w-0">
      {error && (
        <Alert
          type="error"
          showIcon
          title={error}
          className="mb-3"
          action={
            <Button onClick={() => void refresh()}>{t("common.retry")}</Button>
          }
        />
      )}
      <div className="mb-3 flex items-center justify-between">
        <Typography.Text type="secondary">
          {t("tagManagement.libraryCapacity", {
            count: definitions?.length ?? 0,
          })}
        </Typography.Text>
        {canManage && (
          <Button type="primary" onClick={openCreateDefinition}>
            {t("tagManagement.action.addDefinition")}
          </Button>
        )}
      </div>
      <Input.Search
        allowClear
        className="mb-3 max-w-sm"
        placeholder={t("tagManagement.form.searchTags")}
        value={definitionSearch}
        onChange={(event) => {
          setDefinitionSearch(event.target.value);
          setDefinitionPage(1);
        }}
      />
      <Table
        rowKey="definition_id"
        dataSource={filteredDefinitions}
        columns={columns}
        loading={loading}
        locale={{
          emptyText: hasDefinitionSearch
            ? t("tagManagement.empty.noMatchingDefinitions")
            : t("tagManagement.empty.noDefinitions"),
        }}
        size="small"
        expandable={{
          rowExpandable: (definition) =>
            definition.selection_mode !== "no_value",
          expandedRowRender: (definition) => (
            <div className="p-2">
              <div className="mb-2 flex items-center justify-end">
                {canManage && (
                  <Button
                    size="small"
                    onClick={() => {
                      valueForm.resetFields();
                      setValueModal({
                        open: true,
                        definition,
                        editingValue: null,
                      });
                    }}
                  >
                    {t("tagManagement.action.addValue")}
                  </Button>
                )}
              </div>
              <Table
                rowKey="value_id"
                dataSource={definition.values ?? []}
                columns={valueColumns(definition)}
                size="small"
                pagination={false}
                scroll={{ x: 650 }}
              />
            </div>
          ),
        }}
        pagination={{
          current: definitionPage,
          pageSize: 10,
          size: "small",
          onChange: setDefinitionPage,
        }}
        scroll={{ x: 1060, y: 500 }}
      />

      <Modal
        title={
          editingDefinition
            ? t("tagManagement.title.editDefinition")
            : t("tagManagement.title.addDefinition")
        }
        open={definitionModalOpen}
        onCancel={() => {
          setDefinitionModalOpen(false);
          setEditingDefinition(null);
        }}
        onOk={() =>
          editingDefinition
            ? handleUpdateDefinition()
            : handleCreateDefinition()
        }
        okText={t("tagManagement.action.confirm")}
        cancelText={t("common.cancel")}
        destroyOnHidden
        zIndex={1300}
      >
        <Form form={definitionForm} layout="vertical">
          <Form.Item
            name="definition_name"
            label={t("tagManagement.form.definitionName")}
            rules={[{ required: true }]}
          >
            <Input
              addonAfter={
                !editingDefinition ? (
                  <Space size={4}>
                    <span>{t("tagManagement.form.hasValues")}</span>
                    <Switch checked={hasValues} onChange={setHasValues} />
                  </Space>
                ) : null
              }
            />
          </Form.Item>
          {hasValues && (
            <Form.Item
              name="selection_mode"
              label={t("tagManagement.form.selectionMode")}
              rules={[{ required: true }]}
            >
              <Select
                options={[
                  {
                    label: t("tagManagement.form.multiSelect"),
                    value: "multi_select",
                  },
                  {
                    label: t("tagManagement.form.singleSelect"),
                    value: "single_select",
                  },
                ]}
              />
            </Form.Item>
          )}
          {!editingDefinition && hasValues && (
            <Form.Item
              name="initial_values"
              label={t("tagManagement.form.initialValues")}
              rules={[
                {
                  validator: (_, values?: string[]) =>
                    Array.isArray(values) &&
                    values.some((value) => value.trim())
                      ? Promise.resolve()
                      : Promise.reject(
                          new Error(
                            t("tagManagement.validation.initialValuesRequired")
                          )
                        ),
                },
              ]}
            >
              <Select
                mode="tags"
                placeholder={t("tagManagement.form.initialValuesPlaceholder")}
                tokenSeparators={[]}
                maxCount={1000}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>

      <Modal
        title={
          valueModal.editingValue
            ? t("tagManagement.title.editValue")
            : t("tagManagement.title.addValue")
        }
        open={valueModal.open}
        onCancel={() =>
          setValueModal({ open: false, definition: null, editingValue: null })
        }
        onOk={handleSaveValue}
        okText={t("tagManagement.action.confirm")}
        cancelText={t("common.cancel")}
        destroyOnHidden
        zIndex={1300}
      >
        <Form form={valueForm} layout="vertical">
          <Form.Item
            name="display_value"
            label={t("tagManagement.form.displayValue")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
