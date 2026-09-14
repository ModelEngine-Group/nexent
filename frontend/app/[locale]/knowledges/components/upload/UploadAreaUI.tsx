import React from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { NAME_CHECK_STATUS } from "@/const/agentConfig";
import { Upload, Progress } from "antd";
import { WarningFilled } from "@ant-design/icons";
import { Inbox } from "lucide-react";
import type { UploadFile, UploadProps } from "antd/es/upload/interface";

const { Dragger } = Upload;

interface UploadAreaUIProps {
  fileList: UploadFile[];
  uploadProps: UploadProps;
  isLoading: boolean;
  isKnowledgeBaseReady: boolean;
  isCreatingMode: boolean;
  nameStatus: string;
  isUploading: boolean;
  disabled: boolean;
  disabledMessage?: string;
  componentHeight: string;
  newKnowledgeBaseName: string;
  selectedFiles: File[];
  modelMismatch?: boolean;
}

interface UploadStateProps {
  t: TFunction;
  componentHeightStyle: React.CSSProperties;
  isCreatingMode: boolean;
  isUploading: boolean;
}

const getUploadShellClassName = (isCreatingMode: boolean) => {
  const modeClassName = isCreatingMode
    ? "border-0 bg-transparent px-0 pb-0 pt-0"
    : "border-0 bg-transparent p-0";
  const sizeClassName = isCreatingMode
    ? "h-[146px] min-h-[146px]"
    : "min-h-[150px]";
  return `${modeClassName} ${sizeClassName}`;
};

const LoadingUploadState = ({
  t,
  componentHeightStyle,
  isCreatingMode,
  isUploading,
}: UploadStateProps) => (
  <div
    className={getUploadShellClassName(isCreatingMode)}
    style={componentHeightStyle}
  >
    <div className="flex items-center justify-center h-full">
      <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500 mx-auto mb-2"></div>
      <p className="text-sm font-medium text-blue-600 ml-2">
        {t("common.loading")}
      </p>
    </div>
    {isCreatingMode && isUploading && (
      <div className="mt-2 text-center">
        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500 mx-auto mb-2"></div>
        <p className="text-sm font-medium text-blue-600">
          {t("knowledgeBase.status.uploadingAndCreating")}
        </p>
      </div>
    )}
  </div>
);

const KnowledgeBaseNotReadyState = ({
  t,
  componentHeightStyle,
}: Pick<UploadStateProps, "t" | "componentHeightStyle">) => (
  <div
    className="min-h-[150px] border-0 bg-transparent p-0"
    style={componentHeightStyle}
  >
    <div className="flex h-full flex-col items-center justify-center rounded-md border-2 border-dashed border-gray-200 bg-white">
      <WarningFilled className="text-[32px] text-yellow-500 mb-4" />
      <p className="text-base text-gray-600 mb-2">
        {t("knowledgeBase.status.notReady")}
      </p>
      <p className="text-sm text-gray-400">{t("common.retryLater")}</p>
    </div>
  </div>
);

const DisabledUploadState = ({
  t,
  componentHeightStyle,
  disabledMessage,
}: Pick<UploadStateProps, "t" | "componentHeightStyle"> & {
  disabledMessage?: string;
}) => (
  <div
    className="min-h-[150px] border-0 bg-transparent p-0 opacity-50 cursor-not-allowed"
    style={componentHeightStyle}
  >
    <div className="flex h-full flex-col items-center justify-center rounded-md border-2 border-dashed border-gray-300 bg-white p-4 text-center">
      <div className="mb-0.5 text-lg text-blue-500">📄</div>
      <p className="mb-0.5 text-xs font-medium text-gray-700">
        {disabledMessage || t("knowledgeBase.hint.selectFirst")}
      </p>
    </div>
  </div>
);

const NameExistsUploadState = ({
  t,
  componentHeightStyle,
  newKnowledgeBaseName,
  nameStatus,
}: Pick<UploadStateProps, "t" | "componentHeightStyle"> & {
  newKnowledgeBaseName: string;
  nameStatus: string;
}) => {
  const messageKey =
    nameStatus === NAME_CHECK_STATUS.EXISTS_IN_TENANT
      ? "knowledgeBase.message.nameExists"
      : "knowledgeBase.error.nameExistsInOtherTenant";

  return (
    <div className={getUploadShellClassName(true)} style={componentHeightStyle}>
      <div className="flex h-full flex-col items-center justify-center rounded-2xl border-2 border-dashed border-red-200 bg-red-50/30 p-4 text-center">
        <div className="mb-4 text-lg text-red-500">
          <WarningFilled style={{ fontSize: 36, color: "#ff4d4f" }} />
        </div>
        <p className="mb-2 text-lg font-medium text-red-600">
          {t(messageKey, { name: newKnowledgeBaseName })}
        </p>
        <p className="max-w-md text-sm text-gray-500">
          {t("knowledgeBase.hint.changeName")}
        </p>
      </div>
    </div>
  );
};

