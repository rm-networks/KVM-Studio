import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type Network, type NetworkImport } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { useNotifier } from "../../components/notifier";
import { PromptDialog } from "../../components/PromptDialog";
import { ConfirmDialog } from "../vm/ConfirmDialog";
import { type Draft, draftFrom, sameDraft, settingsFrom } from "./draft";
import { defaultDhcp, joinCidr } from "./subnet";
import "./NetworkEditor.css";

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,49}$/;

type Pending =
  | { kind: "delete"; network: Network }
  | { kind: "rename"; network: Network }
  | { kind: "defaults" }
  | null;

export function NetworkEditor({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const { notify, notifyError } = useNotifier();
  const [networks, setNetworks] = useState<Network[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const receive = useCallback((list: Network[]) => {
    setNetworks(list);
    setDrafts({});
    setSelected((current) =>
      current && list.some((n) => n.name === current) ? current : (list[0]?.name ?? null),
    );
  }, []);

  const fail = useCallback(
    (err: unknown) => {
      notifyError(t("networks.title"), err);
      setNetworks([]);
    },
    [notifyError, t],
  );

  const load = useCallback(() => api.networks().then(receive).catch(fail), [receive, fail]);

  useEffect(() => {
    let cancelled = false;
    api
      .networks()
      .then((list) => !cancelled && receive(list))
      .catch((err: unknown) => !cancelled && fail(err));
    return () => {
      cancelled = true;
    };
  }, [receive, fail]);

  const network = networks?.find((n) => n.name === selected) ?? null;
  const original = network ? draftFrom(network) : null;
  const draft = network ? (drafts[network.name] ?? original) : null;
  const dirtyNames = useMemo(
    () =>
      Object.entries(drafts)
        .filter(([name, d]) => {
          const n = networks?.find((x) => x.name === name);
          const base = n ? draftFrom(n) : null;
          return base !== null && !sameDraft(base, d);
        })
        .map(([name]) => name),
    [drafts, networks],
  );

  const edit = (patch: Partial<Draft>) => {
    if (!network || !draft) return;
    setDrafts((all) => ({ ...all, [network.name]: { ...draft, ...patch } }));
  };

  const run = async (action: () => Promise<unknown>, title: string) => {
    setBusy(true);
    try {
      await action();
    } catch (err) {
      notifyError(title, err);
    } finally {
      setBusy(false);
      await load();
    }
  };

  const apply = async (): Promise<boolean> => {
    let ok = true;
    setBusy(true);
    for (const name of dirtyNames) {
      const result = settingsFrom(drafts[name] as Draft);
      if ("error" in result) {
        notifyError(name, new Error(t(`networks.invalid.${result.error}`)));
        ok = false;
        continue;
      }
      try {
        await api.updateNetwork(name, result.settings);
      } catch (err) {
        notifyError(t("networks.applyFailed", { name }), err);
        ok = false;
      }
    }
    setBusy(false);
    await load();
    return ok;
  };

  const add = () =>
    run(async () => {
      const suggestion = await api.networkSuggestion();
      const created = await api.createNetwork({
        number: suggestion.number,
        kind: "host_only",
        subnet: suggestion.subnet,
        host_adapter: true,
        dhcp: suggestion.dhcp,
        autostart: true,
      });
      setSelected(created.name);
    }, t("networks.add"));

  const exportAll = () =>
    run(async () => {
      const data = await api.exportNetworks();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "kvm-studio-networks.json";
      link.click();
      URL.revokeObjectURL(link.href);
    }, t("networks.export"));

  const importFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    void run(async () => {
      const data = JSON.parse(await file.text()) as NetworkImport;
      const report = await api.importNetworks(data);
      notify(
        t("networks.imported", { count: report.created.length }),
        report.skipped.length ? t("networks.skipped", { names: report.skipped.join(", ") }) : "",
      );
    }, t("networks.import"));
  };

  const kindLabel = (n: Network, d: Draft | null) =>
    d ? t(`networks.kind.${d.kind}`) : t("networks.kind.other", { mode: n.forward_mode ?? "?" });

  const cidr = draft ? joinCidr(draft.ip, draft.mask) : null;
  const effectiveAdapter = draft ? draft.kind === "nat" || draft.hostAdapter : false;

  return (
    <>
      <Dialog
        open
        width={680}
        onOpenChange={(open) => !open && onClose()}
        title={t("networks.title")}
        buttons={
          <>
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() => setPending({ kind: "defaults" })}
            >
              {t("networks.restore")}
            </button>
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() => fileInput.current?.click()}
            >
              {t("networks.import")}
            </button>
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() => void exportAll()}
            >
              {t("networks.export")}
            </button>
            <span className="net-spacer" />
            <button
              type="button"
              className="button button-primary"
              disabled={busy}
              onClick={() => void apply().then((ok) => ok && onClose())}
            >
              {t("common.ok")}
            </button>
            <button type="button" className="button" onClick={onClose}>
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="button"
              disabled={busy || dirtyNames.length === 0}
              onClick={() => void apply()}
            >
              {t("common.apply")}
            </button>
          </>
        }
      >
        <input
          ref={fileInput}
          type="file"
          accept="application/json,.json"
          hidden
          onChange={importFile}
        />
        <div className="net-table-wrap">
          <table className="net-table">
            <thead>
              <tr>
                <th>{t("networks.col.name")}</th>
                <th>{t("networks.col.type")}</th>
                <th>{t("networks.col.external")}</th>
                <th>{t("networks.col.host")}</th>
                <th>{t("networks.col.dhcp")}</th>
                <th>{t("networks.col.subnet")}</th>
              </tr>
            </thead>
            <tbody>
              {(networks ?? []).map((n) => {
                const d = drafts[n.name] ?? draftFrom(n);
                const adapter = d ? d.kind === "nat" || d.hostAdapter : n.host_ip !== null;
                const subnet = d ? (joinCidr(d.ip, d.mask) ?? "?") : n.subnet;
                return (
                  <tr
                    key={n.name}
                    className={n.name === selected ? "selected" : undefined}
                    aria-selected={n.name === selected}
                    onClick={() => setSelected(n.name)}
                  >
                    <td>
                      {n.name}
                      {!n.active && <span className="net-muted"> ({t("networks.stopped")})</span>}
                    </td>
                    <td>{kindLabel(n, d)}</td>
                    <td>
                      {(d?.kind ?? n.forward_mode) === "nat"
                        ? "NAT"
                        : n.kind === "other"
                          ? n.forward_mode
                          : "-"}
                    </td>
                    <td>{adapter ? t("networks.connected") : "-"}</td>
                    <td>
                      {(d ? d.dhcpEnabled && adapter : n.dhcp !== null)
                        ? t("networks.enabled")
                        : "-"}
                    </td>
                    <td>{subnet ? subnet.split("/")[0] : "-"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="net-row-buttons">
          <button type="button" className="button" disabled={busy} onClick={() => void add()}>
            {t("networks.add")}
          </button>
          <button
            type="button"
            className="button"
            disabled={busy || !network}
            onClick={() => network && setPending({ kind: "delete", network })}
          >
            {t("networks.remove")}
          </button>
          <button
            type="button"
            className="button"
            disabled={busy || !network}
            onClick={() => network && setPending({ kind: "rename", network })}
          >
            {t("networks.rename")}
          </button>
        </div>

        {network && (
          <fieldset className="net-panel">
            <legend>{t("networks.info", { name: network.name })}</legend>
            {!draft ? (
              <p className="net-muted">
                {t("networks.notEditable", { mode: network.forward_mode })}
              </p>
            ) : (
              <>
                <label className="net-radio net-disabled" title={t("networks.bridgedLater")}>
                  <input type="radio" disabled /> {t("networks.bridged")}
                </label>
                <label className="net-radio">
                  <input
                    type="radio"
                    checked={draft.kind === "nat"}
                    onChange={() => edit({ kind: "nat" })}
                  />{" "}
                  {t("networks.natLabel")}
                </label>
                <label className="net-radio">
                  <input
                    type="radio"
                    checked={draft.kind === "host_only"}
                    onChange={() => edit({ kind: "host_only" })}
                  />{" "}
                  {t("networks.hostOnlyLabel")}
                </label>
                <hr />
                <label className="net-check">
                  <input
                    type="checkbox"
                    checked={effectiveAdapter}
                    disabled={draft.kind === "nat"}
                    onChange={(e) => edit({ hostAdapter: e.target.checked })}
                  />{" "}
                  {t("networks.hostAdapter")}
                </label>
                {network.bridge && (
                  <p className="net-indent net-muted">
                    {t("networks.bridgeName", { bridge: network.bridge })}
                  </p>
                )}
                <label className="net-check">
                  <input
                    type="checkbox"
                    checked={draft.dhcpEnabled && effectiveAdapter}
                    disabled={!effectiveAdapter}
                    onChange={(e) => {
                      const range = cidr ? defaultDhcp(cidr) : null;
                      edit({
                        dhcpEnabled: e.target.checked,
                        ...(e.target.checked && !draft.dhcpStart && range
                          ? { dhcpStart: range.start, dhcpEnd: range.end }
                          : {}),
                      });
                    }}
                  />{" "}
                  {t("networks.dhcp")}
                </label>
                {!effectiveAdapter && (
                  <p className="net-indent net-muted">{t("networks.dhcpNeedsAdapter")}</p>
                )}
                {draft.dhcpEnabled && effectiveAdapter && (
                  <div className="net-grid net-indent">
                    <label>
                      {t("networks.dhcpStart")}
                      <input
                        type="text"
                        value={draft.dhcpStart}
                        onChange={(e) => edit({ dhcpStart: e.target.value })}
                      />
                    </label>
                    <label>
                      {t("networks.dhcpEnd")}
                      <input
                        type="text"
                        value={draft.dhcpEnd}
                        onChange={(e) => edit({ dhcpEnd: e.target.value })}
                      />
                    </label>
                  </div>
                )}
                <div className="net-grid">
                  <label>
                    {t("networks.subnetIp")}
                    <input
                      type="text"
                      value={draft.ip}
                      disabled={!effectiveAdapter}
                      onChange={(e) => edit({ ip: e.target.value })}
                    />
                  </label>
                  <label>
                    {t("networks.subnetMask")}
                    <input
                      type="text"
                      value={draft.mask}
                      disabled={!effectiveAdapter}
                      onChange={(e) => edit({ mask: e.target.value })}
                    />
                  </label>
                </div>
                {effectiveAdapter && cidr === null && (
                  <p className="field-error">{t("networks.invalid.subnet")}</p>
                )}
              </>
            )}
            <div className="net-state">
              <label className="net-check">
                <input
                  type="checkbox"
                  checked={network.active}
                  disabled={busy}
                  onChange={(e) =>
                    void run(
                      () => api.setNetworkState(network.name, { active: e.target.checked }),
                      network.name,
                    )
                  }
                />{" "}
                {t("networks.started")}
              </label>
              <label className="net-check">
                <input
                  type="checkbox"
                  checked={network.autostart}
                  disabled={busy || !network.persistent}
                  onChange={(e) =>
                    void run(
                      () => api.setNetworkState(network.name, { autostart: e.target.checked }),
                      network.name,
                    )
                  }
                />{" "}
                {t("networks.autostart")}
              </label>
            </div>
            {network.used_by.length > 0 && (
              <p className="net-muted">
                {t("networks.usedBy", { names: network.used_by.join(", ") })}
              </p>
            )}
          </fieldset>
        )}
      </Dialog>

      {pending?.kind === "delete" && (
        <ConfirmDialog
          title={t("networks.remove")}
          message={t("networks.confirmRemove", { name: pending.network.name })}
          confirmLabel={t("networks.remove")}
          danger
          onCancel={() => setPending(null)}
          onConfirm={() => {
            const name = pending.network.name;
            setPending(null);
            void run(() => api.deleteNetwork(name), t("networks.remove"));
          }}
        />
      )}
      {pending?.kind === "rename" && (
        <PromptDialog
          title={t("networks.rename")}
          label={t("networks.newName")}
          initial={pending.network.name}
          confirmLabel={t("rename.confirm")}
          validate={(value) => (NAME_RE.test(value) ? null : t("networks.invalid.name"))}
          onSubmit={(value) =>
            api.renameNetwork(pending.network.name, value).then(() => {
              setSelected(value);
              setPending(null);
              return load();
            })
          }
          onClose={() => setPending(null)}
        />
      )}
      {pending?.kind === "defaults" && (
        <ConfirmDialog
          title={t("networks.restore")}
          message={t("networks.confirmRestore")}
          confirmLabel={t("networks.restore")}
          onCancel={() => setPending(null)}
          onConfirm={() => {
            setPending(null);
            void run(() => api.restoreDefaultNetworks(), t("networks.restore"));
          }}
        />
      )}
    </>
  );
}
