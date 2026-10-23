import { type ReactNode, useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type LibraryInfo, type VmSummary } from "../../api/client";
import { useNotifier } from "../../components/notifier";
import { DeleteFolderDialog } from "./DeleteFolderDialog";
import { FolderNameDialog } from "./FolderNameDialog";
import { type LibraryActions, LibraryActionsContext } from "./libraryActionsContext";
import { MoveVmDialog } from "./MoveVmDialog";

type Pending =
  | { kind: "new"; parent: string }
  | { kind: "rename"; path: string }
  | { kind: "delete"; path: string }
  | { kind: "move"; vm: VmSummary; importFiles: boolean }
  | null;

interface Props {
  library: LibraryInfo | null;
  children: ReactNode;
}

export function LibraryActionsProvider({ library, children }: Props) {
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
      renameFolder: (path) => setPending({ kind: "rename", path }),
      deleteFolder: (path) => setPending({ kind: "delete", path }),
      moveVm: (vm, folder) => {
        if (folder === undefined) setPending({ kind: "move", vm, importFiles: false });
        else if (folder !== vm.folder) move(vm, folder);
      },
      importVm: (vm) => setPending({ kind: "move", vm, importFiles: true }),
    }),
    [available, move],
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
    </LibraryActionsContext.Provider>
  );
}