const ModelMismatchUploadState = ({
  t,
  componentHeightStyle,
}: Pick<UploadStateProps, "t" | "componentHeightStyle">) => (
  <div
    className="flex min-h-[150px] items-center justify-center border-0 bg-transparent p-0"
    style={componentHeightStyle}
  >
    <span className="text-center text-base font-medium leading-[1.7] text-gray-500">
      {t("knowledgeBase.upload.modelMismatch.description")}
    </span>
  </div>
);

const UploadFileProgress = ({ file }: { file: UploadFile }) => {
  if (file.status !== "uploading") return null;

  return (
    <div className="mt-1">
      <Progress
        percent={file.percent}
        size="small"
        showInfo={false}
        strokeColor={{
          "0%": "#108ee9",
          "100%": "#87d068",
        }}
      />
    </div>
  );
};

const UploadFileStatus = ({
  status,
  t,
}: {
  status?: UploadFile["status"];
  t: TFunction;
}) => {
  if (status === "uploading") {
    return (
      <span className="text-xs text-blue-500">
        {t("knowledgeBase.upload.status.uploading")}
      </span>
    );
  }
  if (status === "done") {
    return (
      <span className="text-xs text-green-500">
        {t("knowledgeBase.upload.status.completed")}
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="text-xs text-red-500">
        {t("knowledgeBase.upload.status.failed")}
      </span>
    );
  }
  return null;
};

