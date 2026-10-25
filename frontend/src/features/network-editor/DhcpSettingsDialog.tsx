import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type Network } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { type Draft, firstHost, type Reservation } from "./draft";
import { intToIp, ipToInt, joinCidr } from "./subnet";

const MAC_RE = /^([0-9a-f]{2}:){5}[0-9a-f]{2}$/i;

interface Card {
  label: string;
  mac: string;
}

/** The cards of the VMs using this network, to reserve an address without typing a MAC. */
function useCards(network: Network): Card[] {
  const [cards, setCards] = useState<Card[]>([]);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const vms = (await api.listVms()).filter((vm) => network.used_by.includes(vm.name));
        const found: Card[] = [];
        for (const vm of vms) {
          const hw = await api.hardware(vm.uuid);
          for (const nic of hw.nics) {
            if (nic.network === network.name) found.push({ label: vm.name, mac: nic.mac });
          }
        }
        if (!cancelled) setCards(found);
      } catch {
        // Typing the MAC address stays possible.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [network]);
  return cards;
}

interface Props {
  network: Network;
  draft: Draft;
  onSave: (patch: Partial<Draft>) => void;
  onClose: () => void;
}

/** DHCP of a network: the gateway it announces and the reserved addresses. */
export function DhcpSettingsDialog({ network, draft, onSave, onClose }: Props) {
  const { t } = useTranslation();
  const cards = useCards(network);
  const [gateway, setGateway] = useState(draft.gateway);
  const [gatewayIp, setGatewayIp] = useState(draft.gatewayIp);
  const [reservations, setReservations] = useState<Reservation[]>(draft.reservations);
  const [mac, setMac] = useState("");
  const [ip, setIp] = useState("");

  const macTaken = reservations.some((r) => r.mac.toLowerCase() === mac.trim().toLowerCase());
  const canAdd = MAC_RE.test(mac.trim()) && ip.trim() !== "" && !macTaken;
  const hostOnly = draft.kind === "host_only";
  // Examples taken from this network's own subnet.
  const cidr = joinCidr(draft.ip, draft.mask);
  const sample = (offset: number) => {
    const first = cidr ? ipToInt(firstHost(cidr)) : null;
    return first === null ? "" : intToIp(first + offset);
  };

  return (
    <Dialog
      open
      width={560}
      onOpenChange={(open) => !open && onClose()}
      title={t("networks.dhcpSettingsTitle", { name: network.name })}
      buttons={
        <>
          <button
            type="button"
            className="button button-primary"
            disabled={gateway === "custom" && !gatewayIp.trim()}
            onClick={() => {
              onSave({ gateway, gatewayIp, reservations });
              onClose();
            }}
          >
            {t("common.ok")}
          </button>
          <button type="button" className="button" onClick={onClose}>
            {t("common.cancel")}
          </button>
        </>
      }
    >
      <fieldset className="group">
        <legend>{t("networks.gateway")}</legend>
        {hostOnly ? (
          <>
            <label className="check">
              <input
                type="radio"
                checked={gateway === "none"}
                onChange={() => setGateway("none")}
              />
              {t("networks.gatewayNone")}
            </label>
            <label className="check">
              <input
                type="radio"
                checked={gateway === "host"}
                onChange={() => setGateway("host")}
              />
              {t("networks.gatewayHost")}
            </label>
            <label className="check">
              <input
                type="radio"
                checked={gateway === "custom"}
                onChange={() => setGateway("custom")}
              />
              {t("networks.gatewayCustom")}
              <input
                type="text"
                aria-label={t("networks.gatewayAddress")}
                value={gatewayIp}
                disabled={gateway !== "custom"}
                placeholder={sample(1)}
                onChange={(e) => setGatewayIp(e.target.value)}
              />
            </label>
            <p className="check-hint">{t("networks.gatewayHint")}</p>
          </>
        ) : (
          <p className="muted">{t("networks.gatewayNat")}</p>
        )}
      </fieldset>

      <fieldset className="group">
        <legend>{t("networks.reservations")}</legend>
        <div className="list net-reservations">
          <table className="table">
            <thead>
              <tr>
                <th>{t("networks.mac")}</th>
                <th>{t("networks.address")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {reservations.map((r) => (
                <tr key={r.mac}>
                  <td className="mono">
                    {r.mac}
                    {cards.find((c) => c.mac === r.mac) && (
                      <span className="muted"> ({cards.find((c) => c.mac === r.mac)?.label})</span>
                    )}
                  </td>
                  <td className="mono">{r.ip}</td>
                  <td>
                    <button
                      type="button"
                      className="button"
                      onClick={() => setReservations(reservations.filter((x) => x.mac !== r.mac))}
                    >
                      {t("networks.remove")}
                    </button>
                  </td>
                </tr>
              ))}
              {reservations.length === 0 && (
                <tr>
                  <td colSpan={3} className="muted">
                    {t("networks.noReservation")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="net-reservation-add">
          {cards.length > 0 && (
            <select
              aria-label={t("networks.vmCard")}
              value=""
              onChange={(e) => setMac(e.target.value)}
            >
              <option value="">{t("networks.vmCard")}</option>
              {cards.map((c) => (
                <option key={c.mac} value={c.mac}>
                  {c.label} ({c.mac})
                </option>
              ))}
            </select>
          )}
          <input
            type="text"
            aria-label={t("networks.mac")}
            placeholder="52:54:00:12:34:56"
            value={mac}
            onChange={(e) => setMac(e.target.value)}
          />
          <input
            type="text"
            aria-label={t("networks.address")}
            placeholder={sample(19)}
            value={ip}
            onChange={(e) => setIp(e.target.value)}
          />
          <button
            type="button"
            className="button"
            disabled={!canAdd}
            onClick={() => {
              setReservations([...reservations, { mac: mac.trim().toLowerCase(), ip: ip.trim() }]);
              setMac("");
              setIp("");
            }}
          >
            {t("networks.addReservation")}
          </button>
        </div>
        <p className="check-hint">{t("networks.reservationsHint")}</p>
      </fieldset>
    </Dialog>
  );
}
