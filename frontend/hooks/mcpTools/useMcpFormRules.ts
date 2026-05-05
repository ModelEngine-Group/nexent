"use client";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { Rule } from "antd/es/form";
import { MCP_FIELD_LIMITS, MCP_PORT_RANGE } from "@/const/mcpTools";
import { isHttpUrl, isValidPort } from "@/lib/mcpTools";
import { parseContainerMcpConfigJson } from "@/services/mcpToolsService";

/**
 * Returns all AntD Form `Rule[]` arrays used across MCP add / edit forms.
 *
 * Using a hook (rather than plain functions) means callers never have to
 * thread a translator around — `useTranslation` is called once here and the
 * translated messages are memoised per-render.
 */
export function useMcpFormRules() {
  const { t } = useTranslation("common");

  return useMemo(
    () => ({
      name: [
        {
          required: true,
          whitespace: true,
          message: t("mcpTools.add.validate.nameRequired"),
        },
        {
          type: "string",
          max: MCP_FIELD_LIMITS.NAME,
          message: t("mcpTools.add.validate.nameMaxLength"),
        },
      ] as Rule[],

      description: [
        {
          type: "string",
          max: MCP_FIELD_LIMITS.DESCRIPTION,
          message: t("mcpTools.add.validate.descriptionMaxLength"),
        },
      ] as Rule[],

      authToken: [
        {
          type: "string",
          max: MCP_FIELD_LIMITS.AUTH_TOKEN,
          message: t("mcpTools.add.validate.authorizationTokenMaxLength"),
        },
      ] as Rule[],

      httpUrl: [
        {
          validator: async (_rule: Rule, value: unknown) => {
            const text = String(value || "").trim();
            if (!text)
              throw new Error(t("mcpTools.add.validate.httpUrlRequired"));
            if (text.length > MCP_FIELD_LIMITS.URL)
              throw new Error(t("mcpTools.add.validate.httpUrlMaxLength"));
            if (!isHttpUrl(text))
              throw new Error(t("mcpTools.add.validate.httpUrlFormat"));
          },
        },
      ] as Rule[],

      containerPort: [
        {
          validator: async (_rule: Rule, value: unknown) => {
            if (value === undefined || value === null || value === "") {
              throw new Error(t("mcpTools.add.validate.containerRequired"));
            }
            const port = Number(value);
            if (
              !isValidPort(port)
            ) {
              throw new Error(t("mcpTools.add.validate.containerPortRange"));
            }
          },
        },
      ] as Rule[],

      containerConfig: [
        {
          validator: async (_rule: Rule, value: unknown) => {
            const text = String(value || "").trim();
            if (!text)
              throw new Error(
                t("mcpTools.add.validate.containerConfigRequired")
              );
            if (!parseContainerMcpConfigJson(text)) {
              throw new Error(t("mcpTools.add.error.containerJsonInvalid"));
            }
          },
        },
      ] as Rule[],

      /**
       * Rules for a free-text variable/argument inside the registry
       * quick-add picker. `fieldLabel` is interpolated into the required
       * error message so the user sees which field they missed.
       */
      quickAddField: (fieldLabel: string, required: boolean): Rule[] => [
        ...(required
          ? [
              {
                required: true,
                whitespace: true,
                message: t(
                  "mcpTools.registry.quickAddPicker.variableRequiredMissing",
                  { key: fieldLabel }
                ),
              } as Rule,
            ]
          : []),
        {
          type: "string" as const,
          max: MCP_FIELD_LIMITS.QUICK_ADD_FIELD,
          message: t("mcpTools.registry.quickAddPicker.fieldMaxLength"),
        },
      ],

      /** Optional version string (publish / my-community forms); empty is allowed. */
      version: [
        {
          validator: async (_rule: Rule, value: unknown) => {
            const text = String(value || "").trim();
            if (!text) return;
            if (text.length > MCP_FIELD_LIMITS.VERSION) {
              throw new Error(t("mcpTools.community.mine.versionMaxLength"));
            }
          },
        },
      ] as Rule[],

      transportType: [
        {
          required: true,
          message: t("mcpTools.add.validate.transportTypeRequired"),
        },
      ] as Rule[],
    }),
    [t]
  );
}
