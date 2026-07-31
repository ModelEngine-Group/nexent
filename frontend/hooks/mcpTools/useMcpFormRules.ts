"use client";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { Rule } from "antd/es/form";
import { MCP_FIELD_LIMITS, MCP_PORT_RANGE } from "@/const/mcpTools";
import { isValidPort } from "@/lib/mcpTools";

/**
 * Returns all AntD Form `Rule[]` arrays used across MCP add / edit forms.
 *
 * Rules are aligned with the Agent config MCP page (McpConfigModal):
 *   - name:     `^[a-zA-Z0-9_-]+$`, max 20
 *   - authToken: max 500
 *   - httpUrl:   required only
 *   - containerConfig: JSON.parse + mcpServers check
 *   - openApiJson: JSON.parse
 *   - customHeaders: JSON.parse + typeof object + not array
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
          max: 20,
          message: t("mcpTools.add.validate.nameMaxLength"),
        },
        {
          pattern: /^[a-zA-Z0-9_-]+$/,
          message: t("mcpTools.add.validate.namePattern"),
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
          required: true,
          whitespace: true,
          message: t("mcpTools.add.validate.httpUrlRequired"),
        },
      ] as Rule[],

      containerPort: [
        {
          validator: async (_rule: Rule, value: unknown) => {
            if (value === undefined || value === null || value === "") {
              throw new Error(t("mcpTools.add.validate.containerRequired"));
            }
            const port = Number(value);
            if (!isValidPort(port)) {
              throw new Error(t("mcpTools.add.validate.containerPortRange"));
            }
          },
        },
      ] as Rule[],

      containerConfig: [
        {
          validator: async (_rule: Rule, value: unknown) => {
            const text = String(value || "").trim();
            if (!text) {
              throw new Error(t("mcpConfig.message.containerConfigRequired"));
            }
            let parsed: unknown;
            try {
              parsed = JSON.parse(text);
            } catch {
              throw new Error(t("mcpConfig.message.invalidJsonConfig"));
            }
            if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
              throw new Error(t("mcpTools.add.error.containerJsonInvalid"));
            }
            const obj = parsed as Record<string, unknown>;
            if (!obj.mcpServers || typeof obj.mcpServers !== "object" || Array.isArray(obj.mcpServers)) {
              throw new Error(t("mcpConfig.message.invalidConfigStructure"));
            }
          },
        },
      ] as Rule[],

      openApiJson: [
        {
          validator: async (_rule: Rule, value: unknown) => {
            const text = String(value || "").trim();
            if (!text) return;
            try {
              JSON.parse(text);
            } catch {
              throw new Error(t("mcpConfig.openApiToMcp.message.invalidJson"));
            }
          },
        },
      ] as Rule[],

      customHeaders: [
        {
          validator: async (_rule: Rule, value: unknown) => {
            const text = String(value || "").trim();
            if (!text) return;
            let parsed: unknown;
            try {
              parsed = JSON.parse(text);
            } catch {
              throw new Error(t("mcpConfig.message.invalidCustomHeadersJson"));
            }
            if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
              throw new Error(t("mcpConfig.message.invalidCustomHeaders"));
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
