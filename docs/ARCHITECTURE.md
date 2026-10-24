# Architecture

KVM Studio pilote QEMU/KVM au travers de libvirt. Il s'utilise dans une fenêtre
native ou depuis un navigateur, et s'installe par un paquet .rpm ou .deb.

## Principes

- **libvirt est la source de vérité.** Aucun état de VM n'est stocké ailleurs.
  Les données propres à KVM Studio vont dans le `<metadata>` du domaine, sous
  le namespace `https://github.com/rm-networks/kvm-studio/ns/1.0` (préfixe
  `kvmstudio`). Après chaque définition, le XML est relu avec `XMLDesc()`, car
  libvirt le normalise.
- **Compatibilité virt-manager et virsh.** Domaines, réseaux et volumes créés
  par KVM Studio restent utilisables dans ces outils.
- **Aucun chemin en dur.** URI, pools, réseaux, ports et dossiers viennent de la
  configuration, avec des valeurs par défaut détectées.
- **Dossiers ISO en lecture seule.** Jamais de copie, de déplacement ni
  d'écriture dans une bibliothèque ISO.
- **Confinement des chemins.** Tout chemin reçu du client est résolu puis doit
  se trouver sous le dossier des VMs ou sous une bibliothèque ISO déclarée,
  sinon la requête est refusée (403). Le contrôle est fait par le backend.
- **Pas de shell.** Les outils externes (`qemu-img`, `nft`, `firewall-cmd`,
  `ufw`, `semanage`, `setfacl`) sont appelés avec une liste d'arguments, jamais
  par une commande construite en texte.

## Processus

Le processus principal ne contient que la fenêtre (pywebview, Qt WebEngine ou
à défaut GTK WebKit) ou l'icône de notification. Le backend (Uvicorn, FastAPI,
connexion libvirt, boucle d'événements) tourne dans un sous-processus
(`shell/backend_process.py`). libvirt n'est jamais chargé dans le processus Qt :
les deux partagent le `GMainContext` de GLib, ce qui provoque des plantages.

Les événements libvirt sont relayés au frontend par le WebSocket `/ws/events`.

## Helper root

`kvmstudio-helper` est le seul composant qui tourne en root. C'est un service
systemd qui écoute sur un socket Unix et n'expose que des opérations nommées,
aux paramètres validés, chacune autorisée par polkit :

- ouverture et fermeture du port web (firewalld ou ufw) ;
- redirection de ports NAT (table nftables `inet kvmstudio`) ;
- correctifs de droits sur les ISO (contexte SELinux `virt_content_t` ou ACL).
- ajout du compte de l'appelant au groupe `libvirt` ;
- retrait du paquet en fin de désinstallation.

Il n'existe pas d'opération générique d'exécution de commande.

Fonctionnement :

- systemd crée le socket `/run/kvmstudio-helper.sock` (unité
  `kvmstudio-helper.socket`) et démarre le service à la première connexion ;
- chaque connexion porte une requête JSON `{"op": ..., "params": {...}}` ;
  toute clé en trop, tout type inattendu ou toute opération inconnue est
  refusé avant de solliciter polkit ;
- l'appelant est identifié par le noyau (`SO_PEERCRED` : pid, uid réel) et
  jamais par un champ de la requête ; polkit (`pkcheck`) autorise ce processus
  pour l'action de l'opération, en affichant au besoin la fenêtre
  d'authentification du bureau ;
- les chemins sont résolus (liens symboliques et `..` compris), puis doivent
  se trouver strictement sous une bibliothèque déclarée dans
  `/etc/kvm-studio/helper.toml` ;
- le fichier est ensuite rouvert composant par composant avec `O_NOFOLLOW`
  depuis la racine de la bibliothèque, et l'outil reçoit `/proc/self/fd/N` :
  remplacer un dossier par un lien symbolique entre le contrôle et la
  modification n'a donc aucun effet.

| Opération | Action polkit | Effet |
| --- | --- | --- |
| `iso_acl` | `org.kvmstudio.helper.iso-acl` | ACL `u:<qemu>:x` sur les dossiers de la bibliothèque jusqu'à l'image, `u:<qemu>:r` sur l'image |
| `join_libvirt` | `org.kvmstudio.helper.join-libvirt` | ajoute l'appelant au groupe `libvirt` ; aucun paramètre, refusé pour root et les UID inférieurs à 1000, mot de passe administrateur à chaque appel |
| `remove_package` | `org.kvmstudio.helper.remove-package` | retire le paquet `kvm-studio` dans une unité systemd transitoire ; aucun paramètre, mot de passe administrateur à chaque appel |

