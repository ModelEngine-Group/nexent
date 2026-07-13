"use client";

/**
 * CreateKBModal — 2-step knowledge base creation dialog (Phase 3, Component 4).
 *
 * Step 1: Select an adapter from the available list.
 * Step 2: Fill in KB configuration form.
 *
 * Q3 design decision: embedding_model, ingroup_permission, and group_ids
 * fields are ONLY rendered when the selected adapter's platform is 'local'.
 */

import React, { useState, useMemo } from "react";
import {
  Modal,
  Steps,
  Radio,
  Space,
  Tag,
  Alert,
  Form,
  Input,
  Select,
  Button,
  message,
} from "antd";
import { useQuery } from "@tanstack/react-query";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import unifiedKbManager from "@/services/unifiedKnowledgeBaseService";
import { modelService } from "@/services/modelService";
import { listGroups } from "@/services/groupService";
import type { CreateKbConfig } from "@/types/unifiedKnowledgeBase";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CreateKBModalProps {
  visible: boolean;
  adapters: Array<{
    adapter_id: number;
    platform: "local" | "dify" | "aidp" | "datamate" | "haotian" | "custom";
    name: string;
    status: "running" | "error" | "stopped" | "placeholder";
  }>;
  onCreated: (kb: unknown) => void;
  onCancel: () => void;
  onError?: (err: Error, context: string) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const CreateKBModal: React.FC<CreateKBModalProps> = ({
  visible,
  adapters,
  onCreated,
  onCancel,
  onError,
}) => {
  // ── Step navigation ─────────────────────────────────────────────────────
  const [currentStep, setCurrentStep] = useState(0);
  const [selectedAdapterId, setSelectedAdapterId] = useState<number | null>(
    null
  );

  // ── Form data ───────────────────────────────────────────────────────────
  const [formData, setFormData] = useState<{
    name: string;
    description?: string;
    embedding_model?: string;
    ingroup_permission?: "EDIT" | "READ_ONLY" | "PRIVATE";
    group_ids?: number[];
  }>({ name: "" });

  const [submitting, setSubmitting] = useState(false);

  // ── Derived state ───────────────────────────────────────────────────────
  const enabledAdapters = useMemo(
    () => adapters.filter((a) => a.status === "running"),
    [adapters]
  );

  const selectedAdapter = useMemo(
    () => adapters.find((a) => a.adapter_id === selectedAdapterId),
    [adapters, selectedAdapterId]
  );

  const isLocalAdapter = selectedAdapter?.platform === "local";

  // ── Auth context (for tenant-scoped group listing) ──────────────────────
  const { user } = useAuthorizationContext();
  const tenantId = user?.tenantId ?? null;

  // ── Embedding models (only fetched for local adapter) ───────────────────
  const {
    data: allModels = [],
    isLoading: embeddingModelsLoading,
  } = useQuery({
    queryKey: ["models", "embedding"],
    queryFn: () => modelService.getAllModels(),
    enabled: visible && isLocalAdapter,
    select: (models) =>
      models.filter((m) => m.type === "embedding"),
  });

  // ── Groups (only fetched for local adapter) ─────────────────────────────
  const {
    data: groupData,
    isLoading: groupsLoading,
  } = useQuery({
    queryKey: ["groups", tenantId],
    queryFn: () => listGroups(tenantId!),
    enabled: visible && isLocalAdapter && tenantId !== null,
  });

  const groups = groupData?.groups ?? [];

  // ── Handlers ────────────────────────────────────────────────────────────
  const handleCancel = () => {
    setCurrentStep(0);
    setSelectedAdapterId(null);
    setFormData({ name: "" });
    setSubmitting(false);
    onCancel();
  };

  const handleSubmit = async () => {
    if (!formData.name.trim()) {
      message.error("知识库名称必填");
      return;
    }
    if (!selectedAdapterId) {
      message.error("请先选择适配器");
      return;
    }

    const config: CreateKbConfig = {
      name: formData.name.trim(),
      ...(formData.description?.trim()
        ? { description: formData.description.trim() }
        : {}),
      ...(isLocalAdapter && formData.embedding_model
        ? { embedding_model: formData.embedding_model }
        : {}),
      ...(isLocalAdapter && formData.ingroup_permission
        ? { ingroup_permission: formData.ingroup_permission }
        : {}),
      ...(isLocalAdapter && formData.group_ids?.length
        ? { group_ids: formData.group_ids }
        : {}),
    };

    setSubmitting(true);
    try {
      const createdKb = await unifiedKbManager.createKb(
        selectedAdapterId,
        selectedAdapter!.platform,
        config
      );
      message.success("KB 创建成功");
      onCreated(createdKb);
      handleCancel();
    } catch (err) {
      onError?.(err as Error, "创建 KB 失败");
      message.error("创建失败，请重试");
    } finally {
      setSubmitting(false);
    }
  };

  // ── Modal footer ────────────────────────────────────────────────────────
  const modalFooter =
    currentStep === 0 ? (
      <div style={{ textAlign: "right" }}>
        <Button
          type="primary"
          disabled={!selectedAdapterId}
          onClick={() => setCurrentStep(1)}
        >
          下一步
        </Button>
      </div>
    ) : (
      <div>
        <Button onClick={() => setCurrentStep(0)} style={{ marginRight: 8 }}>
          上一步
        </Button>
        <Button
          type="primary"
          loading={submitting}
          onClick={handleSubmit}
        >
          创建
        </Button>
      </div>
    );

  // ── Render ──────────────────────────────────────────────────────────────
  return (
    <Modal
      title="创建知识库"
      open={visible}
      onCancel={handleCancel}
      width={640}
      footer={modalFooter}
      destroyOnClose
    >
      <Steps
        current={currentStep}
        style={{ marginBottom: 24 }}
        items={[
          { title: "选择适配器" },
          { title: "配置知识库" },
        ]}
      />

      {/* Step 1: Select adapter */}
      {currentStep === 0 && (
        <div>
          <p style={{ marginBottom: 16 }}>请选择一个适配器：</p>
          <Radio.Group
            value={selectedAdapterId}
            onChange={(e) => setSelectedAdapterId(e.target.value)}
          >
            <Space direction="vertical">
              {enabledAdapters.map((adapter) => (
                <Radio key={adapter.adapter_id} value={adapter.adapter_id}>
                  <Space>
                    <span>{adapter.name}</span>
                    <Tag
                      color={
                        adapter.platform === "local" ? "blue" : "purple"
                      }
                    >
                      {adapter.platform}
                    </Tag>
                  </Space>
                </Radio>
              ))}
            </Space>
          </Radio.Group>
          {enabledAdapters.length === 0 && (
            <Alert
              type="warning"
              message="暂无可用适配器"
              description="请先注册一个适配器后再创建知识库"
              showIcon
              style={{ marginTop: 16 }}
            />
          )}
        </div>
      )}

      {/* Step 2: Configuration form */}
      {currentStep === 1 && selectedAdapter && (
        <Form layout="vertical">
          {/* Common fields (all adapters) */}
          <Form.Item label="知识库名称" required>
            <Input
              value={formData.name}
              onChange={(e) =>
                setFormData({ ...formData, name: e.target.value })
              }
              placeholder="输入知识库名称"
            />
          </Form.Item>

          <Form.Item label="描述">
            <Input.TextArea
              value={formData.description}
              onChange={(e) =>
                setFormData({ ...formData, description: e.target.value })
              }
              placeholder="输入知识库描述（可选）"
              rows={3}
            />
          </Form.Item>

          {/* Q3: Local adapter-only fields */}
          {isLocalAdapter && (
            <>
              <Form.Item label="Embedding 模型">
                <Select
                  value={formData.embedding_model}
                  onChange={(v) =>
                    setFormData({ ...formData, embedding_model: v })
                  }
                  placeholder="选择 Embedding 模型（可选）"
                  allowClear
                  loading={embeddingModelsLoading}
                  options={allModels.map((m) => ({
                    label: m.displayName || m.name,
                    value: m.name,
                  }))}
                />
              </Form.Item>

              <Form.Item label="群组权限">
                <Select
                  value={formData.ingroup_permission}
                  onChange={(v) =>
                    setFormData({ ...formData, ingroup_permission: v })
                  }
                  placeholder="选择群组权限（可选）"
                  allowClear
                >
                  <Select.Option value="EDIT">可编辑</Select.Option>
                  <Select.Option value="READ_ONLY">只读</Select.Option>
                  <Select.Option value="PRIVATE">私有</Select.Option>
                </Select>
              </Form.Item>

              <Form.Item label="授权群组">
                <Select
                  mode="multiple"
                  value={formData.group_ids}
                  onChange={(v) =>
                    setFormData({ ...formData, group_ids: v })
                  }
                  placeholder="选择授权群组（可选）"
                  loading={groupsLoading}
                  options={groups.map((g) => ({
                    label: g.group_name,
                    value: g.group_id,
                  }))}
                />
              </Form.Item>
            </>
          )}
        </Form>
      )}
    </Modal>
  );
};

export default CreateKBModal;
