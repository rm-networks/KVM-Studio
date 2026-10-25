/**
 * Where the keyboard goes when a dialog opens: the first field of its body, else
 * its main button, else the dialog itself. Never the close button.
 */
export function focusFirstField(event: Event, body: string, primary: string) {
  const content = event.currentTarget as HTMLElement | null;
  if (!content) return;
  event.preventDefault();
  const field = content.querySelector<HTMLElement>(
    `${body} input:not([type="hidden"]):not(:disabled), ${body} select:not(:disabled), ${body} textarea`,
  );
  const button = content.querySelector<HTMLElement>(`${primary}:not(:disabled)`);
  (field ?? button ?? content).focus();
}
