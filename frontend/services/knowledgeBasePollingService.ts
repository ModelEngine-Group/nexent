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
  private maxDocumentPolls: number = 20; // Maximum 20 polling attempts
  private activeKnowledgeBaseId: string | null = null; // Record current active knowledge base ID

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
    
    // Define the polling logic function
    const pollDocuments = async () => {
      try {
        // Increment polling counter
        pollCount++;
        
        // If there is an active knowledge base and polling knowledge base doesn't match active one, stop polling
        if (this.activeKnowledgeBaseId !== null && this.activeKnowledgeBaseId !== kbId) {
          this.stopPolling(kbId);
          return;
        }
        
        // If exceeded maximum polling count, handle timeout
        if (pollCount > this.maxDocumentPolls) {
          log.warn(`Document polling for knowledge base ${kbId} timed out after ${this.maxDocumentPolls} attempts`);
          await this.handlePollingTimeout(kbId, 'document', callback);
          // Push documents to UI
          try {
            const documents = await knowledgeBaseService.getAllFiles(kbId);
            this.triggerDocumentsUpdate(kbId, documents);
          } catch (e) {
            // Ignore error
          }
          this.stopPolling(kbId);
          return;
        }
        
        // Get latest document status
        const documents = await knowledgeBaseService.getAllFiles(kbId);
        
        // Call callback function with latest documents first to ensure UI updates immediately
        callback(documents);
        
        // Check if any documents are in processing
        const hasProcessingDocs = documents.some(doc => 
          NON_TERMINAL_STATUSES.includes(doc.status)
        );
        
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
    kbName: string,
    originalDocumentCount: number = 0,
    expectedIncrement: number = 0
  ): Promise<KnowledgeBase> {
    return new Promise(async (resolve, reject) => {
      let count = 0;
      const checkForStats = async () => {
        try {
          const kbs = await knowledgeBaseService.getKnowledgeBasesInfo(true) as KnowledgeBase[];
          const kb = kbs.find(k => k.name === kbName);

          // Check if KB exists and its stats are populated
          if (kb) {
            // If expectedIncrement > 0, check if documentCount increased as expected
            if (
              expectedIncrement > 0 &&
              kb.documentCount >= (originalDocumentCount + expectedIncrement)
            ) {
              log.log(
                `Knowledge base ${kbName} documentCount increased as expected: ${kb.documentCount} (was ${originalDocumentCount}, expected increment ${expectedIncrement})`
              );
              this.triggerKnowledgeBaseListUpdate(true);
              resolve(kb);
              return;
            }
            // Fallback: for new KB or no increment specified, use old logic
            if (expectedIncrement === 0 && (kb.documentCount > 0 || kb.chunkCount > 0)) {
              log.log(`Knowledge base ${kbName} is ready and stats are populated.`);
              this.triggerKnowledgeBaseListUpdate(true);
              resolve(kb);
              return;
            }
          }

          count++;
          if (count < this.maxKnowledgeBasePolls) {
            log.log(`Knowledge base ${kbName} not ready yet, continue waiting...`);
            setTimeout(checkForStats, this.knowledgeBasePollingInterval);
          } else {
            log.error(`Knowledge base ${kbName} readiness check timed out after ${this.maxKnowledgeBasePolls} attempts.`);
            
            // Handle knowledge base polling timeout - mark related tasks as failed
            await this.handlePollingTimeout(kbName, 'knowledgeBase');
            // Push documents to UI
            try {
              const documents = await knowledgeBaseService.getAllFiles(kbName);
              this.triggerDocumentsUpdate(kbName, documents);
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
            await this.handlePollingTimeout(kbName, 'knowledgeBase');
            // Push documents to UI
            try {
              const documents = await knowledgeBaseService.getAllFiles(kbName);
              this.triggerDocumentsUpdate(kbName, documents);
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
  async handleNewKnowledgeBaseCreation(kbName: string, originalDocumentCount: number = 0, expectedIncrement: number = 0, callback: (kb: KnowledgeBase) => void) {
    // Start document polling
    this.startDocumentStatusPolling(kbName, (documents) => {
      this.triggerDocumentsUpdate(kbName, documents);
    });
    try {
      // Start knowledge base polling parallelly
      const populatedKB = await this.pollForKnowledgeBaseReady(kbName, originalDocumentCount, expectedIncrement);
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