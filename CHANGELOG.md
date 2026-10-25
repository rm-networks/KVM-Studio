# Changelog

## 0.2.1 (2026-10-25)

- Windows guest tools: the KS_TOOLS CD now carries the virtio-win guest tools
  installer, copied from the virtio-win ISO set in Preferences, so a single
  CD/DVD drive is enough and Install-Tools.bat no longer reports a missing
  virtio disc. The dialog shows the drive used and tells apart a virtio-win
  ISO that is not set, missing, outside the ISO libraries (with a button to
  add its folder) or without installer.
- Preferences > Virtual machines: Browse button for the virtio-win ISO, and a
  ? button explaining what it is for, with the link to download it.
- Starting a VM shows the loading cubes over the firmware logo for a moment;
  a key or a click puts them away at once.

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
