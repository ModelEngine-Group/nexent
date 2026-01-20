"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Table, Button, Modal, Form, Input, Select, Popconfirm, message, Tag } from "antd";
import { ColumnsType } from "antd/es/table";
import { useModelList } from "@/hooks/model/useModelList";
import { modelService } from "@/services/modelService";
import { type ModelOption, type ModelType } from "@/types/modelConfig";

export default function ModelList({ tenantId }: { tenantId: string | null }) {
  const { t } = useTranslation("common");
  const { data: models = [], isLoading, refetch } = useModelList();
  const [editingModel, setEditingModel] = useState<ModelOption | null>(null);
  const [modalVisible, setModalVisible] = useState(false);

  const [form] = Form.useForm();

  const openCreate = () => {
    setEditingModel(null);
    form.resetFields();
    setModalVisible(true);
  };

  const openEdit = (model: ModelOption) => {
    setEditingModel(model);
    form.setFieldsValue({
      name: model.name,
      type: model.type,
      displayName: model.displayName,
      apiUrl: model.apiUrl,
      apiKey: model.apiKey,
      maxTokens: model.maxTokens,
    });
    setModalVisible(true);
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

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();

      if (editingModel) {
        // Update model
        await modelService.updateSingleModel({
          currentDisplayName: editingModel.displayName || editingModel.name,
          displayName: values.displayName,
          url: values.apiUrl,
          apiKey: values.apiKey,
          maxTokens: values.maxTokens,
        });
        message.success("Model updated");
      } else {
        // Create model
        await modelService.addCustomModel({
          name: values.name,
          type: values.type,
          url: values.apiUrl,
          apiKey: values.apiKey,
          maxTokens: values.maxTokens,
          displayName: values.displayName,
        });
        message.success("Model created");
      }
      setModalVisible(false);
      refetch();
    } catch (error: any) {
      if (error.response?.data?.message) {
        message.error(error.response.data.message);
      }
    }
  };

  const columns: ColumnsType<ModelOption> = [
    {
      title: "Name",
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
      title: "Type",
      dataIndex: "type",
      key: "type",
      render: (type: ModelType) => <Tag>{type}</Tag>,
    },
    {
      title: "Source",
      dataIndex: "source",
      key: "source",
      render: (source: string) => <Tag color="blue">{source}</Tag>,
    },
    {
      title: "Status",
      dataIndex: "connect_status",
      key: "connect_status",
      render: (status: string) => {
        const color = status === "available" ? "green" : status === "unavailable" ? "red" : "orange";
        return <Tag color={color}>{status}</Tag>;
      },
    },
    {
      title: "Actions",
      key: "actions",
      render: (_, record: ModelOption) => (
        <div className="space-x-2">
          <Button size="small" onClick={() => openEdit(record)}>
            Edit
          </Button>
          <Popconfirm
            title="Delete model?"
            description="This action cannot be undone."
            onConfirm={() => handleDelete(record.displayName, record.source)}
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
        <h3 className="text-lg font-medium">Models</h3>
        <Button type="primary" onClick={openCreate}>
          Add Model
        </Button>
      </div>

      <Table
        columns={columns}
        dataSource={models}
        loading={isLoading}
        rowKey="id"
        pagination={{ pageSize: 10 }}
      />

      <Modal
        title={editingModel ? "Edit Model" : "Add Model"}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="Model Name"
            rules={[{ required: true, message: "Please enter model name" }]}
          >
            <Input placeholder="e.g., gpt-3.5-turbo" />
          </Form.Item>

          <Form.Item
            name="displayName"
            label="Display Name"
            rules={[{ required: true, message: "Please enter display name" }]}
          >
            <Input placeholder="e.g., GPT-3.5 Turbo" />
          </Form.Item>

          <Form.Item
            name="type"
            label="Model Type"
            rules={[{ required: true, message: "Please select model type" }]}
          >
            <Select placeholder="Select model type">
              <Select.Option value="LLM">LLM</Select.Option>
              <Select.Option value="Embedding">Embedding</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="apiUrl"
            label="API URL"
            rules={[{ required: true, message: "Please enter API URL" }]}
          >
            <Input placeholder="https://api.openai.com/v1" />
          </Form.Item>

          <Form.Item
            name="apiKey"
            label="API Key"
            rules={[{ required: true, message: "Please enter API key" }]}
          >
            <Input.Password placeholder="sk-..." />
          </Form.Item>

          <Form.Item
            name="maxTokens"
            label="Max Tokens"
            rules={[{ required: true, message: "Please enter max tokens" }]}
          >
            <Input type="number" placeholder="4096" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
