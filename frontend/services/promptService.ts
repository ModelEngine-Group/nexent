// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { API_ENDPOINTS } from './api';

import {
  OptimizePromptSectionParams,
  OptimizePromptSectionResponse,
  OptimizePromptBadCaseParams,
  OptimizePromptBadCaseResponse,
} from '@/types/agentConfig';
import { fetchWithAuth, getAuthHeaders } from '@/lib/auth';
// @ts-ignore
const fetch = fetchWithAuth;

/**
 * Get Request Headers
 */
const getHeaders = () => {
  return getAuthHeaders();
};

export const optimizePromptSection = async (
  params: OptimizePromptSectionParams,
): Promise<OptimizePromptSectionResponse> => {
  const response = await fetch(API_ENDPOINTS.prompt.optimize, {
    method: 'POST',
    headers: getHeaders(),
    body: JSON.stringify(params),
  });

  const result = await response.json();
  return result.data as OptimizePromptSectionResponse;
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

export interface DebugPromptOptimizeParams {
  agent_id: number;
  model_id: number;
  feedback: string;
  selected: { user_question: string; assistant_answer: string };
  history: Array<{ role: string; content: string }>;
}

export interface DebugPromptOptimizeResult {
  original_full_prompt?: string;
  optimized_full_prompt?: string;
}

export const optimizePromptFromDebug = async (
  params: DebugPromptOptimizeParams
): Promise<DebugPromptOptimizeResult> => {
  const response = await fetch(API_ENDPOINTS.prompt.optimizeFromDebug, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify(params),
  });
  const result = await response.json();
  return result?.data || {};
};

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

// optimizePromptBadCase removed: badcase optimization is now fully automated in agent debug.
