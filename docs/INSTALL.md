# Installation

## .rpm package (Fedora)

Each release (tag `vX.Y.Z`) has its .rpm in the GitHub Releases; the CI also
builds a development package on every build (artifact `kvm-studio-rpm`). It
installs or pulls all its dependencies from the Fedora repositories.

```bash
sudo dnf install ./kvm-studio-*.rpm
```

Contents:

| Location | Purpose |
| --- | --- |
| `/opt/kvm-studio` | application, built interface, Python modules missing from the repositories (`vendor/`) |
| `/usr/bin/kvm-studio` | launcher |
| `/usr/share/applications/kvm-studio.desktop` | applications menu entry |
| `/usr/share/applications/kvm-studio-uninstall.desktop` | "Uninstall KVM Studio" entry |
| `kvmstudio-helper.socket` / `.service` | root helper, started on demand |
| `/usr/share/polkit-1/actions/org.kvmstudio.helper.policy` | helper authorizations |
| `/etc/kvm-studio/helper.toml` | helper settings, libraries declared by the administrator |
| `/var/lib/kvm-studio` | helper state: ISO libraries declared from Preferences, access rights it added |
| `/etc/NetworkManager/conf.d/90-kvm-studio.conf` | hides `kvmnet*`, `ks-*` and `vnet*` from the network applet |
| `/usr/lib/firewalld/services/kvm-studio.xml` | firewall service for sharing on the LAN |

ISO libraries are added in Edit > Preferences > ISO Libraries; the
administrator password is asked once per library (see
[Configuration](CONFIGURATION.md)).

Check that the helper socket is listening:

```bash
systemctl status kvmstudio-helper.socket
```

To uninstall, use the "Uninstall KVM Studio" entry of the applications menu:
it asks what to do with the VMs, the `kvmnet` networks, the access rights given
on the ISO libraries and the settings, then removes the package. The same in a terminal:

```bash
kvm-studio --uninstall
```

A plain `dnf remove` only removes the package files (helper stopped, firewall
service removed from every zone, access rights the helper added taken back);
VMs, networks and settings stay.

### Building the package

It takes [nfpm](https://nfpm.goreleaser.com/) and the built interface.

```bash
cd frontend && npm ci && npm run build && cd ..
```

```bash
python3 packaging/stage.py
```

```bash
VERSION=0.4.0 nfpm package -f packaging/nfpm.yaml -p rpm -t dist/
```

## From the sources (Fedora)

### System packages

Hypervisor and Python bindings from the distribution:

```bash
sudo dnf install libvirt-daemon-kvm qemu-kvm python3-libvirt python3-gobject libosinfo xorriso
```

Engine of the native window (Qt WebEngine):

```bash
sudo dnf install python3-pyqt6-webengine python3-QtPy
```

GTK WebKit fallback, optional:

```bash
sudo dnf install webkit2gtk4.1
```

Node.js, only to build the interface:

```bash
sudo dnf install nodejs24 nodejs24-bin nodejs24-npm nodejs24-npm-bin
```

The account must be in the `libvirt` group (log out and back in after adding
it):

```bash
sudo usermod -aG libvirt "$USER"
```

### Backend

`--system-site-packages` lets the venv see `python3-libvirt`,
`python3-gobject` and PyQt6, installed by dnf.

```bash
python3 -m venv --system-site-packages .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -e "backend[dev]"
```

### Interface

```bash
cd frontend && npm ci && npm run build && cd ..
```

The backend then serves `frontend/dist` by itself.

### Starting

Native window:

```bash
kvm-studio
```

Browser (link with the token printed in the terminal, opened automatically):

```bash
kvm-studio --mode web
```

Check the configuration and the host:

```bash
kvm-studio --check
```

### Launcher icon (optional)

On Wayland, KDE takes the window icon from the `kvm-studio.desktop` menu entry.
The package installs it; from the sources, it can be installed for one account:

```bash
python3 packaging/stage.py && cp -r packaging/desktop/icons ~/.local/share/ && cp build/stage/files/desktop/kvm-studio.desktop ~/.local/share/applications/
```

## Development

Two terminals. The first one runs the API, which restarts on every change to
the Python code and prints a link containing the token:

```bash
kvm-studio --mode web --reload
```

The second one runs Vite, which reloads the interface on every change:

```bash
cd frontend && npm run dev
```

Open `http://127.0.0.1:5173/#token=...` with the token printed by the first
terminal.

After a change to the API, regenerate the TypeScript client (venv active):

```bash
cd frontend && npm run gen:api
```

### Translations

English is the source language. Every visible string lives in
`frontend/src/i18n/en.json` and `fr.json` (interface), and in
`backend/kvmstudio/locale/en.json` and `fr.json` (command line, tray icon). The
product name is never written in them: messages use `{{app}}` (interface) or
`{app}` (backend), filled from `APP_NAME` in `backend/kvmstudio/__init__.py`.
Tests fail when a key exists in one language only, or when a visible string is
written in the code.

### Quality checks

```bash
ruff check . && ruff format --check . && mypy && pytest
```

```bash
cd frontend && npm run lint && npm test
```

Integration tests with a real QEMU (console and UTF-8 clipboard). They start a
temporary diskless VM in `qemu:///session`, which goes away at the end of the
test:

```bash
KVMSTUDIO_QEMU_TESTS=1 pytest tests/backend/test_qemu_clipboard.py tests/backend/test_qemu_console.py
```

## Security of the internal server

In both modes, the server only listens on 127.0.0.1. Each start generates a
token; any API request without it is refused (401). The token travels in the
URL fragment (`#token=...`), which is never sent to the server nor written to
its logs.
