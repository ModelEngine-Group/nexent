// TODO: Move to language.ts
export const languageOptions = [
  { label: "简体中文", value: "zh" },
  { label: "English", value: "en" },
];

export const TOKEN_REFRESH_CD = 1 * 60 * 1000;
// If the remaining lifetime of the access token is below this threshold,
// a refresh will be attempted on user activity (sliding expiration).
export const TOKEN_REFRESH_BEFORE_EXPIRY_MS = 30 * 60 * 1000;
// Throttle interval for activity-driven refresh checks
export const MIN_ACTIVITY_CHECK_INTERVAL_MS = 30 * 1000;

export const isProduction = process.env.NODE_ENV === "production";

export const APP_VERSION = "v1.0.0";

// Default parameter type constant
export const DEFAULT_TYPE = "string";
