import { TFunction } from 'i18next';

import { NAME_CHECK_STATUS } from '@/const/agentConfig';
import knowledgeBaseService from '@/services/knowledgeBaseService';
import { AbortableError } from '@/types/knowledgeBase';
import log from "@/lib/logger";

import '../app/[locale]/i18n';

// New method to check knowledge base name status
export const checkKnowledgeBaseName = async (
  knowledgeBaseName: string,
  t: TFunction
): Promise<{status: string, action?: string}> => {
  try {
    // Call new service method
    return await knowledgeBaseService.checkKnowledgeBaseName(knowledgeBaseName);
  } catch (error) {
    log.error(t('knowledgeBase.check.nameError'), error);
    // Return a status indicating check failure
    return { status: NAME_CHECK_STATUS.CHECK_FAILED };
  }
};


// Get knowledge base document information
export const fetchKnowledgeBaseInfo = async (
  indexName: string, 
  abortController: AbortController, 
  currentKnowledgeBaseRef: React.MutableRefObject<string>,
  onSuccess: () => void,
  onError: (error: unknown) => void,
  t: TFunction,
  message: any
) => {
  try {
    if (!abortController.signal.aborted && indexName === currentKnowledgeBaseRef.current) {
      onSuccess();
    }
  } catch (error: unknown) {
    const err = error as AbortableError;
    if (err.name !== 'AbortError' && indexName === currentKnowledgeBaseRef.current) {
      log.error(t('knowledgeBase.fetch.error'), error);
      message.error(t('knowledgeBase.fetch.retryError'));
      onError(error);
    }
  }
};

// File type validation
export const validateFileType = (file: File, t: TFunction, message: any): boolean => {
  const validTypes = [
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/markdown',
    'text/plain',
    'text/csv',
    'application/csv'
  ];

  // First check MIME type
  let isValidType = validTypes.includes(file.type);

  // If MIME type is empty or not in the list, check by file extension
  if (!isValidType) {
    const name = file.name.toLowerCase();
    if (
      name.endsWith('.md') ||
      name.endsWith('.markdown') ||
      name.endsWith('.csv')
    ) {
      isValidType = true;
    }
  }

  if (!isValidType) {
    message.error(t('knowledgeBase.upload.invalidFileType'));
    return false;
  }

  return true;
};
