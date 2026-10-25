# Changelog

## 0.2.0 (2026-10-25)

- Clone a powered off VM from its context menu or from VM > Manage: full copy
  or linked clone, with a new name, new MAC addresses and the same hardware.
  The UEFI variables and the TPM state are copied after an administrator
  password. A VM with linked clones asks before starting and cannot be
  deleted from disk.
- ISO libraries can be added and removed in Preferences. Removing one takes
  back the access rights given to QEMU.
- The interface is in English, or in French when the desktop is in French; a
  choice is kept in Preferences.
- Redesigned interface: sober look, one frame for every assistant, menu
  entries of features still to come removed.
- Settings in the VM context menu (Ctrl+D).
- A VM tab always shows the VM name.
- VMs with a SPICE display get a single copy and paste offer.
- Animated cubes while the console connects.
- vnet* interfaces created by libvirt are kept out of NetworkManager.

## 0.1.0 (2026-10-24)

- First usable version, for Fedora.
