# Interface

The layout follows that of a classic desktop virtualization application, with
a style of its own: dense, light or dark theme, Lucide icons.

## Main window

- Menus: File, Edit, View, VM, Tabs, Help.
- Toolbar under the menus.
- Library tree on the left (folders and VMs).
- Tabs in the middle: Home, then one tab per open VM.
- Status bar at the bottom.

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

English (source language) and French, with i18next. With the "Same as the
system" setting, French is used when the desktop is in French, English
otherwise.
