# Architecture

KVM Studio drives QEMU/KVM through libvirt. It runs in a native window or in a
browser, and is installed from a .rpm or .deb package.

## Principles

- **libvirt is the source of truth.** No VM state is stored anywhere else.
  KVM Studio's own data goes into the domain `<metadata>`, under the namespace
  `https://github.com/rm-networks/kvm-studio/ns/1.0` (prefix `kvmstudio`).
  After each definition, the XML is read back with `XMLDesc()`, since libvirt
  normalizes it. The library folder of a VM (`folder`) is noted with the
  library root it is relative to (`library`): after the VM location changes,
  a VM under the new root is placed by the real path of its files.
- **virt-manager and virsh compatibility.** Domains, networks and volumes
  created by KVM Studio stay usable in these tools.
- **No hard-coded path.** URI, pools, networks, ports and folders come from the
  configuration, with detected defaults.
- **ISO folders are read-only.** Never a copy, a move or a write in an ISO
  library.
- **Path confinement.** Every path received from the client is resolved and
  must then be under the VM folder or under a declared ISO library, otherwise
  the request is refused (403). The backend does the check. Two exceptions
  for the owner only, as a file dialog would allow: the existing disk a new
  VM starts from (used where it is, copied or moved in) and the folders the
  Browse buttons list in a web browser (`/api/files`). A guest stays
  confined there too. ISO libraries stay read only: a disk found there can
  only be copied.
- **No shell.** External tools (`qemu-img`, `nft`, `firewall-cmd`, `ufw`,
  `semanage`, `setfacl`) are called with a list of arguments, never through a
  command built as text.

## Processes

The main process only holds the window (pywebview, Qt WebEngine) or the tray
icon. The backend (Uvicorn, FastAPI, libvirt connection, event loop) runs in a
child process (`shell/backend_process.py`). libvirt is never loaded in the Qt
process: both share the GLib `GMainContext`, which leads to crashes.

libvirt events reach the frontend through the `/ws/events` WebSocket.

## Root helper

`kvmstudio-helper` is the only component running as root. It is a systemd
service listening on a Unix socket, exposing only named operations with
validated parameters, each one authorized by polkit:

- opening and closing the web port (firewalld or ufw);
- NAT port forwarding (nftables table `inet kvmstudio`);
- declaring and removing ISO libraries, and access fixes on ISO images
  (SELinux context `virt_content_t` or ACL);
- adding the caller's account to the `libvirt` group;
- removing the package at the end of an uninstall.

There is no generic command execution operation.

How it works:

- systemd creates the socket `/run/kvmstudio-helper.sock` (unit
  `kvmstudio-helper.socket`) and starts the service at the first connection;
- each connection carries one JSON request `{"op": ..., "params": {...}}`,
  read within 2 s; at most 16 connections are served at once, 8 per account;
- only the syntax of the parameters is checked before polkit: any extra key,
  unexpected type, relative path or unknown operation is refused there.
  Paths, VMs, networks and accounts are only looked at once polkit said yes,
  so a caller without the right gets the same answer whatever it names; they
  are checked again just before the change;
- the caller is identified by the kernel (`SO_PEERCRED`: pid, real uid) and
  never by a field of the request; polkit (`pkcheck`) authorizes this process
  for the action of the operation, showing the desktop authentication window
  when needed;
- paths are resolved (symbolic links and `..` included), and must then be
  strictly under a declared library: those of `/etc/kvm-studio/helper.toml`
  and those users declared from Preferences, which the helper keeps in its
  state file `/var/lib/kvm-studio/helper-state.json` (root only);
- the file is then reopened component by component with `O_NOFOLLOW` from the
  library root, and the tool receives `/proc/self/fd/N`: replacing a folder
  with a symbolic link between the check and the change therefore has no
  effect.

