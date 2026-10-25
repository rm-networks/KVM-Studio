import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Network } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { type Draft, firstHost } from "./draft";
import { intToIp, ipToInt, joinCidr } from "./subnet";

interface Props {
  network: Network;
  draft: Draft;
  onSave: (patch: Partial<Draft>) => void;
  onClose: () => void;
}

/** DHCP of a network: the gateway it announces. */
export function DhcpSettingsDialog({ network, draft, onSave, onClose }: Props) {
  const { t } = useTranslation();
  const [gateway, setGateway] = useState(draft.gateway);
  const [gatewayIp, setGatewayIp] = useState(draft.gatewayIp);
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
              onSave({ gateway, gatewayIp });
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
    </Dialog>
  );
}
