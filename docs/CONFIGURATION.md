# Configuration

KVM Studio reads `$XDG_CONFIG_HOME/kvm-studio/config.toml`, usually
`~/.config/kvm-studio/config.toml`. The file is optional and so is every key:
a missing key takes its default value. A commented template is in
[config.example.toml](../config.example.toml).

The Edit > Preferences screen changes this file. It rewrites it without the
comments and only keeps the values that differ from the defaults: a default
changed in a later version therefore applies to whoever did not change it.
`port = 8765`, the former default, is ignored when reading. The interface mode,
the port and the libvirt URI apply at the next start; the rest applies at once.

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
| `https_port` | `60443` | HTTPS port for sharing on the local network (V1). |
| `share_on_lan` | `false` | Sharing on the local network (V1). Must stay `false`: KVM Studio refuses to start otherwise. |
| `tls` | `"auto"` | Self-signed certificate for LAN sharing (V1). |
| `guest_enabled` | `true` | Guest account for LAN sharing (V1). |
| `login_max_attempts` | `5` | Failed logins before a temporary lockout (V1). |

## [libvirt]

| Key | Default | Description |
| --- | --- | --- |
| `uri` | `"qemu:///system"` | libvirt connection URI. `qemu:///session` works but without kvmnet virtual networks. |

## [storage]

| Key | Default | Description |
| --- | --- | --- |
| `vm_default_location` | none | Location chosen for the VMs. KVM Studio keeps everything under `KVM-Studio/VM/`: `<location>/KVM-Studio/VM/<folders>/<VM name>/<disks>`. Chosen at first run. `~` is accepted. |

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

## [ui]

| Key | Default | Values |
| --- | --- | --- |
| `theme` | `"system"` | `"system"`, `"light"`, `"dark"` |
| `language` | `"system"` | `"system"` (French when the desktop is in French, English otherwise), `"en"`, `"fr"` |

## Environment variables

| Variable | Purpose |
| --- | --- |
| `XDG_CONFIG_HOME` | Location of the configuration folder. |
| `LC_ALL`, `LC_MESSAGES`, `LANG` | Desktop language, used when `language = "system"`. |
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
