"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Modal, Select, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useQueryClient } from "@tanstack/react-query";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useSkillList } from "@/hooks/agent/useSkillList";
import { updateSkillById } from "@/services/agentConfigService";
import type { Skill } from "@/types/agentConfig";

interface SkillTagManagementModalProps {
  readonly open: boolean;
  readonly onClose: () => void;
}

interface SkillTagRow {
  skillId: number;
  name: string;
  source: string;
  tags: string[];
  editable: boolean;
}

export default function SkillTagManagementModal({
  open,
  onClose,
}: SkillTagManagementModalProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { user } = useAuthorizationContext();
  const { availableSkills } = useSkillList({ enabled: open });
  const [rows, setRows] = useState<SkillTagRow[]>([]);
  const builtRef = useRef(false);

  useEffect(() => {
    if (open && !builtRef.current && availableSkills.length > 0) {
      setRows(
        availableSkills.map((skill: Skill) => ({
          skillId: skill.skill_id,
          name: skill.name,
          source: skill.source || "",
          tags: Array.isArray(skill.tags) ? [...skill.tags] : [],
          editable: Boolean(user?.id && skill.created_by === user.id),
        }))
      );
      builtRef.current = true;
    }
    if (!open) {
      setRows([]);
      builtRef.current = false;
    }
  }, [availableSkills, open, user?.id]);

  const allTags = useMemo(() => {
    const tagSet = new Set<string>();
    rows.forEach((row) => row.tags.forEach((tag) => tagSet.add(tag)));
    return [...tagSet].sort((left, right) => left.localeCompare(right));
  }, [rows]);

  const handleTagsChange = useCallback(
    async (skillId: number, tags: string[]) => {
      const previousRows = rows;
      setRows((current) =>
        current.map((row) => (row.skillId === skillId ? { ...row, tags } : row))
      );
      const result = await updateSkillById(skillId, { tags });
      if (!result.success) {
        setRows(previousRows);
        message.error(
          result.message || t("skillManagement.message.tagsSaveFailed")
        );
        return;
      }
      await queryClient.invalidateQueries({ queryKey: ["skills"] });
    },
    [message, queryClient, rows, t]
  );

  const columns: ColumnsType<SkillTagRow> = [
    {
      title: t("skillManagement.form.name"),
      dataIndex: "name",
      key: "name",
      width: 230,
    },
    {
      title: t("skillManagement.form.source"),
      dataIndex: "source",
      key: "source",
      width: 140,
    },
    {
      title: t("skillManagement.form.tags"),
      dataIndex: "tags",
      key: "tags",
      render: (tags: string[], row) => (
        <Select
          mode="tags"
          value={tags}
          disabled={!row.editable}
          onChange={(value: string[]) => handleTagsChange(row.skillId, value)}
          placeholder={t("skillManagement.form.tagsPlaceholder")}
          tokenSeparators={[","]}
          options={allTags.map((tag) => ({ label: tag, value: tag }))}
          style={{ minWidth: 260, width: "100%" }}
        />
      ),
    },
  ];

  return (
    <Modal
      title={t("skillPool.manageTags")}
      open={open}
      onCancel={onClose}
      mask={{ closable: true }}
      maskClosable
      footer={null}
      width={1000}
      zIndex={1100}
    >
      <Table
        dataSource={rows}
        columns={columns}
        rowKey="skillId"
        size="small"
        pagination={{ pageSize: 25, size: "small" }}
        scroll={{ y: 560 }}
      />
    </Modal>
  );
}
