import { Info } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, type Network, type PortForward } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { ErrorMessage } from "../../components/ErrorMessage";
import { useNotifier } from "../../components/notifier";

const toApiError = (err: unknown) =>
  err instanceof ApiError ? err : new ApiError(0, "http.error", String(err));

const EMPTY: PortForward = {
  proto: "tcp",
  host_address: "127.0.0.1",
  host_port: 8080,
  vm_ip: "",
  vm_port: 80,
  description: "",
};

/** One rule: the administrator writes every field; the helper checks them. */
function RuleDialog({
  initial,
  inUse,
  onSave,
  onClose,
}: {
  initial: PortForward;
  inUse: { tcp: number[]; udp: number[] } | null;
  onSave: (rule: PortForward) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [rule, setRule] = useState(initial);
  const [hostPort, setHostPort] = useState(String(initial.host_port));
  const [vmPort, setVmPort] = useState(String(initial.vm_port));
  const set = (patch: Partial<PortForward>) => setRule({ ...rule, ...patch });
  const port = Number(hostPort);
  const busy = inUse !== null && inUse[rule.proto].includes(port) && port !== initial.host_port;

  return (
    <Dialog
      open
      width={460}
      onOpenChange={(open) => !open && onClose()}
      title={t("networks.forwardTitle")}
      buttons={
        <>
          <button
            type="button"
            className="button button-primary"
            disabled={!hostPort.trim() || !vmPort.trim() || !rule.vm_ip.trim()}
            onClick={() => {
              onSave({
                ...rule,
                host_address: rule.host_address.trim(),
                vm_ip: rule.vm_ip.trim(),
                host_port: Number(hostPort),
                vm_port: Number(vmPort),
              });
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
      <div className="net-form">
        <label>
          {t("networks.forwardHostAddress")}
          <input
            type="text"
            value={rule.host_address}
            onChange={(e) => set({ host_address: e.target.value })}
          />
        </label>
        <label>
          {t("networks.forwardHostPort")}
          <input type="text" value={hostPort} onChange={(e) => setHostPort(e.target.value)} />
        </label>
        <label>
          {t("networks.forwardType")}
          <select
            value={rule.proto}
            onChange={(e) => set({ proto: e.target.value as PortForward["proto"] })}
          >
            {(["tcp", "udp"] as const).map((proto) => (
              <option key={proto} value={proto}>
                {proto.toUpperCase()}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("networks.forwardVmIp")}
          <input type="text" value={rule.vm_ip} onChange={(e) => set({ vm_ip: e.target.value })} />
        </label>
        <label>
          {t("networks.forwardVmPort")}
          <input type="text" value={vmPort} onChange={(e) => setVmPort(e.target.value)} />
        </label>
        <label>
          {t("networks.forwardDescription")}
          <input
            type="text"
            value={rule.description}
            onChange={(e) => set({ description: e.target.value })}
          />
        </label>
      </div>
      {busy && (
        <p className="note">
          <Info aria-hidden />
          <span>{t("networks.portInUse", { port, proto: rule.proto.toUpperCase() })}</span>
        </p>
      )}
    </Dialog>
  );
}

/** NAT Settings of a network: its gateway, and the port forwarding rules. */
export function NatSettingsDialog({ network, onClose }: { network: Network; onClose: () => void }) {
  const { t } = useTranslation();
  const { notifyError } = useNotifier();
  const [rules, setRules] = useState<PortForward[] | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [editing, setEditing] = useState<{ index: number | null; rule: PortForward } | null>(null);
  const [inUse, setInUse] = useState<{ tcp: number[]; udp: number[] } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .portForwards(network.name)
      .then((r) => !cancelled && setRules(r.rules))
      .catch((err: unknown) => {
        if (!cancelled) {
          setRules([]);
          setLoadError(err);
        }
      });
    api
      .portsInUse()
      .then((p) => !cancelled && setInUse(p))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [network.name]);

  const save = () => {
    if (!rules) return;
    setBusy(true);
    api
      .setPortForwards(network.name, rules)
      .then(onClose)
      .catch((err: unknown) => {
        setBusy(false);
        notifyError(t("networks.forwardFailed", { name: network.name }), err);
      });
  };

  const rule = selected !== null ? (rules?.[selected] ?? null) : null;
  return (
    <>
      <Dialog
        open
        width={640}
        onOpenChange={(open) => !open && onClose()}
        title={t("networks.natSettingsTitle", { name: network.name })}
        buttons={
          <>
            <button
              type="button"
              className="button button-primary"
              disabled={busy || rules === null}
              onClick={save}
            >
              {t("common.ok")}
            </button>
            <button type="button" className="button" onClick={onClose}>
              {t("common.cancel")}
            </button>
          </>
        }
      >
        <p>
          {t("networks.natGateway")} <span className="mono">{network.host_ip ?? "-"}</span>
        </p>
        <p className="check-hint">{t("networks.hostIpNat")}</p>
        {loadError !== null && <ErrorMessage error={toApiError(loadError)} />}
        <fieldset className="group">
          <legend>{t("networks.portForwarding")}</legend>
          <div className="list net-forwards">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("networks.forwardHostPort")}</th>
                  <th>{t("networks.forwardType")}</th>
                  <th>{t("networks.forwardVmIp")}</th>
                  <th>{t("networks.forwardVmPort")}</th>
                  <th>{t("networks.forwardDescription")}</th>
                </tr>
              </thead>
              <tbody>
                {(rules ?? []).map((r, i) => (
                  <tr
                    key={`${r.proto}-${r.host_address}-${r.host_port}-${i}`}
                    className={i === selected ? "selected" : undefined}
                    aria-selected={i === selected}
                    onClick={() => setSelected(i)}
                    onDoubleClick={() => setEditing({ index: i, rule: r })}
                  >
                    <td>
                      {r.host_port}
                      {r.host_address !== "127.0.0.1" && (
                        <span className="muted"> ({r.host_address})</span>
                      )}
                    </td>
                    <td>{r.proto.toUpperCase()}</td>
                    <td className="mono">{r.vm_ip}</td>
                    <td>{r.vm_port}</td>
                    <td>{r.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="net-row-buttons">
            <button
              type="button"
              className="button"
              disabled={rules === null}
              onClick={() => setEditing({ index: null, rule: EMPTY })}
            >
              {t("networks.forwardAdd")}
            </button>
            <button
              type="button"
              className="button"
              disabled={rule === null}
              onClick={() => {
                setRules((rules ?? []).filter((_, i) => i !== selected));
                setSelected(null);
              }}
            >
              {t("networks.forwardRemove")}
            </button>
            <button
              type="button"
              className="button"
              disabled={rule === null}
              onClick={() => rule && selected !== null && setEditing({ index: selected, rule })}
            >
              {t("networks.properties")}
            </button>
          </div>
          <p className="check-hint">{t("networks.forwardHint")}</p>
        </fieldset>
      </Dialog>
      {editing && (
        <RuleDialog
          initial={editing.rule}
          inUse={inUse}
          onClose={() => setEditing(null)}
          onSave={(r) =>
            setRules((all) => {
              const list = [...(all ?? [])];
              if (editing.index === null) list.push(r);
              else list[editing.index] = r;
              return list;
            })
          }
        />
      )}
    </>
  );
}
