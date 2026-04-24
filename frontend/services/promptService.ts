import { API_ENDPOINTS } from './api';

import {
  GeneratePromptParams,
  OptimizePromptParams,
  OptimizePromptStreamData,
  PromptTemplateItem,
  StreamResponseData,
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

const extractErrorMessage = (payload: any, fallback: string) => {
  if (!payload) return fallback;
  if (typeof payload === "string") return payload;
  if (typeof payload?.message === "string" && payload.message.trim()) {
    return payload.message;
  }
  if (typeof payload?.detail === "string" && payload.detail.trim()) {
    return payload.detail;
  }
  if (payload?.detail && typeof payload.detail === "object") {
    if (typeof payload.detail.message === "string" && payload.detail.message.trim()) {
      return payload.detail.message;
    }
  }
  return fallback;
};

export const generatePromptStream = async (
  params: GeneratePromptParams,
  onData: (data: StreamResponseData) => void,
  onError?: (err: any) => void,
  onComplete?: () => void
) => {
  try {
    const response = await fetch(API_ENDPOINTS.prompt.generate, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(params),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const errorMessage = extractErrorMessage(
        errorData,
        `Request failed: ${response.status}`
      );
      if (onError) onError(errorData?.detail || { message: errorMessage });
      if (onComplete) onComplete();
      return;
    }

    if (!response.body) throw new Error('No response body');

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let hasError = false;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let lines = buffer.split('\n\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const json = JSON.parse(line.replace('data: ', ''));
            if (json.success) {
              onData(json.data);
            } else if (json.success === false && json.error) {
              // Handle error response from backend
              hasError = true;
              if (onError) onError(json.error);
            }
          } catch (e) {
            if (onError) onError(e);
          }
        }
      }
    }
    // Only call onComplete if no error occurred
    if (!hasError && onComplete) onComplete();
  } catch (err) {
    if (onError) onError(err);
    if (onComplete) onComplete();
  }
};

export const optimizePromptStream = async (
  params: OptimizePromptParams,
  onData: (data: OptimizePromptStreamData) => void,
  onError?: (err: any) => void,
  onComplete?: () => void
) => {
  try {
    const response = await fetch(API_ENDPOINTS.prompt.optimize, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(params),
    });

    if (!response.body) throw new Error('No response body');

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let hasError = false;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const json = JSON.parse(line.replace('data: ', ''));
            if (json.success) {
              onData(json.data);
            } else if (json.success === false && json.error) {
              hasError = true;
              if (onError) onError(json.error);
            }
          } catch (e) {
            if (onError) onError(e);
          }
        }
      }
    }

    if (!hasError && onComplete) onComplete();
  } catch (err) {
    if (onError) onError(err);
    if (onComplete) onComplete();
  }
};

export const fetchPromptTemplates = async (): Promise<PromptTemplateItem[]> => {
  const response = await fetch(API_ENDPOINTS.prompt.templates, {
    headers: getHeaders(),
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  const data = await response.json();
  return data.templates || [];
};

export const createPromptTemplate = async (
  payload: Omit<PromptTemplateItem, "template_id" | "create_time" | "update_time">
): Promise<PromptTemplateItem> => {
  const response = await fetch(API_ENDPOINTS.prompt.templates, {
    method: 'POST',
    headers: getHeaders(),
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(extractErrorMessage(errorData, `Request failed: ${response.status}`));
  }

  return response.json();
};

export const updatePromptTemplate = async (
  templateId: number,
  payload: Partial<Omit<PromptTemplateItem, "template_id" | "create_time" | "update_time">>
): Promise<PromptTemplateItem> => {
  const response = await fetch(API_ENDPOINTS.prompt.template(templateId), {
    method: 'PUT',
    headers: getHeaders(),
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(extractErrorMessage(errorData, `Request failed: ${response.status}`));
  }

  return response.json();
};

export const deletePromptTemplate = async (templateId: number): Promise<void> => {
  const response = await fetch(API_ENDPOINTS.prompt.template(templateId), {
    method: 'DELETE',
    headers: getHeaders(),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(extractErrorMessage(errorData, `Request failed: ${response.status}`));
  }
};
