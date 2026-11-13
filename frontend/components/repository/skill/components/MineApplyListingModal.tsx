// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useRef, useState } from "react";
import { Alert, Button, Input } from "antd";
import { useTranslation } from "react-i18next";
import { Modal } from "antd";

import type {
  MyEditableSkillItem,
  SkillRepositoryListingCreatePayload,
} from "@/types/skillRepository";

interface MineApplyListingModalProps {
  open: boolean;
  skill: MyEditableSkillItem | null;
  loading?: boolean;
  onClose: () => void;
  onConfirm: (payload: SkillRepositoryListingCreatePayload) => Promise<void>;
}

export function MineApplyListingModal({
  open,
  skill,
  loading = false,
  onClose,
  onConfirm,
}: MineApplyListingModalProps) {
  const { t } = useTranslation("common");
  const [listingContent, setListingContent] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(false);
  const submittingRef = useRef(false);

  useEffect(() => {
    if (!open) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Preserve the existing modal reset when its external open state changes.
      setListingContent("");
      setSubmitError(false);
      setSubmitting(false);
      submittingRef.current = false;
    }
  }, [open]);

  if (!skill) {
    return null;
  }

  const title = skill.name?.trim() || t("skillRepository.common.untitled");
  const isBusy = loading || submitting;

  const handleOk = async () => {
    if (submittingRef.current || loading || listingContent.length > 1000) {
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    setSubmitError(false);
    try {
      await onConfirm({
        icon: "skill",
        tags: skill.tags ?? [],
        content: listingContent.trim() || undefined,
      });
      onClose();
    } catch {
      setSubmitError(true);
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <Modal
      centered
      open={open}
      closable={{ "aria-label": t("common.close") }}
      width={760}
      title={t("skillRepository.mine.applyTitle", { name: title })}
      onCancel={() => {
        if (!isBusy) onClose();
      }}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      footer={
        <div className="flex justify-end gap-2">
          <Button disabled={isBusy} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            type="primary"
            loading={isBusy}
            disabled={isBusy || listingContent.length > 1000}
            onClick={handleOk}
          >
            {t("common.confirm")}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <p className="text-sm leading-[22px] text-[#191919]">
          {t("skillRepository.mine.confirmApplyContent")}
        </p>
        <div className="space-y-2">
          <label
            htmlFor="skill-repository-listing-note"
            className="block text-sm font-normal leading-[22px] text-[#191919]"
          >
            {t("repository.mine.applyModal.content")}
          </label>
          <Input.TextArea
            id="skill-repository-listing-note"
            value={listingContent}
            onChange={(event) => {
              setListingContent(event.target.value);
              setSubmitError(false);
            }}
            placeholder={t("skillRepository.mine.applyNotePlaceholder")}
            rows={4}
            maxLength={1000}
            showCount
            className="!rounded !border-[#C9C9C9] text-sm"
            disabled={isBusy}
          />
        </div>
        {submitError && (
          <Alert
            type="error"
            showIcon
            title={t("repository.mine.applyError")}
          />
        )}
      </div>
    </Modal>
  );
}
