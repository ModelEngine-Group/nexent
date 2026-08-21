"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  App,
  Button,
  Empty,
  Modal,
  Progress,
  Select,
  Table,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";

import { useTagAssignments } from "@/hooks/useTagManagement";
import { tagManagementApi } from "@/services/tagManagementService";
import type {
  TagAssignmentBulkOutcome,
  TagDefinition,
  TagSelectionMode,
} from "@/types/tagManagement";

interface ResourceTagAssignmentModalProps {
  open: boolean;
  onClose: () => void;
  resourceType: string;
  resourceId: string;
  definitions: TagDefinition[];
  canEdit: boolean;
  provider?: string | null;
  knowledgeBaseId?: string | null;
  bulkResourceIds?: string[];
  onManageDefinitions?: () => void;
}

interface BulkTarget {
  resourceId: string;
  provider?: string | null;
  knowledgeBaseId?: string | null;
}

export default function ResourceTagAssignmentModal({
  open,
  onClose,
  resourceType,
  resourceId,
  definitions,
  canEdit,
  provider,
  knowledgeBaseId,
  bulkResourceIds,
  onManageDefinitions,
}: ResourceTagAssignmentModalProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const assignmentState = useTagAssignments(
    resourceType,
    open ? resourceId : null,
    { provider, knowledgeBaseId }
  );
  const [selected, setSelected] = useState<Record<number, number[]>>({});
  const [saving, setSaving] = useState(false);
  const [bulkTargets, setBulkTargets] = useState<BulkTarget[]>([]);
  const [bulkOutcomes, setBulkOutcomes] = useState<TagAssignmentBulkOutcome[]>(
    []
  );

  useEffect(() => {
    if (!open) {
      setSelected({});
      setBulkOutcomes([]);
      return;
    }
    const next: Record<number, number[]> = {};
    for (const assignment of assignmentState.data?.assignments ?? []) {
      const group = next[assignment.definition_id] ?? [];
      group.push(assignment.value_id);
      next[assignment.definition_id] = group;
    }
    setSelected(next);
    if (bulkResourceIds && bulkResourceIds.length > 0) {
      setBulkTargets(
        bulkResourceIds.map((targetResourceId) => ({
          resourceId: targetResourceId,
          provider,
          knowledgeBaseId,
        }))
      );
    } else {
      setBulkTargets([{ resourceId, provider, knowledgeBaseId }]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, assignmentState.data, bulkResourceIds]);

  const activeDefinitions = useMemo(
    () => definitions.filter((definition) => definition.status === "active"),
    [definitions]
  );

  const totalSelected = useMemo(
    () => Object.values(selected).reduce((sum, ids) => sum + ids.length, 0),
    [selected]
  );

  const saveSingle = useCallback(async () => {
    const valueIds = Object.values(selected).flat();
    if (valueIds.length > 100) {
      message.warning(t("tagManagement.warning.assignmentCapacity"));
      return;
    }
    setSaving(true);
    try {
      const result = await assignmentState.replace({ value_ids: valueIds });
      message.success(t("tagManagement.message.assignmentsSaved"));
      const projection = result.projection_status;
      if (projection && projection.status !== "synced") {
        message.warning(
          t("tagManagement.warning.projectionPending", {
            status: projection.status,
          })
        );
      }
      onClose();
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  }, [assignmentState, message, onClose, selected, t]);

  const saveBulk = useCallback(async () => {
    const targets = bulkTargets.filter((target) => target.resourceId.trim());
    if (targets.length === 0) return;
    const valueIds = Object.values(selected).flat();
    setSaving(true);
    try {
      const outcomes = await tagManagementApi.replaceAssignmentsBulk(
        resourceType,
        {
          targets: targets.map((target) => ({
            resource_id: target.resourceId,
            provider: target.provider ?? undefined,
            knowledge_base_id: target.knowledgeBaseId ?? undefined,
            value_ids: valueIds,
          })),
        }
      );
      setBulkOutcomes(outcomes);
      const failed = outcomes.filter(
        (outcome) => outcome.outcome !== "updated"
      );
      if (failed.length === 0) {
        message.success(t("tagManagement.message.assignmentsSaved"));
        onClose();
      } else {
        message.warning(
          t("tagManagement.warning.bulkPartialFailure", {
            count: failed.length,
          })
        );
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  }, [bulkTargets, message, onClose, resourceType, selected, t]);

  const outcomeColumns: ColumnsType<TagAssignmentBulkOutcome> = [
    {
      title: t("tagManagement.column.resource"),
      dataIndex: "resource_id",
      key: "resource_id",
    },
    {
      title: t("tagManagement.column.outcome"),
      dataIndex: "outcome",
      key: "outcome",
      width: 180,
      render: (outcome: string) => (
        <Typography.Text type={outcome === "updated" ? "success" : "danger"}>
          {outcome}
        </Typography.Text>
      ),
    },
    {
      title: t("tagManagement.column.message"),
      dataIndex: "message",
      key: "message",
      render: (value: string | null | undefined) => value ?? "—",
    },
  ];

  const renderDefinitionControl = (definition: TagDefinition) => {
    const valueIds = selected[definition.definition_id] ?? [];
    const options = (definition.values ?? [])
      .filter((tagValue) => tagValue.status === "active")
      .map((tagValue) => ({
        label: tagValue.display_value,
        value: tagValue.value_id,
      }));
    const single =
      definition.selection_mode === ("single_select" as TagSelectionMode);
    return (
      <div key={definition.definition_id} className="flex flex-col gap-1">
        <Typography.Text strong>{definition.definition_name}</Typography.Text>
        <Select
          mode={single ? undefined : "multiple"}
          allowClear
          placeholder={t("tagManagement.form.assignPlaceholder")}
          options={options}
          value={single ? (valueIds[0] ?? undefined) : valueIds}
          disabled={!canEdit}
          onChange={(nextValue: number | number[]) => {
            setSelected((current) => ({
              ...current,
              [definition.definition_id]: Array.isArray(nextValue)
                ? nextValue
                : nextValue == null
                  ? []
                  : [nextValue],
            }));
          }}
          style={{ width: "100%" }}
        />
      </div>
    );
  };

  const capacityPercent = Math.min(
    100,
    Math.round((totalSelected / 100) * 100)
  );

  return (
    <Modal
      title={t("tagManagement.title.assignTags")}
      open={open}
      onCancel={onClose}
      onOk={() => (bulkTargets.length > 1 ? saveBulk() : saveSingle())}
      okText={t("tagManagement.action.save")}
      confirmLoading={saving}
      width={720}
      zIndex={1100}
      centered
      destroyOnHidden
    >
      <div className="flex flex-col gap-3">
        <Progress
          percent={capacityPercent}
          size="small"
          format={() => `${totalSelected}/100`}
        />
        {activeDefinitions.length > 0 ? (
          activeDefinitions.map(renderDefinitionControl)
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t("tagManagement.empty.noActiveDefinitions")}
          >
            {canEdit && onManageDefinitions ? (
              <Button type="primary" onClick={onManageDefinitions}>
                {t("tagManagement.action.manageDefinitions")}
              </Button>
            ) : null}
          </Empty>
        )}
        {bulkOutcomes.length > 0 && (
          <Table
            rowKey="resource_id"
            dataSource={bulkOutcomes}
            columns={outcomeColumns}
            size="small"
            pagination={false}
          />
        )}
      </div>
    </Modal>
  );
}
