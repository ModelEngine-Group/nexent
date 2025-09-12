"use client"

import { API_ENDPOINTS, ApiError } from './api';
import { CONNECTION_STATUS, ConnectionStatus } from '@/const/modelConfig';
import { ModelEngineCheckResult } from '@/types/modelConfig';

import { fetchWithAuth } from '@/lib/auth';
import log from "@/lib/logger";

// @ts-ignore
const fetch = fetchWithAuth;

/**
 * ModelEngine service - responsible for interacting with ModelEngine
 */
const modelEngineService = {
  /**
   * Check ModelEngine connection status
   * @returns Promise<ModelEngineCheckResult> Result object containing connection status and check time
   */
  checkConnection: async (): Promise<ModelEngineCheckResult> => {
    try {
      const response = await fetch(API_ENDPOINTS.model.officialModelHealthcheck, {
        method: "GET"
      })

      let status: ConnectionStatus = CONNECTION_STATUS.ERROR;
      
      if (response.ok) {
        try {
          const resp = await response.json()
          status = resp.connectivity ? CONNECTION_STATUS.SUCCESS : CONNECTION_STATUS.ERROR
        } catch (parseError) {
          log.error("Response data parsing failed:", parseError)
        }
      }

      return {
        status,
        lastChecked: new Date().toLocaleTimeString()
      }
    } catch (error) {
      // only print non ApiError
      if (!(error && error instanceof ApiError)) {
        log.error("Failed to check ModelEngine connection status:", error)
      }
      return {
        status: CONNECTION_STATUS.ERROR,
        lastChecked: new Date().toLocaleTimeString()
      }
    }
  }
}

export default modelEngineService; 