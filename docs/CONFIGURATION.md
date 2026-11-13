# Configuration

KVM Studio reads `$XDG_CONFIG_HOME/kvm-studio/config.toml`, usually
`~/.config/kvm-studio/config.toml`. The file is optional and so is every key:
a missing key takes its default value. A commented template is in
[config.example.toml](../config.example.toml).

The Edit > Preferences screen changes this file. It rewrites it without the
comments and only keeps the values that differ from the defaults: a default
changed in a later version therefore applies to whoever did not change it.
`port = 8765`, the former default, is ignored when reading. The interface mode,
the ports, LAN sharing and the libvirt URI apply at the next start; the rest
applies at once.

An unknown key or an invalid value prevents starting, with a message naming the
faulty key. `kvm-studio --check` validates the file without starting anything.
`--config PATH` uses another file.

## [interface]

| Key | Default | Description |
| --- | --- | --- |
| `mode` | `"desktop"` | `"desktop"`: native window. `"web"`: browser. Applied on restart. The `--mode` command line option takes precedence. |

## [web]

| Key | Default | Description |
| --- | --- | --- |
| `port` | `60080` | HTTP port of web mode (local access, 127.0.0.1), between 1024 and 65535. Window mode uses a random port. |
| `https_port` | `60443` | HTTPS port for sharing on the local network, other than `port`. |
| `share_on_lan` | `false` | Web mode: also listen on the local network in HTTPS, for the guest account. Needs the guest password (Preferences > Interface), otherwise KVM Studio refuses to start. The helper opens the port in firewalld (service `kvm-studio` on the default port) or ufw while KVM Studio runs. |
| `tls` | `"auto"` | Self-signed certificate, made with openssl at the first start in `$XDG_CONFIG_HOME/kvm-studio/tls/` (EC P-256, ten years). Its fingerprint is shown in Preferences. |
| `guest_enabled` | `true` | Guest account of LAN sharing; `false` keeps sharing off. |
| `login_max_attempts` | `5` | Failed logins from one address before a five minute lockout. |

The guest password is stored as an argon2 hash in
`$XDG_CONFIG_HOME/kvm-studio/guest.hash` (readable by the user only), set from
Preferences > Interface. Guest sessions end after 30 minutes without a request,
and setting a new password ends them all.

## [libvirt]

| Key | Default | Description |
| --- | --- | --- |
| `uri` | `"qemu:///system"` | libvirt connection URI. `qemu:///session` works but without kvmnet virtual networks. |

## [storage]

| Key | Default | Description |
| --- | --- | --- |
| `vm_default_location` | none | Location chosen for the VMs. KVM Studio keeps everything under `KVM-Studio/VM/`: `<location>/KVM-Studio/VM/<folders>/<VM name>/<disks>`. Chosen at first run. `~` is accepted. Picking the `KVM-Studio` or `KVM-Studio/VM` folder of an existing tree sets its parent, so the VMs already there show up. |

## [[iso_libraries]]

ISO libraries, browsed read-only. Repeat the block for each folder.

| Key | Default | Description |
| --- | --- | --- |
| `name` | required | Displayed name. |
| `path` | required | Root folder. |
| `recursive` | `true` | Browse subfolders. |
| `extensions` | `[".iso", ".img"]` | Recognized extensions. |

## [defaults]

Values offered by the new VM assistant.

| Key | Default | Values |
| --- | --- | --- |
| `firmware` | `"uefi"` | `"uefi"`, `"bios"` |
| `disk_bus` | `"virtio"` | `"virtio"`, `"scsi"`, `"sata"`, `"nvme"`, `"ide"` |
| `nic_model` | `"virtio"` | `"virtio"`, `"e1000e"`, `"rtl8139"`, `"vmxnet3"` |
| `virtio_win_iso` | none | virtio-win ISO, in an ISO library. Only read: its `virtio-win-guest-tools.exe` is copied onto the Windows guest tools CD. |

## [workspace]

Virtual machines keep running when KVM Studio closes: libvirt and QEMU run them,
not KVM Studio. You find them again the next time it starts.

| Key | Default | Values |
| --- | --- | --- |
| `on_close` | `"keep"` | What happens to running VMs when KVM Studio closes or changes between window and web mode: `"keep"` (they keep running), `"ask"` (keep, suspend or shut down, each time), `"suspend"` (state saved to disk, resumed at their next start), `"shutdown"` (clean shutdown; after 60 s the VMs still running can be powered off or left running). Preferences > Workspace. |
| `close_reminder` | `true` | With `"keep"`: list the running VMs and remind that they keep running, with a "Do not show this again" box that sets it to `false`. |

## [ui]

| Key | Default | Values |
| --- | --- | --- |
| `theme` | `"system"` | `"system"`, `"light"`, `"dark"` |
| `language` | `"en"` | `"en"` or `"fr"`. The desktop language is not looked at. `"system"`, from versions before 1.0.0, reads as `"en"`. |
| `vm_tabs` | `true` | Shows the bar of the open VM tabs. Without it, a VM is opened from the library or the Tabs menu. |

## Environment variables

| Variable | Purpose |
| --- | --- |
| `XDG_CONFIG_HOME` | Location of the configuration folder. |
| `XDG_STATE_HOME` | Location of the state folder (`kvm-studio/library-order.json`: display order of the library folders). |
| `KVMSTUDIO_FRONTEND_DIR` | Folder of the built interface, when it is not at its usual place. |
| `KVMSTUDIO_BACKEND` | Development: API address for the Vite server (default `http://127.0.0.1:60080`). |
| `KVMSTUDIO_HELPER_SOCKET` | Helper socket (default `/run/kvmstudio-helper.sock`). |

## ISO libraries and the helper

Preferences > ISO Libraries adds and removes libraries one at a time, asking for
the administrator password: the helper checks the folder (yours, outside the
system folders) and keeps its own list in `/var/lib/kvm-studio/helper-state.json`,
next to the record of the access rights it gave QEMU there. Removing a library
takes those rights back. The "Fix" button of the ISO picker works for the
libraries the helper knows; one written to `config.toml` by an earlier version
is shown as not declared, and removing it then adding it again declares it.

## Helper: /etc/kvm-studio/helper.toml

This file belongs to root and is edited with `sudo` by the administrator, who
can declare libraries there too (shared folders such as `/srv/iso`). The helper
reads it with its own list, the same folder counting once; it never trusts
`config.toml` for that.

```toml
# socket = "/run/kvmstudio-helper.sock"
# state = "/var/lib/kvm-studio/helper-state.json"
# qemu_user = "qemu"          # detected: qemu, then libvirt-qemu

[[iso_libraries]]
path = "/srv/iso"
extensions = [".iso", ".img"]  # default
```

An unknown key prevents the helper from starting. The full template is in
`packaging/helper/helper.toml`.

## Library folders

The library folders are real folders under `<location>/KVM-Studio/VM/`.
Creating, renaming or deleting a folder in KVM Studio does the same on disk;
moving a powered off VM moves its folder and updates the paths in libvirt.

KVM Studio never deletes or moves a file outside `KVM-Studio/`, an ISO image, a
disk used by another VM or the base disk of a linked clone. VMs created
elsewhere (virt-manager) are only filed in the library, without touching their
files.

The folder of each VM is also written in its libvirt XML (`<metadata>`,
namespace `https://github.com/rm-networks/kvm-studio/ns/1.0`). When files were
moved by hand, the VM stays shown at its recorded place, with a warning
triangle: KVM Studio reports the gap without fixing it.
