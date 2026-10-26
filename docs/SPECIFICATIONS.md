# KVM Studio: specifications

Oct 22, 2026 · @Romain

## 1. Context and goals

**KVM Studio** is a virtual machine manager for Linux that follows the ergonomics and features of VMware Workstation, driving QEMU/KVM through libvirt. An open source community project on GitHub, tested first on Fedora KDE Plasma 6.

**Problem.** Former Workstation users find virt-manager dated, Cockpit limited, Incus unable to use an existing ISO folder, Karton too simple. VirtualBox is ruled out.

**Path.** A personal tool first (MVP on Fedora), then shared with friends (V1, Fedora + Debian/Ubuntu), then public if the result holds. The code stays portable from day one so that sharing needs no rewrite.

**Goals.**

1. The organization of Workstation: library tree, VM tabs, summary, assistants, same menus and dialogs.
2. Running either as desktop software (native window) or as a web interface that can be shared on the LAN with a guest account, never both at once.
3. Every location can be changed: existing ISO folders (subfolders included, without import or copy), VM location.
4. NAT and Host-only networks as precise as the Virtual Network Editor, working without tinkering; Bridged in V2.
5. Virtual disks with the same range of choices as Workstation.
6. Native text copy and paste between the host and the VMs, and guest tools installed in one click.
7. A clean computer: no virtual card in the network applet, no Docker, complete uninstall.
8. Installed like normal software: .rpm or .deb package with a double click, then a first-run assistant.
9. libvirt compatible: VMs visible and usable in virt-manager and virsh.

**Audience.** System and network administrators, students (TSSR, AIS, CCNA…), trainers, homelabbers coming from Workstation. Uses: network and security labs (multi-NIC firewalls, Windows Server, Linux, nested hypervisors).

**Non-goals.**

- No containers (LXC, Docker, Incus): only VMs, like Workstation.
- No multi-host management or cluster.
- No hypervisor of its own: everything goes through libvirt.
- No Windows or macOS host.
- No exposure on the Internet.
- No copy and paste of files or images (text only).

## 2. Principles and constraints

libvirt is the only source of truth, and KVM Studio only leaves on the computer what its package knows how to remove.

| Area | Rule |
| --- | --- |
| Legal | Interface and features inspired by simply observing the software (screenshots, use). No reverse engineering or decompilation of VMware, REA-type tools ruled out. No VMware name, logo, icon, text or visual; Lucide icons (ISC). |
| Positioning | Notice in the README and in "About": "KVM Studio is a community project inspired by the interface and features of VMware Workstation. It is not affiliated with VMware or Broadcom and uses none of their code or artwork." |
| Compatibility | Domains, networks and volumes created through the standard libvirt API, visible and editable in virt-manager and virsh. |
| Metadata | The application's own data (library folder, notes, options) in the `<metadata>` of the libvirt XML, in a dedicated namespace. |
| Portability | No hard-coded path, pool, network or URI: everything can be set in Preferences and is stored in the configuration. |
| Clean computer | No virtual interface in the network applet (NetworkManager told to ignore them). No Docker, no third-party service. Every system file belongs to the package. The uninstall assistant removes, as chosen, the VMs, the kvmnet networks and the settings, then the package. |
| Non destructive | ISO folders are read-only: no copy, no move, no rename. |
| Security | Window mode: internal server only reachable by the window (loopback + token). Web mode: 127.0.0.1 by default, with a token; LAN sharing = self-signed HTTPS + password-protected guest account, with rights limited to the VMs (section 6.11). |
| Distribution | MVP: Fedora. V1: Fedora, Debian, Ubuntu. Other distributions later. |
| License | GPL-3.0, consistent with libvirt and virt-manager. |

## 3. Technical architecture

A single Python backend drives libvirt; the same frontend shows either in a native window or in a browser; a small privileged service does the few root operations.

| Layer | Choice | Why |
| --- | --- | --- |
| Backend | Python 3.11+, FastAPI, Uvicorn, Pydantic v2 | Async, automatic OpenAPI, readable for an administrator |
| Hypervisor access | libvirt-python, distribution package (`python3-libvirt`) | Bindings matching the installed libvirt |
| Real time | libvirt events → WebSocket | VM states up to date without refreshing |
| XML | lxml, builders per OS profile | XML following the libvirt schema, testable |
| Frontend | React + TypeScript + Vite, Radix UI, Lucide | Dense desktop software style interface |
| Window mode | pywebview (Qt WebEngine, GTK WebKit fallback) | A real window, a launcher in the applications menu, native clipboard |
| Processes | The window (or the tray icon in web mode) alone in the main process; server, libvirt and its event loop in a child process | The libvirt loop and Qt share the default GLib context: in a single process, the window crashes |
| Web mode | Same frontend served over HTTPS, guest account | Working together on the LAN |
| Graphical console | noVNC + QEMU `qemu-vdagent` channel, VNC in shared mode | Native text copy and paste; several people on the same console |
| Serial console | xterm.js | Firewalls and appliances without a GUI |
| Answer files | autounattend.xml (Windows), kickstart (Fedora/RHEL), preseed / autoinstall (Debian/Ubuntu) templates | Easy install with guest tools |
| Privileged helper | `kvmstudio-helper`: root systemd service, Unix socket, polkit authorizations | The only root component: joining the libvirt group, opening the web port in the firewall, NAT port forwarding, ISO libraries and their access rights, uninstall |
| OS detection | libosinfo, internal profiles as a fallback | Good defaults (virtio, UEFI, TPM) |
| Packaging | .rpm and .deb packages built by the CI (nfpm), published in the GitHub Releases, then COPR and APT repositories | Double click to install, dependencies and uninstall handled by the distribution |
| Tests | pytest + `test:///default` URI, Playwright | Tests without a real VM, in GitHub Actions CI |

