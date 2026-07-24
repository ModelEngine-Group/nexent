/**
 * Deep-link helpers for in-app notifications.
 */

import type { NotificationDetails, NotificationItem } from "@/types/notification";
import {
  NOTIFICATION_EVENT_TYPES,
  NOTIFICATION_RESOURCE_TYPES,
} from "@/types/notification";

function asPositiveInt(value: unknown): number | null {
  if (typeof value === "number" && Number.isInteger(value) && value > 0) {
    return value;
  }
  if (typeof value === "string" && /^\d+$/.test(value)) {
    const parsed = Number.parseInt(value, 10);
    return parsed > 0 ? parsed : null;
  }
  return null;
}

export function extractReviewDeepLinkIds(
  details: NotificationDetails | Record<string, unknown> | null | undefined
): { agentRepositoryId: number; agentId: number } | null {
  if (!details) {
    return null;
  }
  const agentRepositoryId = asPositiveInt(details.agent_repository_id);
  const agentId = asPositiveInt(details.agent_id);
  if (agentRepositoryId == null || agentId == null) {
    return null;
  }
  return { agentRepositoryId, agentId };
}

export function extractSkillReviewDeepLinkIds(
  details: NotificationDetails | Record<string, unknown> | null | undefined
): { skillRepositoryId: number; skillId: number } | null {
  if (!details) {
    return null;
  }
  const skillRepositoryId = asPositiveInt(details.skill_repository_id);
  const skillId = asPositiveInt(details.skill_id);
  if (skillRepositoryId == null || skillId == null) {
    return null;
  }
  return { skillRepositoryId, skillId };
}

function isReviewResultEvent(eventType: string): boolean {
  return (
    eventType === NOTIFICATION_EVENT_TYPES.REPOSITORY_REVIEW_APPROVED ||
    eventType === NOTIFICATION_EVENT_TYPES.REPOSITORY_REVIEW_REJECTED
  );
}

export function isAgentRepositoryReviewResultNotification(
  item: Pick<NotificationItem, "event_type" | "resource_type" | "details">
): boolean {
  if (item.resource_type !== NOTIFICATION_RESOURCE_TYPES.AGENT_REPOSITORY) {
    return false;
  }

  if (item.event_type === NOTIFICATION_EVENT_TYPES.REPOSITORY_REVIEW_PENDING) {
    return true;
  }

  if (!isReviewResultEvent(item.event_type)) {
    return false;
  }
  return extractReviewDeepLinkIds(item.details) != null;
}

export function isSkillRepositoryReviewResultNotification(
  item: Pick<NotificationItem, "event_type" | "resource_type" | "details">
): boolean {
  if (item.resource_type !== NOTIFICATION_RESOURCE_TYPES.SKILL_REPOSITORY) {
    return false;
  }

  if (item.event_type === NOTIFICATION_EVENT_TYPES.REPOSITORY_REVIEW_PENDING) {
    return true;
  }

  if (!isReviewResultEvent(item.event_type)) {
    return false;
  }
  return extractSkillReviewDeepLinkIds(item.details) != null;
}

export function isRepositoryReviewNotification(
  item: Pick<NotificationItem, "event_type" | "resource_type" | "details">
): boolean {
  return (
    isAgentRepositoryReviewResultNotification(item) ||
    isSkillRepositoryReviewResultNotification(item)
  );
}

export function buildAgentRepositoryReviewDeepLink(
  locale: string,
  details: NotificationDetails | Record<string, unknown> | null | undefined,
  eventType?: string
): string | null {
  if (eventType === NOTIFICATION_EVENT_TYPES.REPOSITORY_REVIEW_PENDING) {
    return `/${locale}/agent-space?tab=review`;
  }

  const ids = extractReviewDeepLinkIds(details);
  if (!ids) {
    return null;
  }
  const params = new URLSearchParams({
    tab: "mine",
    agent_repository_id: String(ids.agentRepositoryId),
    agent_id: String(ids.agentId),
  });
  return `/${locale}/agent-space?${params.toString()}`;
}

export function buildSkillRepositoryReviewDeepLink(
  locale: string,
  details: NotificationDetails | Record<string, unknown> | null | undefined,
  eventType?: string
): string | null {
  if (eventType === NOTIFICATION_EVENT_TYPES.REPOSITORY_REVIEW_PENDING) {
    return `/${locale}/skill-space?tab=review`;
  }

  const ids = extractSkillReviewDeepLinkIds(details);
  if (!ids) {
    return null;
  }
  const params = new URLSearchParams({
    tab: "mine",
    skill_repository_id: String(ids.skillRepositoryId),
    skill_id: String(ids.skillId),
  });
  return `/${locale}/skill-space?${params.toString()}`;
}

export function buildRepositoryReviewDeepLink(
  locale: string,
  item: Pick<NotificationItem, "event_type" | "resource_type" | "details">
): string | null {
  if (item.resource_type === NOTIFICATION_RESOURCE_TYPES.SKILL_REPOSITORY) {
    return buildSkillRepositoryReviewDeepLink(
      locale,
      item.details,
      item.event_type
    );
  }
  if (item.resource_type === NOTIFICATION_RESOURCE_TYPES.AGENT_REPOSITORY) {
    return buildAgentRepositoryReviewDeepLink(
      locale,
      item.details,
      item.event_type
    );
  }
  return null;
}

export function parseReviewDeepLinkParams(searchParams: URLSearchParams): {
  agentRepositoryId: number;
  agentId: number;
} | null {
  const agentRepositoryId = asPositiveInt(searchParams.get("agent_repository_id"));
  const agentId = asPositiveInt(searchParams.get("agent_id"));
  if (agentRepositoryId == null || agentId == null) {
    return null;
  }
  return { agentRepositoryId, agentId };
}

export function parseSkillReviewDeepLinkParams(searchParams: URLSearchParams): {
  skillRepositoryId: number;
  skillId: number;
} | null {
  const skillRepositoryId = asPositiveInt(
    searchParams.get("skill_repository_id")
  );
  const skillId = asPositiveInt(searchParams.get("skill_id"));
  if (skillRepositoryId == null || skillId == null) {
    return null;
  }
  return { skillRepositoryId, skillId };
}
