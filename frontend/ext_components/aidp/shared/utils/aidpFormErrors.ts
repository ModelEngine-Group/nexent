// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { FormInstance } from "antd";

export interface AidpFormErrorField {
  name: (string | number)[];
}

/** Read antd validation fields from an unknown rejected value. */
export const getAidpFormErrorFields = (
  error: unknown
): AidpFormErrorField[] => {
  if (typeof error !== "object" || error === null || !("errorFields" in error)) {
    return [];
  }
  const fields = (error as { errorFields?: AidpFormErrorField[] }).errorFields;
  return Array.isArray(fields) ? fields : [];
};

/**
 * Scroll to the first invalid antd field. Returns false when the rejection is
 * not a validation error, so callers can keep their normal error handling.
 */
export const scrollToFirstAidpFormError = (
  form: FormInstance,
  error: unknown,
  options: { defer?: boolean } = {}
): boolean => {
  const first = getAidpFormErrorFields(error)[0];
  if (!first) return false;
  const scroll = () => form.scrollToField(first.name, { focus: true });
  if (options.defer) {
    window.requestAnimationFrame(scroll);
  } else {
    scroll();
  }
  return true;
};
