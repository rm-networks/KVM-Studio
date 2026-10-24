# Configuration

KVM Studio lit `$XDG_CONFIG_HOME/kvm-studio/config.toml`, soit en général
`~/.config/kvm-studio/config.toml`. Le fichier est facultatif et chaque clé
aussi : une clé absente prend sa valeur par défaut. Un modèle commenté se trouve
dans [config.example.toml](../config.example.toml).

L'écran Édition > Préférences modifie ce fichier (il le réécrit sans les
commentaires). Le mode d'interface, le port et l'URI libvirt s'appliquent au
prochain lancement ; le reste s'applique tout de suite.

Une clé inconnue ou une valeur invalide empêche le démarrage, avec un message qui
indique la clé fautive. `kvm-studio --check` valide le fichier sans rien lancer.
`--config CHEMIN` permet d'utiliser un autre fichier.

## [interface]

| Clé | Défaut | Description |
| --- | --- | --- |
| `mode` | `"desktop"` | `"desktop"` : fenêtre native. `"web"` : navigateur. Appliqué au redémarrage. L'option `--mode` de la ligne de commande a priorité. |

## [web]

| Clé | Défaut | Description |
| --- | --- | --- |
| `port` | `60080` | Port HTTP du mode web (accès local, 127.0.0.1), entre 1024 et 65535. Le mode fenêtre utilise un port aléatoire. |
| `https_port` | `60443` | Port HTTPS du partage sur le réseau local (V1). |
| `share_on_lan` | `false` | Partage sur le réseau local (V1). Doit rester à `false` : KVM Studio refuse de démarrer sinon. |
| `tls` | `"auto"` | Certificat auto-signé pour le partage LAN (V1). |
| `guest_enabled` | `true` | Compte invité du partage LAN (V1). |
| `login_max_attempts` | `5` | Échecs de connexion avant blocage temporaire (V1). |

## [libvirt]

| Clé | Défaut | Description |
| --- | --- | --- |
| `uri` | `"qemu:///system"` | URI de connexion libvirt. `qemu:///session` fonctionne mais sans réseaux virtuels kvmnet. |

## [storage]

| Clé | Défaut | Description |
| --- | --- | --- |
| `vm_default_location` | aucun | Emplacement choisi pour les VMs. KVM Studio y range tout sous `KVM-Studio/VM/` : `<emplacement>/KVM-Studio/VM/<dossiers>/<nom de la VM>/<disques>`. À choisir au premier lancement. `~` est accepté. |

## [[iso_libraries]]

Bibliothèques d'ISO, parcourues en lecture seule. Répéter le bloc pour chaque
dossier.

| Clé | Défaut | Description |
| --- | --- | --- |
| `name` | requis | Nom affiché. |
| `path` | requis | Dossier racine. |
| `recursive` | `true` | Parcourir les sous-dossiers. |
| `extensions` | `[".iso", ".img"]` | Extensions reconnues. |

## [defaults]

Valeurs proposées par l'assistant de création de VM.

| Clé | Défaut | Valeurs |
| --- | --- | --- |
| `firmware` | `"uefi"` | `"uefi"`, `"bios"` |
| `disk_bus` | `"virtio"` | `"virtio"`, `"scsi"`, `"sata"`, `"nvme"`, `"ide"` |
| `nic_model` | `"virtio"` | `"virtio"`, `"e1000e"`, `"rtl8139"`, `"vmxnet3"` |
| `virtio_win_iso` | aucun | ISO des pilotes virtio pour Windows, montée en second lecteur. |

## [ui]

| Clé | Défaut | Valeurs |
| --- | --- | --- |
| `theme` | `"system"` | `"system"`, `"light"`, `"dark"` |
| `language` | `"fr"` | `"fr"`, `"en"` |

## Variables d'environnement

| Variable | Rôle |
| --- | --- |
| `XDG_CONFIG_HOME` | Emplacement du dossier de configuration. |
| `KVMSTUDIO_FRONTEND_DIR` | Dossier de l'interface compilée, si elle n'est pas à l'emplacement habituel. |
| `KVMSTUDIO_BACKEND` | Développement : adresse de l'API pour le serveur Vite (défaut `http://127.0.0.1:60080`). |

## Dossiers de la bibliothèque

Les dossiers de la bibliothèque sont de vrais dossiers sous
`<emplacement>/KVM-Studio/VM/`. Créer, renommer ou supprimer un dossier dans
KVM Studio fait la même chose sur le disque ; déplacer une VM éteinte déplace
son dossier et met à jour les chemins dans libvirt.

KVM Studio n'efface ni ne déplace jamais un fichier situé hors de
`KVM-Studio/`, une image ISO, un disque utilisé par une autre VM ou le disque de
base d'un clone lié. Les VMs créées ailleurs (virt-manager) sont seulement
rangées dans la bibliothèque, sans toucher à leurs fichiers.

Le dossier de chaque VM est aussi noté dans son XML libvirt
(`<metadata>`, espace de noms `https://github.com/rm-networks/kvm-studio/ns/1.0`).
Si des fichiers ont été déplacés à la main, la VM reste affichée à sa place
notée, avec un triangle d'avertissement : KVM Studio signale l'écart sans le
corriger.
