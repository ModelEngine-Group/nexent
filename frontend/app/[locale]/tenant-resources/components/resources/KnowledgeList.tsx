"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Table, Popconfirm, message, Button, Modal, Form, Select, Tag, Input } from "antd";
import { ColumnsType } from "antd/es/table";
import { Edit, Trash2, BookOpen } from "lucide-react";
import { Tooltip } from "@/components/ui/tooltip";
import { useKnowledgeList } from "@/hooks/knowledge/useKnowledgeList";
import { useGroupList } from "@/hooks/group/useGroupList";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { type KnowledgeBase } from "@/types/knowledgeBase";

export default function KnowledgeList({
  tenantId,
}: {
  tenantId: string | null;
}) {
  const { t } = useTranslation("common");
  const { data, isLoading, refetch } = useKnowledgeList(tenantId);
  const knowledgeBases = data || [];

  // Fetch groups for group selection
  const { data: groupData } = useGroupList(tenantId, 1, 100);
  const groups = groupData?.groups || [];

  const [editingKnowledge, setEditingKnowledge] = useState<KnowledgeBase | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [summaryModalVisible, setSummaryModalVisible] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryContent, setSummaryContent] = useState<string>("");
  const [form] = Form.useForm();

  // Create group name mapping
  const groupNameMap = useMemo(() => {
    const map = new Map<number, string>();
    groups.forEach((group) => {
      map.set(group.group_id, group.group_name);
    });
    return map;
  }, [groups]);

  // Get group names for knowledge base
  const getGroupNames = (groupIds?: number[]) => {
    if (!groupIds || groupIds.length === 0) return [];
    return groupIds.map((id) => groupNameMap.get(id) || `Group ${id}`).filter(Boolean);
  };

  const handleDelete = async (knowledgeId: string) => {
    try {
      await knowledgeBaseService.deleteKnowledgeBase(knowledgeId);
      message.success(t("tenantResources.knowledgeBase.deleted"));
      refetch();
    } catch (error: any) {
      message.error(error.message || t("tenantResources.knowledgeBase.deleteFailed"));
    }
  };

  const openEdit = (knowledge: KnowledgeBase) => {
    setEditingKnowledge(knowledge);
    form.setFieldsValue({
      knowledge_name: knowledge.name,
      ingroup_permission: knowledge.ingroup_permission || "READ_ONLY",
      group_ids: knowledge.group_ids || [],
    });
    setModalVisible(true);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();

      if (!editingKnowledge) return;

      await knowledgeBaseService.updateKnowledgeBase(editingKnowledge.id, {
        knowledge_name: values.knowledge_name,
        ingroup_permission: values.ingroup_permission,
        group_ids: values.group_ids,
      });

      message.success(t("tenantResources.knowledgeBase.updated"));
      setModalVisible(false);
      refetch();
    } catch (error: any) {
      if (error.errorFields) {
        return; // Form validation error
      }
      message.error(error.message || t("tenantResources.knowledgeBase.updateFailed"));
    }
  };

  const openEditSummary = async (knowledge: KnowledgeBase) => {
    setEditingKnowledge(knowledge);
    setSummaryLoading(true);
    setSummaryContent("");
    try {
      const summary = await knowledgeBaseService.getSummary(knowledge.id);
      setSummaryContent(summary || "");
      setSummaryModalVisible(true);
    } catch (error: any) {
      message.error(error.message || t("tenantResources.knowledgeBase.getSummaryFailed"));
    } finally {
      setSummaryLoading(false);
    }
  };

  const handleSummarySubmit = async () => {
    setSummaryModalVisible(false);
    setSummaryContent("");
  };

  const formatDateTime = (date: string | null | undefined) => {
    if (!date) return t("common.unknown");
    const d = new Date(date);
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const hours = String(d.getHours()).padStart(2, "0");
    const minutes = String(d.getMinutes()).padStart(2, "0");
    const seconds = String(d.getSeconds()).padStart(2, "0");
    return `${year}/${month}/${day} ${hours}:${minutes}:${seconds}`;
  };

  const formatStoreSize = (size: string | null | undefined) => {
    if (!size) return "-";
    return size;
  };

  const columns: ColumnsType<KnowledgeBase> = [
    {
      title: t("common.name"),
      dataIndex: "name",
      key: "name",
      width: 150,
      render: (text: string) => (
        <Tooltip title={text}>
          <div className="font-medium truncate max-w-[140px]">{text}</div>
        </Tooltip>
      ),
    },
    {
      title: t("tenantResources.knowledgeBase.sources"),
      dataIndex: "knowledge_sources",
      key: "knowledge_sources",
      width: 80,
      render: (source: string) => (
        <Tag color="default">{source || t("common.unknown")}</Tag>
      ),
    },
    {
      title: t("tenantResources.knowledgeBase.permission"),
      dataIndex: "ingroup_permission",
      key: "ingroup_permission",
      width: 100,
      render: (permission: string) => {
        const color = permission === "EDIT" ? "geekblue"
                 : permission === "PRIVATE" ? "magenta"
                 : permission === "READ_ONLY" ? "cyan" : "default";
        return (
          <Tag color={color}>
            {t(`tenantResources.knowledgeBase.permission.${permission || "DEFAULT"}`)}
          </Tag>
        );
      },
    },
    {
      title: t("tenantResources.knowledgeBase.documents"),
      dataIndex: "documentCount",
      key: "documentCount",
      width: 60,
      render: (count: number) => count || 0,
    },
    {
      title: t("tenantResources.knowledgeBase.chunks"),
      dataIndex: "chunkCount",
      key: "chunkCount",
      width: 60,
      render: (count: number) => count || 0,
    },
    {
      title: t("tenantResources.knowledgeBase.storeSize"),
      dataIndex: "store_size",
      key: "store_size",
      width: 80,
      render: (size: string) => formatStoreSize(size),
    },
    {
      title: t("tenantResources.knowledgeBase.processSource"),
      dataIndex: "process_source",
      key: "process_source",
      width: 80,
      render: (source: string) => (
        <Tag color="default">{source || t("common.unknown")}</Tag>
      ),
    },
    {
      title: t("tenantResources.knowledgeBase.groupNames"),
      dataIndex: "group_ids",
      key: "group_names",
      width: 200,
      render: (groupIds: number[]) => {
        const names = getGroupNames(groupIds);
        return (
          <div className="flex flex-wrap gap-1">
            {names.length > 0 ? (
              names.map((name, index) => (
                <Tag key={index} color="blue" variant="outlined">
                  {name}
                </Tag>
              ))
            ) : (
              <span className="text-gray-400">{t("tenantResources.knowledgeBase.noGroups")}</span>
            )}
          </div>
        );
      },
    },
    {
      title: t("common.updated"),
      dataIndex: "updatedAt",
      key: "updatedAt",
      width: 120,
      render: (date: string) => formatDateTime(date),
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 140,
      fixed: "right",
      render: (_, record: KnowledgeBase) => (
        <div className="flex items-center space-x-2">
          <Tooltip title={t("common.edit")}>
            <Button
              type="text"
              icon={<Edit className="h-4 w-4" />}
              onClick={() => openEdit(record)}
              size="small"
            />
          </Tooltip>
          <Tooltip title={t("tenantResources.knowledgeBase.viewSummary")}>
            <Button
              type="text"
              icon={<BookOpen className="h-4 w-4" />}
              onClick={() => openEditSummary(record)}
              size="small"
            />
          </Tooltip>
          <Popconfirm
            title={t("knowledgeBase.modal.deleteConfirm.title")}
            description={t("common.cannotBeUndone")}
            onConfirm={() => handleDelete(record.id)}
          >
            <Tooltip title={t("common.delete")}>
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
    <>
      <Table
        columns={columns}
        dataSource={knowledgeBases}
        loading={isLoading}
        rowKey="id"
        pagination={{ pageSize: 10 }}
        scroll={{ x: 1400 }}
      />

      <Modal
        title={t("tenantResources.knowledgeBase.edit")}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
        width={500}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="knowledge_name"
            label={t("common.name")}
            rules={[
              { required: true, message: t("tenantResources.knowledgeBase.nameRequired") },
            ]}
          >
            <Input placeholder={t("tenantResources.knowledgeBase.enterName")} />
          </Form.Item>

          <Form.Item
            name="ingroup_permission"
            label={t("tenantResources.knowledgeBase.permission")}
            rules={[
              { required: true, message: t("tenantResources.knowledgeBase.permissionRequired") },
            ]}
          >
            <Select placeholder={t("tenantResources.knowledgeBase.permission")}>
              <Select.Option value="EDIT">{t("tenantResources.knowledgeBase.permission.EDIT")}</Select.Option>
              <Select.Option value="READ_ONLY">{t("tenantResources.knowledgeBase.permission.READ_ONLY")}</Select.Option>
              <Select.Option value="PRIVATE">{t("tenantResources.knowledgeBase.permission.PRIVATE")}</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item name="group_ids" label={t("tenantResources.knowledgeBase.groupNames")}>
            <Select
              mode="multiple"
              placeholder={t("tenantResources.knowledgeBase.groupNames")}
              options={groups.map((group) => ({
                label: group.group_name,
                value: group.group_id,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t("tenantResources.knowledgeBase.viewSummary")}
        open={summaryModalVisible}
        onCancel={() => setSummaryModalVisible(false)}
        footer={[
          <Button key="confirm" type="primary" onClick={() => setSummaryModalVisible(false)}>
            {t("common.confirm")}
          </Button>,
        ]}
        width={600}
        confirmLoading={summaryLoading}
      >
        {summaryLoading ? (
          <div className="text-gray-400">{t("common.loading")}</div>
        ) : summaryContent ? (
          <div className="text-gray-700 whitespace-pre-wrap">{summaryContent}</div>
        ) : (
          <div className="text-gray-400 italic">{t("tenantResources.knowledgeBase.noSummary")}</div>
        )}
      </Modal>
    </>
  );
}
