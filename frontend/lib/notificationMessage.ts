/**
 * Format in-app notification messages from event_type + details via i18n.
 */

import type { TFunction } from "i18next";

import type { NotificationItem } from "@/types/notification";

const EVENT_MESSAGE_KEYS: Record<string, string> = {
  repository_review_approved: "notifications.events.repository_review_approved",
  repository_review_rejected: "notifications.events.repository_review_rejected",
  repository_review_pending: "notifications.events.repository_review_pending",
};

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

/**
 * Resolve a localized notification message from event_type and details.
 */
export function formatNotificationMessage(
  item: Pick<NotificationItem, "event_type" | "details">,
  t: TFunction
): string {
  const details = item.details ?? {};
  const name = asString(details.name) ?? "";
  const content = asString(details.content);
  const contentSuffix = content
    ? t("notifications.events.contentSuffix", { content })
    : "";

  const messageKey = EVENT_MESSAGE_KEYS[item.event_type];
  if (messageKey) {
    return t(messageKey, { name, contentSuffix, content: content ?? "" });
  }

  return name;
}