**Interface modes (exclusive).** Chosen in Preferences > Interface, applied when the application restarts.

- *Window* (default): the backend listens on 127.0.0.1, random port, token per session. Nothing can be reached outside the window.
- *Web*: HTTP on 127.0.0.1, port 60080 by default; HTTPS port 60443 for sharing on the local network (V1); both ports are set in Preferences > Interface. At start, the page opens in the default browser with the token in the URL fragment (like a click on a link); the URL is also printed in the terminal. An icon in the notification area (StatusNotifierItem, KVM Studio logo) shows that KVM Studio is running: Open in the Browser, Copy the Address, Switch to Window Mode, Quit. Without a notification area (GNOME without the AppIndicator extension), the application runs normally without an icon. "Share on the local network" option: listening on the LAN, self-signed HTTPS, port opened in firewalld or ufw, login with the guest account. The owner also uses the browser in this mode.
- *Mode change*: Preferences > Interface offers to restart right away; the message gives the ports (60080 over HTTP for local access, 60443 over HTTPS for sharing). The application starts again in the new mode.

**libvirt connection.** Configurable URI, `qemu:///system` by default. The first-run assistant adds the user to the `libvirt` group through the helper (operation without parameters, administrator authentication every time), then asks to log in again.

**ISO access rights.** QEMU runs as the `qemu` user and must read the ISO images. KVM Studio detects a refusal (Unix rights, ACL, SELinux, AppArmor) and offers a "Fix" button that goes through the helper after polkit authentication.

## 4. Configuration and installation

Everything is set in Preferences and in the first-run assistant; the settings are stored as readable TOML, and installation goes through a .rpm or .deb package.

**Files.** User settings in `$XDG_CONFIG_HOME/kvm-studio/config.toml`; helper settings in `/etc/kvm-studio/helper.toml`, its own state (declared ISO libraries, access rights it added) in `/var/lib/kvm-studio`; guest password stored hashed (argon2) in `$XDG_CONFIG_HOME/kvm-studio/guest.hash`. `kvm-studio --check` validates the configuration and tests libvirt, pools and ISO rights.

```toml
[interface]
mode = "desktop"          # "desktop" (window) | "web"

[web]
port = 60080              # HTTP, local access (127.0.0.1)
https_port = 60443        # HTTPS, sharing on the local network
share_on_lan = false      # true = LAN listening + HTTPS + guest account
tls = "auto"              # self-signed certificate generated at first start
guest_enabled = true      # password set in Preferences > Interface
login_max_attempts = 5    # temporary lockout beyond

[libvirt]
uri = "qemu:///system"

[storage]
# vm_default_location = "/srv/vm"     # chosen at first run; the VMs go in <location>/KVM-Studio/VM

[[iso_libraries]]
name = "Main ISO"
path = "/srv/iso"
recursive = true
extensions = [".iso", ".img"]

[defaults]
firmware = "uefi"
disk_bus = "virtio"
nic_model = "virtio"
# virtio_win_iso = "/srv/iso/drivers/virtio-win.iso"

[ui]
theme = "system"
language = "en"           # "en" | "fr"
```

**Installation.**

1. Download `kvm-studio-<version>.x86_64.rpm` (Fedora) or `kvm-studio_<version>_amd64.deb` (Debian/Ubuntu) from the GitHub Releases.
2. Double click: Discover or Software installs it with its dependencies (libvirt, qemu, python3-libvirt, edk2/OVMF, swtpm…). On the command line: `sudo dnf install ./kvm-studio-*.rpm` or `sudo apt install ./kvm-studio_*.deb`.
3. The package installs `/opt/kvm-studio` (code + frontend), the launcher and the icon, the `kvmstudio-helper` service, the polkit rules, the NetworkManager hiding file and the firewall service definition.
4. Updates: a new package from the Releases; later, COPR (Fedora) and APT (Debian/Ubuntu) repositories for automatic updates.
5. Uninstall: "Uninstall KVM Studio" assistant (see below); a plain `dnf remove` / `apt remove` only removes the package files.

**First-run assistant** (the counterpart of the Workstation setup assistant): Welcome and license → Checks (VT-x/AMD-V, KVM module, nested virtualization, libvirt service) → Joining the `libvirt` group → Locations (VMs, ISO libraries) → Interface mode → Creating kvmnet1 and kvmnet8 → Done. It can be started again from Help.

**Uninstall** (the counterpart of the Workstation uninstaller): an "Uninstall KVM Studio" entry in the applications menu, which opens an assistant (Next / Back / Cancel): Welcome → Virtual machines (keep, or delete with the exact list of files and a confirmation box) → kvmnet networks created by KVM Studio (keep or delete) → Access rights granted on the ISO libraries (keep or remove) → Settings (keep or delete) → Summary → Uninstalling → Done. At the end, the helper removes the package after polkit authentication, without a terminal. Same rules as deleting a VM: no file deleted outside `KVM-Studio/VM`, never an ISO, never a file a kept VM needs; VMs created outside KVM Studio and the networks they use are always kept. `kvm-studio --uninstall` asks the same questions in a terminal. A plain `dnf remove` / `apt remove` only removes the package files (VMs, networks and settings kept) and says so with a line pointing to the "Uninstall KVM Studio" entry.

An INSTALL.md document also covers installing from the repository and troubleshooting.

