// The window opens the UI with #token=... in the URL; a browser gets
// #code=..., a single-use code traded at once for the token, since its
// command line is readable by every account. The fragment never reaches the
// server; we keep the token for this tab only and clean the URL.

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

async function redeem(code: string): Promise<string | null> {
  try {
    const answer = await fetch("/api/auth/redeem", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    if (!answer.ok) return null;
    const body = (await answer.json()) as { token?: unknown };
    return typeof body.token === "string" ? body.token : null;
  } catch {
    return null;
  }
}

export async function captureToken(): Promise<void> {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const code = params.get("code");
  const token = params.get("token") ?? (code ? await redeem(code) : null);
  if (params.has("token") || code) {
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }
  if (!token) return;
  memoryToken = token;
  writeStorage(token);
}

export function getToken(): string | null {
  return memoryToken ?? readStorage();
}
