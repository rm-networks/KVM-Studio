# Security policy

## Supported versions

Only the latest release receives security fixes. Please update before
reporting, and check that the problem is still there.

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| Older releases | No |

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it
privately through GitHub: on the repository page, open the **Security** tab,
then **Report a vulnerability**. Only the maintainers see the report.

A useful report includes:

- the KVM Studio version, the distribution and its version, and the
  interface mode (window, web, LAN sharing);
- what an attacker needs beforehand (a local account, the guest password,
  access to the local network, a VM they control...);
- the steps to reproduce, with the smallest setup that shows the problem;
- what happens, and what you expected instead;
- logs or screenshots if they help, with personal data removed.

This is a project maintained in spare time: reports are read and answered
as soon as possible, without a guaranteed delay. You will be told whether
the report is accepted, and credited in the release notes if you wish.
Please keep the details private until a fixed release is published.

## Security model in short

- The only component running as root is `kvmstudio-helper`, a systemd
  service on a Unix socket. It offers a short list of named operations, each
  one authorized by polkit for the calling process, with strictly checked
  parameters; there is no generic command execution.
- The application itself runs as the user and drives `qemu:///system`
  through libvirt, which requires membership of the `libvirt` group.
- Its internal web server listens on 127.0.0.1 only, requires a per-session
  token, and refuses connections made by other accounts of the computer.
- With LAN sharing turned on, a second listener serves HTTPS on the local
  network to a single guest account protected by a password. The guest
  manages virtual machines but not the host: preferences, the network
  editor, ISO access rights, USB devices, imports and host files outside the
  VM library are refused on every route.

Details are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
