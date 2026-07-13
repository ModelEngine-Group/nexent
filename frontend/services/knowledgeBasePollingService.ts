/**
 * @fileoverview Background polling service.
 *
 * Owns `setInterval`-based document-state and KB-ready polling plus the
 * cross-component `documentsUpdated` / `knowledgeBaseDataUpdated` custom
 * events that keep various KB-aware components in sync with server-side
 * progress.
 *
 * The polling itself (`listDocuments` for per-KB doc state, and
 * `getKnowledgeBase` for KB readiness in the create workflow) routes through
 * the unified KB surface `/api/v1/kb/...`, which requires an `adapter_id`
 * along with the `kbId`. The legacy local `/api/indices/{num}/files` and
 * `/api/indices` paths are never called by this service, even when the KB
 * state is stale — a missing `adapter_id` is logged as a data bug and the
 * poll either retries on the next tick or, for the KB-ready path, rejects,
 * rather than silently falling back to the legacy endpoint.
 *
 * Legacy `knowledgeBaseService` is still imported for its local-only helpers
 * (e.g. chunk/summary APIs), which live outside the standard KB CRUD
 * surface and are not covered by this service's polling contract.
 */
import unifiedKBService from './unifiedKBService';
import knowledgeBaseService from './knowledgeBaseService';

import { NON_TERMINAL_STATUSES } from '@/const/knowledgeBase';
import { Document, KnowledgeBase } from '@/types/knowledgeBase';
import type { UnifiedDocument } from '@/types/unifiedKB';
import log from '@/lib/logger';

/**
 * Map a `UnifiedDocument` (returned by the unified `/api/v1/kb/...`
 * endpoints) onto the legacy `Document` shape consumed by the pre-migration
 * UI. Fields without a unified counterpart fall back to defensive defaults.
 */
const mapUnifiedDocToLegacy = (ud: UnifiedDocument, kbId: string): Document => ({
  id: ud.id,
  kb_id: kbId,
  name: ud.name || ud.id,
  type: (ud.type as Document["type"]) || "UNKNOWN",
  size: ud.size || 0,
  create_time: ud.created_at || "",
  chunk_num: ud.chunk_count || 0,
  token_num: ud.token_count || 0,
  status: (ud.status as Document["status"]) || "UNKNOWN",
  latest_task_id: "",
  error_reason: ud.error_message || undefined,
});

class KnowledgeBasePollingService {
  private pollingIntervals: Map<string, NodeJS.Timeout> = new Map();
  private knowledgeBasePollingInterval: number = 1000; // 1 second
  private documentPollingInterval: number = 3000; // 3 seconds
  private maxKnowledgeBasePolls: number = 60; // Maximum 60 polling attempts
  private maxDocumentPolls: number = 200; // Maximum 200 polling attempts (10 minutes for long-running tasks)
  private activeKnowledgeBaseId: string | null = null; // Record current active knowledge base ID
  private activeAdapterId: number | null = null;       // Adapter ID for the active KB (required for unified calls)
  private pendingRequests: Map<string, Promise<Document[]>> = new Map();
  
  // Debounce timers for batching multiple rapid requests
  private debounceTimers: Map<string, NodeJS.Timeout> = new Map();

  // Set current active knowledge base ID and its adapter ID.
  // `adapterId` is required for any polling tick that will call
  // `listDocuments` — without it the unified surface refuses the call,
  // and this service will NOT silently fall back to the legacy
  // `/api/indices/{num}/files` endpoint. Callers that don't yet know the
  // adapter ID can pass `undefined` but subsequent polls for that KB will
  // log a data-bug warning and skip the HTTP request until the ID is set.
  setActiveKnowledgeBase(kbId: string | null, adapterId?: number): void {
    this.activeKnowledgeBaseId = kbId;
    this.activeAdapterId = typeof adapterId === "number" ? adapterId : null;
    if (kbId != null && this.activeAdapterId == null) {
      log.warn(
        `setActiveKnowledgeBase: KB ${kbId} registered without an adapter_id; document polling will be disabled until one is provided.`
      );
    }
  }

