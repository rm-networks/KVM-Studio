# Changelog

## Unreleased

- Port forwarding no longer uses a libvirt network hook: SELinux keeps
  virtnetworkd from running it on Fedora, and once libvirt loaded it every VM
  start on a network failed. A udev rule and a systemd unit write the table
  again when a kvmnet bridge is created; upgrading removes the hook.
- New Virtual Machine assistant: its backdrop covered it, so the page was
  dimmed and any click closed it. Interface tests in a real browser
  (Playwright) now go through it to the last page.
- Virtual network editor: Export no longer closes the window (it now opens a
  save dialog); the list of VMs using each network is gone.
- Snapshots: "Include RAM" choice, limits of libvirt (raw disks, raw UEFI
  variables, TPM of a powered-off VM) shown before taking one; snapshots run
  in the background, followed in the status bar with a Cancel button.
- System updates: KVM checked at each start and by `kvm-studio --check`
  (kernel updated but not restarted, module not loaded, nested
  virtualization); new VMs get a versioned machine type; the port forwarding
  table comes back after nftables or firewalld restart; the helper
  service can now write it (host network, CAP_NET_ADMIN). The nested profile
  asks for svm on AMD hosts instead of vmx.
- Sharing on the local network (web mode): HTTPS on port 60443 with a
  self-signed certificate, a guest account (argon2 password set in
  Preferences > Interface, lockout after 5 failures, sessions ending after 30
  minutes idle), the rights of the guest checked on every route, the firewall
  port opened and closed by the helper (firewalld or ufw), and a shared
  console showing how many people are on it.

## 0.4.0 (2026-10-25)

- Virtual network editor: the host address can be anywhere in the subnet (the
  DHCP range moves off it); DHCP Settings choose the gateway announced on a
  host-only network (none, the host, or another address such as a firewall
  VM). Changes that restart a network list the running VMs using it and stop
  and start them again after a confirmation.
- NAT Settings > Port Forwarding: host port, type, VM IP address, VM port and
  description, written by the administrator; host address 127.0.0.1 by
  default. The rules live in KVM Studio's own nftables table, kept across
  network restarts.
- Snapshots: take, restore and delete, powered off or running with the
  memory, from the toolbar, VM > Snapshot and the Snapshot Manager.

## 0.3.0 (2026-10-25)

- VM settings, new Options tab: name and guest system, start with the host
  and the restart and crash actions, BIOS or UEFI, Secure Boot and TPM (with a
  warning and a confirmation for an installed VM), boot order per device by
  drag and drop or arrows, boot menu, and copy and paste on or off.
- View > Full Screen (Ctrl+Alt+Enter) shows the VM console alone on the
  screen; a thin bar at the top edge gives Exit, Send Ctrl+Alt+Del and the
  power menu. The whole window goes full screen with F11.
- Library folders move by drag and drop into one another, nested, with the
  files of their VMs; their display order is kept.
- When KVM Studio closes or changes mode, a reminder lists the VMs still
  running: libvirt and QEMU keep them running. Preferences > Workspace can
  ask, suspend or shut them down instead.
- Settings is the last entry of the VM context menu.
- The virtio-win help links to its documentation instead of the ISO itself.
- A console out of sight lets go of its stream after 15 s, saving CPU.

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
