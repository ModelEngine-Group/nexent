// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { API_ENDPOINTS } from './api';

import { fetchWithAuth, getAuthHeaders } from '@/lib/auth';
// @ts-ignore
const fetch = fetchWithAuth;

/**
 * Get Request Headers
 */
const getHeaders = () => {
  return getAuthHeaders();
};

export interface GenerateGuardrailRulesParams {
  description: string;
  model_id: number;
  language?: string;
}

export interface GuardrailAiResult {
  type: "single" | "multi";
  candidates?: { pattern: string; desc: string }[];
  rules?: { name: string; pattern: string; severity: "block" | "mask" | "pass"; desc: string }[];
}

export const generateGuardrailRules = async (
  params: GenerateGuardrailRulesParams,
): Promise<GuardrailAiResult> => {
  const response = await fetch(API_ENDPOINTS.agent.generateGuardrailRules, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify(params),
  });

  const result = await response.json();
  return result.data as GuardrailAiResult;
};
