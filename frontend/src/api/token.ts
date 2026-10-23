// The backend opens the UI with #token=... in the URL. The fragment never
// reaches the server; we keep the token for this tab only and clean the URL.

const STORAGE_KEY = "kvmstudio.token";
let memoryToken: string | null = null;

function readStorage(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStorage(token: string): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, token);
  } catch {
    // Storage can be unavailable; the in-memory copy is enough for this page.
  }
}

export function captureToken(): void {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const token = params.get("token");
  if (!token) return;
  memoryToken = token;
  writeStorage(token);
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
}

export function getToken(): string | null {
  return memoryToken ?? readStorage();
}
