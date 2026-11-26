import { afterEach, describe, expect, it, vi } from "vitest";

import { captureToken, getToken } from "./token";

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("captureToken", () => {
  it("trades a link code for the token, once, and cleans the URL", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify({ token: "from-code" }), { status: 200 })),
    );
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState(null, "", "/#code=one-time");

    await captureToken();

    expect(window.location.hash).toBe("");
    expect(getToken()).toBe("from-code");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/redeem",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ code: "one-time" }) }),
    );
  });

  it("cleans the URL of a refused code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("{}", { status: 401 }))),
    );
    window.history.replaceState(null, "", "/#code=expired");

    await captureToken();

    expect(window.location.hash).toBe("");
  });
});
