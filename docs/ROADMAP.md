# Roadmap

Development goes phase by phase. A phase starts when the CI is green and the
acceptance test of the previous one is signed off. The F-xx identifiers refer
to the [specifications](SPECIFICATIONS.md).

## Phase 0: foundation

Backend, frontend, configuration, libvirt connection, pywebview window, CI.
Exit criterion: the window lists the domains.

## MVP (Fedora)

F-01, F-02 (folders synced to disk, section 6.1.1), F-03, F-04, F-10, F-12,
F-20, F-22, F-24, F-30, F-31, F-33, F-34, F-35, F-40, F-41, F-52, F-53, F-60,
F-61, F-62, F-64, F-70, F-71, F-72, F-73 (without forwarding), F-76, F-77,
F-90, F-93, F-94 (window and local web mode), F-95 (.rpm and first run).

Order: UTF-8 copy and paste prototype, list and states, life cycle, library
folders, kvmnet networks and hiding, ISO picker, assistant, console with copy
and paste and guest tools, several network cards, .rpm package.

Exit criterion: an OPNsense lab with 3 network cards and a Windows 11 VM,
working copy and paste, host network applet free of stray interfaces.

## Before V1

Feedback from the 0.1.0 acceptance test: an English interface with French as
a choice, ISO libraries declared from Preferences through the
helper, removal of the access rights the helper granted, vnet* interfaces kept
out of NetworkManager, a redesign of the interface, and VM cloning (F-84,
brought forward from V2).

## V1 (Fedora, Debian 13, Ubuntu 26.04 LTS): done, version 1.0.0

Released on 2026-10-26: .deb package next to the .rpm, serial console,
snapshots, NAT port forwarding, disk expansion, existing disks used where
they are or brought into the library, folder scan for virtual machines,
sharing on the LAN with a guest account (F-100 to F-106).

Moved to V2: Easy Install (F-26), shared folders through virtiofs (F-65) and
network diagnostics (F-78).

## 1.1.0: done

Add and remove a hard disk in the VM settings, live where QEMU allows it;
USB storage devices of the host connected to a running VM (Removable
Devices); Autofit Guest for virtio displays; notes of a VM in its libvirt
description; Generate for a MAC address; New Virtual Machine from a folder's
context menu; one Snapshot Manager entry for a VM; dialogs moved by their
title bar.

Not delivered: live resolution change for Windows guests (the VirtIO GPU
driver only reads the size at startup) and for X11 sessions.

## V2 (public release)

Easy Install, virtiofs shared folders, network diagnostics, Bridged, USB
devices other than storage,
thumbnails, topology, AutoProtect, import and export of OVF,
COPR and APT repositories, remote server.
