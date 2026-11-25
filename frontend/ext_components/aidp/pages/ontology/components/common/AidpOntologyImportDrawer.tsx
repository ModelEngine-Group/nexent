// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, App, Button, Drawer, Tooltip, Upload } from "antd";
import { InboxOutlined, QuestionCircleOutlined } from "@ant-design/icons";

import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import {
  parseOntologyJson,
  previewOntologyImport,
} from "@/ext_components/aidp/shared/utils/aidpOntologyJson";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import { ApiError } from "@/services/api";
import type {
  AidpOntologyImportError,
  AidpOntologyImportPreview,
  AidpOntologyImportResult,
  AidpOntologyJsonDocument,
  AidpOntologySyncImportResult,
} from "@/ext_components/aidp/shared/types/ontology";
import drawerStyles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import styles from "./AidpOntologyImportDrawer.module.css";

interface AidpOntologyImportDrawerProps {
  open: boolean;
  domainId: string;
  domainName: string;
  onClose: () => void;
  onImported: () => void;
}

const INITIAL_ERRORS = 10;

const AidpOntologyImportDrawer: React.FC<AidpOntologyImportDrawerProps> = ({
  open,
  domainId,
  domainName,
  onClose,
  onImported,
}) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [fileName, setFileName] = useState("");
  const [document, setDocument] = useState<AidpOntologyJsonDocument | null>(
    null
  );
  const [preview, setPreview] = useState<AidpOntologyImportPreview | null>(
    null
  );
  const [reading, setReading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<AidpOntologySyncImportResult | null>(
    null
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [serverErrors, setServerErrors] = useState<AidpOntologyImportError[]>(
    []
  );
  const [showAllErrors, setShowAllErrors] = useState(false);

  const reset = () => {
    setFileName("");
    setDocument(null);
    setPreview(null);
    setResult(null);
    setErrorMessage(null);
    setServerErrors([]);
    setShowAllErrors(false);
    setReading(false);
    setImporting(false);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const handleFile = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".json")) {
      setFileName(file.name);
      setDocument(null);
      setPreview(null);
      setErrorMessage(t("aidpKnowledge.ontologyImportJsonOnly"));
      return;
    }
    setReading(true);
    setResult(null);
    setErrorMessage(null);
    setServerErrors([]);
    setShowAllErrors(false);
    try {
      const text = await file.text();
      const parsed = parseOntologyJson(text, t);
      if (!parsed.document) {
        setFileName(file.name);
        setDocument(null);
        setPreview(null);
        setErrorMessage(
          parsed.error ?? t("aidpKnowledge.ontologyImportParseFailed")
        );
        return;
      }
      const nextPreview = previewOntologyImport(
        parsed.document,
        file.name,
        domainName,
        t
      );
      setFileName(file.name);
      setDocument(parsed.document);
      setPreview(nextPreview);
      if (nextPreview.errors.length > 0) {
        setErrorMessage(t("aidpKnowledge.ontologyImportValidationFailed"));
      }
    } catch {
      setFileName(file.name);
      setDocument(null);
      setPreview(null);
      setErrorMessage(t("aidpKnowledge.ontologyImportReadFailed"));
    } finally {
      setReading(false);
    }
  };

  const handleSubmit = async () => {
    if (!document || !preview) return;
    setImporting(true);
    setErrorMessage(null);
    setServerErrors([]);
    try {
      const response: AidpOntologyImportResult =
        await aidpOntologyService.importDomain(domainId, fileName, document);
      if (response.accepted) {
        message.info(
          t("aidpKnowledge.ontologyImportAccepted", {
            taskId: response.task_id ?? "",
          }),
          8
        );
        reset();
        onImported();
        onClose();
        return;
      }
      setResult(response);
      onImported();
    } catch (error) {
      if (error instanceof ApiError) {
        const details = error.details as { errors?: unknown } | undefined;
        if (Array.isArray(details?.errors)) {
          setServerErrors(details.errors as AidpOntologyImportError[]);
        }
      }
      setErrorMessage(
        getAidpErrorMessage(error, t, t("aidpKnowledge.ontologyImportFailed"))
      );
    } finally {
      setImporting(false);
    }
  };

  const issueMessage = (
    issue: AidpOntologyImportError | { field: string; message: string }
  ): string => {
    const reason = "reason" in issue ? issue.reason : undefined;
    if (!reason) return issue.message;
    const params = "params" in issue ? issue.params : undefined;
    return t(`aidpKnowledge.ontologyImportIssue.${reason}`, params ?? {});
  };
  const previewErrors = preview?.errors ?? [];
  const resultErrors = result?.errors ?? [];
  const visiblePreviewErrors = showAllErrors
    ? previewErrors
    : previewErrors.slice(0, INITIAL_ERRORS);
  const visibleResultErrors = showAllErrors
    ? resultErrors
    : resultErrors.slice(0, INITIAL_ERRORS);
  const canSubmit =
    !!document && !!preview && preview.errors.length === 0 && !importing;

  return (
    <Drawer
      rootClassName={drawerStyles.drawer}
      open={open}
      width={640}
      onClose={handleClose}
      destroyOnHidden
      title={
        <span className={styles.drawerTitle}>
          {t("aidpKnowledge.ontologyImportTitle")}
          <Tooltip title={t("aidpKnowledge.ontologyImportTitleHint")}>
            <QuestionCircleOutlined className={styles.questionIcon} />
          </Tooltip>
        </span>
      }
      footer={
        <div className={drawerStyles.footer}>
          {result ? (
            <Button type="primary" onClick={handleClose}>
              {t("aidpKnowledge.ontologyImportDone")}
            </Button>
          ) : (
            <>
              <Button onClick={handleClose}>{t("common.cancel")}</Button>
              <Button
                type="primary"
                loading={importing}
                disabled={!canSubmit}
                onClick={() => void handleSubmit()}
              >
                {t("aidpKnowledge.ontologyImportStart")}
              </Button>
            </>
          )}
        </div>
      }
    >
      <div className={styles.body}>
        {!result && (
          <Upload.Dragger
            className={styles.dropzone}
            accept=".json,application/json"
            multiple={false}
            maxCount={1}
            showUploadList={false}
            beforeUpload={(file) => {
              void handleFile(file);
              return false;
            }}
            disabled={reading || importing}
          >
            <p className={styles.dropzoneIcon}>
              <InboxOutlined />
            </p>
            <p className={styles.dropzoneTitle}>
              {t("aidpKnowledge.ontologyImportDropTitle")}
            </p>
            <p className={styles.dropzoneNote}>
              {t("aidpKnowledge.ontologyImportDropNote")}
            </p>
          </Upload.Dragger>
        )}

        {preview && !result && (
          <div className={styles.preview}>
            <div className={styles.previewHeader}>
              <span className={styles.fileName}>{fileName}</span>
              <Button
                type="link"
                size="small"
                onClick={() => {
                  setFileName("");
                  setDocument(null);
                  setPreview(null);
                  setErrorMessage(null);
                }}
              >
                {t("aidpKnowledge.ontologyImportChooseAnother")}
              </Button>
            </div>
            <dl className={styles.counts}>
              <div>
                <dt>Type</dt>
                <dd>{preview.typeCount}</dd>
              </div>
              <div>
                <dt>Entity</dt>
                <dd>{preview.entityCount}</dd>
              </div>
              <div>
                <dt>Relation</dt>
                <dd>{preview.relationCount}</dd>
              </div>
            </dl>
            <div className={styles.target}>
              {t("aidpKnowledge.ontologyImportTarget", {
                name: preview.targetDomainName,
              })}
            </div>
            {previewErrors.length > 0 && (
              <div className={styles.errorList}>
                <Alert
                  type="error"
                  showIcon
                  message={t("aidpKnowledge.ontologyImportValidationFailed")}
                />
                <ul>
                  {visiblePreviewErrors.map((error, index) => (
                    <li key={`${error.field}-${index}`}>
                      <span className={styles.errorField}>{error.field}</span>
                      <span>{issueMessage(error)}</span>
                    </li>
                  ))}
                </ul>
                {previewErrors.length > INITIAL_ERRORS && (
                  <Button
                    type="link"
                    size="small"
                    onClick={() => setShowAllErrors((value) => !value)}
                  >
                    {showAllErrors
                      ? t("aidpKnowledge.ontologyImportShowLess")
                      : t("aidpKnowledge.ontologyImportShowAll", {
                          count: previewErrors.length,
                        })}
                  </Button>
                )}
              </div>
            )}
          </div>
        )}

        {result && (
          <div className={styles.result}>
            <dl className={styles.counts}>
              <div>
                <dt>{t("aidpKnowledge.ontologyImportImported")}</dt>
                <dd>{result.imported_count}</dd>
              </div>
              <div>
                <dt>{t("aidpKnowledge.ontologyImportSkipped")}</dt>
                <dd>{result.skipped_count}</dd>
              </div>
              <div>
                <dt>{t("aidpKnowledge.ontologyImportEntityFailed")}</dt>
                <dd>{result.failed_count}</dd>
              </div>
              <div>
                <dt>{t("aidpKnowledge.ontologyImportRelationImported")}</dt>
                <dd>{result.relation_imported}</dd>
              </div>
              <div>
                <dt>{t("aidpKnowledge.ontologyImportRelationFailed")}</dt>
                <dd>{result.relation_failed}</dd>
              </div>
            </dl>
            {resultErrors.length > 0 && (
              <div className={styles.errorList}>
                <Alert
                  type="warning"
                  showIcon
                  message={t("aidpKnowledge.ontologyImportPartial", {
                    count: resultErrors.length,
                  })}
                />
                <ul>
                  {visibleResultErrors.map((error, index) => (
                    <li key={`${error.index}-${error.api_name}-${index}`}>
                      <span className={styles.errorField}>
                        {[error.type, error.api_name]
                          .filter(Boolean)
                          .join(" · ") || "—"}
                      </span>
                      <span>{issueMessage(error)}</span>
                    </li>
                  ))}
                </ul>
                {resultErrors.length > INITIAL_ERRORS && (
                  <Button
                    type="link"
                    size="small"
                    onClick={() => setShowAllErrors((value) => !value)}
                  >
                    {showAllErrors
                      ? t("aidpKnowledge.ontologyImportShowLess")
                      : t("aidpKnowledge.ontologyImportShowAll", {
                          count: resultErrors.length,
                        })}
                  </Button>
                )}
              </div>
            )}
          </div>
        )}

        {serverErrors.length > 0 && (
          <div className={styles.errorList}>
            <Alert
              type="error"
              showIcon
              message={t("aidpKnowledge.ontologyImportValidationFailed")}
            />
            <ul>
              {serverErrors.slice(0, INITIAL_ERRORS).map((error, index) => (
                <li key={`${error.index}-${error.field}-${index}`}>
                  <span className={styles.errorField}>{error.field}</span>
                  <span>{issueMessage(error)}</span>
                </li>
              ))}
            </ul>
          </div>
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

export default AidpOntologyImportDrawer;
