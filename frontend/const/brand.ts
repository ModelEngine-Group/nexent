// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ConfigProviderProps, ThemeConfig } from "antd";

// Approved Light palette from xyq/update_skills (45cd133de).
export const BRAND_PALETTE = {
  "05": "#E6F2FD",
  "10": "#B8D9F9",
  "20": "#8ABEF3",
  "30": "#5CA2E9",
  "40": "#2E86DE",
  "50": "#0067D1",
  "60": "#004EA8",
  "70": "#003D83",
  "80": "#002E6A",
  "90": "#00214B",
} as const;

export const BRAND = {
  primary: BRAND_PALETTE["50"],
  hover: BRAND_PALETTE["40"],
  active: BRAND_PALETTE["60"],
  disabled: BRAND_PALETTE["20"],
  selection: BRAND_PALETTE["05"],
  border: "#C9C9C9",
  text: "#191919",
  radius: 4,
} as const;

// Generate custom-control variables from the same source as the AntD tokens.
// Dark currently inherits this palette; no independent Dark brand scale is approved.
export const BRAND_CSS = `:root {
${Object.entries(BRAND_PALETTE)
  .map(([shade, color]) => `--palette-brand-${shade}: ${color};`)
  .join("\n")}
--color-brand: ${BRAND.primary};
--color-brand-hover: ${BRAND.hover};
--color-brand-active: ${BRAND.active};
--color-brand-disabled: ${BRAND.disabled};
--color-select: ${BRAND.selection};
--color-brand-border: ${BRAND.border};
--color-brand-text: ${BRAND.text};
--radius-control: ${BRAND.radius}px;
}`;

export const NEXENT_THEME: ThemeConfig = {
  token: {
    colorPrimary: BRAND.primary,
    colorPrimaryHover: BRAND.hover,
    colorPrimaryActive: BRAND.active,
    colorPrimaryBg: BRAND.selection,
    colorPrimaryBgHover: BRAND_PALETTE["10"],
    colorPrimaryBorder: BRAND_PALETTE["20"],
    colorPrimaryBorderHover: BRAND_PALETTE["30"],
    colorPrimaryText: BRAND.primary,
    colorPrimaryTextHover: BRAND.hover,
    colorPrimaryTextActive: BRAND.active,
    colorInfo: BRAND.primary,
    colorInfoBg: BRAND.selection,
    colorLink: BRAND.primary,
    colorLinkHover: BRAND.hover,
    colorLinkActive: BRAND.active,
    colorBorder: BRAND.border,
    colorText: BRAND.text,
    borderRadius: BRAND.radius,
    controlHeight: 32,
    fontSize: 14,
    lineHeight: 22 / 14,
  },
  components: {
    Button: {
      paddingInline: 16,
      primaryShadow: "none",
      defaultShadow: "none",
      dangerShadow: "none",
    },
    Input: { controlHeight: 28 },
    Card: { borderRadiusLG: 8 },
    Table: {
      headerBorderRadius: BRAND.radius,
      headerSplitColor: "transparent",
      headerBg: "#F7F9FC",
      headerColor: "#475569",
      borderColor: "#EEF1F5",
      rowHoverBg: BRAND.selection,
      rowSelectedBg: BRAND.selection,
      rowSelectedHoverBg: BRAND_PALETTE["10"],
      cellFontSizeSM: 14,
      cellPaddingBlockSM: 12,
      cellPaddingInlineSM: 16,
    },
  },
};

/** Native component defaults; no compatibility Button wrapper is needed. */
export const NEXENT_BUTTON_DEFAULTS: ConfigProviderProps["button"] = {
  autoInsertSpace: false,
  styles: ({ props }) => ({
    root: {
      letterSpacing: 0,
      ...(props.disabled &&
      props.type === "primary" &&
      !props.danger &&
      !props.ghost
        ? {
            backgroundColor: BRAND.disabled,
            borderColor: BRAND.disabled,
            color: "#FFFFFF",
          }
        : {}),
    },
    content: { letterSpacing: 0 },
  }),
};
