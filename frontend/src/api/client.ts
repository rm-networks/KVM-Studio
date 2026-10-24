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
export type Network = components["schemas"]["Network"];
export type NetworkSettings = components["schemas"]["NetworkSettings"];
export type NetworkCreate = components["schemas"]["NetworkCreate"];
export type NetworkSuggestion = components["schemas"]["Suggestion"];
export type NetworkExport = components["schemas"]["NetworkExport-Output"];
export type NetworkImport = components["schemas"]["NetworkExport-Input"];
export type ImportReport = components["schemas"]["ImportReport"];
export type Config = Required<components["schemas"]["Config"]>;
export type DisplayInfo = components["schemas"]["DisplayInfo"];
export type IsoLibrary = components["schemas"]["IsoLibrary"];
export type Preferences = components["schemas"]["Preferences"] & { config: Config };
export type SaveResult = components["schemas"]["SaveResult"];
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
  display: (uuid: string) => request<DisplayInfo>("GET", `${vmPath(uuid)}/display`),
  addVnc: (uuid: string) =>
    request<{ restart_required: boolean }>("POST", `${vmPath(uuid)}/display/vnc`),
  preferences: () => request<Preferences>("GET", "/api/preferences"),
  savePreferences: (config: Config) => request<SaveResult>("PUT", "/api/preferences", config),
  networks: () => request<Network[]>("GET", "/api/networks"),
  networkSuggestion: () => request<NetworkSuggestion>("GET", "/api/networks/suggestion"),
  createNetwork: (body: NetworkCreate) => request<Network>("POST", "/api/networks", body),
  updateNetwork: (name: string, body: NetworkSettings) =>
    request<undefined>("PUT", `/api/networks/${encodeURIComponent(name)}`, body),
  renameNetwork: (name: string, newName: string) =>
    request<undefined>("POST", `/api/networks/${encodeURIComponent(name)}/rename`, {
      name: newName,
    }),
  setNetworkState: (name: string, state: { active?: boolean; autostart?: boolean }) =>
    request<undefined>("PATCH", `/api/networks/${encodeURIComponent(name)}`, state),
  deleteNetwork: (name: string) =>
    request<undefined>("DELETE", `/api/networks/${encodeURIComponent(name)}`),
  restoreDefaultNetworks: () => request<string[]>("POST", "/api/networks/defaults"),
  exportNetworks: () => request<NetworkExport>("GET", "/api/networks/export"),
  importNetworks: (body: NetworkImport) =>
    request<ImportReport>("POST", "/api/networks/import", body),
  deleteFolder: (path: string) =>
    request<{ failed: string[] }>(
      "DELETE",
      `/api/library/folders?path=${encodeURIComponent(path)}`,
    ),
};
