import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type DiskSize, type Drive } from "../../api/client";
import { useNotifier } from "../../components/notifier";
import { PromptDialog } from "../../components/PromptDialog";

const GIB = 1024 ** 3;

/** A disk of the VM: its sizes, and Expand (F-44). */
export function DiskPanel({ uuid, disk }: { uuid: string; disk: Drive }) {
  const { t } = useTranslation();
  const { notify } = useNotifier();
  const [size, setSize] = useState<DiskSize | null>(null);
  const [expanding, setExpanding] = useState(false);

  const load = useCallback(
    () =>
      api
        .diskSize(uuid, disk.target)
        .then(setSize)
        .catch(() => setSize(null)),
    [uuid, disk.target],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const gib = (bytes: number) => (bytes / GIB).toFixed(bytes % GIB === 0 ? 0 : 1);
  const current = size ? Math.ceil(size.capacity / GIB) : 0;

  return (
    <fieldset className="group">
      <legend>{t("settings.diskTitle")}</legend>
      <p className="mono">{disk.path}</p>
      <p className="muted">
        {disk.bus.toUpperCase()} {disk.target}, {disk.format}
      </p>
      {size && (
        <>
          <p>
            {t("disk.sizes", { capacity: gib(size.capacity), allocation: gib(size.allocation) })}
          </p>
          <div className="settings-row">
            <button
              type="button"
              className="button"
              disabled={!size.expandable}
              title={size.expandable ? undefined : t("disk.outside")}
              onClick={() => setExpanding(true)}
            >
              {t("disk.expand")}
            </button>
          </div>
        </>
      )}
      {expanding && size && (
        <PromptDialog
          title={t("disk.expandTitle", { target: disk.target })}
          label={t("disk.newSize")}
          initial={String(current)}
          confirmLabel={t("disk.expandButton")}
          validate={(value) => {
            const n = Number(value);
            return Number.isInteger(n) && n * GIB > size.capacity
              ? null
              : t("disk.larger", { current: gib(size.capacity) });
          }}
          onSubmit={(value) =>
            api.expandDisk(uuid, disk.target, Number(value)).then((next) => {
              setSize(next);
              setExpanding(false);
              notify(t("disk.expanded", { size: gib(next.capacity) }), t("disk.guestHint"));
            })
          }
          onClose={() => setExpanding(false)}
        />
      )}
    </fieldset>
  );
}
