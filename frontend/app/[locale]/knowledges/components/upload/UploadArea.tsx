import React, { useState, forwardRef, useImperativeHandle, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';

import type { UploadFile, UploadProps, RcFile } from 'antd/es/upload/interface';
import { App, Upload } from 'antd';

import { NAME_CHECK_STATUS } from '@/const/agentConfig';
import log from "@/lib/logger";
import { 
  checkKnowledgeBaseName,
  fetchKnowledgeBaseInfo,
  validateKnowledgeBaseFileSize,
  validateFileType,
} from '@/services/uploadService';

import UploadAreaUI from './UploadAreaUI';

interface UploadAreaProps {
  isDragging?: boolean;
  onDragOver?: (e: React.DragEvent) => void;
  onDragLeave?: (e: React.DragEvent) => void;
  onDrop?: (e: React.DragEvent) => void;
  onFileSelect: (files: File[]) => void;
  selectedFiles?: File[];
  onUpload?: (files: File[]) => Promise<void>;
  isUploading?: boolean;
  disabled?: boolean;
  disabledMessage?: string;
  componentHeight?: string;
  isCreatingMode?: boolean;
  indexName?: string;
  newKnowledgeBaseName?: string;
  modelMismatch?: boolean;
  onNameStatusChange?: (status: string) => void;
}

export interface UploadAreaRef {
  fileList: UploadFile[];
}

const UploadArea = forwardRef<UploadAreaRef, UploadAreaProps>(
  (
    {
      onFileSelect,
      onUpload,
      isUploading = false,
      disabled = false,
      disabledMessage,
      componentHeight = "100%",
      isCreatingMode = false,
      indexName = "",
      newKnowledgeBaseName = "",
      selectedFiles = [],
      modelMismatch = false,
      onNameStatusChange,
    },
    ref
  ) => {
    const { t } = useTranslation("common");
    const { message } = App.useApp();
    const [fileList, setFileList] = useState<UploadFile[]>([]);
    const [nameStatus, setNameStatus] = useState<string>("available");
    const [isLoading, setIsLoading] = useState(false);
    const [isKnowledgeBaseReady, setIsKnowledgeBaseReady] = useState(false);
    const currentKnowledgeBaseRef = useRef<string>("");
    const pendingRequestRef = useRef<AbortController | null>(null);
    // UIDs already handed off to the parent upload; kept in the visible list but not re-sent.
    const uploadedUidsRef = useRef<Set<string>>(new Set());
    const pendingUploadRequestsRef = useRef<any[]>([]);
    const uploadScheduledRef = useRef(false);

    const updateNameStatus = useCallback((status: string) => {
      setNameStatus(status);
      onNameStatusChange?.(status);
    }, [onNameStatusChange]);

    // Function to reset all states
    const resetAllStates = useCallback(() => {
      uploadedUidsRef.current = new Set();
      setFileList([]);
      updateNameStatus("available");
      setIsLoading(true);
      setIsKnowledgeBaseReady(false);
    }, [updateNameStatus]);

    // Listen for knowledge base changes, reset file list and get knowledge base info
    useEffect(() => {
      // If knowledge base name hasn't changed, don't reset
      if (indexName === currentKnowledgeBaseRef.current) {
        return;
      }

      // Cancel previous request
      if (pendingRequestRef.current) {
        pendingRequestRef.current.abort();
        pendingRequestRef.current = null;
      }

      // Immediately reset state and clear file list
      resetAllStates();

      // Update current knowledge base reference
      currentKnowledgeBaseRef.current = indexName;

      if (!indexName || isCreatingMode) {
        setIsKnowledgeBaseReady(true);
        setIsLoading(false);
        return;
      }

      // Create new AbortController
      const abortController = new AbortController();
      pendingRequestRef.current = abortController;

      // Use service function to get knowledge base info
      fetchKnowledgeBaseInfo(
        indexName,
        abortController,
        currentKnowledgeBaseRef,
        () => {
          setIsKnowledgeBaseReady(true);
          setIsLoading(false);
        },
        () => {
          setIsKnowledgeBaseReady(false);
          setIsLoading(false);
        },
        t,
        message
      );

      // Cleanup function
      return () => {
        if (pendingRequestRef.current) {
          pendingRequestRef.current.abort();
          pendingRequestRef.current = null;
        }
      };
    }, [indexName, isCreatingMode, resetAllStates, t, message]);

    // Expose file list to parent component
    useImperativeHandle(
      ref,
      () => ({
        fileList,
      }),
      [fileList]
    );

    // Check if knowledge base name already exists
    useEffect(() => {
      if (!isCreatingMode || !newKnowledgeBaseName) {
        updateNameStatus("available");
        return;
      }

      const checkName = async () => {
        try {
          const result = await checkKnowledgeBaseName(newKnowledgeBaseName, t);
          updateNameStatus(result.status);
        } catch (error) {
          log.error(t("knowledgeBase.error.checkName"), error);
          updateNameStatus(NAME_CHECK_STATUS.CHECK_FAILED); // Handle check failure
        }
      };

      const timer = setTimeout(() => {
        checkName();
      }, 300); // Debounce for 300ms

      return () => {
        clearTimeout(timer);
      };
    }, [isCreatingMode, newKnowledgeBaseName, t]);

    // Handle file changes
    const handleChange = useCallback(
      ({ fileList: newFileList }: { fileList: UploadFile[] }) => {
        // Ensure only updating current knowledge base's file list
        if (!(isCreatingMode || indexName === currentKnowledgeBaseRef.current)) {
          return;
        }

        // Deduplicate by name + size + lastModified to avoid duplicates within and across selections
        const seen = new Set<string>();
        const deduped: UploadFile[] = [];
        for (const f of newFileList) {
          const origin = f.originFileObj as RcFile | undefined;
          const key = origin
            ? `${origin.name.toLowerCase()}|${origin.size}|${
                origin.lastModified
              }`
            : f.name.toLowerCase();
          if (!seen.has(key)) {
            seen.add(key);
            deduped.push(f);
          }
        }
        // Keep completed history visible; accumulate across successive uploads
        setFileList(deduped);

        // Only pass files not yet uploaded so the API request is the current batch only
        const pendingFiles = deduped
          .filter((file) => !uploadedUidsRef.current.has(file.uid))
          .map((file) => file.originFileObj)
          .filter((file): file is RcFile => !!file);
        if (pendingFiles.length > 0) {
          onFileSelect(pendingFiles as unknown as File[]);
        }

      },
      [indexName, onFileSelect, isCreatingMode]
    );

    // Handle custom upload request
    const handleCustomRequest = useCallback(
      (options: any) => {
        pendingUploadRequestsRef.current.push(options);
        if (uploadScheduledRef.current) {
          return;
        }

        uploadScheduledRef.current = true;
        setTimeout(async () => {
          try {
            while (pendingUploadRequestsRef.current.length > 0) {
              const requests = pendingUploadRequestsRef.current.splice(0);
              try {
                await onUpload?.(requests.map(({ file }) => file as File));
                requests.forEach(({ onSuccess, file }) => {
                  uploadedUidsRef.current.add(file.uid);
                  onSuccess?.({}, file);
                });
              } catch (error) {
                requests.forEach(({ onError, file }) =>
                  onError?.(error, undefined, file)
                );
              }
            }
          } catch (error) {
            log.error("Unexpected error while updating upload status", error);
          } finally {
            uploadScheduledRef.current = false;
          }
        }, 0);
      },
      [onUpload]
    );

    // Upload component properties
    const uploadProps: UploadProps = {
      name: "file",
      multiple: true,
      fileList,
      onChange: handleChange,
      customRequest: handleCustomRequest,
      accept: ".pdf,.doc,.docx,.pptx,.xlsx,.md,.txt,.csv,.json,.epub,.xml,.html",
      showUploadList: true,
      disabled: disabled,
      progress: {
        strokeColor: {
          "0%": "#108ee9",
          "100%": "#87d068",
        },
        size: 3,
        format: (percent?: number) =>
          percent ? `${parseFloat(percent.toFixed(2))}%` : "0%",
      },
      beforeUpload: (file) => {
        if (
          !validateKnowledgeBaseFileSize(file, t, message) ||
          !validateFileType(file, t, message)
        ) {
          return Upload.LIST_IGNORE;
        }
        return true;
      },
    };

    return (
      <UploadAreaUI
        fileList={fileList}
        uploadProps={uploadProps}
        isLoading={isLoading}
        isKnowledgeBaseReady={isKnowledgeBaseReady}
        isCreatingMode={isCreatingMode}
        nameStatus={nameStatus}
        isUploading={isUploading}
        disabled={disabled}
        disabledMessage={disabledMessage}
        componentHeight={componentHeight}
        newKnowledgeBaseName={newKnowledgeBaseName}
        selectedFiles={selectedFiles}
        modelMismatch={modelMismatch}
      />
    );
  }
);

export default UploadArea;
