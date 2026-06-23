"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  Empty,
  Flex,
  Modal,
  Table,
  Tag,
  Typography,
  Upload,
  Input,
  message,
} from "antd";
const { TextArea } = Input;
import { Trash2, CheckCircle } from "lucide-react";
import type { ColumnsType } from "antd/es/table";
import { evaluationService } from "@/services/evaluationService";
import { useEvaluationSets } from "@/hooks/evaluation/useEvaluationSets";
import type { EvaluationSet } from "@/types/agentEvaluation";

const { Text } = Typography;

interface TestCaseLibraryModalProps {
  open: boolean;
  onClose: () => void;
  selectedSetId: number | null;
  onSelect: (set: EvaluationSet) => void;
  uploadOpen?: boolean;
  onUploadOpenChange?: (open: boolean) => void;
}

export default function TestCaseLibraryModal({
  open,
  onClose,
  selectedSetId,
  onSelect,
  uploadOpen: uploadOpenProp,
  onUploadOpenChange,
}: TestCaseLibraryModalProps) {
  const { t } = useTranslation("common");
  const { sets, loading, deletingId, loadSets, deleteSet } = useEvaluationSets();

  const [uploadOpenInternal, setUploadOpenInternal] = useState(false);
  const uploadOpen = uploadOpenProp !== undefined ? uploadOpenProp : uploadOpenInternal;
  const setUploadOpen = onUploadOpenChange ?? setUploadOpenInternal;
  const [uploadName, setUploadName] = useState("");
  const [uploadDesc, setUploadDesc] = useState("");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    if (open) {
      loadSets();
    }
  }, [open, loadSets]);

  const handleUpload = async () => {
    const name = uploadName.trim();
    if (!name) {
      message.error(t("agentEvaluation.createSetModal.nameRequired"));
      return;
    }
    if (!uploadFiles.length) {
      message.error(t("agentEvaluation.createSetModal.fileRequired"));
      return;
    }
    setUploading(true);
    try {
      await evaluationService.uploadEvaluationSetExcel({
        name,
        description: uploadDesc || undefined,
        files: uploadFiles,
      });
      message.success(t("agentEvaluation.message.createSetSuccess"));
      setUploadOpen(false);
      setUploadName("");
      setUploadDesc("");
      setUploadFiles([]);
      loadSets();
    } catch (err: any) {
      message.error(err?.message || t("agentEvaluation.message.createSetFailed"));
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (setId: number, setName: string) => {
    Modal.confirm({
      title: t("agentEvaluation.lib.deleteConfirm", { name: setName }),
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
      async onOk() {
        await deleteSet(setId);
      },
    });
  };

  const columns: ColumnsType<EvaluationSet> = [
    {
      title: t("common.name"),
      dataIndex: "name",
      key: "name",
      render: (name, record) => (
        <Flex align="center" gap={8}>
          <Text>{name}</Text>
          {record.evaluation_set_id === selectedSetId && (
            <Tag color="blue" icon={<CheckCircle className="w-3 h-3" />}>
              {t("agentEvaluation.lib.used")}
            </Tag>
          )}
        </Flex>
      ),
    },
    {
      title: t("agentEvaluation.lib.caseCount", { n: 0 }).replace("0", ""),
      key: "case_count",
      width: 100,
      render: (_, record) => (
        <Text type="secondary">{t("agentEvaluation.lib.caseCount", { n: record.case_count ?? 0 })}</Text>
      ),
    },
    {
      title: t("common.description"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
      render: (v) => <Text type="secondary">{v || "-"}</Text>,
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 160,
      render: (_, record) => (
        <Flex gap={8}>
          {record.evaluation_set_id !== selectedSetId && (
            <Button size="small" type="primary" onClick={() => onSelect(record)}>
              {t("agentEvaluation.lib.use")}
            </Button>
          )}
          <Button
            size="small"
            danger
            type="text"
            icon={<Trash2 className="w-4 h-4" />}
            loading={deletingId === record.evaluation_set_id}
            onClick={() => handleDelete(record.evaluation_set_id, record.name)}
          />
        </Flex>
      ),
    },
  ];

  return (
    <>
      <Modal
        title={t("agentEvaluation.lib.title")}
        open={open}
        onCancel={onClose}
        footer={null}
        width={640}
        destroyOnClose
      >
        <Flex vertical gap={12}>
          <Text type="secondary" className="text-sm">
            {t("agentEvaluation.lib.desc")}
          </Text>
          {sets.length === 0 && !loading ? (
            <Empty
              description={t("agentEvaluation.lib.empty")}
              className="py-8"
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          ) : (
            <Table
              columns={columns}
              dataSource={sets}
              rowKey="evaluation_set_id"
              size="small"
              loading={loading}
              pagination={false}
              scroll={{ y: 360 }}
            />
          )}
        </Flex>
      </Modal>

      {/* Inner upload modal */}
      <Modal
        title={t("agentEvaluation.createSetModal.title")}
        open={uploadOpen}
        onCancel={() => setUploadOpen(false)}
        onOk={handleUpload}
        okText={t("agentEvaluation.createSetModal.create")}
        confirmLoading={uploading}
        destroyOnClose
      >
        <Flex vertical gap={12}>
          <Flex vertical gap={4}>
            <Text className="text-sm">{t("agentEvaluation.createSetModal.namePlaceholder")}</Text>
            <Input
              placeholder={t("agentEvaluation.createSetModal.namePlaceholder")}
              value={uploadName}
              onChange={(e) => setUploadName(e.target.value)}
            />
          </Flex>
          <Flex vertical gap={4}>
            <Text className="text-sm">{t("agentEvaluation.createSetModal.descPlaceholder")}</Text>
            <TextArea
              placeholder={t("agentEvaluation.createSetModal.descPlaceholder")}
              value={uploadDesc}
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setUploadDesc(e.target.value)}
              rows={2}
            />
          </Flex>
          <Flex vertical gap={4}>
            <Text className="text-sm">{t("agentEvaluation.createSetModal.chooseFile")}</Text>
            <Upload.Dragger
              accept=".xlsx,.xls"
              beforeUpload={(file) => {
                setUploadFiles([file]);
                return false;
              }}
              fileList={uploadFiles.map((f, i) => ({
                uid: String(i),
                name: f.name,
                status: "done" as const,
              }))}
              onRemove={() => setUploadFiles([])}
              maxCount={1}
            >
              <p className="text-slate-500">{t("agentEvaluation.createSetModal.chooseFile")}</p>
            </Upload.Dragger>
          </Flex>
        </Flex>
      </Modal>
    </>
  );
}
