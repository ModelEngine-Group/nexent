"use client";

import React from "react";
import { Flex } from "antd";
import UserProfileComp from "./components/UserProfileComp";

/**
 * User Management page - User profile and account settings UI
 *
 * Notes:
 * - The backend APIs may be unavailable during development; the UI uses
 *   hooks/services that provide mock data until real endpoints are wired.
 * - Layout uses Flex for responsive design and proper content flow.
 */
export default function UsersPage() {

  return (
    <>
      <Flex
        vertical
        className="h-full w-full overflow-hidden"
      >
        <UserProfileComp />
      </Flex>
    </>
  );
}
