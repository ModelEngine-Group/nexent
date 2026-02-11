"use client";

import React from "react";
import { Flex } from "antd";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import UserManageComp from "./components/UserManageComp";

/**
 * Tenant Resources page - tenant-scoped resource management UI
 *
 * Notes:
 * - The backend APIs may be unavailable during development; the UI uses
 *   hooks/services that provide mock data until real endpoints are wired.
 * - Layout uses Flex for responsive design and proper content flow.
 */
export default function TenantResourcesPage() {

  return (
    <>
      <Flex
        vertical
        style={{ width: "100%", height: "100%" }}
        className="h-full w-full overflow-hidden"
      >
        <UserManageComp />
      </Flex>
    </>
  );
}
