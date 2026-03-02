// Knowledge Base Polling Service - Encapsulates polling logic, separates business logic from components

import knowledgeBaseService from './knowledgeBaseService';

import { NON_TERMINAL_STATUSES } from '@/const/knowledgeBase';
import { Document, KnowledgeBase } from '@/types/knowledgeBase';
import log from '@/lib/logger';

class KnowledgeBasePollingService {
  private pollingIntervals: Map<string, NodeJS.Timeout> = new Map();
  private knowledgeBasePollingInterval: number = 1000; // 1 second
  private documentPollingInterval: number = 3000; // 3 seconds
  private maxKnowledgeBasePolls: number = 60; // Maximum 60 polling attempts
  private maxDocumentPolls: number = 200; // Maximum 200 polling attempts (10 minutes for long-running tasks)
  private activeKnowledgeBaseId: string | null = null; // Record current active knowledge base ID
  private pendingRequests: Map<string, Promise<Document[]>> = new Map();
  
  // Debounce timers for batching multiple rapid requests
  private debounceTimers: Map<string, NodeJS.Timeout> = new Map();

  // Set current active knowledge base ID 
  setActiveKnowledgeBase(kbId: string | null): void {
    this.activeKnowledgeBaseId = kbId;
  }

  // Start document status polling, only update documents for specified knowledge base
  startDocumentStatusPolling(kbId: string, callback: (documents: Document[]) => void): void {
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
          // Create new request and track it
          const requestPromise = knowledgeBaseService.getAllFiles(kbId);
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
   */
  private async handlePollingTimeout(
    kbId: string, 
    timeoutType: 'document' | 'knowledgeBase',
    callback?: (documents: Document[]) => void
  ): Promise<void> {
    try {
      log.log(`Handling ${timeoutType} polling timeout for knowledge base ${kbId}`);
      // Get current documents
      const documents = await knowledgeBaseService.getAllFiles(kbId);
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
   * @param kbName Knowledge base name
   * @param originalDocumentCount The document count before upload (for incremental upload)
   * @param expectedIncrement The number of new files uploaded
   */
  pollForKnowledgeBaseReady(
    kbId: string,
    kbName: string,
    originalDocumentCount: number = 0,
    expectedIncrement: number = 0
  ): Promise<KnowledgeBase> {
    return new Promise(async (resolve, reject) => {
      let count = 0;
      const checkForStats = async () => {
        try {
          const result = await knowledgeBaseService.getKnowledgeBasesInfo(true);
          const kbs = result.knowledgeBases;
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
            await this.handlePollingTimeout(kbId, 'knowledgeBase');
            // Push documents to UI
            try {
              const documents = await knowledgeBaseService.getAllFiles(kbId);
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
            await this.handlePollingTimeout(kbId, 'knowledgeBase');
            // Push documents to UI
            try {
              const documents = await knowledgeBaseService.getAllFiles(kbId);
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

  // Simplified method for new knowledge base creation workflow
  async handleNewKnowledgeBaseCreation(kbId: string, kbName: string, originalDocumentCount: number = 0, expectedIncrement: number = 0, callback: (kb: KnowledgeBase) => void) {
    // Start document polling
    this.startDocumentStatusPolling(kbId, (documents) => {
      this.triggerDocumentsUpdate(kbId, documents);
    });
    try {
      // Start knowledge base polling parallelly
      const populatedKB = await this.pollForKnowledgeBaseReady(kbId, kbName, originalDocumentCount, expectedIncrement);
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