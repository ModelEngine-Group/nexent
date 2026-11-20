// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  App,
  Button,
  Drawer,
  Input,
  InputNumber,
  Select,
  Tag,
} from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";

import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { validateMetadataText } from "@/ext_components/aidp/shared/utils/aidpOntologyValidation";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type {
  AidpBatchMetadataResult,
  AidpOntologyMetadataField,
} from "@/ext_components/aidp/shared/types/ontology";
import drawerStyles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import styles from "./AidpOntologyChunkAnnotateDrawer.module.css";

interface AidpOntologyChunkAnnotateDrawerProps {
  open: boolean;
  domainId: string;
  kdsId: string;
  kbName: string;
  fileName: string;
  chunkIds: Array<string | number>;
  fields: AidpOntologyMetadataField[];
  onClose: () => void;
  onFinished: (result: AidpBatchMetadataResult) => void;
}

interface AssignmentRow {
  key: number;
  field?: string;
  value: string | number | null;
}

let rowSequence = 0;

const nextRowKey = (): number => {
  rowSequence += 1;
  return rowSequence;
};

const AidpOntologyChunkAnnotateDrawer: React.FC<
  AidpOntologyChunkAnnotateDrawerProps
> = ({
  open,
  domainId,
  kdsId,
  kbName,
  fileName,
  chunkIds,
  fields,
  onClose,
  onFinished,
}) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [rows, setRows] = useState<AssignmentRow[]>(() => [
    { key: nextRowKey(), value: "" },
  ]);
  const [saving, setSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [result, setResult] = useState<AidpBatchMetadataResult | null>(null);

  const handleClose = () => {
    setRows([{ key: nextRowKey(), value: "" }]);
    setResult(null);
    setErrorMessage(null);
    setSaving(false);
    onClose();
  };

  const fieldByName = useMemo(
    () => new Map(fields.map((field) => [field.field_name, field])),
    [fields]
  );

  const updateRow = (key: number, patch: Partial<AssignmentRow>) => {
    setRows((current) =>
      current.map((row) => (row.key === key ? { ...row, ...patch } : row))
    );
  };

  const addRow = () => {
    if (rows.length >= fields.length) return;
    setRows((current) => [...current, { key: nextRowKey(), value: "" }]);
  };

  const removeRow = (key: number) => {
    setRows((current) => current.filter((row) => row.key !== key));
  };

  const validate = (): {
    metadata?: Record<string, unknown>;
    error?: string;
  } => {
    const used = new Set<string>();
    const metadata: Record<string, unknown> = {};
    for (const row of rows) {
      if (!row.field) {
        return { error: t("aidpKnowledge.ontologyAnnotateFieldRequired") };
      }
      if (used.has(row.field)) {
        return { error: t("aidpKnowledge.ontologyAnnotateFieldDuplicated") };
      }
      used.add(row.field);
      const definition = fieldByName.get(row.field);
      if (!definition) {
        return { error: t("aidpKnowledge.ontologyAnnotateFieldUndefined") };
      }
      if (definition.field_type === "number") {
        if (
          row.value === null ||
          row.value === "" ||
          Number.isNaN(Number(row.value))
        ) {
          return {
            error: t("aidpKnowledge.ontologyAnnotateValueRequired", {
              name: row.field,
            }),
          };
        }
        metadata[row.field] = Number(row.value);
      } else {
        const value = String(row.value ?? "");
        if (!value.trim()) {
          return {
            error: t("aidpKnowledge.ontologyAnnotateValueRequired", {
              name: row.field,
            }),
          };
        }
        const byteError = validateMetadataText(row.field, value);
        if (byteError) return { error: byteError };
        metadata[row.field] = value;
      }
    }
    if (Object.keys(metadata).length === 0) {
      return { error: t("aidpKnowledge.ontologyAnnotateEmpty") };
    }
    return { metadata };
  };

  const handleSubmit = async () => {
    const validated = validate();
    if (!validated.metadata) {
      setErrorMessage(validated.error ?? null);
      return;
    }
    setSaving(true);
    setErrorMessage(null);
    try {
      const response = await aidpOntologyService.batchSetChunkMetadata(kdsId, {
        domain_id: domainId,
        metadata: validated.metadata,
        chunk_ids: chunkIds,
      });
      setResult(response);
      onFinished(response);
      if (response.failed_count === 0) {
        message.success(
          t("aidpKnowledge.ontologyAnnotateSuccess", {
            count: response.success_count,
          })
        );
      }
    } catch (error) {
      setErrorMessage(
        getAidpErrorMessage(error, t, t("aidpKnowledge.ontologyAnnotateFailed"))
      );
    } finally {
      setSaving(false);
    }
  };

  const optionFields = fields.map((field) => ({
    value: field.field_name,
    label: `${field.field_name} (${field.field_type})`,
    disabled: rows.some(
      (row) => row.field === field.field_name && row.key !== undefined
    ),
  }));

  return (
    <Drawer
      rootClassName={drawerStyles.drawer}
      open={open}
      width={640}
      onClose={handleClose}
      destroyOnHidden
      title={t("aidpKnowledge.ontologyAnnotateTitle")}
      footer={
        <div className={drawerStyles.footer}>
          {result ? (
            <Button type="primary" onClick={handleClose}>
              {t("aidpKnowledge.ontologyAnnotateDone")}
            </Button>
          ) : (
            <>
              <Button onClick={handleClose}>{t("common.cancel")}</Button>
              <Button
                type="primary"
                loading={saving}
                disabled={rows.length === 0}
                onClick={() => void handleSubmit()}
              >
                {t("aidpKnowledge.ontologyAnnotateSubmit")}
              </Button>
            </>
          )}
        </div>
      }
    >
      <div className={styles.body}>
        <div className={styles.summary}>
          <div className={styles.summaryTitle}>
            {t("aidpKnowledge.ontologyAnnotateSelected", {
              count: chunkIds.length,
            })}
          </div>
          <div className={styles.summaryLine}>
            {t("aidpKnowledge.ontologyAnnotateContext", {
              kb: kbName,
              file: fileName,
            })}
          </div>
        </div>

        {result ? (
          <div className={styles.resultBlock}>
            <Alert
              type={result.failed_count > 0 ? "warning" : "success"}
              showIcon
              message={t("aidpKnowledge.ontologyAnnotateResultSummary", {
                success: result.success_count,
                failed: result.failed_count,
              })}
            />
            {result.failed_list.length > 0 && (
              <ul className={styles.failedList}>
                {result.failed_list.map((item) => (
                  <li key={String(item.chunk_id)}>
                    <Tag className={styles.failedTag}>
                      {t("aidpKnowledge.ontologyChunkId")} {item.chunk_id}
                    </Tag>
                    <span>{item.message}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <>
            <div className={styles.rows}>
              {rows.map((row) => {
                const definition = row.field
                  ? fieldByName.get(row.field)
                  : undefined;
                return (
                  <div key={row.key} className={styles.row}>
                    <Select
                      className={styles.fieldSelect}
                      value={row.field}
                      placeholder={t(
                        "aidpKnowledge.ontologyAnnotateFieldPlaceholder"
                      )}
                      options={optionFields.map((option) => ({
                        ...option,
                        disabled: option.disabled && option.value !== row.field,
                      }))}
                      onChange={(value) =>
                        updateRow(row.key, { field: value, value: "" })
                      }
                      showSearch
                      optionFilterProp="label"
                    />
                    {definition?.field_type === "number" ? (
                      <InputNumber
                        className={styles.valueInput}
                        value={
                          typeof row.value === "number" ? row.value : undefined
                        }
                        placeholder={t(
                          "aidpKnowledge.ontologyAnnotateValuePlaceholder"
                        )}
                        onChange={(value) => updateRow(row.key, { value })}
                        step={1}
                      />
                    ) : (
                      <Input
                        className={styles.valueInput}
                        value={String(row.value ?? "")}
                        placeholder={t(
                          "aidpKnowledge.ontologyAnnotateValuePlaceholder"
                        )}
                        onChange={(event) =>
                          updateRow(row.key, { value: event.target.value })
                        }
                      />
                    )}
                    <Button
                      type="text"
                      aria-label={t("aidpKnowledge.ontologyRemoveAssignment")}
                      icon={<DeleteOutlined />}
                      onClick={() => removeRow(row.key)}
                    />
                  </div>
                );
              })}
            </div>
            <Button
              type="dashed"
              block
              icon={<PlusOutlined />}
              disabled={rows.length >= fields.length}
              onClick={addRow}
            >
              {t("aidpKnowledge.ontologyAnnotateAddField")}
            </Button>
            <div className={styles.hint}>
              {t("aidpKnowledge.ontologyAnnotateHint")}
            </div>
          </>
        )}

        {errorMessage && (
          <div className={drawerStyles.error} role="alert">
            {errorMessage}
          </div>
        )}
      </div>
    </Drawer>
  );
};

export default AidpOntologyChunkAnnotateDrawer;
