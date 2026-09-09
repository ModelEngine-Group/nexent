import assert from "node:assert/strict";
import test from "node:test";

import {
  formatMessageDate,
  formatMessageTime,
  shouldShowDateSeparator,
  toMessageCreatedAt,
  // @ts-ignore -- Node's built-in TypeScript runner needs the extension.
} from "../lib/messageDate.ts";

test("converts a persisted millisecond timestamp to a Date", () => {
  const createdAt = toMessageCreatedAt(1_780_000_000_123);

  assert.ok(createdAt instanceof Date);
  assert.equal(createdAt.getTime(), 1_780_000_000_123);
});

test("does not invent a message time when the database value is missing or invalid", () => {
  assert.equal(toMessageCreatedAt(null), undefined);
  assert.equal(toMessageCreatedAt(undefined), undefined);
  assert.equal(toMessageCreatedAt(Number.NaN), undefined);
  assert.equal(toMessageCreatedAt(0), undefined);
});

test("formats message time as local HH:mm", () => {
  const localTime = new Date(2026, 7, 21, 9, 5, 30);

  assert.equal(formatMessageTime(localTime), "09:05");
});

test("shows a date separator for the first timestamped message and across local days", () => {
  const first = new Date(2026, 7, 21, 23, 59);
  const sameDay = new Date(2026, 7, 21, 23, 59, 30);
  const nextDay = new Date(2026, 7, 22, 0, 1);

  assert.equal(shouldShowDateSeparator(first, undefined), true);
  assert.equal(shouldShowDateSeparator(sameDay, first), false);
  assert.equal(shouldShowDateSeparator(nextDay, sameDay), true);
  assert.equal(shouldShowDateSeparator(undefined, sameDay), false);
});

test("formats the separator date using the requested locale", () => {
  const localDate = new Date(2026, 7, 21, 9, 5);

  assert.match(formatMessageDate(localDate, "zh-CN") ?? "", /2026.*8.*21/);
  assert.match(formatMessageDate(localDate, "en-US") ?? "", /August.*21.*2026/);
});
