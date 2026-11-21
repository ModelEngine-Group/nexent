// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Format AIDP audit values, which arrive as ISO strings or Unix seconds/ms. */
const toDate = (value: number): Date | null => {
  if (!Number.isFinite(value)) return null;
  const milliseconds =
    Math.abs(value) < 1_000_000_000_000 ? value * 1000 : value;
  const date = new Date(milliseconds);
  return Number.isNaN(date.getTime()) ? null : date;
};

const pad = (value: number): string => String(value).padStart(2, "0");

export const formatAidpDateTime = (value?: string | number | null): string => {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    const date = toDate(value);
    if (!date) return String(value);
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
      date.getDate()
    )} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }
  const text = String(value).trim();
  if (/^\d{10,13}$/.test(text)) {
    const date = toDate(Number(text));
    if (date) {
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
        date.getDate()
      )} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
    }
  }
  if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(text)) {
    return text.slice(0, 16).replace("T", " ");
  }
  return text || "—";
};

export const formatAidpDate = (value?: string | number | null): string => {
  const formatted = formatAidpDateTime(value);
  return /^\d{4}-\d{2}-\d{2}/.test(formatted)
    ? formatted.slice(0, 10)
    : formatted;
};
