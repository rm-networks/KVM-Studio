# Interface

The layout follows that of a classic desktop virtualization application, with
a style of its own: a sober and dense desktop application, light or dark theme,
Lucide icons.

## Look

- Neutral grey window, white views (lists, fields, pages), 1 px borders, a
  single corner radius, no gradients, glows or decorative shadows.
- One accent colour, taken from the logo, for the main button, the selection
  and the focus.
- The system font; one spacing scale (4, 8, 12, 16 px); one icon size and
  stroke for every Lucide icon.
- Text keeps a contrast of at least 4.5:1 in both themes, on main and disabled
  buttons too; a test checks every colour pair.
- A selected row is coloured whole, in one tint, and its text wraps rather
  than being cut.
- Bars that run out of room keep their first items and move the others to a
  "»" menu (tabs).
- Only what works is shown: a feature still to come has no menu entry, button
  or setting.

## Assistants

New virtual machine, first run, uninstall and cloning share one frame: a header
with the logo, the title of the page and a discreet "Step 2 of 7" with a thin
progress bar; the page; a fixed footer with Cancel, Back and Next aligned to the
right, Next being the main button. The uninstall assistant is alone in its own
window.

## Main window

- Menus: File, Edit, View, VM, Tabs, Help.
- Toolbar under the menus.
- Library tree on the left (folders and VMs).
- Tabs in the middle: Home, then one tab per open VM.
- Status bar at the bottom: connection, versions, number of VMs, and the
  long tasks under way (a snapshot of a running VM) with a Cancel button.
- A running VM with a serial console shows Screen and Serial Console views
  above its console; the console shows how many people are on it when the
  VMs are shared on the local network.

A guest of LAN sharing has no Edit menu (Preferences, virtual network editor)
and no first-run assistant; File > Log Out ends the session.

The menu entries are detailed in section 5 of the
[specifications](SPECIFICATIONS.md).

## Dialogs

- VM settings (Hardware and Options tabs).
- New VM assistant (Typical, Custom, Easy Install).
- Snapshot manager.
- Virtual network editor.
- Preferences.
- ISO picker.
- Login (shared web mode).
- First-run assistant.

Every destructive action asks for a confirmation. libvirt errors are shown in
plain words, with the raw message available on demand.

## Shortcuts

Shortcuts follow the usual conventions of desktop virtualization software and
can be remapped. In web mode, the browser takes Ctrl+W, Ctrl+N and Ctrl+T:
other combinations must then be assigned to them. Window mode has no such
limit.

## Languages

English and French, with i18next. English is the default; French is picked
in Preferences, or on the first page of the first-run assistant, and applies
at once. The language of the desktop is not looked at. A guest of LAN
sharing picks theirs in Edit > Language, kept by their own browser.
