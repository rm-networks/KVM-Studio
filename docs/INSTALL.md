# Installation

Les paquets .rpm et .deb arriveront avec le MVP. Pour l'instant, KVM Studio se
lance depuis les sources.

## Depuis les sources (Fedora)

### Paquets système

Hyperviseur et bindings Python fournis par la distribution :

```bash
sudo dnf install libvirt-daemon-kvm qemu-kvm python3-libvirt python3-gobject libosinfo
```

Moteur de la fenêtre native (Qt WebEngine) :

```bash
sudo dnf install python3-pyqt6-webengine python3-QtPy
```

Repli GTK WebKit, facultatif :

```bash
sudo dnf install webkit2gtk4.1
```

Node.js, uniquement pour compiler l'interface :

```bash
sudo dnf install nodejs24 nodejs24-bin nodejs24-npm nodejs24-npm-bin
```

Le compte doit faire partie du groupe `libvirt` (déconnexion puis reconnexion
nécessaire après l'ajout) :

```bash
sudo usermod -aG libvirt "$USER"
```

### Backend

`--system-site-packages` permet au venv de voir `python3-libvirt`,
`python3-gobject` et PyQt6, installés par dnf.

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

Le backend sert ensuite `frontend/dist` tout seul.

### Lancement

Fenêtre native :

```bash
kvm-studio
```

Navigateur (lien à jeton affiché dans le terminal, ouvert automatiquement) :

```bash
kvm-studio --mode web
```

Diagnostic de la configuration et de l'hôte :

```bash
kvm-studio --check
```

### Icône du lanceur (facultatif)

Sous Wayland, KDE prend l'icône de la fenêtre dans l'entrée de menu
`kvm-studio.desktop`. Le paquet l'installera ; depuis les sources, on peut
l'installer pour son seul compte :

```bash
cp -r packaging/desktop/icons ~/.local/share/ && cp packaging/desktop/kvm-studio.desktop ~/.local/share/applications/
```

## Développement

Deux terminaux. Le premier lance l'API, qui redémarre à chaque modification du
code Python et affiche un lien contenant le jeton :

```bash
kvm-studio --mode web --reload
```

Le second lance Vite, qui recharge l'interface à chaque modification :

```bash
cd frontend && npm run dev
```

Ouvrir `http://127.0.0.1:5173/#token=...` en reprenant le jeton affiché par le
premier terminal.

Après une modification de l'API, régénérer le client TypeScript (venv activé) :

```bash
cd frontend && npm run gen:api
```

### Contrôles qualité

```bash
ruff check . && ruff format --check . && mypy && pytest
```

```bash
cd frontend && npm run lint && npm test
```

Tests d'intégration avec un vrai QEMU (console et presse-papiers UTF-8). Ils
démarrent une VM temporaire sans disque dans `qemu:///session`, qui disparaît à
la fin du test :

```bash
KVMSTUDIO_QEMU_TESTS=1 pytest tests/backend/test_qemu_clipboard.py tests/backend/test_qemu_console.py
```

## Sécurité du serveur interne

Dans les deux modes, le serveur n'écoute que sur 127.0.0.1. Chaque lancement
génère un jeton ; toute requête à l'API sans ce jeton est refusée (401). Le jeton
voyage dans le fragment de l'URL (`#token=...`), qui n'est jamais envoyé au
serveur ni enregistré dans ses journaux.