Les dossiers situés au-dessus de la racine d'une bibliothèque ne sont jamais
modifiés : le sélecteur d'ISO indique la commande à lancer. Le masquage
NetworkManager est porté uniquement par un fichier du paquet. L'ACL `u:qemu:x`
sur les dossiers de VMs situés sous le home est posée par l'utilisateur
lui-même, sans le helper.

## Modes d'interface

Les deux modes sont exclusifs et se choisissent dans la configuration
(appliqués au redémarrage).

| Mode | Écoute | Accès |
| --- | --- | --- |
| Logiciel | 127.0.0.1, port aléatoire | jeton par session |
| Web local | 127.0.0.1:60080 | jeton obligatoire, lien affiché au lancement |
| Web partagé (`share_on_lan = true`) | LAN, HTTPS auto-signé sur 60443 | compte invité avec mot de passe, sinon refus de démarrer |

### Compte invité

Un seul compte invité, utilisable par plusieurs personnes en même temps. Son mot
de passe est défini dans Préférences > Interface et stocké sous forme de hash
argon2. Les tentatives de connexion sont limitées (`login_max_attempts`) et les
sessions expirent après inactivité.

Deux rôles : `owner` (session du mode logiciel ou connexion depuis 127.0.0.1)
et `guest`. Les droits sont vérifiés par le backend sur chaque route.

- Autorisé à l'invité : créer, supprimer, modifier, démarrer et arrêter des VMs,
  console, snapshots, clones, choix des ISO des bibliothèques et des réseaux
  `kvmnet` existants.
- Interdit à l'invité : Préférences, éditeur de réseaux, bibliothèques ISO,
  partage LAN, éditeur XML brut, passthrough (disque physique, USB, PCI), tout
  chemin hors confinement.

Activer ou couper le partage ouvre ou ferme le port par le helper. La console
partagée utilise `<graphics type='vnc' sharePolicy='allow-exclusive'>` :
plusieurs clients noVNC peuvent se connecter et l'interface indique le nombre
de personnes connectées.

## Intégration invité

- **Copier-coller (texte uniquement).** Chaque VM avec affichage reçoit
  `<channel type='qemu-vdagent'>` avec `<clipboard copypaste='yes'/>`, sauf si
  Options > Isolation le désactive. Le presse-papiers de l'hôte est relié à noVNC
  par l'API pywebview en mode logiciel et par `navigator.clipboard` en mode web
  (contexte sécurisé : 127.0.0.1 ou HTTPS).
- **Installation des outils invités.** KVM Studio fabrique avec `xorriso` un
  petit CD `KS_TOOLS` dans `<emplacement>/KVM-Studio/Tools` et l'insère dans un
  lecteur de la VM (virtio-win en plus, dans un second lecteur, pour Windows).
  L'utilisateur lance l'installation dans la VM : `Install-Tools.bat` sous
  Windows, `install.sh` sous Linux. Rien n'est tapé à sa place, la disposition
  du clavier ne compte donc pas. qemu-guest-agent confirme ensuite que l'agent
  répond, et l'éjection remet ce que les lecteurs contenaient avant.
- **Installation simplifiée.** L'assistant collecte utilisateur, mot de passe,
  langue, clavier et clé produit facultative, puis génère le fichier de réponse
  (autounattend.xml, kickstart, preseed, autoinstall) sur une petite ISO séparée.
  L'ISO source n'est jamais modifiée. Cibles : Windows 10/11/Server,
  Fedora/RHEL, Debian, Ubuntu.

## Disques

Contrôleurs NVMe (masqué si la libvirt installée ne le gère pas), SATA,
virtio-scsi, IDE et virtio-blk. Création qcow2 ou raw avec préallocation
facultative. Disques existants qcow2, raw, VMDK, VDI ou VHDX, avec conversion
proposée. Modes normal, indépendant persistant (`snapshot='no'`) et indépendant
non persistant (`<transient/>`). Utilitaires : agrandir, compacter, convertir,
informations.

## Arborescence cible

Certaines parties (helper, fichiers de réponse) arrivent dans les phases
suivantes de la [feuille de route](ROADMAP.md).

