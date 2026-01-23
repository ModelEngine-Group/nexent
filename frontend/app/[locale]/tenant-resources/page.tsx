"use client";

import React from "react";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import UserManageComp from "./components/UserManageComp";

/**
 * Tenant Resources page - tenant-scoped resource management UI
 *
 * Notes:
 * - The backend APIs may be unavailable during development; the UI uses
 *   hooks/services that provide mock data until real endpoints are wired.
 * - Layout follows the tenant-resource pattern used by the `agents` pages.
 */
export default function TenantResourcesPage() {
  const { canAccessProtectedData } = useSetupFlow({
    requireAdmin: true,
  });

  if (!canAccessProtectedData) {
    return null;
  }

  return <UserManageComp />;
}
