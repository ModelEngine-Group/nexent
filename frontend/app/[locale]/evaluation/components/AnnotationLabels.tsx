"use client";
import { useState, useEffect } from "react";
import {
  Typography,
  Table,
  Button,
  Tag,
  Flex,
  Modal,
  Input,
  Select,
  Space,
  Popconfirm,
  App,
  Tooltip,
} from "antd";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getAuthHeaders } from "@/lib/auth";
import { getI18nErrorMessage } from "@/const/errorMessageI18n";

const { Text, Title } = Typography;

type AnnotationLabelsProps = {
  embedded?: boolean;
};

export default function AnnotationLabels({
  embedded = false,
}: AnnotationLabelsProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [schemas, setSchemas] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState<any>(null);
  const [f, setF] = useState({
    name: "",
    description: "",
    annotation_type: "classification",
    optionsText: "",
  });

  const TYPE_OPTIONS = [
    { value: "classification", label: t("分类") },
    { value: "boolean", label: t("agentEvaluation.booleanLabel") },
    { value: "number", label: t("agentEvaluation.numberLabel") },
    { value: "text", label: t("agentEvaluation.textLabel") },
  ];

  const fetchSchemas = () => {
    setLoading(true);
    fetch("/api/evaluation-annotations/schemas", { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((d) => setSchemas(d.data || []))
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    fetchSchemas();
  }, []);

  const openCreate = () => {
    setEditing(null);
    setF({
      name: "",
      description: "",
      annotation_type: "classification",
      optionsText: "",
    });
    setModal(true);
  };
  const openEdit = (s: any) => {
    setEditing(s);
    setF({
      name: s.name,
      description: s.description || "",
      annotation_type: s.annotation_type,
      optionsText: s.options?.map((o: any) => o.label).join("\n") || "",
    });
    setModal(true);
  };

  const save = async () => {
    if (!f.name.trim()) {
      message.warning(t("agentEvaluation.labelNameRequired"));
      return;
    }
    const options =
      f.annotation_type === "classification"
        ? f.optionsText
            .split("\n")
            .filter((l) => l.trim())
            .map((l) => ({ label: l.trim() }))
        : f.annotation_type === "boolean"
          ? [{ label: "True" }, { label: "False" }]
          : null;
    const body = {
      name: f.name,
      description: f.description,
      annotation_type: f.annotation_type,
      options,
    };
    const url = editing
      ? `/api/evaluation-annotations/schemas/${editing.schema_id}`
      : "/api/evaluation-annotations/schemas";
    const method = editing ? "PUT" : "POST";
    const res = await fetch(url, {
      method,
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      message.error(getI18nErrorMessage(d.code, t));
      return;
    }
    setModal(false);
    fetchSchemas();
  };

  const cols = [
    {
      title: t("agentEvaluation.labelName"),
      dataIndex: "name",
      ellipsis: true,
      width: 150,
    },
    {
      title: t("agentEvaluation.colHeader.type"),
      dataIndex: "annotation_type",
      width: 80,
      render: (v: string) => (
        <Tag>{TYPE_OPTIONS.find((o) => o.value === v)?.label || v}</Tag>
      ),
    },
    {
      title: t("agentEvaluation.description"),
      dataIndex: "description",
      ellipsis: true,
      render: (v: any) => v || "-",
    },
    {
      title: t("agentEvaluation.options"),
      dataIndex: "options",
      width: 200,
      ellipsis: true,
      render: (v: any) =>
        v?.length ? v.map((o: any) => o.label).join(", ") : "-",
    },
    {
      title: t("agentEvaluation.colHeader.actions"),
      width: 80,
      render: (_: any, r: any) => (
        <Space size={0}>
          <Tooltip title={t("agentEvaluation.edit")}>
            <Button
              type="link"
              size="small"
              icon={<Pencil className="size-3.5" />}
              onClick={() => openEdit(r)}
            />
          </Tooltip>
          <Popconfirm
            title={t("agentEvaluation.deleteLabelConfirm")}
            onConfirm={async () => {
              const res = await fetch(
                `/api/evaluation-annotations/schemas/${r.schema_id}`,
                { method: "DELETE", headers: getAuthHeaders() }
              );
              if (!res.ok) {
                const d = await res.json().catch(() => ({}));
                message.error(getI18nErrorMessage(d.code, t));
                return;
              }
              fetchSchemas();
            }}
          >
            <Tooltip title={t("agentEvaluation.delete")}>
              <Button
                type="link"
                size="small"
                danger
                icon={<Trash2 className="size-3.5" />}
              />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const header = embedded ? (
    <Flex justify="space-between" className="mb-3">
      <Text strong>{t("agentEvaluation.annotationLabels")}</Text>
      <Button
        type="primary"
        icon={<Plus className="size-4" />}
        onClick={openCreate}
      >
        {t("agentEvaluation.createLabel")}
      </Button>
    </Flex>
  ) : (
    <Flex justify="space-between" className="mb-4">
      <Title level={4}>{t("agentEvaluation.annotationLabels")}</Title>
      <Button
        type="primary"
        icon={<Plus className="size-4" />}
        onClick={openCreate}
      >
        {t("agentEvaluation.createLabel")}
      </Button>
    </Flex>
  );

  return (
    <div className={embedded ? "" : "p-4 max-w-4xl mx-auto"}>
      {header}
      <Table
        columns={cols}
        dataSource={schemas}
        rowKey="schema_id"
        size="small"
        loading={loading}
        pagination={{ pageSize: 20 }}
      />
      <Modal
        title={
          editing
            ? t("agentEvaluation.editLabel")
            : t("agentEvaluation.createLabel")
        }
        open={modal}
        onOk={save}
        onCancel={() => setModal(false)}
        width={500}
      >
        <Flex vertical gap={12}>
          <Flex vertical gap={4}>
            <Text className="text-xs">
              {t("agentEvaluation.labelName")} <Text type="danger">*</Text>
            </Text>
            <Input
              maxLength={50}
              showCount
              value={f.name}
              onChange={(e) => setF({ ...f, name: e.target.value })}
              placeholder={t("agentEvaluation.labelNamePlaceholder")}
            />
          </Flex>
          <Flex vertical gap={4}>
            <Text className="text-xs">{t("agentEvaluation.description")}</Text>
            <Input
              maxLength={200}
              showCount
              value={f.description}
              onChange={(e) => setF({ ...f, description: e.target.value })}
              placeholder={t("agentEvaluation.labelDescPlaceholder")}
            />
          </Flex>
          <Flex vertical gap={4}>
            <Text className="text-xs">
              {t("agentEvaluation.colHeader.type")}
            </Text>
            <Select
              value={f.annotation_type}
              onChange={(v) => setF({ ...f, annotation_type: v })}
              options={TYPE_OPTIONS}
              disabled={!!editing}
            />
          </Flex>
          {f.annotation_type === "classification" && (
            <Flex vertical gap={4}>
              <Text className="text-xs">
                {t("agentEvaluation.labelOptionsHint")}
              </Text>
              <Input.TextArea
                rows={5}
                value={f.optionsText}
                onChange={(e) => setF({ ...f, optionsText: e.target.value })}
                placeholder={t("agentEvaluation.labelOptionsPlaceholder")}
              />
            </Flex>
          )}
        </Flex>
      </Modal>
    </div>
  );
}
