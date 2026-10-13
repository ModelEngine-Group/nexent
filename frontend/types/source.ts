export type JsonValue =
  string | number | boolean | null | JsonValue[] | JsonObject;

export interface JsonObject {
  [key: string]: JsonValue;
}

export interface AidpDownloadLocator {
  provider: "aidp";
  kds_id: string;
  file_uuid: string;
}

export interface SourceAttributes {
  searchType?: string;
  toolSign?: string;
  sourceMetadata?: JsonObject;
  sourceReference?: Record<string, unknown>;
}