const UploadedFilesPanel = ({
  fileList,
  hasFiles,
  t,
}: {
  fileList: UploadFile[];
  hasFiles: boolean;
  t: TFunction;
}) => (
  <div
    className={`overflow-hidden rounded-lg transition-all duration-300 ease-in-out ${
      hasFiles ? "w-[60%] pl-2 opacity-100" : "w-0 opacity-0"
    }`}
  >
    {hasFiles && (
      <div className="h-full">
        <div className="h-full rounded-lg border border-gray-200">
          <div className="flex items-center justify-between border-b border-gray-100 bg-gray-50 p-3">
            <h4 className="m-0 text-sm font-medium text-gray-700">
              {t("knowledgeBase.upload.completed")}
            </h4>
            <span className="text-xs text-gray-500">
              {t("knowledgeBase.upload.fileCount", {
                count: fileList.length,
              })}
            </span>
          </div>
          <div className="h-[calc(100%_-_41px)] overflow-auto">
            {fileList.map((file) => (
              <div
                key={file.uid}
                className="border-b border-gray-100 last:border-b-0"
              >
                <div className="flex items-center justify-between px-3 py-2 transition-colors hover:bg-gray-50">
                  <div className="flex min-w-0 flex-1 items-center">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs font-medium text-gray-700">
                        {file.name}
                      </div>
                      <UploadFileProgress file={file} />
                    </div>
                  </div>
                  <div className="ml-3 flex items-center">
                    <UploadFileStatus status={file.status} t={t} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    )}
  </div>
);

const UploadDropZone = ({
  uploadProps,
  isCreatingMode,
  t,
}: {
  uploadProps: UploadProps;
  isCreatingMode: boolean;
  t: TFunction;
}) => (
  <div className="relative h-full">
    <div
      className="absolute inset-0 transition-opacity duration-300 ease-in-out"
      onDragOver={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
      onDragEnter={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
    >
      <div className="h-full">
        <Dragger
          {...uploadProps}
          className={`!h-full flex flex-col justify-center !rounded-2xl !border-2 !border-dashed ${
            isCreatingMode
              ? "!border-blue-300 !bg-white shadow-sm"
              : "!border-blue-200 !bg-blue-50/30"
          }`}
          showUploadList={false}
          style={{
            height: "100%",
            overflow: isCreatingMode ? "hidden" : "auto",
          }}
        >
          <div className="flex flex-col items-center justify-center">
            <p
              className={`ant-upload-drag-icon ${
                isCreatingMode ? "!mb-2" : "!mb-4"
              }`}
            >
              <Inbox
                size={isCreatingMode ? 32 : 48}
                className="text-blue-600"
              />
            </p>
            <p
              className={`ant-upload-text ${
                isCreatingMode ? "!mb-1 text-sm" : "!mb-2 text-base"
              }`}
            >
              {t("knowledgeBase.upload.dragHint")}
            </p>
            <p
              className={`ant-upload-hint text-gray-500 ${
                isCreatingMode ? "text-xs" : ""
              }`}
            >
              {t("knowledgeBase.upload.supportedFormats")}
            </p>
            <p
              className={`ant-upload-hint text-gray-500 ${
                isCreatingMode ? "!mt-0 text-xs" : "!mt-1"
              }`}
            >
              {t("knowledgeBase.upload.fileSizeLimit")}
            </p>
          </div>
        </Dragger>
      </div>
    </div>
  </div>
);

const DefaultUploadState = ({
  t,
  componentHeightStyle,
  isCreatingMode,
  isUploading,
  fileList,
  uploadProps,
}: UploadStateProps & {
  fileList: UploadFile[];
  uploadProps: UploadProps;
}) => {
  const hasFiles = fileList.length > 0;

  return (
    <div
      className={getUploadShellClassName(isCreatingMode)}
      style={componentHeightStyle}
    >
      <div className="flex h-full transition-all duration-300 ease-in-out">
        <div
          className={`transition-all duration-300 ease-in-out ${
            hasFiles ? "w-[40%] pr-2" : "w-full"
          }`}
        >
          <UploadDropZone
            uploadProps={uploadProps}
            isCreatingMode={isCreatingMode}
            t={t}
          />
        </div>
        <UploadedFilesPanel fileList={fileList} hasFiles={hasFiles} t={t} />
      </div>

      {isCreatingMode && isUploading && (
        <div className="mt-2 text-center">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500 mx-auto mb-2"></div>
          <p className="text-sm font-medium text-blue-600">
            {t("knowledgeBase.status.uploadingAndCreating")}
          </p>
        </div>
      )}
    </div>
  );
};

const UploadAreaUI: React.FC<UploadAreaUIProps> = ({
  fileList,
  uploadProps,
  isLoading,
  isKnowledgeBaseReady,
  isCreatingMode,
  nameStatus,
  isUploading,
  disabled,
  disabledMessage,
  componentHeight,
  newKnowledgeBaseName,
  modelMismatch = false,
}) => {
  const { t } = useTranslation("common");
  const resolvedComponentHeight = isCreatingMode ? "146px" : componentHeight;
  const componentHeightStyle = {
    height: resolvedComponentHeight,
    minHeight: resolvedComponentHeight,
  };

  // Loading state UI
  if (isLoading) {
    return (
      <LoadingUploadState
        t={t}
        componentHeightStyle={componentHeightStyle}
        isCreatingMode={isCreatingMode}
        isUploading={isUploading}
      />
    );
  }

  // Knowledge base not ready UI
  if (!isKnowledgeBaseReady && !isCreatingMode) {
    return (
      <KnowledgeBaseNotReadyState
        t={t}
        componentHeightStyle={componentHeightStyle}
      />
    );
  }

  // Disabled state UI
  if (disabled) {
    return (
      <DisabledUploadState
        t={t}
        componentHeightStyle={componentHeightStyle}
        disabledMessage={disabledMessage}
      />
    );
  }

  // Name already exists UI - render different messages based on status
  if (
    isCreatingMode &&
    (nameStatus === NAME_CHECK_STATUS.EXISTS_IN_TENANT ||
      nameStatus === NAME_CHECK_STATUS.EXISTS_IN_OTHER_TENANT)
  ) {
    return (
      <NameExistsUploadState
        t={t}
        componentHeightStyle={componentHeightStyle}
        newKnowledgeBaseName={newKnowledgeBaseName}
        nameStatus={nameStatus}
      />
    );
  }

  // Model mismatch status UI
  if (modelMismatch) {
    return (
      <ModelMismatchUploadState
        t={t}
        componentHeightStyle={componentHeightStyle}
      />
    );
  }

  // Default UI state
  return (
    <DefaultUploadState
      t={t}
      componentHeightStyle={componentHeightStyle}
      isCreatingMode={isCreatingMode}
      isUploading={isUploading}
      fileList={fileList}
      uploadProps={uploadProps}
    />
  );
};

export default UploadAreaUI;
