/**
 * Hook for quota warning notifications with role-based visibility.
 *
 * Visibility rules:
 * - SU: tenant-level warnings only (aggregated). No KB warnings.
 * - ADMIN: both tenant-level AND KB-level warnings (KB aggregated).
 * - USER/DEVELOPER: KB-level warnings only for KBs they interact with. No tenant warnings.
 *
 * Notification levels (matches backend warning_level):
 * - warning: orange (warning threshold reached, default 80%)
 * - critical: red (critical threshold reached, default 95%)
 * - exceeded: red (KB soft quota exceeded, using shared pool)
 * - blocked: red (tenant hard limit reached, uploads blocked)
 *
 * Aggregation: when multiple tenants/KBs trigger the same level,
 * shows "<count> tenants/knowledge bases" instead of individual names.
 */
import { useCallback, useRef } from "react";
import { notification } from "antd";
import { useParams, useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import type {
  PlatformQuotaOverview,
  QuotaStatusResponse,
  QuotaUsageResponse,
} from "@/types/quota";

const DISMISS_PREFIX = "quota_warning_dismissed";
const DISMISS_TTL_MS = 24 * 60 * 60 * 1000;

function getDismissKey(scope: string, id: string, level: string): string {
  return `${DISMISS_PREFIX}_${scope}_${id}_${level}`;
}

function isDismissed(key: string): boolean {
  try {
    const stored = localStorage.getItem(key);
    if (!stored) return false;

    const dismissedAt = Number.parseInt(stored, 10);
    if (!Number.isFinite(dismissedAt)) {
      localStorage.removeItem(key);
      return false;
    }

    if (Date.now() - dismissedAt < DISMISS_TTL_MS) return true;
    localStorage.removeItem(key);
    return false;
  } catch {
    return false;
  }
}

function setDismissed(key: string): void {
  try {
    localStorage.setItem(key, Date.now().toString());
  } catch {
    // localStorage may be unavailable in restricted browser contexts.
  }
}

function clearDismissed(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // localStorage may be unavailable in restricted browser contexts.
  }
}

// ── Helpers ────────────────────────────────────────────────────────────

type WarningLevel = "warning" | "critical" | "exceeded" | "blocked";

interface WarningItem {
  id: string;
  scope: "tenant" | "kb";
  level: WarningLevel;
  description: string;
  name: string;
  usagePct: number;
}

type UserRole = "SU" | "ADMIN" | string;

