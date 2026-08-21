"use client";

import { useCallback, useEffect, useState } from "react";

import {
  App,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";

import { useTagDefinitions } from "@/hooks/useTagManagement";
import { tagManagementApi } from "@/services/tagManagementService";
import type {
  TagDefinition,
  TagSelectionMode,
  TagValue,
} from "@/types/tagManagement";

interface TagDefinitionManagementModalProps {
  open: boolean;
  onClose: () => void;
  bucketId: number;
  bucketName: string;
  canManage: boolean;
}

interface DefinitionFormValues {
  definition_key: string;
  definition_name: string;
  selection_mode: TagSelectionMode;
  initial_values?: string;
}

interface ValueFormValues {
  display_value: string;
}

export default function TagDefinitionManagementModal({
  open,
  onClose,
  bucketId,
  bucketName,
  canManage,
}: TagDefinitionManagementModalProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const {
    data: definitions,
    loading,
    refresh,
  } = useTagDefinitions(open ? bucketId : null);
  const [definitionModalOpen, setDefinitionModalOpen] = useState(false);
  const [editingDefinition, setEditingDefinition] =
    useState<TagDefinition | null>(null);
  const [valueModal, setValueModal] = useState<{
    open: boolean;
    definition: TagDefinition | null;
    editingValue: TagValue | null;
  }>({ open: false, definition: null, editingValue: null });
  const [definitionForm] = Form.useForm<DefinitionFormValues>();
  const [valueForm] = Form.useForm<ValueFormValues>();

  useEffect(() => {
    if (!open) {
      setDefinitionModalOpen(false);
      setValueModal({ open: false, definition: null, editingValue: null });
    }
  }, [open]);

  const handleCreateDefinition = useCallback(async () => {
    const values = await definitionForm.validateFields();
    const initialValues = (values.initial_values ?? "")
      .split(/[,，\n]/)
      .map((item: string) => item.trim())
      .filter(Boolean);
    try {
      await tagManagementApi.createDefinition(bucketId, {
        definition_key: values.definition_key,
        definition_name: values.definition_name,
        selection_mode: values.selection_mode,
        initial_values: initialValues,
      });
      message.success(t("tagManagement.message.definitionSaved"));
      setDefinitionModalOpen(false);
      definitionForm.resetFields();
      void refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    }
  }, [bucketId, definitionForm, message, refresh, t]);

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
    setDefinitionModalOpen(true);
  }, [definitionForm]);

  const openEditDefinition = useCallback(
    (definition: TagDefinition) => {
      setEditingDefinition(definition);
      definitionForm.setFieldsValue({
        definition_key: definition.definition_key,
        definition_name: definition.definition_name,
        selection_mode: definition.selection_mode,
      });
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

  const reorderDefinition = useCallback(
    async (definition: TagDefinition, direction: -1 | 1) => {
      if (!definitions) return;
      const siblings = [...definitions].sort(
        (a, b) => a.sort_order - b.sort_order
      );
      const index = siblings.findIndex(
        (item) => item.definition_id === definition.definition_id
      );
      const swapWith = siblings[index + direction];
      if (!swapWith) return;
      try {
        await Promise.all([
          tagManagementApi.updateDefinitionOrder(
            bucketId,
            definition.definition_id,
            {
              sort_order: swapWith.sort_order,
            }
          ),
          tagManagementApi.updateDefinitionOrder(
            bucketId,
            swapWith.definition_id,
            {
              sort_order: definition.sort_order,
            }
          ),
        ]);
        void refresh();
      } catch (error) {
        message.error(error instanceof Error ? error.message : String(error));
      }
    },
    [bucketId, definitions, message, refresh]
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
        <Tag>{mode === "single_select" ? "Single" : "Multi"}</Tag>
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
          percent={Math.min(
            100,
            Math.round(
              (definition.active_value_count / definition.value_capacity) * 100
            )
          )}
          size="small"
          format={() =>
            `${definition.active_value_count}/${definition.value_capacity}`
          }
        />
      ),
    },
    {
      title: t("tagManagement.column.actions"),
      key: "actions",
      width: 300,
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
            disabled={!canManage}
            onClick={() => reorderDefinition(definition, -1)}
          >
            ↑
          </Button>
          <Button
            size="small"
            disabled={!canManage}
            onClick={() => reorderDefinition(definition, 1)}
          >
            ↓
          </Button>
          <Popconfirm
            title={t("tagManagement.confirm.deleteDefinition")}
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
  return (
    <Modal
      title={`${t("tagManagement.title.definitionManagement")} - ${bucketName}`}
      open={open}
      onCancel={onClose}
      footer={null}
      width={1100}
      zIndex={1100}
    centered
    destroyOnHidden
    >
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
      <Table
        rowKey="definition_id"
        dataSource={definitions ?? []}
        columns={columns}
        loading={loading}
        size="small"
        expandable={{
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
              />
            </div>
          ),
        }}
        pagination={{ pageSize: 10, size: "small" }}
        scroll={{ y: 500 }}
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
        destroyOnHidden
        zIndex={1200}
      >
        <Form form={definitionForm} layout="vertical">
          <Form.Item
            name="definition_key"
            label={t("tagManagement.form.definitionKey")}
            rules={[{ required: true }]}
          >
            <Input disabled={Boolean(editingDefinition)} />
          </Form.Item>
          <Form.Item
            name="definition_name"
            label={t("tagManagement.form.definitionName")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
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
          {!editingDefinition && (
            <Form.Item
              name="initial_values"
              label={t("tagManagement.form.initialValues")}
            >
              <Input.TextArea
                rows={3}
                placeholder={t("tagManagement.form.initialValuesPlaceholder")}
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
        destroyOnHidden
        zIndex={1200}
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
    </Modal>
  );
}
