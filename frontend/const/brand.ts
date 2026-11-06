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

export const BRAND_RADII = {
  none: 0,
  xs: 2,
  base: 4,
  lg: 8,
  full: 9999,
} as const;

export const BRAND_BODY_FONT_SIZES = {
  "body-1": 12,
  "body-2": 14,
  "body-3": 16,
} as const;

export const BRAND = {
  primary: BRAND_PALETTE["50"],
  hover: BRAND_PALETTE["40"],
  active: BRAND_PALETTE["60"],
  disabled: BRAND_PALETTE["20"],
  selection: BRAND_PALETTE["05"],
  border: "#C9C9C9",
  text: "#191919",
  radius: BRAND_RADII.base,
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
${Object.entries(BRAND_RADII)
  .map(
    ([role, radius]) =>
      `--brand-radius-${role}: ${radius}px; --radius-${role}: var(--brand-radius-${role});`
  )
  .join("\n")}
${Object.entries(BRAND_BODY_FONT_SIZES)
  .map(([role, size]) => `--font-${role}: ${size}px;`)
  .join("\n")}
--radius-control: var(--radius-base);
--radius: var(--radius-base);
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
    borderRadiusLG: BRAND_RADII.lg,
    borderRadiusSM: BRAND.radius,
    borderRadiusXS: BRAND_RADII.xs,
    controlHeight: 32,
    fontSizeSM: BRAND_BODY_FONT_SIZES["body-1"],
    fontSize: BRAND_BODY_FONT_SIZES["body-2"],
    fontSizeLG: BRAND_BODY_FONT_SIZES["body-3"],
    lineHeight: 22 / 14,
  },
  components: {
    Button: {
      borderRadiusLG: BRAND_RADII.base,
      paddingInline: 16,
      primaryShadow: "none",
      defaultShadow: "none",
      dangerShadow: "none",
    },
    Input: { controlHeight: 28, borderRadiusLG: BRAND_RADII.base },
    InputNumber: { borderRadiusLG: BRAND_RADII.base },
    Card: { borderRadiusLG: BRAND_RADII.lg },
    Modal: { borderRadiusLG: BRAND_RADII.lg },
    Checkbox: { borderRadiusSM: BRAND_RADII.xs },
    Select: {
      borderRadiusLG: BRAND_RADII.base,
      borderRadiusXS: BRAND_RADII.base,
    },
    Dropdown: {
      borderRadiusLG: BRAND_RADII.base,
      borderRadiusSM: BRAND_RADII.xs,
    },
    Popover: { borderRadiusLG: BRAND_RADII.base },
    Alert: { borderRadius: BRAND_RADII.base },
    Slider: { borderRadiusXS: BRAND_RADII.full },
    Progress: { lineBorderRadius: BRAND_RADII.full },
    Table: {
      headerBorderRadius: BRAND.radius,
      headerSplitColor: "transparent",
      headerBg: "#F7F9FC",
      headerColor: "#475569",
      borderColor: "#EEF1F5",
      rowHoverBg: BRAND.selection,
      rowSelectedBg: BRAND.selection,
      rowSelectedHoverBg: BRAND_PALETTE["10"],
      cellFontSizeSM: BRAND_BODY_FONT_SIZES["body-2"],
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

/** Popup item geometry differs from the enclosing Select control and panel. */
export const NEXENT_SELECT_DEFAULTS: ConfigProviderProps["select"] = {
  styles: {
    popup: {
      root: { borderRadius: BRAND_RADII.base },
      listItem: { borderRadius: BRAND_RADII.xs },
    },
    item: { borderRadius: BRAND_RADII.base },
  },
};

export const NEXENT_BADGE_DEFAULTS: ConfigProviderProps["badge"] = {
  styles: ({ props }) => ({
    indicator:
      props.dot || props.status ? {} : { borderRadius: BRAND_RADII.base },
  }),
};