## 5. Interface: screens and menus

The interface follows the layout, menus and dialogs of Workstation 17 (from screenshots), with 100% original visuals, in English and French.

**Layout.**

- Menu bar: File, Edit, View, VM, Tabs, Help.
- Toolbar: power (with a drop-down menu), send Ctrl+Alt+Del, snapshot / revert / manager, show the library, thumbnails, full screen, console.
- Library on the left: search with a filter, "My Computer" tree → folders → VMs, drag and drop between folders. A single click on a VM shows its tab (and opens it if needed); the other way round, the active tab selects its VM in the library, opening its folder and scrolling to it. With the Home tab active, no VM is selected.
- Tabbed central area: Home + one tab per open VM. A VM tab always shows the VM name.
- Status bar: devices (disk, network, CD, USB) with activity, reminder of the release shortcut.

**Screens.**

| Screen | Content |
| --- | --- |
| Home | Tiles for what is available: Create a New Virtual Machine (Open a Virtual Machine and Connect to a Server arrive later) |
| VM summary | Actions (start, settings), device list, description, details (state, folder, IP through the guest agent, linked clones depending on it) |
| Console | Console inside the tab, scaling, full screen |
| VM settings | Hardware and Options tabs, "Device / Summary" list on the left, details on the right, Add… / Remove buttons |
| New VM assistant | Typical / Custom, with Easy Install (section 6.3) |
| Clone assistant | Source VM, clone type (full or linked), name, library folder, summary (F-84) |
| Snapshot manager | Tree, "You are here" marker, Take / Revert / Delete / Clone |
| Virtual network editor | Section 6.8 |
| Preferences | Section list on the left, settings on the right |
| ISO picker | Tree of the ISO libraries, search, size, detected OS |
| Login (shared web mode) | Guest account password, message during a temporary lockout; "Logged in as guest" banner afterwards |

Only what works is shown: an entry, a tile or a setting that is not available yet is hidden, never shown disabled with a "coming later" notice.

**Menus.**

| Menu | Entries |
| --- | --- |
| File | New Virtual Machine… (Ctrl+N), Open… (Ctrl+O: libvirt XML, OVA/OVF), Scan for Virtual Machines…, Configure Auto Start of VMs…, Close Tab (Ctrl+W), Connect to a Server… (V2), Export to OVF…, Quit |
| Edit | Cut / Copy / Paste, Virtual Network Editor…, Preferences… (Ctrl+P) |
| View | Full Screen (Ctrl+Alt+Enter), Toggle Application Full Screen (F11), Console View, Fit Guest Now, Fit Window Now, Autosize ›, Customize › (library, toolbar, status bar, thumbnails) |
| VM | Power ›, Removable Devices ›, Pause (Ctrl+Shift+P), Send Ctrl+Alt+Del, Grab Input (Ctrl+G), Snapshot ›, Capture Screen (Ctrl+Alt+PrtScn), Manage › (clone, rename, delete from disk), Install Guest Tools…, Settings… (Ctrl+D) |
| Tabs | List of the open tabs, Go to the Home Tab, Next Tab (Ctrl+Tab), Previous Tab (Ctrl+Shift+Tab) |
| Help | Documentation, Keyboard Shortcuts, About (with the non-affiliation notice), Report a Bug |

The Power submenu holds: Start, Shut Down Guest, Restart Guest, Suspend, Resume, Power Off, Reset.

The context menu of a VM in the library holds Open in a Tab, the power actions, Clone…, Rename, Move To, Delete, then Settings… (Ctrl+D) last, after a separator, as in the VM menu.

**VM settings, Hardware tab.** Memory, Processors, Disks, CD/DVD, Network adapters, USB controller, Sound card, Display, Serial port, TPM. The Memory panel has the vertical slider from 4 MB to the host maximum, with three marks: guest OS minimum, recommended, recommended maximum.

**VM settings, Options tab.** Changes that need the VM powered off are disabled while it runs, with a note; the others apply at its next start.

| Option | Content |
| --- | --- |
| General | Name (VM powered off), guest system (the profile in `<metadata>`, the hardware is not changed) |
| Power | Start with the host (libvirt autostart), action when the guest restarts (`on_reboot`) or crashes (`on_crash`) |
| Shared folders | virtiofs shares host → VM |
| Snapshots | Behavior at power off (nothing, revert, ask) |
| AutoProtect | Scheduled snapshots with rotation |
| Guest isolation | Copy and paste allowed or not (`<clipboard copypaste>` of the qemu-vdagent channel; turned off, the console no longer offers to turn it on) |
| Access control | Disk encryption (LUKS qcow2) |
| Guest tools | Agent state, time synchronization |
| VNC connections | External VNC access with port and password |
| Firmware and boot | BIOS or UEFI, Secure Boot, TPM 2.0 (VM powered off; an installed VM gets a warning and a confirmation before changing between BIOS and UEFI or removing its TPM), boot order per device (drag or arrows, a box to leave a device out), boot menu at start. Turning Secure Boot on or off rebuilds the UEFI variables the next time KVM Studio starts the VM (`VIR_DOMAIN_START_RESET_NVRAM`) |
| Advanced | Raw XML editor, priority |

