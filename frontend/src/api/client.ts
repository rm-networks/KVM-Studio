import type { components } from "./schema";
import { getToken } from "./token";

export type AppInfo = components["schemas"]["AppInfo"];
export type AuthMe = components["schemas"]["Me"];
export type SharingState = components["schemas"]["SharingState"];
export type DiskSize = components["schemas"]["DiskSize"];
export type VmSummary = components["schemas"]["VmSummary"];
export type VmState = VmSummary["state"];
export type DeletionPlan = components["schemas"]["DeletionPlan"];
export type DeletionResult = components["schemas"]["DeletionResult"];
export type KeepReason = components["schemas"]["KeptFile"]["reason"];
export type PowerAction = "start" | "shutdown" | "reboot" | "reset" | "poweroff";
export type LibraryInfo = components["schemas"]["LibraryInfo"];
export type FolderDeletionPlan = components["schemas"]["FolderDeletionPlan"];
export type FolderMovePlan = components["schemas"]["FolderMovePlan"];
export type ImportResult = components["schemas"]["ImportResult"];
export type Drift = VmSummary["drift"][number];
export type Network = components["schemas"]["Network"];
// Fields with a default on the server stay optional here.
type Defaulted<T> = Omit<T, "gateway"> & Partial<Pick<T & { gateway: unknown }, "gateway">>;
export type NetworkSettings = Defaulted<components["schemas"]["NetworkSettings"]>;
export type NetworkCreate = Defaulted<components["schemas"]["NetworkCreate"]>;
export type NetworkSuggestion = components["schemas"]["Suggestion"];
export type NetworkExport = components["schemas"]["NetworkExport-Output"];
export type NetworkImport = components["schemas"]["NetworkExport-Input"];
export type ImportReport = components["schemas"]["ImportReport"];
export type Config = Required<components["schemas"]["Config"]>;
export type DisplayInfo = components["schemas"]["DisplayInfo"];
export type IsoListing = components["schemas"]["IsoListing"];
export type IsoFile = components["schemas"]["IsoFile"];
export type AccessReport = components["schemas"]["AccessReport"];
export type CdromDevice = components["schemas"]["CdromDevice"];
export type ProfileInfo = components["schemas"]["ProfileInfo"];
export type HostCapabilities = components["schemas"]["HostInfo"];
export type NewVmRequest = components["schemas"]["NewVmRequest"];
export type Hardware = components["schemas"]["Hardware"];
export type Drive = components["schemas"]["Drive"];
export type HardwareNic = components["schemas"]["Nic"];
export type NicChange = components["schemas"]["NicChange"];
export type VmOptions = components["schemas"]["Options"];
export type VmOptionsChange = components["schemas"]["OptionsChange"];
export type BootDevice = components["schemas"]["BootDevice"];
export type PortForward = components["schemas"]["PortForward"];
export type Snapshot = components["schemas"]["Snapshot"];
export type SnapshotLimits = components["schemas"]["SnapshotLimits"];
export type RunningVm = components["schemas"]["RunningVm"];
export type CloseResult = components["schemas"]["ActionResult"];
export type IsoLibrary = components["schemas"]["IsoLibrary"];
export type Preferences = components["schemas"]["Preferences"] & { config: Config };
export type SaveResult = components["schemas"]["SaveResult"];
export type NewIsoLibrary = components["schemas"]["NewIsoLibrary"];
export type IsoLibraryChange = components["schemas"]["IsoLibraryChange"] & { config: Config };
export type GuestToolsInfo = components["schemas"]["GuestToolsInfo"];
export type GuestFamily = components["schemas"]["InsertRequest"]["family"];
export type InsertResult = components["schemas"]["InsertResult"];
export type SetupStatus = components["schemas"]["SetupStatus"];
export type GroupState = SetupStatus["libvirt_group"];
export type UninstallPlan = components["schemas"]["UninstallPlan"];
export type UninstallRequest = components["schemas"]["UninstallRequest"];
export type UninstallReport = components["schemas"]["UninstallReport"];
export type CloneRequest = components["schemas"]["CloneRequest"];
export type TaskInfo = components["schemas"]["TaskInfo"];
export type PackageState = components["schemas"]["PackageState"];
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
  me: () => request<AuthMe>("GET", "/api/auth/me"),
  login: (password: string) => request<undefined>("POST", "/api/auth/login", { password }),
  logout: () => request<undefined>("POST", "/api/auth/logout"),
  sharing: () => request<SharingState>("GET", "/api/sharing"),
  setGuestPassword: (password: string) =>
    request<undefined>("PUT", "/api/sharing/password", { password }),
  listVms: () => request<VmSummary[]>("GET", "/api/vms"),
  /** force: start a VM even though linked clones depend on its disks. */
  power: (uuid: string, action: PowerAction, force = false) =>
    request<undefined>("POST", `${vmPath(uuid)}/power/${action}${force ? "?force=true" : ""}`),
  cloneVm: (uuid: string, body: CloneRequest) =>
    request<TaskInfo>("POST", `${vmPath(uuid)}/clone`, body),
  linkedClones: (uuid: string) =>
    request<{ names: string[] }>("GET", `${vmPath(uuid)}/linked-clones`),
  task: (id: string) => request<TaskInfo>("GET", `/api/tasks/${encodeURIComponent(id)}`),
  cancelTask: (id: string) =>
    request<TaskInfo>("POST", `/api/tasks/${encodeURIComponent(id)}/cancel`),
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
  folderMovePlan: (path: string, parent: string) =>
    request<FolderMovePlan>(
      "GET",
      `/api/library/folders/move-plan?path=${encodeURIComponent(path)}&parent=${encodeURIComponent(parent)}`,
    ),
  moveFolder: (path: string, parent: string, before: string | null) =>
    request<{ path: string }>("POST", "/api/library/folders/move", { path, parent, before }),
  setFolderOrder: (parent: string, names: string[]) =>
    request<undefined>("PUT", "/api/library/order", { parent, names }),
  folderDeletionPlan: (path: string) =>
    request<FolderDeletionPlan>(
      "GET",
      `/api/library/folders/deletion-plan?path=${encodeURIComponent(path)}`,
    ),
  profiles: () => request<ProfileInfo[]>("GET", "/api/profiles"),
  guessProfile: (iso: string) =>
    request<{ profile: string }>("GET", `/api/profiles/guess?iso=${encodeURIComponent(iso)}`),
  host: () => request<HostCapabilities>("GET", "/api/host"),
  createVm: (body: NewVmRequest) => request<{ uuid: string }>("POST", "/api/vms", body),
  hardware: (uuid: string) => request<Hardware>("GET", `${vmPath(uuid)}/hardware`),
  snapshots: (uuid: string) => request<Snapshot[]>("GET", `${vmPath(uuid)}/snapshots`),
  snapshotLimits: (uuid: string) =>
    request<SnapshotLimits>("GET", `${vmPath(uuid)}/snapshots/limits`),
  takeSnapshot: (uuid: string, name: string, description: string, memory: boolean) =>
    request<TaskInfo>("POST", `${vmPath(uuid)}/snapshots`, { name, description, memory }),
  revertSnapshot: (uuid: string, name: string) =>
    request<undefined>("POST", `${vmPath(uuid)}/snapshots/${encodeURIComponent(name)}/revert`),
  deleteSnapshot: (uuid: string, name: string) =>
    request<undefined>("DELETE", `${vmPath(uuid)}/snapshots/${encodeURIComponent(name)}`),
  options: (uuid: string) => request<VmOptions>("GET", `${vmPath(uuid)}/options`),
  setOptions: (uuid: string, change: VmOptionsChange) =>
    request<{ restart_required: boolean }>("PUT", `${vmPath(uuid)}/options`, change),
  setCpuMemory: (uuid: string, memory_mib: number, vcpus: number) =>
    request<{ restart_required: boolean }>("PUT", `${vmPath(uuid)}/hardware/cpu-memory`, {
      memory_mib,
      vcpus,
    }),
  addNic: (uuid: string, network: string, model: string) =>
    request<HardwareNic>("POST", `${vmPath(uuid)}/nics`, { network, model }),
  changeNic: (uuid: string, mac: string, change: NicChange) =>
    request<{ restart_required: boolean }>(
      "PATCH",
      `${vmPath(uuid)}/nics/${encodeURIComponent(mac)}`,
      change,
    ),
  removeNic: (uuid: string, mac: string) =>
    request<undefined>("DELETE", `${vmPath(uuid)}/nics/${encodeURIComponent(mac)}`),
  addCdrom: (uuid: string, path: string | null) =>
    request<{ restart_required: boolean }>("POST", `${vmPath(uuid)}/cdroms`, { path }),
  removeCdrom: (uuid: string, target: string) =>
    request<{ restart_required: boolean }>(
      "DELETE",
      `${vmPath(uuid)}/cdroms/${encodeURIComponent(target)}`,
    ),
  isos: () => request<IsoListing>("GET", "/api/isos"),
  isoAccess: (path: string) =>
    request<AccessReport>("GET", `/api/isos/access?path=${encodeURIComponent(path)}`),
  fixIsoAccess: (path: string) => request<AccessReport>("POST", "/api/isos/access/fix", { path }),
  cdroms: (uuid: string) => request<CdromDevice[]>("GET", `${vmPath(uuid)}/cdroms`),
  changeMedia: (uuid: string, target: string, path: string | null) =>
    request<undefined>("PUT", `${vmPath(uuid)}/cdroms/${encodeURIComponent(target)}`, { path }),
  diskSize: (uuid: string, target: string) =>
    request<DiskSize>("GET", `${vmPath(uuid)}/disks/${encodeURIComponent(target)}`),
  expandDisk: (uuid: string, target: string, gib: number) =>
    request<DiskSize>("POST", `${vmPath(uuid)}/disks/${encodeURIComponent(target)}/expand`, {
      gib,
    }),
  display: (uuid: string) => request<DisplayInfo>("GET", `${vmPath(uuid)}/display`),
  guestTools: (uuid: string) => request<GuestToolsInfo>("GET", `${vmPath(uuid)}/guest-tools`),
  insertGuestTools: (uuid: string, family: GuestFamily) =>
    request<InsertResult>("POST", `${vmPath(uuid)}/guest-tools`, { family }),
  ejectGuestTools: (uuid: string) =>
    request<{ drives: string[] }>("POST", `${vmPath(uuid)}/guest-tools/eject`),
  agentStatus: (uuid: string) => request<{ responding: boolean }>("GET", `${vmPath(uuid)}/agent`),
  addVnc: (uuid: string) =>
    request<{ restart_required: boolean }>("POST", `${vmPath(uuid)}/display/vnc`),
  enableClipboard: (uuid: string) =>
    request<{ restart_required: boolean }>("POST", `${vmPath(uuid)}/display/clipboard`),
  runningVms: () => request<RunningVm[]>("GET", "/api/session/running"),
  closeAction: (action: "suspend" | "shutdown" | "poweroff") =>
    request<CloseResult>("POST", `/api/session/running/${action}`),
  restart: () => request<{ restarting: boolean }>("POST", "/api/restart"),
  preferences: () => request<Preferences>("GET", "/api/preferences"),
  savePreferences: (config: Config) => request<SaveResult>("PUT", "/api/preferences", config),
  addIsoLibrary: (library: NewIsoLibrary) =>
    request<IsoLibraryChange>("POST", "/api/preferences/iso-libraries", library),
  removeIsoLibrary: (path: string) =>
    request<IsoLibraryChange>("POST", "/api/preferences/iso-libraries/remove", { path }),
  networks: () => request<Network[]>("GET", "/api/networks"),
  networkSuggestion: () => request<NetworkSuggestion>("GET", "/api/networks/suggestion"),
  createNetwork: (body: NetworkCreate) => request<Network>("POST", "/api/networks", body),
  updateNetwork: (name: string, body: NetworkSettings, stopVms?: "shutdown" | "poweroff") =>
    request<undefined>("PUT", `/api/networks/${encodeURIComponent(name)}`, {
      ...body,
      stop_vms: stopVms ?? null,
    }),
  portForwards: (name: string) =>
    request<{ rules: PortForward[] }>("GET", `/api/networks/${encodeURIComponent(name)}/forwards`),
  setPortForwards: (name: string, rules: PortForward[]) =>
    request<{ rules: PortForward[] }>("PUT", `/api/networks/${encodeURIComponent(name)}/forwards`, {
      rules,
    }),
  portsInUse: () =>
    request<{ tcp: number[]; udp: number[] }>("GET", "/api/networks/host/ports-in-use"),
  networkPlan: (name: string, body: NetworkSettings) =>
    request<{ restart: boolean; running: string[] }>(
      "POST",
      `/api/networks/${encodeURIComponent(name)}/plan`,
      body,
    ),
  renameNetwork: (name: string, newName: string) =>
    request<undefined>("POST", `/api/networks/${encodeURIComponent(name)}/rename`, {
      name: newName,
    }),
  setNetworkState: (name: string, state: { active?: boolean; autostart?: boolean }) =>
    request<undefined>("PATCH", `/api/networks/${encodeURIComponent(name)}`, state),
  deleteNetwork: (name: string) =>
    request<undefined>("DELETE", `/api/networks/${encodeURIComponent(name)}`),
  restoreDefaultNetworks: () => request<string[]>("POST", "/api/networks/defaults"),
  setup: () => request<SetupStatus>("GET", "/api/setup"),
  joinLibvirtGroup: () =>
    request<{ libvirt_group: GroupState }>("POST", "/api/setup/libvirt-group"),
  createDefaultNetworks: () => request<string[]>("POST", "/api/setup/networks"),
  uninstallPlan: () => request<UninstallPlan>("GET", "/api/uninstall/plan"),
  uninstall: (body: UninstallRequest) => request<UninstallReport>("POST", "/api/uninstall", body),
  removePackage: () => request<PackageState>("POST", "/api/uninstall/package"),
  packageState: () => request<PackageState>("GET", "/api/uninstall/package"),
  exportNetworks: () => request<NetworkExport>("GET", "/api/networks/export"),
  importNetworks: (body: NetworkImport) =>
    request<ImportReport>("POST", "/api/networks/import", body),
  deleteFolder: (path: string) =>
    request<{ failed: string[] }>(
      "DELETE",
      `/api/library/folders?path=${encodeURIComponent(path)}`,
    ),
};
