import { API_ENDPOINTS } from "./api";
import { fetchWithAuth, getAuthHeaders } from "@/lib/auth";
import type {
  PromptTemplateCreateRequest,
  PromptTemplateUpdateRequest,
  PromptTemplateDeleteRequest,
} from "@/types/promptTemplate";

// @ts-ignore
const fetch = fetchWithAuth;

const getHeaders = () => getAuthHeaders();

export const listPromptTemplates = async (keyword?: string) => {
  const response = await fetch(API_ENDPOINTS.promptTemplate.list(keyword), {
    method: "GET",
    headers: getHeaders(),
  });
  return response.json();
};

export const createPromptTemplate = async (
  payload: PromptTemplateCreateRequest
) => {
  const response = await fetch(API_ENDPOINTS.promptTemplate.create, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify(payload),
  });
  return response.json();
};

export const updatePromptTemplate = async (
  payload: PromptTemplateUpdateRequest
) => {
  const response = await fetch(API_ENDPOINTS.promptTemplate.update, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify(payload),
  });
  return response.json();
};

export const deletePromptTemplate = async (
  payload: PromptTemplateDeleteRequest
) => {
  const response = await fetch(API_ENDPOINTS.promptTemplate.delete, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify(payload),
  });
  return response.json();
};
