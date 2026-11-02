// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { publicAsset } from "@/lib/publicAsset";

export function getBrowserTabTitle(config: Record<string, string>): string {
  return config.productName?.trim() || "";
}

export function getBrowserTabLogo(): string {
  return publicAsset("/modelengine-logo.png");
}

export function getHomeTitle(config: Record<string, string>): string {
  return (config.homeTitle ?? config.tabTitle ?? "").trim();
}

export function getHomeLogo(config: Record<string, string>): string {
  const logo = config.homeLogo ?? config.tabLogo;
  return publicAsset(
    logo &&
      /^(home-logo|browser-tab-logo)\.(png|jpg)(\?v=[a-f0-9]+)?$/.test(logo)
      ? `/${logo}`
      : "/modelengine-logo.png"
  );
}
