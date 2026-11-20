// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { App, Button, Drawer, Form, Input, Select } from "antd";

import log from "@/lib/logger";
import aidpSensitiveWordService from "@/ext_components/aidp/shared/services/aidpSensitiveWordService";
import type {
  AidpSensitiveWordItem,
  AidpSensitiveWordPayload,
} from "@/ext_components/aidp/shared/types/sensitiveWord";
import { isAidpDuplicateWordError } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import {
  useCreateAidpSensitiveWord,
  useUpdateAidpSensitiveWord,
} from "@/ext_components/aidp/pages/sensitive-words/hooks/useAidpSensitiveWords";
import styles from "./AidpSensitiveWords.module.css";

interface AidpSensitiveWordDrawerProps {
  knowledgeBaseId: string;
  open: boolean;
  editing: AidpSensitiveWordItem | null;
  onClose: () => void;
  onSaved: () => void;
}

/**
 * Add/edit drawer for one custom sensitive word.
 *
 * The edit form re-reads the latest upstream value when it opens so a stale
 * list row can never overwrite a concurrent change. Built-in words never
 * reach this component because the list hides their edit action.
 */
const AidpSensitiveWordDrawer: React.FC<AidpSensitiveWordDrawerProps> = ({
  knowledgeBaseId,
  open,
  editing,
  onClose,
  onSaved,
}) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [form] = Form.useForm<AidpSensitiveWordPayload>();
  const [loadingLatest, setLoadingLatest] = useState(false);
  const createMutation = useCreateAidpSensitiveWord(knowledgeBaseId);
  const updateMutation = useUpdateAidpSensitiveWord(knowledgeBaseId);
  const submitting =
    loadingLatest || createMutation.isPending || updateMutation.isPending;

  const describeError = useCallback(
    (error: unknown, fallback: string) => {
      if (isAidpDuplicateWordError(error))
        return t("aidpSensitiveWords.duplicateWord");
      return error instanceof Error && error.message ? error.message : fallback;
    },
    [t]
  );

  useEffect(() => {
    if (!open) return;
    form.resetFields();
    form.setFieldsValue({ mode: "BLACK", word: "", description: "" });
    if (!editing) return;

    let cancelled = false;
    // Defer the loading flag so the effect synchronizes the external request
    // instead of triggering a cascading render on open.
    const frame = window.requestAnimationFrame(() => {
      if (!cancelled) setLoadingLatest(true);
    });
    aidpSensitiveWordService
      .get(knowledgeBaseId, editing.id)
      .then((latest) => {
        if (cancelled) return;
        form.setFieldsValue({
          word: latest.word,
          mode: latest.mode,
          description: latest.description,
        });
      })
      .catch((error) => {
        if (cancelled) return;
        log.error("Failed to load AIDP sensitive word for editing:", {
          id: editing.id,
          error,
        });
        message.error(
          describeError(error, t("aidpSensitiveWords.loadDetailFailed"))
        );
        onClose();
      })
      .finally(() => {
        if (!cancelled) setLoadingLatest(false);
      });
    return () => {
      cancelled = true;
      window.cancelAnimationFrame(frame);
    };
  }, [
    describeError,
    editing,
    form,
    knowledgeBaseId,
    message,
    onClose,
    open,
    t,
  ]);

  const handleSubmit = async () => {
    if (submitting) return;
    let values: AidpSensitiveWordPayload;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const payload: AidpSensitiveWordPayload = {
      word: values.word.trim(),
      mode: values.mode,
      description: values.description.trim(),
    };
    try {
      if (editing) {
        const updates: Partial<AidpSensitiveWordPayload> = {};
        if (payload.word !== editing.word) updates.word = payload.word;
        if (payload.mode !== editing.mode) updates.mode = payload.mode;
        if (payload.description !== editing.description)
          updates.description = payload.description;
        if (!Object.keys(updates).length) {
          onClose();
          return;
        }
        await updateMutation.mutateAsync({ id: editing.id, payload: updates });
        message.success(t("aidpSensitiveWords.updateSuccess"));
      } else {
        await createMutation.mutateAsync(payload);
        message.success(t("aidpSensitiveWords.createSuccess"));
      }
      onClose();
      onSaved();
    } catch (error) {
      log.error("Failed to save AIDP sensitive word:", {
        id: editing?.id,
        error,
      });
      message.error(describeError(error, t("aidpSensitiveWords.saveFailed")));
    }
  };

  return (
    <Drawer
      title={
        editing
          ? t("aidpSensitiveWords.editTitle")
          : t("aidpSensitiveWords.addTitle")
      }
      placement="right"
      size={480}
      open={open}
      onClose={onClose}
      closable={!submitting}
      maskClosable={!submitting}
      keyboard={!submitting}
      destroyOnHidden
      styles={{ body: { padding: 24 }, footer: { padding: "16px 24px" } }}
      footer={
        <div className={styles.drawerFooter}>
          <Button onClick={onClose} disabled={submitting}>
            {t("common.cancel")}
          </Button>
          <Button
            type="primary"
            loading={submitting}
            onClick={() => void handleSubmit()}
          >
            {t("common.confirm")}
          </Button>
        </div>
      }
    >
      <Form
        form={form}
        layout="vertical"
        className={styles.drawerForm}
        initialValues={{ mode: "BLACK" }}
      >
        <Form.Item
          name="word"
          label={t("aidpSensitiveWords.wordLabel")}
          rules={[
            {
              required: true,
              whitespace: true,
              message: t("aidpSensitiveWords.wordRequired"),
            },
            {
              max: 64,
              message: t("aidpSensitiveWords.wordTooLong"),
            },
          ]}
        >
          <Input
            maxLength={64}
            showCount
            placeholder={t("aidpSensitiveWords.wordPlaceholder")}
          />
        </Form.Item>
        <Form.Item
          name="mode"
          label={t("aidpSensitiveWords.modeLabel")}
          rules={[
            {
              required: true,
              message: t("aidpSensitiveWords.modeRequired"),
            },
          ]}
        >
          <Select
            options={[
              {
                value: "BLACK",
                label: t("aidpSensitiveWords.modeBlack"),
              },
              {
                value: "WHITE",
                label: t("aidpSensitiveWords.modeWhite"),
              },
            ]}
          />
        </Form.Item>
        <Form.Item
          name="description"
          label={t("aidpSensitiveWords.descriptionLabel")}
          rules={[
            {
              required: true,
              whitespace: true,
              message: t("aidpSensitiveWords.descriptionRequired"),
            },
            {
              max: 512,
              message: t("aidpSensitiveWords.descriptionTooLong"),
            },
          ]}
        >
          <Input.TextArea
            rows={5}
            maxLength={512}
            showCount
            placeholder={t("aidpSensitiveWords.descriptionPlaceholder")}
          />
        </Form.Item>
      </Form>
    </Drawer>
  );
};

export default AidpSensitiveWordDrawer;