| Operation | polkit action | Effect |
| --- | --- | --- |
| `iso_acl` | `org.kvmstudio.helper.iso-acl` | ACL `u:<qemu>:x` on the library folders down to the image, `u:<qemu>:r` on the image; for a library a user declared, `u:<qemu>:x` also on the folders right above it that belong to that user |
| `add_iso_library` | `org.kvmstudio.helper.iso-library` | declares a folder: resolved, existing, a folder, owned by the caller, neither a system folder (`/`, `/etc`, `/usr`, `/var`, `/boot`, `/root`, `/proc`, `/sys`, `/dev`, `/run`, `/bin`, `/sbin`, `/lib`), inside one, nor above one; administrator password on every call |
| `remove_iso_library` | `org.kvmstudio.helper.iso-library` | forgets a library of the caller's and takes back the ACL entries the helper added for it; administrator password on every call |
| `clear_iso_libraries` | `org.kvmstudio.helper.iso-library` | at uninstall: forgets every declared library, taking back every entry the helper added when asked to |
| `list_iso_libraries` | none | the libraries of helper.toml and the caller's; changes nothing |
| `join_libvirt` | `org.kvmstudio.helper.join-libvirt` | adds the caller to the `libvirt` group; no parameter, refused for root and UIDs below 1000, administrator password on every call |
| `clone_vm_state` | `org.kvmstudio.helper.clone-state` | copies the UEFI variables and the TPM state of a powered off VM to its clone; takes the two UUIDs only and reads both files from libvirt (`qemu:///system`); both VMs shut off, checked before and after the password; the copy goes to a new file in a folder of the caller's under `KVM-Studio/VM/`, with the owner and mode of the original (QEMU for the NVRAM, swtpm's account for the TPM); links, hard links and existing files are refused; administrator password on every call |
| `set_port_forwards` | `org.kvmstudio.helper.port-forward` | NAT port forwarding of one network: takes the network name and the rules (protocol tcp or udp, host address, host port, VM address, VM port, description); checks the ports (1 to 65535), the addresses, and that the VM address is in the network's subnet read from libvirt (`qemu:///system`); writes the nftables table `inet kvmstudio` again as a whole (`nft -f`), and `route_localnet` on the bridge for loopback rules; administrator password on every call |
| `list_port_forwards` | none | the rules kept by the helper; changes nothing; root and members of the `libvirt` group only (groups read from the kernel, `SO_PEERGROUPS`) |
| `lan_port` | `org.kvmstudio.helper.lan-port` | opens the HTTPS port of LAN sharing in firewalld (`kvm-studio` service, runtime only) or ufw, and writes down what it opened; administrator password on every call |
| `close_lan_port` | `org.kvmstudio.helper.lan-port-close` | closes what `lan_port` wrote down and nothing else; no parameter; no password in the active session, refused elsewhere |
| `remove_package` | `org.kvmstudio.helper.remove-package` | removes the `kvm-studio` package in a transient systemd unit; no parameter, administrator password on every call |

Every ACL bit the helper adds is written to its state with the inode it was
added on. Removing a library takes back only those bits, never an entry that was
there before (an entry the helper only completed gets its former value back),
and the search permission on a folder above several libraries stays while one
of them needs it. A file replaced since keeps whatever it has. Folders of other
accounts above a library are never changed: the ISO picker shows the command to
run. The NetworkManager rule is only carried by a package file. The `u:qemu:x`
ACL on VM folders under the home folder is set by the user, without the helper.

A plain package removal runs `kvmstudio-helper --clear-state`, which takes back
the entries still recorded, then deletes `/var/lib/kvm-studio`.

Every action that opens or grants something asks the administrator password
on every call, with one exception kept on purpose: `iso-acl` is
`auth_admin_keep`, so making several images of a library readable in a row
asks it once; for five minutes the same
process may then give QEMU read access to other images of the declared
libraries, nothing else. The LAN sharing port is opened at runtime only: a
crash, a reboot or a firewall reload leaves it closed. At boot
(`kvmstudio-forwards.service`) and when the backend starts without sharing, a
port still recorded as open is closed.

The units that run the helper's code as root (`kvmstudio-helper.service`,
`kvmstudio-forwards.service`, `kvmstudio-bridge@.service`) are confined by
systemd: no new privileges, no device nodes, no namespaces, no SUID files, no
realtime scheduling, `@system-service` system calls only, `UMask=0077`, at
most 64 tasks for the helper. `ProtectHome` cannot be used: ISO libraries may
sit in home folders.

## Interface modes

The two modes are exclusive and chosen in the configuration (applied on
restart).

| Mode | Listens on | Access |
| --- | --- | --- |
| Window | 127.0.0.1, random port | token per session |
| Local web | 127.0.0.1:60080 | token required, link printed at start |
| Shared web (`share_on_lan = true`) | LAN, self-signed HTTPS on 60443 | guest account with a password, otherwise refuses to start |

### Guest account

A single guest account, usable by several people at once. Its password is set
in Preferences > Interface and stored as an argon2 hash. Login attempts are
limited (`login_max_attempts`) and sessions expire after inactivity.

Two roles: `owner` (window mode session or login from 127.0.0.1) and `guest`.
The backend checks the rights on every route.

- Allowed to the guest: creating, deleting, changing, starting and stopping
  VMs, console, snapshots, clones, picking ISO images from the libraries and
  existing `kvmnet` networks (a card on any other network answers 403).