  /**
   * Fetch the per-KB document list through the unified surface.
   *
   * Requires the KB to be the currently active one; when the active
   * `adapter_id` is unknown, returns an empty array and logs a data-bug
   * warning. Never calls the legacy `/api/indices/{num}/files` endpoint —
   * that path uses raw numeric IDs and misses the real UUID-suffixed ES
   * index, so falling back to it would hide the upstream mapping bug.
   */
  private async _fetchDocsViaUnified(
    kbId: string,
    adapterIdOverride?: number
  ): Promise<Document[]> {
    const adapterId =
      typeof adapterIdOverride === "number"
        ? adapterIdOverride
        : this.activeAdapterId;
    if (typeof adapterId !== "number") {
      log.warn(
        `polling: cannot fetch documents for KB ${kbId} — active adapter_id is missing; returning empty list.`
      );
      return [];
    }
    try {
      const resp = await unifiedKBService.listDocuments(adapterId, kbId, {
        pageSize: 100,
      });
      return (resp.list || []).map((ud) => mapUnifiedDocToLegacy(ud, kbId));
    } catch (err) {
      log.error(
        `polling: unified listDocuments failed for KB ${kbId} on adapter ${adapterId}:`,
        err
      );
      throw err;
    }
  }

  /**
   * Refresh KB list via the unified cross-adapter aggregate endpoint.
   *
   * Used by `pollForKnowledgeBaseReady` which needs to wait for a newly
   * created KB to show up in the list after upload. Unlike the legacy
   * `getKnowledgeBasesInfo(true)` path, this returns KBs from the adapter
   * registry with `adapter_id` already populated, so downstream callers
   * (e.g. document polling) can route requests through the unified surface
   * without a further lookup.
   */
  private async _listKbsUnified(): Promise<KnowledgeBase[]> {
    try {
      const resp = await unifiedKBService.listAllKnowledgeBases();
      return (resp.list || []).map((ukb) => ({
        id: ukb.knowledge_base_id,
        name: ukb.name,
        description: ukb.description || "",
        chunkCount: ukb.chunk_count || 0,
        documentCount: ukb.document_count || 0,
        createdAt: null,
        avatar: "",
        chunkNum: 0,
        language: "",
        nickname: "",
        parserId: "",
        permission: "",
        tokenNum: 0,
        source: ukb.platform || "nexent",
        embeddingModel: ukb.embedding_model || "unknown",
        adapter_id: ukb.adapter_id,
        adapter_name: ukb.adapter_name,
      }));
    } catch (err) {
      log.error("polling: unified listAllKnowledgeBases failed:", err);
      throw err;
    }
  }

  // Start document status polling, only update documents for specified knowledge base.
  // `adapterId` is recommended — when provided it is used instead of
  // `activeAdapterId` so each polling interval can route through the
  // unified surface even if the caller switches the active KB mid-poll.
  startDocumentStatusPolling(
    kbId: string,
    callback: (documents: Document[]) => void,
    adapterId?: number
  ): void {
    log.debug(`Start polling documents status for knowledge base ${kbId}`);
    
    // Clear existing polling first
    this.stopPolling(kbId);
    
    // Initialize polling counter
    let pollCount = 0;
    
    // Track if we're in extended polling mode (after initial timeout)
    let isExtendedPolling = false;
    
    // Define the polling logic function
    const pollDocuments = async () => {
      try {
        // Increment polling counter only if not in extended polling mode
        if (!isExtendedPolling) {
          pollCount++;
        }
        
        // If there is an active knowledge base and polling knowledge base doesn't match active one, stop polling
        if (this.activeKnowledgeBaseId !== null && this.activeKnowledgeBaseId !== kbId) {
          this.stopPolling(kbId);
          return;
        }
        
        // Use request deduplication to avoid concurrent duplicate requests
        let documents: Document[];
        const requestKey = `poll:${kbId}`;
        
        // Check if there's already a pending request for this KB
        const pendingRequest = this.pendingRequests.get(requestKey);
        if (pendingRequest) {
          // Reuse existing request to avoid duplicate API calls
          documents = await pendingRequest;
        } else {
          // Create new request and track it — route through unified surface.
          // `_fetchDocsViaUnified` is the single source of truth for per-KB
          // doc listing inside this service; missing adapter_id is handled
          // inside it (returns [] and logs), so we do NOT fall back to the
          // legacy `/api/indices/{num}/files` endpoint here.
          const requestPromise = this._fetchDocsViaUnified(kbId, adapterId);
          this.pendingRequests.set(requestKey, requestPromise);
          
          try {
            documents = await requestPromise;
          } finally {
            // Clean up after request completes
            this.pendingRequests.delete(requestKey);
          }
        }
        
        // Call callback function with latest documents first to ensure UI updates immediately
        callback(documents);
        
        // Check if any documents are in processing
        const hasProcessingDocs = documents.some(doc => 
          NON_TERMINAL_STATUSES.includes(doc.status)
        );
        
        // If exceeded maximum polling count and still processing, switch to extended polling mode
        if (pollCount > this.maxDocumentPolls && hasProcessingDocs && !isExtendedPolling) {
          log.warn(`Document polling for knowledge base ${kbId} exceeded ${this.maxDocumentPolls} attempts, switching to extended polling mode (reduced frequency)`);
          isExtendedPolling = true;
          // Stop the current interval and restart with longer interval
          this.stopPolling(kbId);
          // Continue polling with reduced frequency (every 10 seconds)
          const extendedInterval = setInterval(pollDocuments, 10000);
          this.pollingIntervals.set(kbId, extendedInterval);
          return;
        }
        
        // If there are processing documents, continue polling
        if (hasProcessingDocs) {
          log.log('Documents processing, continue polling');
          // Continue polling, don't stop
          return;
        }
        
        // All documents processed, stopping polling
        log.log('All documents processed, stopping polling');
        this.stopPolling(kbId);
        
        // Trigger knowledge base list update
        this.triggerKnowledgeBaseListUpdate(true);
      } catch (error) {
        log.error(`Error polling knowledge base ${kbId} document status:`, error);
      }
    };
    
    // Execute the first poll immediately to sync with knowledge base polling
    pollDocuments();
    
    // Create recurring polling
    const interval = setInterval(pollDocuments, this.documentPollingInterval);
    
    // Save polling identifier
    this.pollingIntervals.set(kbId, interval);
  }

