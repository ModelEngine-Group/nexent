import type { ThemeConfig } from "antd";

/** UCD colors scoped to the AIDP overview and its shared pagination. */
export const aidpKnowledgeVisualTheme: ThemeConfig = {
  token: {
    colorPrimary: "#0067d1",
    colorText: "#191919",
    colorTextSecondary: "#777777",
    colorTextPlaceholder: "#aeaeae",
    colorBorder: "#c9c9c9",
    borderRadius: 4,
    controlHeight: 32,
    fontSize: 14,
  },
  components: {
    Segmented: {
      trackBg: "rgba(25, 25, 25, 0.05)",
      trackPadding: 2,
      itemSelectedBg: "#0067d1",
      itemSelectedColor: "#ffffff",
      itemColor: "#777777",
    },
    Pagination: {
      itemSize: 32,
      itemActiveBg: "#e6f2fd",
      itemActiveColor: "#0067d1",
    },
    Table: {
      headerBg: "#f5f5f5",
      headerColor: "#191919",
      borderColor: "#ededed",
    },
  },
};
