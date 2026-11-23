"use client";

import { useEffect, useMemo, useState } from "react";
import { App, Checkbox, Input, Modal } from "antd";
import { useTranslation } from "react-i18next";
import { McpTransportType } from "@/const/mcpTools";

import type { MineMcpCardItem } from "./MineMcpServiceCard";

interface MineApplyListingModalProps {
  open: boolean;
  item: MineMcpCardItem | null;
  loading?: boolean;
  onClose: () => void;
  onConfirm: (
    content?: string,
    sharedFields?: Record<string, boolean>
  ) => Promise<void>;
}

export default function MineApplyListingModal({
  open,
  item,
  loading = false,
  onClose,
  onConfirm,
}: MineApplyListingModalProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [listingContent, setListingContent] = useState("");
  const [sharedFields, setSharedFields] = useState<Record<string, boolean>>({});
  const [submitting, setSubmitting] = useState(false);

  const shareOptions = useMemo(() => {
    if (!item) return [];
    const service = item.service;
    if (service.transportType === McpTransportType.CONTAINER) {
      return service.configJson
        ? [
            {
              key: "containerConfigJson",
              label: t("mcpTools.detail.containerConfig"),
            },
          ]
        : [];
    }
    return [
      service.serverUrl
        ? { key: "serverUrl", label: t("mcpTools.detail.serverUrl") }
        : null,
      service.authorizationToken
        ? {
            key: "authorizationToken",
            label: t("mcpConfig.editServer.authorizationToken"),
          }
        : null,
      service.customHeaders && Object.keys(service.customHeaders).length > 0
        ? { key: "customHeaders", label: t("mcpTools.detail.customHeaders") }
        : null,
    ].filter(
      (option): option is { key: string; label: string } => option !== null
    );
  }, [item, t]);

  useEffect(() => {
    if (!open) {
      setListingContent("");
      setSharedFields({});
      setSubmitting(false);
      return;
    }
    setSharedFields(item?.service.sharedFields ?? {});
  }, [item, open]);

  if (!item) {
    return null;
  }

  const title = item.service.name?.trim() || "-";
  const isBusy = loading || submitting;

  const handleOk = async () => {
    if (!Object.values(sharedFields).some(Boolean)) {
      message.warning(t("mcpTools.mine.sharedFieldsRequired"));
      return;
    }
    setSubmitting(true);
    try {
      await onConfirm(listingContent.trim() || undefined, sharedFields);
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title={t("repository.mine.applyForListing")}
      onCancel={onClose}
      onOk={handleOk}
      okText={t("repository.mine.applyForListing")}
      cancelText={t("common.cancel")}
      confirmLoading={isBusy}
      centered
      destroyOnHidden
    >
      <div className="space-y-4">
        <p className="text-sm text-slate-600 dark:text-slate-300">
          {t("repository.mine.confirmApplyTitle", { name: title })}
        </p>
        <div className="space-y-2">
          <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
            {t("repository.mine.applyModal.sharedFields")}
          </p>
          <div className="flex flex-col gap-2 rounded-md border border-slate-200 p-3 dark:border-slate-700">
            {shareOptions.map((option) => (
              <Checkbox
                key={option.key}
                checked={sharedFields[option.key] ?? false}
                disabled={isBusy}
                onChange={(event) => {
                  setSharedFields((previous) => ({
                    ...previous,
                    [option.key]: event.target.checked,
                  }));
                }}
              >
                {option.label}
              </Checkbox>
            ))}
          </div>
        </div>
        <div className="space-y-2">
          <label
            htmlFor="mcp-repository-listing-note"
            className="block text-sm font-medium text-slate-700 dark:text-slate-200"
          >
            {t("repository.mine.applyModal.content")}
          </label>
          <Input.TextArea
            id="mcp-repository-listing-note"
            value={listingContent}
            onChange={(event) => setListingContent(event.target.value)}
            placeholder={t("repository.mine.applyModal.contentPlaceholder")}
            rows={4}
            disabled={isBusy}
          />
        </div>
      </div>
    </Modal>
  );
}
