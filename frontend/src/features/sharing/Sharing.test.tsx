import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Gate } from "../../app/Gate";
import { NotificationProvider } from "../../components/Notifications";
import { GuestLogin } from "./GuestLogin";
import { SharingPrefs } from "./SharingPrefs";

type Handler = (path: string, init?: RequestInit) => [number, unknown];

function mockFetch(handler: Handler) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      calls.push({
        method: init?.method ?? "GET",
        path,
        body: init?.body ? JSON.parse(init.body as string) : null,
      });
      const [status, body] = handler(path, init);
      return Promise.resolve(
        new Response(status === 204 ? null : JSON.stringify(body), { status }),
      );
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

const web = {
  port: 60080,
  https_port: 60443,
  share_on_lan: false,
  tls: "auto" as const,
  guest_enabled: true,
  login_max_attempts: 5,
};

describe("LAN sharing", () => {
  it("asks a browser without a session for the guest password", async () => {
    mockFetch((path) => [200, path === "/api/auth/me" ? { role: null, sharing: true } : {}]);
    render(<Gate />);
    expect(await screen.findByLabelText("Mot de passe invité")).toBeTruthy();
  });

  it("explains a wrong password and logs in with the right one", async () => {
    let right = false;
    mockFetch(() =>
      right
        ? [204, null]
        : [401, { error: { code: "auth.bad_password", detail: "Wrong password" } }],
    );
    const onLoggedIn = vi.fn();
    render(<GuestLogin onLoggedIn={onLoggedIn} />);
    const field = screen.getByLabelText("Mot de passe invité");
    fireEvent.change(field, { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(await screen.findByText("Mot de passe incorrect.")).toBeTruthy();
    right = true;
    fireEvent.change(field, { target: { value: "correct horse" } });
    fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));
    await waitFor(() => expect(onLoggedIn).toHaveBeenCalled());
  });

  it("sets the guest password before sharing can be turned on", async () => {
    let hasPassword = false;
    const calls = mockFetch((path, init) => {
      if (path === "/api/sharing/password" && init?.method === "PUT") {
        hasPassword = true;
        return [204, null];
      }
      return [
        200,
        {
          enabled: false,
          active: false,
          https_port: 60443,
          has_password: hasPassword,
          addresses: [],
          fingerprint: "",
          guests: 0,
          firewall: null,
        },
      ];
    });
    const onChange = vi.fn();
    render(
      <NotificationProvider>
        <SharingPrefs web={web} webMode onChange={onChange} />
      </NotificationProvider>,
    );
    const share = (await screen.findByRole("checkbox")) as HTMLInputElement;
    expect(share.disabled).toBe(true);
    const set = screen.getByRole("button", {
      name: "Définir le mot de passe",
    }) as HTMLButtonElement;
    fireEvent.change(screen.getByLabelText("Mot de passe invité"), { target: { value: "short" } });
    expect(set.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Mot de passe invité"), {
      target: { value: "correct horse" },
    });
    fireEvent.click(set);
    await waitFor(() => expect(share.disabled).toBe(false));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ password: "correct horse" });
    fireEvent.click(share);
    expect(onChange).toHaveBeenCalledWith({ ...web, share_on_lan: true });
  });
});