  /**
   * Handle polling timeout - mark all processing documents as failed
   * @param kbId Knowledge base ID
   * @param timeoutType Type of timeout (for logging purposes)
   * @param callback Optional callback to update UI with modified documents
   * @param adapterId Adapter ID for the KB, used to route doc listing via unified surface
   */
  private async handlePollingTimeout(
    kbId: string, 
    timeoutType: 'document' | 'knowledgeBase',
    callback?: (documents: Document[]) => void,
    adapterId?: number
  ): Promise<void> {
    try {
      log.log(`Handling ${timeoutType} polling timeout for knowledge base ${kbId}`);
      // Get current documents via the unified surface. On failure (or when
      // adapter_id is unknown) `_fetchDocsViaUnified` returns [] and logs a
      // warning rather than silently calling legacy `/api/indices/{num}/files`.
      const documents = await this._fetchDocsViaUnified(kbId, adapterId);
      // Find all documents that are still in processing state
      const processingDocs = documents.filter(doc => 
        NON_TERMINAL_STATUSES.includes(doc.status)
      );
      if (processingDocs.length > 0) {
        log.warn(`${timeoutType} polling timed out with ${processingDocs.length} documents still processing:`, 
          processingDocs.map(doc => ({ name: doc.name, status: doc.status })));
        if (callback) {
          callback(documents);
        }
        this.triggerDocumentsUpdate(kbId, documents);
      } else {
        // Should forward documents to UI even if there is no processing document, prevent UI stuck
        this.triggerDocumentsUpdate(kbId, documents);
      }
    } catch (error) {
      log.error(`Error handling ${timeoutType} polling timeout for knowledge base ${kbId}:`, error);
      // Even if we can't get documents, we should still log the timeout
      if (timeoutType === 'knowledgeBase') {
        log.warn(`Knowledge base ${kbId} polling timed out, but could not retrieve documents to update their status`);
      }
    }
  }
  
