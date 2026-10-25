/**
 * Saves a text file the user names: native dialog in the desktop window (the
 * embedded engine's downloads are not usable), a download in a browser.
 */
export async function saveTextFile(name: string, text: string, type: string): Promise<void> {
  const api = window.pywebview?.api;
  if (api?.save_file) {
    await api.save_file(name, text);
    return;
  }
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text], { type }));
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  // Revoked later: some engines start reading the blob after click() returns.
  const url = link.href;
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
