// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import React from "react";
import { Flex } from "antd";
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
      <Flex vertical className="h-full w-full overflow-hidden">
        <UserManageComp />
      </Flex>
    </>
  );
}
