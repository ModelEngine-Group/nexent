"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  App,
  Badge,
  Button,
  Empty,
  Flex,
  Modal,
  Pagination,
  Progress,
  Select,
  Table,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";

import { useTagAssignments } from "@/hooks/useTagManagement";
import {
  getTagDefinitionDisplayName,
  getTagValueDisplayName,
} from "@/lib/systemTagLabels";
import { tagManagementApi } from "@/services/tagManagementService";
import type {
  TagAssignment,
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
  initialSelection?: Record<number, number[]>;
  onSaved?: (assignment: TagAssignment) => void;
  onManageDefinitions?: () => void;
}

interface BulkTarget {
  resourceId: string;
  provider?: string | null;
  knowledgeBaseId?: string | null;
}

const DEFINITION_PAGE_SIZE = 8;

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
  initialSelection,
  onSaved,
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
  const [activeDefinitionId, setActiveDefinitionId] = useState<number | null>(
    null
  );
  const [definitionPage, setDefinitionPage] = useState(1);

  useEffect(() => {
    if (!open) {
      setSelected({});
      setBulkOutcomes([]);
      setActiveDefinitionId(null);
      setDefinitionPage(1);
      return;
    }
    const next: Record<number, number[]> = {};
    for (const assignment of assignmentState.data?.assignments ?? []) {
      const group = next[assignment.definition_id] ?? [];
      group.push(assignment.value_id);
      next[assignment.definition_id] = group;
    }
    if (Object.keys(next).length === 0 && initialSelection) {
      for (const [definitionId, valueIds] of Object.entries(initialSelection)) {
        next[Number(definitionId)] = valueIds;
      }
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
  }, [open, assignmentState.data, bulkResourceIds, initialSelection]);

  const activeDefinitions = useMemo(
    () => definitions.filter((definition) => definition.status === "active"),
    [definitions]
  );

  useEffect(() => {
    if (!open || activeDefinitions.length === 0) return;
    setActiveDefinitionId((current) =>
      activeDefinitions.some(
        (definition) => definition.definition_id === current
      )
        ? current
        : activeDefinitions[0].definition_id
    );
  }, [activeDefinitions, open]);

  const definitionPageCount = Math.max(
    1,
    Math.ceil(activeDefinitions.length / DEFINITION_PAGE_SIZE)
  );
  const visibleDefinitions = activeDefinitions.slice(
    (definitionPage - 1) * DEFINITION_PAGE_SIZE,
    definitionPage * DEFINITION_PAGE_SIZE
  );

  useEffect(() => {
    setDefinitionPage((current) => Math.min(current, definitionPageCount));
  }, [definitionPageCount]);

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
      onSaved?.(result);
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
  }, [assignmentState, message, onClose, onSaved, selected, t]);

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
    const definitionName = getTagDefinitionDisplayName(
      definition.definition_key,
      definition.definition_name,
      t
    );
    const valueIds = selected[definition.definition_id] ?? [];
    const options = (definition.values ?? [])
      .filter((tagValue) => tagValue.status === "active")
      .map((tagValue) => ({
        label: getTagValueDisplayName(
          definition.definition_key,
          tagValue.display_value,
          t
        ),
        value: tagValue.value_id,
      }));
    const single =
      definition.selection_mode === ("single_select" as TagSelectionMode);
    return (
      <div className="flex flex-col gap-2">
        <div>
          <Typography.Text strong>{definitionName}</Typography.Text>
          <Typography.Paragraph type="secondary" className="!mb-0 !text-xs">
            {single
              ? t("tagManagement.form.singleSelectHint")
              : t("tagManagement.form.multiSelectHint")}
          </Typography.Paragraph>
        </div>
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
  const activeDefinition = activeDefinitions.find(
    (definition) => definition.definition_id === activeDefinitionId
  );

  return (
    <Modal
      title={
        <Flex align="center" gap={8}>
          <span>
            {bulkTargets.length > 1
              ? t("tagManagement.title.bulkAssignTags")
              : t("tagManagement.action.editTags")}
          </span>
          {onManageDefinitions ? (
            <Button type="link" size="small" onClick={onManageDefinitions}>
              {t("tagManagement.action.manageDefinitions")}
            </Button>
          ) : null}
        </Flex>
      }
      open={open}
      onCancel={onClose}
      onOk={() => (bulkTargets.length > 1 ? saveBulk() : saveSingle())}
      okText={t("tagManagement.action.save")}
      cancelText={t("common.cancel")}
      confirmLoading={saving}
      width={880}
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
        {activeDefinition ? (
          <div className="grid min-h-[320px] grid-cols-1 gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
            <div className="rounded-md border border-slate-200 bg-slate-50 p-2">
              <div className="mb-2 px-2 text-xs font-medium text-slate-500">
                {t("tagManagement.form.keys")}
              </div>
              <div className="flex flex-col gap-1">
                {visibleDefinitions.map((definition) => {
                  const selectedCount =
                    selected[definition.definition_id]?.length ?? 0;
                  const isActive =
                    definition.definition_id === activeDefinition.definition_id;
                  return (
                    <Button
                      key={definition.definition_id}
                      type={isActive ? "primary" : "text"}
                      className="!flex !h-auto !items-center !justify-between !px-3 !py-2 !text-left"
                      onClick={() =>
                        setActiveDefinitionId(definition.definition_id)
                      }
                    >
                      <span className="truncate">
                        {getTagDefinitionDisplayName(
                          definition.definition_key,
                          definition.definition_name,
                          t
                        )}
                      </span>
                      {selectedCount > 0 ? (
                        <Badge
                          count={selectedCount}
                          overflowCount={99}
                          color={isActive ? "#ffffff" : "#1677ff"}
                          className={
                            isActive
                              ? "[&_.ant-badge-count]:!text-blue-600"
                              : ""
                          }
                        />
                      ) : null}
                    </Button>
                  );
                })}
              </div>
              <Pagination
                className="mt-3 flex justify-center"
                current={definitionPage}
                pageSize={DEFINITION_PAGE_SIZE}
                total={activeDefinitions.length}
                size="small"
                showSizeChanger={false}
                hideOnSinglePage
                onChange={setDefinitionPage}
              />
            </div>
            <div className="rounded-md border border-slate-200 p-4">
              {renderDefinitionControl(activeDefinition)}
            </div>
          </div>
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
