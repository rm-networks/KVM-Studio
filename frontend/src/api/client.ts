import type { components } from "./schema";
import { getToken } from "./token";

export type AppInfo = components["schemas"]["AppInfo"];
export type VmSummary = components["schemas"]["VmSummary"];
export type VmState = VmSummary["state"];
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

async function get<T>(path: string): Promise<T> {
  const headers: HeadersInit = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(path, { headers });
  } catch (err) {
    throw new ApiError(0, "network.unreachable", String(err));
  }

  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (isErrorBody(body)) {
      throw new ApiError(response.status, body.error.code, body.error.detail);
    }
    throw new ApiError(response.status, "http.error", `HTTP ${response.status}`);
  }
  return body as T;
}

export const api = {
  info: () => get<AppInfo>("/api/info"),
  listVms: () => get<VmSummary[]>("/api/vms"),
};
