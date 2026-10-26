# KVM Studio

Virtual machine manager for Linux, built on QEMU/KVM and libvirt. A VM library,
tabs, assistants and a virtual network editor, in a native window or in a
browser.

The VMs it creates stay standard libvirt domains: they also open in
virt-manager and `virsh`.

The interface is in English, or in French when the desktop is in French
(Edit > Preferences > Interface changes it).

Virtual machines keep running when KVM Studio closes: libvirt and QEMU run them,
not KVM Studio. You find them again the next time it starts (Edit > Preferences >
Workspace can suspend or shut them down instead).

## Status

Version 1.0.0 is in preparation: a .rpm for Fedora and a .deb for Debian 13
and Ubuntu 26.04 LTS, built by the CI on every change. Version 0.4.0 is the
latest release. See the [roadmap](docs/ROADMAP.md).

## Features

- VM library with folders, tabs, a New Virtual Machine assistant and an ISO
  picker over read-only ISO libraries.
- Console with copy and paste, full screen, and a serial console for
  firewalls and appliances.
- Virtual network editor (NAT, host-only, DHCP, NAT port forwarding), with
  the host network applet kept free of KVM Studio's interfaces.
- Snapshots (with or without the memory), clones, disk expansion.
- Web mode, and sharing on the local network with a guest account (HTTPS).
- Installation and removal that leave the host clean.

## Running from the sources

See [docs/INSTALL.md](docs/INSTALL.md).

## Documentation

- [Specifications](docs/SPECIFICATIONS.md)
- [Installation](docs/INSTALL.md)
- [Configuration](docs/CONFIGURATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Virtual networks](docs/NETWORKING.md)
- [Interface](docs/INTERFACE.md)
- [Roadmap](docs/ROADMAP.md)

## License

GPL-3.0, see [LICENSE](LICENSE).

## Notice

KVM Studio is a community project inspired by the interface and features of
VMware Workstation. It is not affiliated with VMware or Broadcom and uses none
of their code or artwork.
