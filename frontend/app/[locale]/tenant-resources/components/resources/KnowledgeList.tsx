"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  Popconfirm,
  message,
  Tag,
  Upload,
} from "antd";
import { ColumnsType } from "antd/es/table";
import { UploadOutlined } from "@ant-design/icons";
import { useKnowledgeList } from "@/hooks/knowledge/useKnowledgeList";
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
  const [editingKnowledge, setEditingKnowledge] =
    useState<KnowledgeBase | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [uploading, setUploading] = useState(false);

  const [form] = Form.useForm();

  const openCreate = () => {
    setEditingKnowledge(null);
    form.resetFields();
    setModalVisible(true);
  };

  const openEdit = (knowledge: KnowledgeBase) => {
    setEditingKnowledge(knowledge);
    form.setFieldsValue({
      name: knowledge.name,
      description: knowledge.description,
    });
    setModalVisible(true);
  };

  const handleDelete = async (knowledgeId: string) => {
    try {
      await knowledgeBaseService.deleteKnowledgeBase(knowledgeId);
      message.success("Knowledge base deleted");
      refetch();
    } catch (error: any) {
      message.error("Delete failed");
    }
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();

      if (editingKnowledge) {
        // Update knowledge base (if API supports)
        message.info("Knowledge base update not yet implemented");
      } else {
        // Create knowledge base
        await knowledgeBaseService.createKnowledgeBase({
          name: values.name,
          description: values.description,
        });
        message.success("Knowledge base created");
      }
      setModalVisible(false);
      refetch();
    } catch (error: any) {
      message.error("Operation failed");
    }
  };

  const handleFileUpload = async (file: File, knowledgeId: string) => {
    try {
      setUploading(true);
      await knowledgeBaseService.uploadDocuments(knowledgeId, [file]);
      message.success("Document uploaded successfully");
      refetch();
    } catch (error: any) {
      message.error("Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const columns: ColumnsType<KnowledgeBase> = [
    {
      title: "Name",
      dataIndex: "name",
      key: "name",
      render: (text: string) => <div className="font-medium">{text}</div>,
    },
    {
      title: "Description",
      dataIndex: "description",
      key: "description",
    },
    {
      title: "Documents",
      dataIndex: "documentCount",
      key: "documentCount",
      render: (count: number) => count || 0,
    },
    {
      title: "Chunks",
      dataIndex: "chunkCount",
      key: "chunkCount",
      render: (count: number) => count || 0,
    },
    {
      title: "Created",
      dataIndex: "createdAt",
      key: "createdAt",
      render: (date: any) => date ? new Date(date).toLocaleDateString() : "Unknown",
    },
    {
      title: "Actions",
      key: "actions",
      render: (_, record: KnowledgeBase) => (
        <div className="space-x-2">
          <Upload
            accept=".pdf,.txt,.md,.doc,.docx"
            showUploadList={false}
            beforeUpload={(file) => {
              handleFileUpload(file, record.id);
              return false;
            }}
          >
            <Button size="small" loading={uploading} icon={<UploadOutlined />}>
              Upload
            </Button>
          </Upload>
          <Button size="small" onClick={() => openEdit(record)}>
            Edit
          </Button>
          <Popconfirm
            title="Delete knowledge base?"
            description="This action cannot be undone."
            onConfirm={() => handleDelete(record.id)}
          >
            <Button size="small" danger>
              Delete
            </Button>
          </Popconfirm>
        </div>
      ),
    },
  ];

  return (
    <div>
      <div className="mb-4 flex justify-between items-center">
        <h3 className="text-lg font-medium">Knowledge Bases</h3>
        <Button type="primary" onClick={openCreate}>
          Create Knowledge Base
        </Button>
      </div>

      <Table
        columns={columns}
        dataSource={knowledgeBases}
        loading={isLoading}
        rowKey="id"
        pagination={{ pageSize: 10 }}
      />

      <Modal
        title={
          editingKnowledge ? "Edit Knowledge Base" : "Create Knowledge Base"
        }
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="Name"
            rules={[
              { required: true, message: "Please enter knowledge base name" },
            ]}
          >
            <Input placeholder="e.g., Company Documents" />
          </Form.Item>

          <Form.Item name="description" label="Description">
            <Input.TextArea placeholder="Optional description" rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
