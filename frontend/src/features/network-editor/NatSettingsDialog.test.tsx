import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Network } from "../../api/client";
import { NotificationProvider } from "../../components/Notifications";
import { NatSettingsDialog } from "./NatSettingsDialog";

const network = {
  name: "kvmnet8",
  kind: "nat",
  host_ip: "192.168.108.1",
} as Network;

afterEach(() => vi.unstubAllGlobals());

describe("NatSettingsDialog", () => {
  it("adds a rule the administrator writes, and tells about a port in use", async () => {
    const puts: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, init?: RequestInit) => {
        if (init?.method === "PUT") puts.push(JSON.parse(init.body as string));
        const body = path.endsWith("ports-in-use") ? { tcp: [2222], udp: [] } : { rules: [] };
        return Promise.resolve(new Response(JSON.stringify(body)));
      }),
    );
    const onClose = vi.fn();
    render(
      <NotificationProvider>
        <NatSettingsDialog network={network} onClose={onClose} />
      </NotificationProvider>,
    );
    expect(await screen.findByText("192.168.108.1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ajouter…" }));
    expect(screen.getByDisplayValue("127.0.0.1")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Port de l'hôte"), { target: { value: "2222" } });
    expect(await screen.findByText("Le port TCP 2222 est déjà utilisé sur l'hôte.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Adresse IP de la VM"), {
      target: { value: "192.168.108.20" },
    });
    fireEvent.change(screen.getByLabelText("Port de la VM"), { target: { value: "22" } });
    // A port in use does not block anything.
    fireEvent.click(screen.getAllByRole("button", { name: "OK" }).at(-1) as HTMLElement);
    expect(await screen.findByText("192.168.108.20")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toEqual({
      rules: [
        {
          proto: "tcp",
          host_address: "127.0.0.1",
          host_port: 2222,
          vm_ip: "192.168.108.20",
          vm_port: 22,
          description: "",
        },
      ],
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
