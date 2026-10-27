import { type ReactNode, useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type LibraryInfo, type TidyPlan, type VmSummary } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { useNotifier } from "../../components/notifier";
import { DeleteFolderDialog } from "./DeleteFolderDialog";
import { FolderNameDialog } from "./FolderNameDialog";
import { type LibraryActions, LibraryActionsContext } from "./libraryActionsContext";
import { MoveFolderDialog } from "./MoveFolderDialog";
import { MoveVmDialog } from "./MoveVmDialog";
import { parentOf } from "./tree";

type Pending =
  | { kind: "new"; parent: string }
  | { kind: "rename"; path: string }
  | { kind: "delete"; path: string }
  | { kind: "move"; vm: VmSummary; importFiles: boolean }
  | { kind: "moveFolder"; path: string; parent: string; before: string | null }
  | { kind: "tidy"; vm: VmSummary; plan: TidyPlan }
  | null;

interface Props {
  library: LibraryInfo | null;
  onNewVm?: (folder: string) => void;
  children: ReactNode;
}

export function LibraryActionsProvider({ library, onNewVm, children }: Props) {
  const { t } = useTranslation();
  const { notify, notifyError } = useNotifier();
  const [pending, setPending] = useState<Pending>(null);
  const available = Boolean(library?.root);

  const move = useCallback(
    (vm: VmSummary, folder: string) => {
      api
        .moveVm(vm.uuid, folder)
        .catch((err: unknown) => notifyError(t("library.moveFailed", { name: vm.name }), err));
    },
    [notifyError, t],
  );

  const actions = useMemo<LibraryActions>(
    () => ({
      available,
      newFolder: (parent) => setPending({ kind: "new", parent }),
      newVm: (folder) => onNewVm?.(folder),
      renameFolder: (path) => setPending({ kind: "rename", path }),
      deleteFolder: (path) => setPending({ kind: "delete", path }),
      moveVm: (vm, folder) => {
        if (folder === undefined) setPending({ kind: "move", vm, importFiles: false });
        else if (folder !== vm.folder) move(vm, folder);
      },
      importVm: (vm) => setPending({ kind: "move", vm, importFiles: true }),
      tidyVm: (vm) => {
        api
          .tidyPlan(vm.uuid)
          .then((plan) => setPending({ kind: "tidy", vm, plan }))
          .catch((err: unknown) => notifyError(t("library.tidyTitle"), err));
      },
      moveFolder: (path, parent, before) => {
        if (parent !== parentOf(path)) {
          setPending({ kind: "moveFolder", path, parent, before });
          return;
        }
        // Same parent: only the order of the names changes, no file moves.
        const name = path.slice(path.lastIndexOf("/") + 1);
        const siblings = (library?.folders ?? [])
          .filter((f) => parentOf(f) === parent && f !== path)
          .map((f) => f.slice(f.lastIndexOf("/") + 1));
        const chosen = library?.order[parent] ?? [];
        const known = (n: string) => (chosen.includes(n) ? chosen.indexOf(n) : chosen.length);
        siblings.sort((a, b) => known(a) - known(b) || a.localeCompare(b));
        const at = before === null ? siblings.length : Math.max(0, siblings.indexOf(before));
        siblings.splice(at, 0, name);
        api
          .setFolderOrder(parent, siblings)
          .catch((err: unknown) =>
            notifyError(t("library.moveFolderFailed", { folder: path }), err),
          );
      },
    }),
    [available, move, library, notifyError, onNewVm, t],
  );

  const close = () => setPending(null);
  const folders = library?.folders ?? [];

  return (
    <LibraryActionsContext.Provider value={actions}>
      {children}
      {pending?.kind === "new" && (
        <FolderNameDialog
          title={t("library.newFolderTitle")}
          parent={pending.parent}
          initial=""
          confirmLabel={t("library.create")}
          onSubmit={(name) =>
            api.createFolder(pending.parent ? `${pending.parent}/${name}` : name).then(close)
          }
          onClose={close}
        />
      )}
      {pending?.kind === "rename" && (
        <FolderNameDialog
          title={t("library.renameFolderTitle")}
          parent={
            pending.path.includes("/") ? pending.path.slice(0, pending.path.lastIndexOf("/")) : ""
          }
          initial={pending.path.slice(pending.path.lastIndexOf("/") + 1)}
          confirmLabel={t("rename.confirm")}
          onSubmit={(name) => api.renameFolder(pending.path, name).then(close)}
          onClose={close}
        />
      )}
      {pending?.kind === "delete" && <DeleteFolderDialog path={pending.path} onClose={close} />}
      {pending?.kind === "moveFolder" && (
        <MoveFolderDialog
          path={pending.path}
          parent={pending.parent}
          before={pending.before}
          onClose={close}
        />
      )}
      {pending?.kind === "move" && (
        <MoveVmDialog
          vm={pending.vm}
          folders={folders}
          importFiles={pending.importFiles}
          onSubmit={(folder) => {
            if (!pending.importFiles) {
              move(pending.vm, folder);
              close();
              return Promise.resolve();
            }
            return api.importVm(pending.vm.uuid, folder).then((result) => {
              close();
              notify(
                t("library.imported", { name: pending.vm.name }),
                t("library.originalsKept", {
                  files: result.originals.join("\n"),
                }),
              );
            });
          }}
          onClose={close}
        />
      )}
      {pending?.kind === "tidy" && (
        <ConfirmDialog
          title={t("library.tidyTitle")}
          confirmLabel={t("library.tidyMove")}
          onConfirm={() =>
            api
              .tidyVm(pending.vm.uuid)
              .then(() => notify(t("library.tidied", { name: pending.vm.name }), ""))
          }
          onClose={close}
        >
          <p>{t("library.tidyIntro", { name: pending.vm.name })}</p>
          <ul className="move-list mono">
            {pending.plan.moves.map(([from, to]) => (
              <li key={from}>
                {from} → {to}
              </li>
            ))}
          </ul>
          {pending.vm.state !== "shutoff" && <p className="field-error">{t("delete.mustBeOff")}</p>}
        </ConfirmDialog>
      )}
    </LibraryActionsContext.Provider>
  );
}
