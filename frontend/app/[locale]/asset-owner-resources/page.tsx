"use client";

import React from "react";
import { Flex } from "antd";

import AssetOwnerResourcesComp from "../tenant-resources/components/AssetOwnerResourcesComp";

export default function AssetOwnerResourcesPage() {
  return (
    <Flex
      vertical
      style={{ width: "100%", height: "100%" }}
      className="h-full w-full overflow-hidden"
    >
      <AssetOwnerResourcesComp />
    </Flex>
  );
}