export function useQuotaWarning(userRole?: UserRole, tenantId?: string | null) {
  const { t } = useTranslation("common");
  const router = useRouter();
  const params = useParams();
  const locale = (params as { locale?: string })?.locale || "en";
  const shownRef = useRef<Set<string>>(new Set());
  const notificationKeysByItemRef = useRef<Map<string, Set<string>>>(new Map());
  const activeLevelByItemRef = useRef<Map<string, WarningLevel>>(new Map());
  const programmaticCloseRef = useRef<Set<string>>(new Set());
  const isPlatformAdmin = userRole === "SU" || userRole === "ASSET_OWNER";

  const unregisterNotificationKey = useCallback((notificationKey: string) => {
    for (const [
      itemKey,
      notificationKeys,
    ] of notificationKeysByItemRef.current) {
      notificationKeys.delete(notificationKey);
      if (notificationKeys.size === 0) {
        notificationKeysByItemRef.current.delete(itemKey);
      }
    }
  }, []);

  const clearWarningState = useCallback(
    (scope: "tenant" | "kb", id: string) => {
      for (const level of [
        "warning",
        "critical",
        "exceeded",
        "blocked",
      ] as WarningLevel[]) {
        clearDismissed(getDismissKey(scope, id, level));
      }

      const itemKey = `${scope}:${id}`;
      const notificationKeys = notificationKeysByItemRef.current.get(itemKey);
      if (notificationKeys) {
        for (const notificationKey of [...notificationKeys]) {
          programmaticCloseRef.current.add(notificationKey);
          notification.destroy(notificationKey);
          shownRef.current.delete(notificationKey);
          unregisterNotificationKey(notificationKey);
        }
      }
      notificationKeysByItemRef.current.delete(itemKey);
      activeLevelByItemRef.current.delete(itemKey);
    },
    [unregisterNotificationKey]
  );

  const clearAllActiveNotifications = useCallback(() => {
    for (const itemKey of [...activeLevelByItemRef.current.keys()]) {
      const separatorIndex = itemKey.indexOf(":");
      if (separatorIndex === -1) continue;
      clearWarningState(
        itemKey.slice(0, separatorIndex) as "tenant" | "kb",
        itemKey.slice(separatorIndex + 1)
      );
    }
  }, [clearWarningState]);

  const closeAllActiveNotifications = useCallback(() => {
    const notificationKeys = new Set<string>();
    for (const keys of notificationKeysByItemRef.current.values()) {
      for (const key of keys) notificationKeys.add(key);
    }
    for (const key of notificationKeys) {
      programmaticCloseRef.current.add(key);
      notification.destroy(key);
      shownRef.current.delete(key);
    }
    notificationKeysByItemRef.current.clear();
    activeLevelByItemRef.current.clear();
  }, []);

  const reconcileWarningItems = useCallback(
    (scope: "tenant" | "kb", currentIds: Set<string>) => {
      const prefix = `${scope}:`;
      for (const itemKey of [...activeLevelByItemRef.current.keys()]) {
        if (!itemKey.startsWith(prefix)) continue;
        const id = itemKey.slice(prefix.length);
        if (!currentIds.has(id)) {
          clearWarningState(scope, id);
        }
      }
    },
    [clearWarningState]
  );

  const navigateToQuotaManagement = useCallback(() => {
    // Platform admins allocate quota from the tenant list in resource management.
    // /owner-manage only exposes the asset owner's own resources.
    const targetPath = "/resource-manage";
    router.push(`/${locale}${targetPath}`);
  }, [locale, router]);

  const dismissWarning = useCallback(
    (scope: "tenant" | "kb", id: string, level: WarningLevel) => {
      setDismissed(getDismissKey(scope, id, level));
      const itemKey = `${scope}:${id}`;
      const notificationKeys = notificationKeysByItemRef.current.get(itemKey);
      if (!notificationKeys) return;
      for (const notificationKey of [...notificationKeys]) {
        programmaticCloseRef.current.add(notificationKey);
        notification.destroy(notificationKey);
        shownRef.current.delete(notificationKey);
        unregisterNotificationKey(notificationKey);
      }
    },
    [unregisterNotificationKey]
  );

  /**
   * Build an Ant Design notification config.
   */
  const notify = useCallback(
    (
      level: WarningLevel,
      message: string,
      description: React.ReactNode,
      scope: "tenant" | "kb",
      notificationId: string,
      items: WarningItem[]
    ) => {
      const key = `quota:${scope}:${level}:${notificationId}`;
      if (shownRef.current.has(key)) return;
      shownRef.current.add(key);
      for (const item of items) {
        const itemKey = `${scope}:${item.id}`;
        activeLevelByItemRef.current.set(itemKey, level);
        const notificationKeys =
          notificationKeysByItemRef.current.get(itemKey) || new Set<string>();
        notificationKeys.add(key);
        notificationKeysByItemRef.current.set(itemKey, notificationKeys);
      }

      const config: any = {
        key,
        message,
        description,
        placement: "topRight" as const,
        duration: 0, // stay until dismissed
        onClose: () => {
          shownRef.current.delete(key);
          const wasProgrammatic = programmaticCloseRef.current.delete(key);
          if (!wasProgrammatic) {
            for (const item of items) {
              setDismissed(getDismissKey(scope, item.id, level));
            }
          }
          unregisterNotificationKey(key);
        },
      };

      if (level === "warning") {
        notification.warning(config);
      } else {
        // critical, exceeded, blocked → red
        notification.error(config);
      }
    },
    [unregisterNotificationKey]
  );

  /**
   * Aggregate multiple warnings into a single notification.
   */
  const notifyAggregated = useCallback(
    (scope: "tenant" | "kb", level: WarningLevel, items: WarningItem[]) => {
      for (const item of items) {
        const itemKey = `${scope}:${item.id}`;
        const activeLevel = activeLevelByItemRef.current.get(itemKey);
        if (activeLevel && activeLevel !== level) {
          clearWarningState(scope, item.id);
        }
      }

      const activeItems = items.filter(
        (item) => !isDismissed(getDismissKey(scope, item.id, level))
      );
      if (activeItems.length === 0) return;

      let message: string;
      let description: React.ReactNode;

      if (activeItems.length === 1) {
        const item = activeItems[0];
        message = t(`quota.warning.${scope}.title.${level}`);
        description = (
          <div>
            <p>{item.description}</p>
            {scope === "tenant" && (
              <a
                onClick={navigateToQuotaManagement}
                style={{ cursor: "pointer" }}
              >
                {t("quota.warning.manageTenant")}
              </a>
            )}
            {scope === "kb" && userRole === "ADMIN" && (
              <a
                onClick={navigateToQuotaManagement}
                style={{ cursor: "pointer" }}
              >
                {t("quota.warning.manageKb")}
              </a>
            )}
          </div>
        );
      } else {
        message = t(`quota.warning.${scope}.multipleTitle.${level}`, {
          count: activeItems.length,
        });
        description = (
          <div>
            <p>
              {t(`quota.warning.${scope}.multipleDescription.${level}`, {
                count: activeItems.length,
              })}
            </p>
            {(scope === "tenant" || userRole === "ADMIN") && (
              <a
                onClick={navigateToQuotaManagement}
                style={{ cursor: "pointer" }}
              >
                {scope === "tenant"
                  ? t("quota.warning.manageTenant")
                  : t("quota.warning.manageKb")}
              </a>
            )}
          </div>
        );
      }

      const notificationId = activeItems
        .map((item) => item.id)
        .sort()
        .join("|");
      notify(level, message, description, scope, notificationId, activeItems);
    },
    [clearWarningState, navigateToQuotaManagement, notify, t, userRole]
  );

  /**
   * Process dual-level quota status from upload response.
   */
  const processUploadQuotaStatus = useCallback(
    (
      quotaStatus: QuotaStatusResponse | undefined,
      kbName?: string,
      kbId?: string
    ) => {
      if (!quotaStatus) return;
      if (quotaStatus.warning_enabled === false) {
        clearAllActiveNotifications();
        return;
      }

      const { kb_level, tenant_level } = quotaStatus;

      // ── KB-level warnings ──────────────────────────────────────────
      // SU should NOT see KB warnings
      if (kb_level && kbId && !isPlatformAdmin) {
        const kbNameDisplay = kbName || kbId;
        if (kb_level.warning_level === "warning") {
          notifyAggregated("kb", "warning", [
            {
              id: kbId,
              scope: "kb",
              level: "warning",
              description: t("quota.warning.kb.approaching", {
                name: kbNameDisplay,
                usagePct: kb_level.usage_pct ?? 0,
              }),
              name: kbNameDisplay,
              usagePct: kb_level.usage_pct ?? 0,
            },
          ]);
        } else if (kb_level.warning_level === "critical") {
          notifyAggregated("kb", "critical", [
            {
              id: kbId,
              scope: "kb",
              level: "critical",
              description: t("quota.warning.kb.criticalDescription", {
                name: kbNameDisplay,
                usagePct: kb_level.usage_pct ?? 0,
              }),
              name: kbNameDisplay,
              usagePct: kb_level.usage_pct ?? 0,
            },
          ]);
        } else if (kb_level.warning_level === "exceeded") {
          notifyAggregated("kb", "exceeded", [
            {
              id: kbId,
              scope: "kb",
              level: "exceeded",
              description: t("quota.warning.kb.exceededDescription", {
                name: kbNameDisplay,
              }),
              name: kbNameDisplay,
              usagePct: kb_level.usage_pct ?? 0,
            },
          ]);
        } else {
          clearWarningState("kb", kbId);
        }
      }

      // ── Tenant-level warnings ──────────────────────────────────────
      // Developer/USER should NOT see tenant warnings
      if (tenant_level && (isPlatformAdmin || userRole === "ADMIN")) {
        if (tenant_level.warning_level === "warning") {
          notifyAggregated("tenant", "warning", [
            {
              id: tenantId || "tenant",
              scope: "tenant",
              level: "warning",
              description: t("quota.warning.tenant.usageDescription", {
                usagePct: tenant_level.usage_pct ?? 0,
                used: tenant_level.total_readable || "-",
                limit: tenant_level.hard_limit_readable || "-",
              }),
              name: "Tenant",
              usagePct: tenant_level.usage_pct ?? 0,
            },
          ]);
        } else if (tenant_level.warning_level === "critical") {
          notifyAggregated("tenant", "critical", [
            {
              id: tenantId || "tenant",
              scope: "tenant",
              level: "critical",
              description: t("quota.warning.tenant.criticalDescription", {
                usagePct: tenant_level.usage_pct ?? 0,
              }),
              name: "Tenant",
              usagePct: tenant_level.usage_pct ?? 0,
            },
          ]);
        } else {
          clearWarningState("tenant", tenantId || "tenant");
        }
      }
    },
    [
      clearAllActiveNotifications,
      clearWarningState,
      isPlatformAdmin,
      notifyAggregated,
      t,
      tenantId,
      userRole,
    ]
  );

  /**
   * Process quota usage response for tenant-level and per-KB warnings.
   */
  const processUsageQuotaStatus = useCallback(
    (usageData: QuotaUsageResponse | undefined) => {
      if (!usageData) return;
      if (!usageData.warning_enabled) {
        clearAllActiveNotifications();
        return;
      }

      // ── Tenant-level ───────────────────────────────────────────────
      // Only SU and ADMIN see tenant warnings
      if (isPlatformAdmin || userRole === "ADMIN") {
        const level = usageData.tenant_warning_level as
          | WarningLevel
          | undefined;
        if (level && (level as string) !== "normal") {
          const desc =
            level === "blocked"
              ? t("quota.warning.tenant.blockedDescription")
              : t("quota.warning.tenant.usageDescription", {
                  usagePct: usageData.usage_pct ?? 0,
                  used: usageData.total_readable || "-",
                  limit: usageData.hard_limit_readable || "-",
                });

          notifyAggregated("tenant", level, [
            {
              id: tenantId || "tenant",
              scope: "tenant",
              level,
              description: desc,
              name: "Tenant",
              usagePct: usageData.usage_pct ?? 0,
            },
          ]);
        } else {
          clearWarningState("tenant", tenantId || "tenant");
        }
      }

      // ── Per-KB breakdown ───────────────────────────────────────────
      // SU should NOT see KB warnings; others see filtered list
      if (!isPlatformAdmin && usageData.breakdown) {
        const kbWarningItems: WarningItem[] = [];
        const kbCriticalItems: WarningItem[] = [];
        const kbExceededItems: WarningItem[] = [];
        const currentKbIds = new Set<string>();

        for (const kb of usageData.breakdown) {
          const kbId = kb.index_name || String(kb.knowledge_id);
          currentKbIds.add(kbId);
          if (kb.kb_warning_level === "warning") {
            kbWarningItems.push({
              id: kbId,
              scope: "kb",
              level: "warning",
              description: t("quota.warning.kb.usageDescription", {
                name: kb.knowledge_name,
                used: kb.actual_readable || "-",
                limit: kb.soft_quota_readable || "-",
                usagePct: kb.usage_pct ?? 0,
              }),
              name: kb.knowledge_name,
              usagePct: kb.usage_pct ?? 0,
            });
          } else if (kb.kb_warning_level === "critical") {
            kbCriticalItems.push({
              id: kbId,
              scope: "kb",
              level: "critical",
              description: t("quota.warning.kb.criticalUsageDescription", {
                name: kb.knowledge_name,
                used: kb.actual_readable || "-",
                limit: kb.soft_quota_readable || "-",
                usagePct: kb.usage_pct ?? 0,
              }),
              name: kb.knowledge_name,
              usagePct: kb.usage_pct ?? 0,
            });
          } else if (kb.kb_warning_level === "exceeded") {
            kbExceededItems.push({
              id: kbId,
              scope: "kb",
              level: "exceeded",
              description: t("quota.warning.kb.exceededUsageDescription", {
                name: kb.knowledge_name,
                used: kb.actual_readable || "-",
                limit: kb.soft_quota_readable || "-",
              }),
              name: kb.knowledge_name,
              usagePct: kb.usage_pct ?? 0,
            });
          } else {
            clearWarningState("kb", kbId);
          }
        }

        reconcileWarningItems("kb", currentKbIds);
        notifyAggregated("kb", "warning", kbWarningItems);
        notifyAggregated("kb", "critical", kbCriticalItems);
        notifyAggregated("kb", "exceeded", kbExceededItems);
      }
    },
    [
      clearAllActiveNotifications,
      clearWarningState,
      isPlatformAdmin,
      notifyAggregated,
      reconcileWarningItems,
      t,
      tenantId,
      userRole,
    ]
  );

  const processPlatformQuotaStatus = useCallback(
    (overview: PlatformQuotaOverview | undefined) => {
      if (!overview || !isPlatformAdmin) return;

      const warningItems: WarningItem[] = [];
      const criticalItems: WarningItem[] = [];
      const blockedItems: WarningItem[] = [];
      const currentTenantIds = new Set<string>();
      for (const tenant of overview.tenants) {
        currentTenantIds.add(tenant.tenant_id);
        if (tenant.warning_level === "normal") {
          clearWarningState("tenant", tenant.tenant_id);
          continue;
        }
        const item: WarningItem = {
          id: tenant.tenant_id,
          scope: "tenant",
          level: tenant.warning_level,
          description: t("quota.warning.tenant.platformDescription", {
            name: tenant.tenant_name,
            usagePct: tenant.usage_pct ?? 0,
          }),
          name: tenant.tenant_name,
          usagePct: tenant.usage_pct ?? 0,
        };
        if (tenant.warning_level === "warning") {
          warningItems.push(item);
        } else if (tenant.warning_level === "critical") {
          criticalItems.push(item);
        } else {
          blockedItems.push(item);
        }
      }

      reconcileWarningItems("tenant", currentTenantIds);
      notifyAggregated("tenant", "warning", warningItems);
      notifyAggregated("tenant", "critical", criticalItems);
      notifyAggregated("tenant", "blocked", blockedItems);
    },
    [
      clearWarningState,
      isPlatformAdmin,
      notifyAggregated,
      reconcileWarningItems,
      t,
    ]
  );

  return {
    closeAllActiveNotifications,
    dismissWarning,
    processPlatformQuotaStatus,
    processUploadQuotaStatus,
    processUsageQuotaStatus,
  };
}
