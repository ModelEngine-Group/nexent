// TODO: Move to language.ts
export const languageOptions = [
  { label: "简体中文", value: "zh" },
  { label: "English", value: "en" },
];

export const TOKEN_REFRESH_CD = 1 * 60 * 1000;

export const isProduction = process.env.NODE_ENV === "production";

export const APP_VERSION = "v1.0.0";