- Forbidden to the guest (403 on every route, `auth/roles.py`, tested by direct
  calls): Preferences and ISO libraries (`/api/preferences`), the network
  editor (`/api/networks/...`, only the list stays), LAN sharing
  (`/api/sharing`), the access fix of an ISO (`/api/isos/access/fix`), first
  run, uninstall, restart and closing actions (`/api/setup`, `/api/uninstall`,
  `/api/restart`, `/api/session`), importing a VM's disks from outside the
  root (`/api/vms/{uuid}/import`), the host's USB storage devices and their
  connection to a VM (`/api/usb`, `/api/vms/{uuid}/usb`; a device the owner
  connected stays usable in the guest system), opening a library folder in
  the host's file manager (`/api/library/folders/open`). There is no raw XML editor nor
  PCI passthrough route, and every path stays confined.

The owner's token is only accepted from a loopback address; a guest's session
cookie (HttpOnly, Secure, SameSite=Strict) only on the HTTPS listener. Both
listeners run in the backend process, on one event loop. The loopback one only
answers to `127.0.0.1` and `localhost` as host name (DNS rebinding).

Other accounts of the same computer reach the loopback address too. Every
loopback connection is checked against the account that runs the backend:
the kernel lists the owner of each TCP socket in `/proc/net/tcp` and
`/proc/net/tcp6`, and a client of another account gets 403, token or not. When
the client's socket is not listed (another network namespace, no `/proc`), the
token alone is checked and a warning is logged. The token itself never reaches
a command line: the window gets it inside its own process, and a browser is
opened (or the tray icon copies a link) with a single-use code valid a few
seconds, which the page trades for the token at once (`/api/auth/redeem`).

Both listeners bound what a client can make the backend hold: 64 KiB of
request body before signing in and 8 MiB after (`413` beyond, counted as
it arrives), 128 requests and connections at once, 32 WebSockets per guest
session or address, three password checks at a time (argon2id takes 64 MiB
each), and login attempts counted before the password is checked. A
WebSocket whose `Origin` is not the page's own address is refused. Every
answer carries a Content Security Policy (scripts from the application only,
no framing), `X-Content-Type-Options`, `Referrer-Policy` and, on HTTPS,
`Strict-Transport-Security`; the API schema is only served by the
development server. The HTTPS listener accepts TLS 1.2 or later, with
ECDHE AEAD suites only.

Turning sharing on or off opens or closes the port through the helper. The
shared console uses `<graphics type='vnc' sharePolicy='allow-exclusive'>`:
several noVNC clients can connect and the interface shows how many people are
connected (event `console.viewers`). Each client has its own VNC connection
through libvirt. From two people on, the guest keeps its resolution: the relay
reads the client to server RFB stream message by message and drops
SetDesktopSize (owner and guests alike), the interface stops asking and greys
out View > Autofit Guest, and each client scales the picture to its window.
With one person left, Autofit Guest applies that person's window size again.
Besides keeping each picture steady, this avoids a QEMU VNC server defect seen
with QEMU 11.1: when one client resizes the guest while another is connected,
the other client can miss parts of the following updates with the compressing
encodings (Tight, ZRLE), leaving stale areas until they change again. Raw
updates and resolution changes made by the guest itself are not affected.

## Guest integration

