/** Opens a web page in the default browser, from the window or from a browser tab. */
export function openLink(url: string): void {
  const open = window.pywebview?.api?.open_link;
  if (open) void open(url);
  else window.open(url, "_blank", "noopener,noreferrer");
}
