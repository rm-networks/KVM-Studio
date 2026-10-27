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

The main process only holds the window (pywebview, Qt WebEngine or else GTK
WebKit) or the tray icon. The backend (Uvicorn, FastAPI, libvirt connection,
event loop) runs in a child process (`shell/backend_process.py`). libvirt is
never loaded in the Qt process: both share the GLib `GMainContext`, which leads
to crashes.

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
- each connection carries one JSON request `{"op": ..., "params": {...}}`;
  any extra key, unexpected type or unknown operation is refused before polkit
  is asked;
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
| `list_port_forwards` | none | the rules kept by the helper; changes nothing |
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
  connected stays usable in the guest system). There is no raw XML editor nor
  PCI passthrough route, and every path stays confined.

The owner's token is only accepted from a loopback address; a guest's session
cookie (HttpOnly, Secure, SameSite=Strict) only on the HTTPS listener. Both
listeners run in the backend process, on one event loop. The loopback one only
answers to `127.0.0.1` and `localhost` as host name (DNS rebinding).

Turning sharing on or off opens or closes the port through the helper. The
shared console uses `<graphics type='vnc' sharePolicy='allow-exclusive'>`:
several noVNC clients can connect and the interface shows how many people are
connected (event `console.viewers`).

## Guest integration

- **Copy and paste (text only).** Every VM with a display gets
  `<channel type='qemu-vdagent'>` with `<clipboard copypaste='yes'/>`, unless
  Options > Isolation turns it off. The host clipboard is linked to noVNC by the
  pywebview API in window mode and by `navigator.clipboard` in web mode (secure
  context: 127.0.0.1 or HTTPS).
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

## Disks

NVMe controllers (hidden when the installed libvirt lacks it), SATA,
virtio-scsi, IDE and virtio-blk. qcow2 or raw creation with optional
preallocation. Existing qcow2, raw, VMDK, VDI or VHDX disks, with a conversion
offered. Normal, independent persistent (`snapshot='no'`) and independent non
persistent (`<transient/>`) modes. Utilities: expand, compact, convert,
information.

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
| OS detection | libosinfo when available, internal profiles otherwise |
| Frontend | React 18, strict TypeScript, Vite, Radix UI, Lucide, i18next (en, fr) |
| Window | pywebview (Qt WebEngine, GTK WebKit fallback) |
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