**Preferences.** Workspace (VM location, ISO folders, remembered tabs, VMs that keep running on close, thumbnails, screenshots; "When KVM Studio closes": keep the VMs running (default), ask, suspend, or shut down cleanly with a 60 s delay then an offer to force; closing the window, File > Quit, the tray icon's Quit and a change between window and web mode list the running VMs and recall that libvirt and QEMU run them, with a "Do not show this again" box; the same sentence ends the first-run assistant), Interface (window or web mode, port, LAN sharing, certificate, guest account password, connected people), Input, Shortcuts, Display (theme, language, scaling), USB, Memory (reserve for the host), Devices.

**Shortcuts** the same as those of Workstation listed above, all remappable (the browser takes some combinations in web mode).

## 6. Detailed features

Each feature has an identifier (F-xx) used in the prioritization.

### 6.1 VM library

- **F-01** List every libvirt domain (active and inactive), including those created outside KVM Studio.
- **F-02** Library folders synced with the file system (details in 6.1.1).
- **F-03** Search, filter (all / running), sort.
- **F-04** Live state through libvirt events.
- **F-05** Scan for virtual machines: scan a folder to find unregistered XML files or disks.

#### 6.1.1 Library folders synced to disk (F-02)

The library folders are real folders on disk: what the user sees in the tree matches what they find in their file manager.

- **Tree.** `<chosen location>/KVM-Studio/VM/<folders>/<VM name>/<disks>`. Example: `…/KVM-Studio/VM/Labs/SRV-WS22/SRV-WS22.qcow2`. Next disks: `SRV-WS22-2.qcow2`, `SRV-WS22-3.qcow2`… The UEFI NVRAM is also in the VM folder. Nested folders allowed.
- **Folders.** Creating, renaming or deleting a folder in the library does the same on disk.
- **Moving.** Moving a VM to another folder (menu or drag and drop) moves its files and updates the paths in the libvirt XML. Powered off VMs only. A folder is moved by drag and drop into another one (or onto the top level), nested folders included: its subfolders and the files of its VMs follow, with the same rules (VMs powered off, linked clones outside the folder blocking, a confirmation listing the VMs, never outside the `KVM-Studio` root). Dropped on the top or bottom edge of a folder, it goes before or after it: the display order is kept in a small state file of KVM Studio (`$XDG_STATE_HOME/kvm-studio/library-order.json`), never on disk next to the VMs.
- **Deleting.** Deleting a VM or a whole folder deletes the related files, after a confirmation listing exactly what will be erased.
- **Safeguards.** Never deleting or moving a file outside the `KVM-Studio` root, a disk used by another VM, or an ISO. Linked clones (backing file): the chain is updated, otherwise the action is blocked with a clear message.
- **VMs created outside KVM Studio** (virt-manager, disks elsewhere): never moved automatically. They can be filed in a library folder (virtual filing, written in `<metadata>`), with a "Move the Files into KVM Studio" action.
- **Rebuilding.** The library folder of each VM is also written in `<metadata>`, so that the library rebuilds even when files were moved by hand. When `<metadata>` and the real location differ, KVM Studio reports it and does not fix it by itself.
- **Guest account (V1)**: can create, file and delete in this tree, always confined to the `KVM-Studio` root.

### 6.2 Life cycle

- **F-10** Start, shut down the guest (ACPI), power off, restart, reset. A guest still on 20 s after Shut Down Guest (firmware screen, system still starting) gets a notice offering Power Off; nothing is forced on its own.
- **F-11** Pause (frozen in RAM) and Suspend (state saved to disk), like Workstation.
- **F-12** Rename, delete (unregister only or delete the disks too, after a confirmation listing the files).
- **F-13** Configure the automatic start of VMs with the host, with a delay between VMs.

### 6.3 New VM assistant

- **F-20** Typical: installation source → guest OS → name and location (default folder from Preferences) → disk → summary with "Customize Hardware".
- **F-21** Custom: firmware (BIOS/UEFI, Secure Boot), processors (sockets/cores/threads), memory, network, disk controller and type, disk (new / existing / none).
- **F-22** Source: ISO through the picker (F-30), "install the OS later", or an existing disk, picked with Browse. An existing disk is used where it is (default, no folder created), copied into the VM's folder (the original stays) or moved there after a confirmation that lists the move. File > Open… picks a disk image (`.qcow2`, `.raw`, `.img`) and opens the wizard on it, named after the file. A VM whose disks lie loose in the `KVM-Studio` root offers "Put Files in Their Own Folder…"; one whose disks are outside offers "Move Files into KVM Studio…"; neither entry shows when there is nothing to move.
- **F-23** OS detection from the ISO (libosinfo), manual choice as a fallback.
- **F-24** OS profiles: Windows 11 (UEFI + Secure Boot + TPM 2.0), Windows Server, Linux, firewall/BSD (pfSense, OPNsense, FortiGate VM, Stormshield EVA…: 3 NICs + serial console by default), nested hypervisor (host-passthrough CPU).
- **F-25** Windows: a second CD drive with the virtio-win ISO when it is configured.
- **F-26** Easy install (the counterpart of Workstation's Easy Install): the assistant asks for a user name, password, language, keyboard and, for Windows, the product key (optional). KVM Studio generates an answer file (autounattend.xml, kickstart, preseed or autoinstall) on a small separate ISO, without touching the original ISO. The OS installs without intervention, guest tools included. Targets: Windows 10/11, Windows Server, Fedora/RHEL, Debian, Ubuntu.

### 6.4 Storage and ISO libraries

- **F-30** ISO picker as a tree over several root folders, subfolders included, read-only.
- **F-31** Search on names, sort by name/date/size.
- **F-32** Metadata cache (size, date, detected OS), refreshed on demand.
- **F-33** Check that QEMU can read, "Fix" button through the helper.
- **F-34** Change or eject the ISO of a running VM.
- **F-35** Changeable VM location (root `<location>/KVM-Studio/VM`); one VM = one folder holding its disks and NVRAM, filed in the tree of library folders (F-02).
- **F-36** ISO libraries declared and removed from Preferences > ISO Libraries, without editing a file: the helper checks the folder (owned by the user, outside system folders), keeps the list, and removes at the end only the access rights it granted itself.

### 6.5 Virtual disks

- **F-40** Choice of controller type, with a recommendation by OS: NVMe (when the libvirt version allows it), SATA, SCSI (virtio-scsi), IDE, virtio-blk.
- **F-41** Create a disk: size, qcow2 or raw format, "Allocate all disk space now" box (preallocation), location (VM folder by default).
- **F-42** Use an existing disk: qcow2, raw, VMDK, VDI, VHDX, with a conversion to qcow2 offered to enable snapshots.
- **F-43** Modes: normal, independent persistent (left out of snapshots), independent non persistent (changes lost at power off).
- **F-44** Utilities: Expand, Compact (get free space back), Convert, Information (real/virtual size, backing chain), Mount on the host (V2, libguestfs). Expand (V1): VM settings, disk, shows the virtual size and the space used on the host; grows only, running (libvirt block resize, the guest sees it at once) or powered off (libvirt resizes the volume, through a transient storage pool when the folder is in none); only disks under the `KVM-Studio` root, never a disk linked clones are built on. The partition is grown in the guest by the user.
- **F-45** Advanced: cache, I/O mode, TRIM/discard, serial number, IOPS limits.
- **F-46** Physical disk passthrough (advanced, with a warning, owner only).
- **F-47** Scan for virtual machines (File menu and Preferences > Workspace, owner only): a folder and its subfolders are searched for `.qcow2` disks, grouped by folder, and libvirt definitions (`.xml`); the VMs libvirt already knows are marked and cannot be picked. Each VM picked keeps its files where they are (default) or has them copied or moved into the `KVM-Studio` tree, never elsewhere, after a confirmation that lists every copy and move. Library folders are rebuilt from the tree found (what lies under `KVM-Studio/VM`, when there is one). A disk without a definition gets the "Other" profile, with UEFI when it holds a GPT table.

"Split into several files" has no useful counterpart with KVM and is not offered.

### 6.6 Other virtual hardware

- **F-50** Processors: count, topology, mode (host-passthrough, host-model, custom), nested virtualization.
- **F-51** Memory with a slider and marks (guest minimum, recommended, recommended maximum).
- **F-52** CD/DVD drives: several per VM, ISO or empty.
- **F-53** Network adapters: several per VM, added in one click, model (virtio, e1000e, rtl8139, vmxnet3), target kvmnet network, MAC, card connected/disconnected live.
- **F-54** Display (virtio-gpu, qxl, vga), sound card, USB controller, serial port, TPM.
- **F-55** Firmware and boot: boot order, boot menu, Secure Boot. When a VM started on a CD placed first in the boot order reboots (end of an installation), the first disk moves ahead of the CD and the VM starts again on it; the CD stays inserted, second. Done by the backend while it runs.
- **F-56** Raw XML editor with validation before applying (owner only).
- **F-57** USB passthrough (V2), PCI passthrough (later), owner only.

### 6.7 Console and guest integration

- **F-60** Console inside the VM tab, scaling, full screen, Fit Guest / Window. The console uses the VNC display of the VM (no listening port, through libvirt). For a VM with only a SPICE display (made in virt-manager), the console works through it; when the VM lacks the QEMU vdagent channel, a single banner offers to turn copy and paste on, and no banner remains once it is on and the VM has been restarted. When the VM is started from KVM Studio, the console opens on the KVM Studio splash (the loading cubes, still when animations are reduced), which covers the UEFI firmware logo: it stays at least 1.5 s even when the console connects sooner, 3 s at most, and goes at the first key or click, which still reaches the guest, so that no "Press any key" prompt or boot menu stays hidden. Opening the tab of a VM that is already running shows no splash. A console out of sight for 15 s (another tab, the window minimized, a hidden browser tab) lets go of its VNC stream, which costs CPU for nothing, and connects again as soon as it shows. View > Full Screen (Ctrl+Alt+Enter, also the toolbar button) shows the console of the VM alone on the screen, without frame or bars; a thin bar comes out when the pointer touches the top of the screen and hides 2 s after it leaves: Exit full screen, Send Ctrl+Alt+Del, power menu. Ctrl+Alt+Enter leaves it too; Escape stays for the VM. Toggle Application Full Screen (F11, given to the guest while the console holds the keyboard) puts the whole window in full screen. In web mode the console full screen uses the browser Fullscreen API: the browser imposes Escape to leave it, except Chromium-based browsers, where the Keyboard Lock API gives Escape to the VM and a long press leaves; a notice says so the first time. The firmware logo itself is drawn by OVMF and cannot be removed or replaced through libvirt or QEMU without a custom firmware build.
- **F-61** Native text copy and paste host ↔ VM through the `qemu-vdagent` channel and the guest's `spice-vdagent` agent; can be turned off in Options > Isolation. Files and images not supported.
- **F-62** Sending key combinations (Ctrl+Alt+Del, Ctrl+Alt+F1…F12, Print Screen), Grab Input (Ctrl+G).
- **F-63** Serial console (xterm.js) for firewalls and appliances: a running VM with a serial console shows Screen and Serial Console views above its console, and opens on the serial one when it has no display. The stream comes from libvirt (`virDomainOpenConsole`), without taking over a console already open elsewhere (`virsh console`), so the VM keeps working in virt-manager.
- **F-64** Install the guest tools on an existing VM (VM > Install Guest Tools): KVM Studio builds a small CD (label `KS_TOOLS`) in its own folder `<location>/KVM-Studio/Tools`, never in an ISO library, and inserts it in one CD/DVD drive of the VM: a drive that already holds it, else an empty one, else one holding something (the Windows setup ISO, for instance); on a running VM a drive that is only in the config comes last. What the drive held before is written in `<metadata>` and put back at eject. A SATA drive is added only when the VM has none; on a running VM it appears after the VM is shut down and started again (a reboot inside the guest is not enough), and the dialog says so. Windows: the CD holds `autorun.inf`, `Install-Tools.bat` and `virtio-win-guest-tools.exe`, copied with `xorriso` from the `defaults.virtio_win_iso` ISO, which is only read; this installer includes the virtio drivers, qemu-guest-agent and spice-vdagent. `Install-Tools.bat` asks for elevation and runs the installer with `/quiet /norestart` from its own drive, or from another drive when it is not there; `/unattended` skips the pauses (guest-exec), and the exit code is the installer's (0 or 3010 give 0). In Preferences > Virtual machines, the virtio-win ISO is chosen with Browse (the ISO picker of the libraries, in window and web mode alike) or typed; a path outside the libraries offers to add its folder as a library (helper, administrator password), and a ? button explains what the ISO is for and links to two stable documentation pages, the Fedora guide on Windows virtual machines with the virtio drivers and the README of the virtio-win project, opened in the default browser; there is no direct link to the ISO and no download button: KVM Studio downloads nothing, and the user alone is responsible for what they download. Before inserting, the dialog tells apart a virtio-win ISO that is not set, no longer exists, is outside the ISO libraries (with a button to add its folder as a library), or has no installer at its root. Linux: `install.sh` detects the package manager (apt, dnf, zypper, pacman), installs qemu-guest-agent and spice-vdagent and enables the services. The user starts the installation inside the VM (double click, autorun, or a short command shown with a Copy button): nothing depends on the guest keyboard layout. The agent channel is added to the VM when missing. The dialog shows the real state of each step (installer copied, drive used, installation, agent), asks qemu-guest-agent every 5 s for 10 min at most, then offers to eject the CD.
- **F-65** Shared folders host → VM through virtiofs.
- **F-66** VM screenshot (clipboard and/or file).
- **F-67** Live thumbnails of the running VMs.

### 6.8 Virtual networks

- **F-70** Virtual network editor: Name / Type / External connection / Host connection / DHCP / Subnet table; Add, Remove, Rename buttons; panel of the selected network (type, host adapter, DHCP and its settings, IP and mask); Restore Defaults, Import, Export.
- **F-71** Networks created at first run: kvmnet1 (Host-only, DHCP) and kvmnet8 (NAT, DHCP), on subnets that do not overlap the LAN. kvmnet0 is reserved for Bridged (V2).
- **F-72** Host-only: isolated network, "Connect a host virtual adapter" box (the host has an IP on this network or not), optional DHCP. The host address can be anywhere in the subnet (the DHCP range moves off it); DHCP Settings choose the gateway DHCP announces (none, which is libvirt's default, the host, or another address such as a firewall VM); KVM Studio reserves no DHCP address. Changes that restart the network list the running VMs that use it and ask before stopping and starting them again (details in NETWORKING.md).
- **F-73** NAT: outside access through the host IP, DHCP, NAT settings (gateway, TCP/UDP port forwarding) handled in an nftables table of KVM Studio's own. NAT Settings > Port Forwarding as in Workstation (Host port, Type, VM IP address, VM port, Description; Add, Remove, Properties): the administrator writes the VM address, KVM Studio neither looks it up nor reserves it; the host address is 127.0.0.1 by default and can be any address, 0.0.0.0 included, without a confirmation; a host port already in use is only mentioned. The helper checks protocol, ports, addresses and that the VM address is in the network's subnet read from libvirt (details in NETWORKING.md, with the limit of libvirt's own rules for connections from other machines).
- **F-74** Transparent Bridged (V2): small transparent router with proxy ARP + DHCP relay, Wi-Fi or wired, without touching the user's connection. To prototype before committing (boxes refusing the DHCP relay, corporate networks with port security).
- **F-75** Full L2 Bridged (V2, Ethernet only option): a real bridge through NetworkManager.
- **F-76** Quick lab segments (LAN-1, LAN-2, DMZ…) = Host-only without a host adapter.
- **F-77** Clean computer: every network created by KVM Studio has a bridge named `kvmnetN`, whatever its displayed name (for example Host-Only-3); VM cards `ks-*`; they and the `vnet*` cards libvirt names itself are declared unmanaged in NetworkManager → invisible in the network applet (`virbr*` and the other interfaces are left alone). `kvm-studio --check` reports a missing `/etc/NetworkManager/conf.d/90-kvm-studio.conf` and prints the sudo command installing it.
- **F-78** Network diagnostics: IP routing, nftables, subnet overlap with the LAN, Docker or a firewall blocking forwarding, with a fix offered.
- **F-79** Topology view: which VMs and cards on which kvmnet (V2).

### 6.9 Snapshots, clones, import

- **F-80** Take, revert, delete a snapshot, with a name and a description. A name takes letters without accents, digits, "-", "_" and "." (not first), up to 100 characters: QEMU refuses anything else in the job of a running VM's snapshot. The dialog says which character is refused as the name is typed.
- **F-81** Tree manager with "You are here".
- **F-82** Internal qcow2 snapshots: with libvirt 12 they work for UEFI VMs whose firmware variables are stored as qcow2, TPM included, powered off (disks) or running (disks and memory, the VM goes on). Where libvirt refuses (raw disk, raw firmware variables of older VMs), the Take Snapshot dialog says so beforehand and libvirt's message is shown. A snapshot taken powered off does not hold the TPM state, which the dialog mentions. "Include RAM" is greyed out and unchecked for a powered-off VM, checked for a running one (tooltip: without the memory, restoring is like pulling the plug); libvirt only snapshots a running VM internally with its memory, so unchecking it asks to shut the VM down first (a disk-only snapshot would be an external one, whose restore leaves overlay files in the VM folder). A snapshot runs in the background: the manager can be closed, the status bar shows it with a Cancel button and a discreet notification tells when it ends. libvirt 12 reports no progress for an internal snapshot and cannot abort it: the bar moves without a percentage, and Cancel deletes the snapshot as soon as it is written. Other actions on the VM meanwhile wait for libvirt, which after 30 s answers that another operation holds the VM, shown in plain words. Take, Restore and Delete with a name and a description, from the toolbar, VM > Snapshot and the Snapshot Manager (tree with "You are here"); Restore and Delete ask first. A VM whose disks back linked clones can neither take, restore nor delete snapshots, and a VM with snapshots is not moved to another folder (libvirt keeps the disk paths in them).
- **F-83** AutoProtect: scheduled snapshots with rotation.
- **F-84** Full clone and linked clone (details in 6.9.1).
- **F-85** OVA/OVF/VMDK import: extraction, qcow2 conversion, translation of the OVF hardware, import report.
- **F-86** Export to OVF.

#### 6.9.1 Cloning (F-84)

- **Entries.** "Clone…" in the context menu of a VM (with Rename and Move To) and in VM > Manage.
- **Assistant.** Source VM → clone type (full or linked) → name → destination library folder → summary. The source VM must be powered off.
- **New VM.** New name, new UUID, new MAC addresses, the same hardware settings. Its files follow the same tree as the other VMs: `<location>/KVM-Studio/VM/<folder>/<name>/`.
- **Full clone.** The disks are copied (`qemu-img convert`), and so are the UEFI NVRAM and the TPM state.
- **Linked clone.** A new qcow2 disk with the source disk as its backing file. While linked clones depend on a VM, starting it asks for an explicit confirmation explaining that it would damage its clones; its summary lists them. Deleting or moving a source with linked clones stays blocked with a clear message.
- **Progress.** A progress bar for long copies, with a Cancel button; a cancelled or failed clone removes everything it had created.

### 6.10 Cross-cutting

- **F-90** English and French interface. English is the default; French is chosen in Preferences or on the first page of the first-run assistant (applied at once). The desktop language is not looked at.
- **F-91** Light/dark/system theme.
- **F-92** Log of long tasks with progress.
- **F-93** libvirt errors translated into plain words, raw message available on demand.
- **F-94** Window / web interface modes (section 3).
- **F-95** .rpm/.deb packages and first-run assistant (section 4).

### 6.11 Shared web mode and guest account

- **F-100** A single guest account, password set by the owner in Preferences > Interface, usable by several people at once.
- **F-101** The guest manages VMs like the owner: create, delete, change the settings, start/stop, console, snapshots, clones.
- **F-102** The guest does not touch the host: no access to Preferences, the network editor, the ISO libraries or LAN sharing; no raw XML editor; no passthrough (physical disk, USB, PCI); no import of a VM's disks from outside the root; VM cards on `kvmnet` networks only. Their Edit menu shows these entries greyed out, and Language, whose choice stays in their browser and never changes the host's language.
- **F-103** Path confinement: a guest can only attach disks from the `KVM-Studio` root and ISO images from the declared libraries. Checked by the backend, not only in the interface.
- **F-104** Shared console: several people on the same VM see the same screen and share keyboard and mouse; "N people connected" indicator.
- **F-105** Login security: self-signed HTTPS, hashed password, temporary lockout after 5 failures, sessions expired after inactivity.
- **F-106** Port opened and closed automatically in the firewall (firewalld or ufw) when LAN sharing is turned on or off.

## 7. Prioritization

The MVP is Romain's personal tool on Fedora: installed from the .rpm, it builds an OPNsense lab with 3 NICs (NAT + 2 Host-only) from an ISO stored in a subfolder, with copy and paste, in window mode.

| Phase | Audience | Features | Exit criterion |
| --- | --- | --- | --- |
| Phase 0: foundation | Romain | Backend + frontend, TOML configuration, libvirt connection, pywebview window, GitHub Actions CI, tests on `test:///default` | The KVM Studio window lists the host domains |
| MVP | Romain, Fedora | F-01, F-02, F-03, F-04, F-10, F-12, F-20, F-22, F-24, F-30, F-31, F-33, F-34, F-35, F-40, F-41, F-52, F-53, F-60, F-61, F-62, F-64, F-70, F-71, F-72, F-73 (without port forwarding), F-76, F-77, F-90, F-93, F-94 (window + local web), F-95 (.rpm + first run) | OPNsense 3 NIC lab + Windows 11 installed, guest tools in one click, copy and paste OK, clean network applet |
| Before V1 | Romain, Fedora | F-36, F-84, English as the source language, redesign of the interface, vnet* hidden from NetworkManager | Acceptance feedback of 0.1.0 handled |
| V1 | Friends, Fedora + Debian/Ubuntu | F-05, F-11, F-13, F-21, F-23, F-25, F-26 (Easy Install), F-42 to F-45, F-47, F-50, F-51, F-54, F-55, F-63, F-65, F-73 (port forwarding), F-78, F-80 to F-82, F-91, F-92, F-95 (.deb), F-100 to F-106 (LAN sharing + guest account) | A friend installs the .deb or the .rpm and builds their lab alone; working together on the LAN |
| V2 | Public | F-44 (host mount), F-46, F-56, F-57 (USB), F-66, F-67, F-74 and F-75 (Bridged), F-79, F-83, F-85, F-86, COPR/APT repositories, connection to a remote server | A former Workstation user moves their VMs over for good |
| Later | Public | Other distributions (Arch, openSUSE), PCI passthrough, shareable lab templates | - |

Advised order in the MVP: foundation → UTF-8 copy and paste prototype → list and states → life cycle → library folders → kvmnet + hiding → ISO picker → assistant → console + copy and paste + guest tools → several NICs → .rpm package.

## 8. Non-functional requirements and acceptance

| Requirement | Target |
| --- | --- |
| Performance | A list of 100 VMs shown in less than 1 s; a state change visible in less than 1 s |
| ISO library | 5,000 files on 3 roots browsed without blocking the UI |
| Clean computer | After installation: no KVM Studio interface in the network applet; after `dnf remove` / `apt remove`: no file, service, rule or interface left (apart from kept VMs) |
| Security | No shell command built from an input; paths confined to the VM folder and the ISO libraries; root helper with a minimal API authorized by polkit; guest rights checked by the backend; HTTPS + hashed password for LAN sharing |
| Robustness | Automatic reconnection to libvirt; no destructive action without confirmation |
| Accessibility | Menus, dialogs and tree usable with the keyboard |
| Readability | Text contrast of at least 4.5:1 in both themes, buttons included |
| Code | strict mypy, strict TypeScript, ruff, eslint, backend coverage ≥ 70% |
| Docs | README (with the non-affiliation notice), INSTALL, CONFIGURATION, TROUBLESHOOTING, CONTRIBUTING, CHANGELOG |

**MVP acceptance (Fedora KDE Plasma 6).**

- [ ] .rpm installed by double click, first-run assistant gone through without a manual command.
- [ ] kvmnet1 and kvmnet8 created; the Plasma network applet only shows the Wi-Fi and the wired card.
- [ ] Two ISO libraries set in Preferences, browsing 3 levels of subfolders.
- [ ] Library folders: create "Labs", move a powered off VM into it, the files follow on disk and the VM starts; deletion with the list of files.
- [ ] Windows 11 VM (UEFI, Secure Boot, TPM) installed; "Install Guest Tools" in one click; text copy and paste both ways.
- [ ] OPNsense with 3 NICs (kvmnet8 + 2 Host-only segments), console access.
- [ ] A VM created in KVM Studio visible and startable in virt-manager, and the other way round.
- [ ] ISO changed live.
- [ ] `sudo dnf remove kvm-studio`: no trace left apart from kept VMs.

**V1 acceptance (Fedora, Debian, Ubuntu).**

- [ ] Same acceptance as the MVP with the .deb on Debian 13 and Ubuntu 26.04 LTS.
- [ ] Easy install of a Windows 11 and an Ubuntu without any intervention.
- [ ] LAN sharing on: two colleagues log in at the same time with the guest account, create and delete a VM, share a console.
- [ ] The guest can neither open Preferences nor attach a file outside the allowed locations (also tested by calling the API directly).
- [ ] LAN sharing off: the port is closed again in the firewall.

## 9. Decisions and risks

**Decisions made.**

- Name KVM Studio; no reverse engineering.
- Path personal → friends → public; MVP Fedora, V1 Fedora + Debian/Ubuntu.
- Exclusive window and web modes; LAN sharing in V1 with a single guest account, self-signed HTTPS.
- Guest: full VM management, no access to the host settings, confined paths.
- Text copy and paste only, through qemu-vdagent; guest tools from a small CD started by the user, and Easy Install (answer files).
- NAT and Host-only networks (kvmnet1, kvmnet8); Bridged postponed to V2.
- No Docker; interfaces hidden in NetworkManager.
- GPL-3.0 license; code and commits in English, English interface with French.
- V1 target Ubuntu: 26.04 LTS.
- Installation from .rpm / .deb packages + first-run assistant (no Flatpak or Snap, incompatible with the helper and system libvirt).

**Open decisions.**

- [ ] Check the availability of "KVM Studio" (GitHub, domain name, package repositories).

**Risks.**

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Scope too wide for a project run by one person | Never a usable version | Strict MVP, next phase only after the acceptance of the previous one |
| Guest account = libvirt access ≈ root access to the host | Takeover of the PC | Rights limited to the VMs, paths confined and checked by the backend, no raw XML or passthrough |
| Guest tools installation | Command typed wrongly (AZERTY/QWERTY layout) | Nothing is typed in the guest: a CD started by the user, checked through the agent afterwards |
| Answer files specific to each OS version | Easy install failing | Templates tested per version, manual installation as a fallback |
| Root helper | Attack surface | Minimal API, validated inputs, polkit, mandatory review of the PRs touching it |
| Qt WebEngine missing or heavy | Degraded window mode | GTK WebKit fallback, otherwise web mode offered |
| ISO rights (qemu user, SELinux) | OS installation impossible | Detection + "Fix" button |
| Snapshots + UEFI depending on libvirt versions | Snapshots unavailable | Version detection, external snapshots |
| Closeness to Workstation | Trademark risk | Original visuals, non-affiliation notice, no VMware asset |