  /**
   * Poll to check if knowledge base is ready (exists and stats updated).
   * @param kbId Knowledge base ID
   * @param kbName Knowledge base name
   * @param originalDocumentCount The document count before upload (for incremental upload)
   * @param expectedIncrement The number of new files uploaded
   * @param adapterId Adapter ID — required for both KB listing (cross-adapter aggregate)
   *                  and any document fallback that runs after a timeout.
   */
  pollForKnowledgeBaseReady(
    kbId: string,
    kbName: string,
    originalDocumentCount: number = 0,
    expectedIncrement: number = 0,
    adapterId?: number
  ): Promise<KnowledgeBase> {
    return new Promise(async (resolve, reject) => {
      let count = 0;
      const checkForStats = async () => {
        try {
          // Use the unified cross-adapter aggregate. The legacy
          // `getKnowledgeBasesInfo(true)` call is deliberately avoided here —
          // it doesn't populate `adapter_id` on the returned KBs, which makes
          // any downstream poll unable to route through the unified surface.
          const kbs = await this._listKbsUnified();
          const kb = kbs.find(k => k.id === kbId || k.name === kbName);

          // Check if KB exists and its stats are populated
          if (kb) {
            log.log(`Knowledge base ${kbName} detected.`);
            this.triggerKnowledgeBaseListUpdate(true);
            resolve(kb);
            return;
          }

          count++;
          if (count < this.maxKnowledgeBasePolls) {
            log.log(`Knowledge base ${kbName} not ready yet, continue waiting...`);
            setTimeout(checkForStats, this.knowledgeBasePollingInterval);
          } else {
            log.error(`Knowledge base ${kbName} readiness check timed out after ${this.maxKnowledgeBasePolls} attempts.`);
            
            // Handle knowledge base polling timeout - mark related tasks as failed
            await this.handlePollingTimeout(kbId, 'knowledgeBase', undefined, adapterId);
            // Push documents to UI
            try {
              const documents = await this._fetchDocsViaUnified(kbId, adapterId);
              this.triggerDocumentsUpdate(kbId, documents);
            } catch (e) {
              // Ignore error
            }
            
            reject(new Error(`创建知识库 ${kbName} 超时失败。`));
          }
        } catch (error) {
          log.error(`Failed to get stats for knowledge base ${kbName}:`, error);
          count++;
          if (count < this.maxKnowledgeBasePolls) {
            setTimeout(checkForStats, this.knowledgeBasePollingInterval);
          } else {
            // Handle knowledge base polling timeout on error as well
            await this.handlePollingTimeout(kbId, 'knowledgeBase', undefined, adapterId);
            // Push documents to UI
            try {
              const documents = await this._fetchDocsViaUnified(kbId, adapterId);
              this.triggerDocumentsUpdate(kbId, documents);
            } catch (e) {
              // Ignore error
            }
            reject(new Error(`获取知识库 ${kbName} 状态失败。`));
          }
        }
      };
      checkForStats();
    });
  }

  // Simplified method for new knowledge base creation workflow.
  // `adapterId` is passed through to both the doc-polling and the KB-ready
  // polling paths so they can route through the unified surface end-to-end.
  async handleNewKnowledgeBaseCreation(
    kbId: string,
    kbName: string,
    adapterId: number | undefined,
    originalDocumentCount: number = 0,
    expectedIncrement: number = 0,
    callback: (kb: KnowledgeBase) => void
  ): Promise<void> {
    // Start document polling (routes through unified surface when adapterId is set)
    this.startDocumentStatusPolling(kbId, (documents) => {
      this.triggerDocumentsUpdate(kbId, documents);
    }, adapterId);
    try {
      // Start knowledge base polling parallelly
      const populatedKB = await this.pollForKnowledgeBaseReady(
        kbId, kbName, originalDocumentCount, expectedIncrement, adapterId
      );
      // callback with populated knowledge base when everything is ready
      callback(populatedKB);
    } catch (error) {
      log.error(`Failed to handle new knowledge base creation for ${kbName}:`, error);
      throw error;
    }
  }
  
  // Stop polling for specific knowledge base
  stopPolling(kbId: string): void {
    const interval = this.pollingIntervals.get(kbId);
    if (interval) {
      clearInterval(interval);
      this.pollingIntervals.delete(kbId);
    }
  }
  
  // Stop all polling
  stopAllPolling(): void {
    this.pollingIntervals.forEach((interval) => {
      clearInterval(interval);
    });
    this.pollingIntervals.clear();
    
    // Clear pending requests and debounce timers to prevent memory leaks
    this.pendingRequests.clear();
    this.debounceTimers.forEach((timer) => {
      clearTimeout(timer);
    });
    this.debounceTimers.clear();
  }
  
  // Trigger knowledge base list update (optionally force refresh)
  triggerKnowledgeBaseListUpdate(forceRefresh: boolean = false): void {
    // Trigger custom event to notify knowledge base list update
    window.dispatchEvent(new CustomEvent('knowledgeBaseDataUpdated', {
      detail: { forceRefresh }
    }));
  }
  
  // Trigger document list update - only update documents for specified knowledge base
  triggerDocumentsUpdate(kbId: string, documents: Document[]): void {
    // If there is an active knowledge base and update knowledge base doesn't match active one, ignore this update
    if (this.activeKnowledgeBaseId !== null && this.activeKnowledgeBaseId !== kbId) {
      return;
    }
    
    window.dispatchEvent(new CustomEvent('documentsUpdated', {
      detail: { 
        kbId,
        documents
      }
    }));
  }
}

// Export singleton instance
const knowledgeBasePollingService = new KnowledgeBasePollingService();
export default knowledgeBasePollingService;