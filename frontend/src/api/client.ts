import type { components } from "./schema";
import { getToken } from "./token";

export type AppInfo = components["schemas"]["AppInfo"];
export type VmSummary = components["schemas"]["VmSummary"];
export type VmState = VmSummary["state"];
export type DeletionPlan = components["schemas"]["DeletionPlan"];
export type DeletionResult = components["schemas"]["DeletionResult"];
export type KeepReason = components["schemas"]["KeptFile"]["reason"];
export type PowerAction = "start" | "shutdown" | "reboot" | "reset" | "poweroff";
export type LibraryInfo = components["schemas"]["LibraryInfo"];
export type FolderDeletionPlan = components["schemas"]["FolderDeletionPlan"];
export type ImportResult = components["schemas"]["ImportResult"];
export type Drift = VmSummary["drift"][number];
type ApiErrorBody = components["schemas"]["ApiError"];

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;

  constructor(status: number, code: string, detail: string) {
    super(detail);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as ApiErrorBody).error?.code === "string"
  );
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    throw new ApiError(0, "network.unreachable", String(err));
  }

  if (response.status === 204) return undefined as T;
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (isErrorBody(data)) {
      throw new ApiError(response.status, data.error.code, data.error.detail);
    }
    throw new ApiError(response.status, "http.error", `HTTP ${response.status}`);
  }
  return data as T;
}

const vmPath = (uuid: string) => `/api/vms/${encodeURIComponent(uuid)}`;

export const api = {
  info: () => request<AppInfo>("GET", "/api/info"),
  listVms: () => request<VmSummary[]>("GET", "/api/vms"),
  power: (uuid: string, action: PowerAction) =>
    request<undefined>("POST", `${vmPath(uuid)}/power/${action}`),
  rename: (uuid: string, name: string) => request<undefined>("PATCH", vmPath(uuid), { name }),
  deletionPlan: (uuid: string) => request<DeletionPlan>("GET", `${vmPath(uuid)}/deletion-plan`),
  deleteVm: (uuid: string, files: boolean) =>
    request<DeletionResult>("DELETE", `${vmPath(uuid)}?files=${files}`),
  moveVm: (uuid: string, folder: string) =>
    request<undefined>("POST", `${vmPath(uuid)}/move`, { folder }),
  importVm: (uuid: string, folder: string) =>
    request<ImportResult>("POST", `${vmPath(uuid)}/import`, { folder }),
  library: () => request<LibraryInfo>("GET", "/api/library"),
  createFolder: (path: string) =>
    request<{ path: string }>("POST", "/api/library/folders", { path }),
  renameFolder: (path: string, name: string) =>
    request<{ path: string }>("POST", "/api/library/folders/rename", { path, name }),
  folderDeletionPlan: (path: string) =>
    request<FolderDeletionPlan>(
      "GET",
      `/api/library/folders/deletion-plan?path=${encodeURIComponent(path)}`,
    ),
  deleteFolder: (path: string) =>
    request<{ failed: string[] }>(
      "DELETE",
      `/api/library/folders?path=${encodeURIComponent(path)}`,
    ),
};
