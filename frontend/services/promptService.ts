import { API_ENDPOINTS } from './api';

import { GeneratePromptParams, StreamResponseData } from '@/types/agentConfig';
import { fetchWithAuth, getAuthHeaders } from '@/lib/auth';
// @ts-ignore
const fetch = fetchWithAuth;

/**
 * Get Request Headers
 */
const getHeaders = () => {
  return getAuthHeaders();
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
