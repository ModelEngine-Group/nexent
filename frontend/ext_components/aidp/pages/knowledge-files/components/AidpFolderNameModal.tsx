// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Input, Modal } from "antd";

interface AidpFolderNameModalProps {
  open: boolean;
  title: string;
  label: string;
  initialValue?: string;
  placeholder?: string;
  /** Fixed, read-only text shown after the editable value (e.g. ".pdf"). */
  suffix?: string;
  confirmLoading?: boolean;
  /** Server-side validation error, e.g. a duplicate folder name. */
  errorMessage?: string | null;
  onCancel: () => void;
  onSubmit: (name: string) => void;
}

/** Shared create/rename dialog for one folder name. */
const AidpFolderNameModal: React.FC<AidpFolderNameModalProps> = ({
  open,
  title,
  label,
  initialValue = "",
  placeholder,
  suffix,
  confirmLoading = false,
  errorMessage,
  onCancel,
  onSubmit,
}) => {
  const { t } = useTranslation();
  const [value, setValue] = useState(initialValue);
  const [error, setError] = useState<string | null>(null);
  const displayedError = error || errorMessage;

  useEffect(() => {
    if (open) {
      /* eslint-disable react-hooks/set-state-in-effect -- Opening the dialog must start from the caller's value, not a previous edit. */
      setValue(initialValue);
      setError(null);
      /* eslint-enable react-hooks/set-state-in-effect */
    }
  }, [initialValue, open]);

  const submit = () => {
    const name = value.trim();
    if (!name) {
      setError(t("aidpKnowledge.folderNameRequired"));
      return;
    }
    if (name === "." || name === ".." || /[/\\]/.test(name)) {
      setError(t("aidpKnowledge.folderNameInvalid"));
      return;
    }
    setError(null);
    onSubmit(name);
  };

  return (
    <Modal
      open={open}
      title={title}
      centered
      width={420}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      confirmLoading={confirmLoading}
      onCancel={onCancel}
      onOk={submit}
      destroyOnHidden
    >
      <div className="flex flex-col gap-1">
        <label className="text-sm text-gray-700" htmlFor="aidp-folder-name">
          {label}
        </label>
        <Input
          id="aidp-folder-name"
          autoFocus
          maxLength={255}
          value={value}
          placeholder={placeholder}
          suffix={
            suffix ? <span className="text-gray-400">{suffix}</span> : undefined
          }
          status={displayedError ? "error" : undefined}
          onChange={(event) => {
            setValue(event.target.value);
            if (error) setError(null);
          }}
          onPressEnter={submit}
        />
        {displayedError && (
          <div className="text-xs text-red-500">{displayedError}</div>
        )}
      </div>
    </Modal>
  );
};

export default AidpFolderNameModal;
