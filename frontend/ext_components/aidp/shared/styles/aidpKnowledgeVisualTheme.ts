import type { ThemeConfig } from "antd";

/** Text tokens shared by the AIDP list and creation pages. */
export const aidpKnowledgeTypographyTheme: ThemeConfig = {
  token: {
    colorText: "#191919",
    colorTextSecondary: "#595959",
    colorTextPlaceholder: "#aeaeae",
    fontSize: 14,
  },
};

/** UCD colors scoped to the AIDP overview and its shared pagination. */
export const aidpKnowledgeVisualTheme: ThemeConfig = {
  token: {
    ...aidpKnowledgeTypographyTheme.token,
    colorPrimary: "#0067d1",
    colorBorder: "#c9c9c9",
    borderRadius: 4,
    controlHeight: 32,
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
      headerBg: "#f3f3f3",
      headerColor: "#191919",
      borderColor: "#f3f3f3",
    },
  },
};
