/** Native folder picker of the desktop window; null in a browser (type the path). */
export function folderPicker(): ((start: string | null) => Promise<string | null>) | null {
  const api = window.pywebview?.api;
  if (!api?.choose_folder) return null;
  const choose = api.choose_folder;
  return (start) => choose(start);
}

/** Native picker for a disk image; null in a browser (the backend lists the files). */
export function diskPicker(): ((start: string | null) => Promise<string | null>) | null {
  const api = window.pywebview?.api;
  if (!api?.choose_disk) return null;
  const choose = api.choose_disk;
  return (start) => choose(start);
}