- **Copy and paste (text only).** Every VM with a display gets
  `<channel type='qemu-vdagent'>` with `<clipboard copypaste='yes'/>`, unless
  Options > Isolation turns it off. The host clipboard is linked to noVNC by the
  pywebview API in window mode and by `navigator.clipboard` in web mode (secure
  context: 127.0.0.1 or HTTPS). Text pasted from the host reaches QEMU
  NUL-terminated, as the VNC extended clipboard asks; the console relay removes
  that NUL, which QEMU would otherwise hand to the guest. See
  [Copy and paste](#copy-and-paste) for what the guest side needs.
- **Guest tools installation.** KVM Studio builds with `xorriso` a small
  `KS_TOOLS` CD in `<location>/KVM-Studio/Tools` and inserts it in one drive of
  the VM. For Windows the CD also carries `virtio-win-guest-tools.exe`, copied
  from the virtio-win ISO of the Preferences, which is only read. The user starts
  the installation inside the VM: `Install-Tools.bat` on Windows, `install.sh`
  on Linux. Nothing is typed for them, so the keyboard layout does not matter.
  qemu-guest-agent then confirms that the agent answers, and ejecting puts back
  what the drives held before.
- **Easy install.** The assistant collects user, password, language, keyboard
  and an optional product key, then generates the answer file (autounattend.xml,
  kickstart, preseed, autoinstall) on a small separate ISO. The source ISO is
  never changed. Targets: Windows 10/11/Server, Fedora/RHEL, Debian, Ubuntu.

## Copy and paste

The chain is: guest application, guest clipboard, `spice-vdagent` in the guest
session, the virtio port `com.redhat.spice.0`, QEMU's `qemu-vdagent`, the VNC
extended clipboard, the console relay, noVNC, then the host clipboard (Qt in
window mode, the browser in web mode). Host to guest works as soon as the agent
runs. Guest to host depends on the agent seeing the copy:

| Guest session | Host to guest | Guest to host |
|---|---|---|
| Linux, X11 (Plasma X11, GNOME on Xorg, Xfce...) | Yes | Yes |
| Linux, Wayland (Plasma, GNOME) | Yes | Only text copied from an X11 (XWayland) application |
| Windows, with the guest tools | Yes | Yes |

Why Wayland differs: `spice-vdagent` (0.22 in Debian 13) is an X11 client. It
writes the X11 clipboard, which the compositor passes on to Wayland
applications, but it never sees what Wayland applications copy, since the
compositor does not hand the Wayland clipboard to an X11 client that has no
focused window. QEMU then has nothing to send. Workarounds: log in to an X11
session (on Plasma: "Plasma (X11)" at the login screen), or copy from an X11
application (a terminal started with `QT_QPA_PLATFORM=xcb`, for example). A
script that copies the Wayland clipboard into the X11 one (`wl-paste --watch`)
was tried and works only some of the time, so it is not provided.

The Linux guest tools install `spice-vdagent` and `qemu-guest-agent`; the
agent starts with the next graphical session. On Windows, the virtio-win guest
tools installer (`virtio-win-guest-tools.exe`, on the `KS_TOOLS` CD) installs
the SPICE agent service along with the drivers and the QEMU guest agent.

In a shared console the VM has one clipboard: a copy in the guest is offered to
every session on the console (owner and LAN guests), and text pasted by any of
them replaces it.

Line ends: noVNC sends CRLF line ends, as the VNC extended clipboard defines,
and QEMU passes them on to the guest as they are.

### Checking copy and paste in a Windows guest

1. The VM was made by KVM Studio, or Settings > Options > Isolation shows copy
   and paste allowed; `virsh dumpxml <vm>` lists
   `<channel type='qemu-vdagent'>` with `<clipboard copypaste='yes'/>`.
2. VM > Install Guest Tools, then run `Install-Tools.bat` from the `KS_TOOLS`
   CD inside Windows; sign out and in again.
3. In Windows, `services.msc` shows "Spice Agent" running (vdservice), and
   Task Manager shows `vdagent.exe` in the session.
4. Host to guest: copy `Grüße, été 2026` on the host, click in the console,
   paste in Notepad: the text appears with no extra character at the end.
5. Guest to host: copy a line in Notepad, paste on the host (text editor):
   same text. Repeat with two lines.
6. Repeat 4 and 5 in window mode and in web mode (Firefox and a Chromium-based
   browser). If 5 fails only in a browser, check that the console had the
   focus when copying.

## Disks

NVMe controllers (hidden when the installed libvirt lacks it), SATA,
virtio-scsi, IDE and virtio-blk. qcow2 or raw creation with optional
preallocation. Existing qcow2, raw, VMDK, VDI or VHDX disks, with a conversion
offered. Normal, independent persistent (`snapshot='no'`) and independent non
persistent (`<transient/>`) modes. Utilities: expand, compact, convert,
information.

The format of an existing disk is never read from its content: a raw disk is
written freely by its VM. It is the format declared in the libvirt definition
of the VM that uses the file, otherwise the one its name stands for (`.qcow2`
for qcow2, raw for anything else), and it is always passed to `qemu-img` with
`-f`. A qcow2 disk brought in without a base gets an empty `<backingStore/>`;
one with a base keeps it, and the chain is logged. A guest may only use disks
whose whole chain lies in the library, and never the disk of another VM.

A disk added to a running VM is attached live first (`virDomainAttachDeviceFlags`)
and written to the config only once QEMU took it; a disk removed from a
running VM is detached, and the config and the file change only once the
guest has released it. New q35 VMs get 14 `pcie-root-port` controllers so
that hotplugged devices find a slot.

## USB storage

`services/usb.py` reads `/sys`: USB devices with a mass storage interface
(class 08), the block devices below them, their mount points
(`/proc/self/mountinfo`), swap (`/proc/swaps`) and device mapper holders. A
device is attached live as `<hostdev type='usb' managed='yes'>` by bus and
device number; libvirt sets the owner and SELinux label of the device node,
so the helper is not involved.

## Source tree

Some parts (answer files) arrive in later phases of the
[roadmap](ROADMAP.md).

```
kvm-studio/
├── backend/kvmstudio/
│   ├── __main__.py          # CLI: run, --check, --mode
│   ├── config.py
│   ├── i18n.py, locale/     # messages of the command line and tray icon
│   ├── app.py               # FastAPI and static frontend
│   ├── shell/               # window (pywebview), web mode (TLS, guest)
│   ├── auth/                # owner/guest roles, sessions, rate limiting
│   ├── libvirt_conn.py
│   ├── api/                 # vms, isos, disks, networks, snapshots, console, prefs, tasks
│   ├── services/
│   ├── xml/                 # domain and network builders, OS profiles
│   ├── unattended/          # answer file templates, ISO generation
│   ├── guesttools/          # guest tools CD (scripts, build, insertion)
│   ├── isolib/              # ISO scan, cache, access check
│   ├── paths.py             # path confinement
│   ├── console/             # VNC and serial WebSocket proxy
│   └── helper_client.py
├── helper/kvmstudio_helper/
│   ├── server.py            # Unix socket, named operations
│   ├── paths.py             # resolution, confinement, race-free opening
│   ├── polkit.py            # caller identity, pkcheck
│   ├── state.py, acl.py     # declared libraries, record of the ACL entries added
│   └── ops/                 # iso_acl, iso_library, join_libvirt, clone_state, port_forward, remove_package (then firewall_port)
├── frontend/src/
│   ├── app/                 # menus, toolbar, library, tabs, status bar
│   ├── features/            # one folder per screen or dialog
│   ├── components/
│   ├── api/                 # typed client generated from the OpenAPI
│   └── i18n/
├── frontend/e2e/            # interface tests (Playwright, test:///default)
├── packaging/               # nfpm, scripts, systemd, polkit, NetworkManager, firewalld, .desktop
└── tests/                   # backend, helper
```

## Stack

| Layer | Choice |
| --- | --- |
| Backend | Python 3.11+, FastAPI, Uvicorn, Pydantic v2 |
| Hypervisor | `libvirt-python` from the distribution |
| XML | `lxml`, builders per OS profile |
| OS detection | internal profiles, and the libosinfo id recorded by virt-manager |
| Frontend | React 18, strict TypeScript, Vite, Radix UI, Lucide, i18next (en, fr) |
| Window | pywebview (Qt WebEngine) |
| Console | noVNC, `qemu-vdagent` chardev, xterm.js for the serial console |
| Answer files | Jinja2 |
| Configuration | TOML validated by Pydantic |
| Packages | nfpm (.rpm, .deb) |
| Quality | ruff, mypy --strict, pytest, eslint, prettier, vitest, Playwright |

The automated tests run on the libvirt `test:///default` driver: neither KVM
nor root is needed in the CI. The helper is tested with simulated commands.

## Installation

The package installs `/opt/kvm-studio`, the `.desktop` launcher, the
`kvmstudio-helper` service, the polkit rules, the NetworkManager file and the
firewalld service. Python dependencies missing from the repositories are
bundled in `/opt/kvm-studio/vendor`. Flatpak and Snap are not offered: their
sandbox does not fit system libvirt, the helper and polkit.

### Uninstall

The "Uninstall KVM Studio" entry runs `kvm-studio --uninstall-wizard`, a window
showing only the uninstall assistant; `kvm-studio --uninstall` asks the same
questions in a terminal.

1. The backend computes a plan (`GET /api/uninstall/plan`): VMs whose files are
   in `KVM-Studio/VM`, exact files to delete and files kept with their reason,
   `kvmnet` networks and the VMs using them, ISO libraries declared through
   the helper with the number of access rights it added, settings files.
2. The execution (`POST /api/uninstall`) receives the fingerprint of the plan
   shown and refuses it when anything changed in between. The rules are those
   of deleting a VM; a network still used by a kept VM stays.
3. The package is removed by the `remove_package` helper operation, which runs
   `dnf remove` (or `apt-get remove`) in a transient systemd unit
   `kvm-studio-removal`: removing the package stops the helper itself.

A plain `dnf remove` only removes the package files and prints a line pointing
to the "Uninstall KVM Studio" entry.

The first-run assistant goes through: welcome and license, checks (VT-x/AMD-V,
KVM module, nested, libvirt service), joining the `libvirt` group, VM and ISO
locations, interface mode, creating `kvmnet1` and `kvmnet8`. It can be started
again from the Help menu.

## Out of scope

Containers, multiple hosts, clusters, a hypervisor of its own, exposure on the
Internet, Windows or macOS hosts, copy and paste of files or images.