```
kvm-studio/
├── backend/kvmstudio/
│   ├── __main__.py          # CLI : run, --check, --mode
│   ├── config.py
│   ├── app.py               # FastAPI et frontend statique
│   ├── shell/               # fenêtre (pywebview), mode web (TLS, invité)
│   ├── auth/                # rôles owner/guest, sessions, limitation
│   ├── libvirt_conn.py
│   ├── api/                 # vms, isos, disks, networks, snapshots, console, prefs, tasks
│   ├── services/
│   ├── xml/                 # builders domaine et réseau, profils d'OS
│   ├── unattended/          # modèles de fichiers de réponse, génération d'ISO
│   ├── guesttools/          # CD des outils invités (scripts, fabrication, insertion)
│   ├── isolib/              # scan des ISO, cache, contrôle des droits
│   ├── paths.py             # confinement des chemins
│   ├── console/             # proxy WebSocket VNC et série
│   └── helper_client.py
├── helper/kvmstudio_helper/
│   ├── server.py            # socket Unix, opérations nommées
│   ├── paths.py             # résolution, confinement, ouverture sans course
│   ├── polkit.py            # identité de l'appelant, pkcheck
│   └── ops/                 # iso_acl, join_libvirt, remove_package (puis firewall_port, nat_portfwd)
├── frontend/src/
│   ├── app/                 # menus, barre d'outils, bibliothèque, onglets, barre d'état
│   ├── features/            # un dossier par écran ou dialogue
│   ├── components/
│   ├── api/                 # client typé généré depuis l'OpenAPI
│   └── i18n/
├── packaging/               # nfpm, scripts, systemd, polkit, NetworkManager, firewalld, .desktop
└── tests/                   # backend, helper, e2e
```

## Stack

| Couche | Choix |
| --- | --- |
| Backend | Python 3.11+, FastAPI, Uvicorn, Pydantic v2 |
| Hyperviseur | `libvirt-python` de la distribution |
| XML | `lxml`, builders par profil d'OS |
| Détection d'OS | libosinfo si disponible, sinon profils internes |
| Frontend | React 18, TypeScript strict, Vite, Radix UI, Lucide, i18next (fr, en) |
| Fenêtre | pywebview (Qt WebEngine, repli GTK WebKit) |
| Console | noVNC, chardev `qemu-vdagent`, xterm.js pour la console série |
| Fichiers de réponse | Jinja2 |
| Configuration | TOML validé par Pydantic |
| Paquets | nfpm (.rpm, .deb) |
| Qualité | ruff, mypy --strict, pytest, eslint, prettier, vitest, Playwright |

Les tests automatisés tournent sur le pilote libvirt `test:///default` : ni KVM
ni root ne sont nécessaires en CI. Le helper est testé avec des commandes
simulées.

## Installation

Le paquet installe `/opt/kvm-studio`, le lanceur `.desktop`, le service
`kvmstudio-helper`, les règles polkit, le fichier NetworkManager et le service
firewalld. Les dépendances Python absentes des dépôts sont embarquées dans
`/opt/kvm-studio/vendor`. Flatpak et Snap
ne sont pas proposés : leur bac à sable est incompatible avec libvirt système,
le helper et polkit.

### Désinstallation

L'entrée « Désinstaller KVM Studio » lance `kvm-studio --uninstall-wizard`,
une fenêtre qui n'affiche que l'assistant de désinstallation ;
`kvm-studio --uninstall` pose les mêmes questions dans un terminal.

1. Le backend calcule un plan (`GET /api/uninstall/plan`) : VMs dont les
   fichiers sont dans `KVM-Studio/VM`, fichiers exacts à supprimer et fichiers
   conservés avec leur raison, réseaux `kvmnet` et VMs qui les utilisent,
   fichiers de réglages.
2. L'exécution (`POST /api/uninstall`) reçoit l'empreinte du plan affiché et
   la refuse si quoi que ce soit a changé entre-temps. Les règles sont celles
   de la suppression d'une VM ; un réseau encore utilisé par une VM conservée
   reste en place.
3. Le paquet est retiré par l'opération helper `remove_package`, qui lance
   `dnf remove` (ou `apt-get remove`) dans une unité systemd transitoire
   `kvm-studio-removal` : retirer le paquet arrête le helper lui-même.

Un `dnf remove` direct ne retire que les fichiers du paquet et affiche une
ligne qui renvoie vers l'entrée « Désinstaller KVM Studio ».

L'assistant de premier lancement enchaîne : bienvenue et licence, vérification
(VT-x/AMD-V, module KVM, nested, service libvirt), ajout au groupe `libvirt`,
emplacements des VMs et des ISO, mode d'interface, création de `kvmnet1` et
`kvmnet8`. Il se relance depuis le menu Aide.

## Hors périmètre

Conteneurs, multi-hôtes, cluster, hyperviseur propre, exposition sur Internet,
hôtes Windows ou macOS, copier-coller de fichiers ou d'images.
