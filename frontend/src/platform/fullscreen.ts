/** Full screen for the whole window: pywebview in the desktop window, the Fullscreen API in a browser. */
export function toggleFullscreen(): void {
  const api = window.pywebview?.api as { toggle_fullscreen?: () => Promise<void> } | undefined;
  if (api?.toggle_fullscreen) {
    void api.toggle_fullscreen();
    return;
  }
  if (document.fullscreenElement) void document.exitFullscreen();
  else void document.documentElement.requestFullscreen?.();
}
