# KVM Studio : cahier des charges

Oct 22, 2026 · @Romain

## 1. Contexte et objectifs

**KVM Studio** est un gestionnaire de machines virtuelles pour Linux qui reprend l'ergonomie et les fonctionnalités de VMware Workstation, en pilotant QEMU/KVM via libvirt. Projet communautaire open source sur GitHub, testé d'abord sur Fedora KDE Plasma 6.

**Problème.** Les anciens utilisateurs de Workstation trouvent virt-manager daté, Cockpit limité, Incus incapable d'utiliser un dossier ISO existant, Karton trop simple. VirtualBox est exclu.

**Trajectoire.** Outil personnel d'abord (MVP sur Fedora), puis partagé avec des amis (V1, Fedora + Debian/Ubuntu), puis public si le résultat tient. Le code reste portable dès le premier jour pour que le partage ne demande aucune réécriture.

**Objectifs.**

1. Retrouver l'organisation de Workstation : bibliothèque arborescente, onglets de VMs, résumé, assistants, mêmes menus et dialogues.
2. Fonctionner au choix comme un logiciel de bureau (fenêtre native) ou comme une interface web partageable sur le LAN avec un compte invité, jamais les deux à la fois.
3. Rendre tous les emplacements modifiables : dossiers ISO existants (sous-dossiers inclus, sans import ni copie), emplacement des VMs.
4. Offrir des réseaux NAT et Host-only aussi précis que le Virtual Network Editor, fonctionnels sans bidouille ; Bridged en V2.
5. Gérer les disques virtuels avec le même niveau de choix que Workstation.
6. Assurer le copier-coller de texte natif entre l'hôte et les VMs, et installer les outils invités en un clic.
7. Ne pas polluer le poste : aucune carte virtuelle dans l'applet réseau, pas de Docker, désinstallation complète.
8. S'installer comme un logiciel normal : paquet .rpm ou .deb en double-clic, puis assistant de premier lancement.
9. Rester compatible libvirt : VMs visibles et utilisables dans virt-manager et virsh.

**Public cible.** Admins systèmes et réseaux, étudiants (TSSR, AIS, CCNA…), formateurs, homelabbers venant de Workstation. Usages : labs réseau et sécu (firewalls multi-NIC, Windows Server, Linux, hyperviseurs imbriqués).

**Non-objectifs.**

- Pas de conteneurs (LXC, Docker, Incus) : uniquement des VMs, comme Workstation.
- Pas de gestion multi-hôtes ni de cluster.
- Pas d'hyperviseur propre : tout passe par libvirt.
- Pas d'hôte Windows ou macOS.
- Pas d'exposition Internet.
- Pas de copier-coller de fichiers ou d'images (texte uniquement).

## 2. Principes et contraintes

libvirt est la seule source de vérité, et KVM Studio ne laisse sur le poste que ce que son paquet sait retirer.

| Domaine | Règle |
| --- | --- |
| Légal | Inspiration de l'interface et des fonctionnalités par simple observation du logiciel (captures, usage). Aucun reverse engineering ni décompilation de VMware, outils type REA exclus. Aucun nom, logo, icône, texte ou visuel VMware ; icônes Lucide (ISC). |
| Positionnement | Mention dans le README et « À propos » : « KVM Studio est un projet communautaire inspiré de l'interface et des fonctionnalités de VMware Workstation. Il n'est affilié ni à VMware ni à Broadcom et ne reprend aucun de leurs codes ou éléments graphiques. » |
| Compatibilité | Domaines, réseaux et volumes créés via l'API libvirt standard, visibles et modifiables dans virt-manager et virsh. |
| Métadonnées | Données propres à l'appli (dossier de bibliothèque, notes, options) dans `<metadata>` du XML libvirt, namespace dédié. |
| Portabilité | Aucun chemin, pool, réseau ou URI en dur : tout est réglable dans les Préférences et stocké dans la config. |
| Poste propre | Aucune interface virtuelle dans l'applet réseau (NetworkManager configuré pour les ignorer). Pas de Docker, pas de service tiers. Tous les fichiers système appartiennent au paquet : `dnf remove` / `apt remove` retire tout ; le désinstalleur du paquet retire aussi les réseaux kvmnet et la règle pare-feu, en demandant s'il faut garder les VMs. |
| Non destructif | Dossiers ISO en lecture seule : aucune copie, aucun déplacement, aucun renommage. |
| Sécurité | Mode logiciel : serveur interne accessible uniquement par la fenêtre (loopback + jeton). Mode web : 127.0.0.1 par défaut, avec jeton ; partage LAN = HTTPS auto-signé + compte invité à mot de passe, aux droits limités aux VMs (section 6.11). |
| Distribution | MVP : Fedora. V1 : Fedora, Debian, Ubuntu. Autres distros plus tard. |
| Licence | GPL-3.0, cohérente avec libvirt et virt-manager. |

## 3. Architecture technique

Un backend Python unique pilote libvirt ; le même frontend s'affiche soit dans une fenêtre native, soit dans un navigateur ; un petit service privilégié fait les rares opérations root.

| Couche | Choix | Pourquoi |
| --- | --- | --- |
| Backend | Python 3.11+, FastAPI, Uvicorn, Pydantic v2 | Async, OpenAPI auto, lisible pour un admin |
| Accès hyperviseur | libvirt-python, paquet de la distro (`python3-libvirt`) | Bindings alignés sur la libvirt installée |
| Temps réel | Événements libvirt → WebSocket | États des VMs à jour sans rafraîchir |
| XML | lxml, générateurs par profil d'OS | XML conforme au schéma libvirt, testable |
| Frontend | React + TypeScript + Vite, Radix UI, Lucide | Interface dense type logiciel de bureau |
| Mode logiciel | pywebview (Qt WebEngine, repli GTK WebKit) | Vraie fenêtre, lanceur dans le menu des applis, presse-papiers natif |
| Mode web | Même frontend servi en HTTPS, compte invité | Travail à plusieurs sur le LAN |
| Console graphique | noVNC + canal QEMU `qemu-vdagent`, VNC en mode partagé | Copier-coller de texte natif ; plusieurs personnes sur la même console |
| Console série | xterm.js | Firewalls et appliances sans GUI |
| Fichiers de réponse | Modèles autounattend.xml (Windows), kickstart (Fedora/RHEL), preseed / autoinstall (Debian/Ubuntu) | Installation simplifiée avec outils invités |
| Helper privilégié | `kvmstudio-helper` : service systemd root, socket Unix, autorisations polkit | Seul composant root : masquage NetworkManager, ouverture du port web dans le pare-feu, redirection de ports NAT, correctifs de droits ISO |
| Détection OS | libosinfo, repli sur profils internes | Bonnes valeurs par défaut (virtio, UEFI, TPM) |
| Packaging | Paquets .rpm et .deb construits par la CI (nfpm), publiés dans les Releases GitHub, puis dépôts COPR et APT | Double-clic pour installer, dépendances et désinstallation gérées par la distro |
| Tests | pytest + URI `test:///default`, Playwright | Tests sans vraie VM, en CI GitHub Actions |

**Modes d'interface (exclusifs).** Choisis dans Préférences > Interface, appliqués au redémarrage de l'appli.

- *Logiciel* (défaut) : le backend écoute sur 127.0.0.1, port aléatoire, jeton par session. Rien n'est joignable hors de la fenêtre.
- *Web* : port fixe sur 127.0.0.1, accès par un lien à jeton affiché au lancement. Option « Partager sur le réseau local » : écoute sur le LAN, HTTPS auto-signé, ouverture du port dans firewalld ou ufw, connexion par compte invité. Le propriétaire utilise lui aussi le navigateur dans ce mode.

**Connexion libvirt.** URI configurable, `qemu:///system` par défaut. Le paquet ajoute l'utilisateur au groupe `libvirt` au premier lancement (via polkit).

**Droits sur les ISO.** QEMU tourne sous l'utilisateur `qemu` et doit lire les ISO. KVM Studio détecte un refus (droits Unix, ACL, SELinux, AppArmor) et propose un bouton « Corriger » qui passe par le helper après authentification polkit.

## 4. Configuration et installation

Tout se règle dans Préférences et dans l'assistant de premier lancement ; les réglages sont stockés en TOML lisible, et l'installation se fait par un paquet .rpm ou .deb.

**Fichiers.** Réglages utilisateur dans `$XDG_CONFIG_HOME/kvm-studio/config.toml` ; réglages du helper dans `/etc/kvm-studio/helper.toml` ; mot de passe invité stocké hashé (argon2) dans `$XDG_CONFIG_HOME/kvm-studio/guest.hash`. `kvm-studio --check` valide la config et teste libvirt, pools et droits ISO.

```toml
[interface]
mode = "desktop"          # "desktop" (fenêtre logicielle) | "web"

[web]
port = 8765
share_on_lan = false      # true = écoute LAN + HTTPS + compte invité
tls = "auto"              # certificat auto-signé généré au 1er lancement
guest_enabled = true      # mot de passe défini dans Préférences > Interface
login_max_attempts = 5    # blocage temporaire au-delà

[libvirt]
uri = "qemu:///system"

[storage]
# vm_default_location = "/srv/vm"     # un dossier par VM, choisi au premier lancement
default_iso_folder = "~/ISO"

[[iso_libraries]]
name = "ISO principales"
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
language = "fr"
```

**Installation.**

1. Télécharger `kvm-studio-<version>.x86_64.rpm` (Fedora) ou `kvm-studio_<version>_amd64.deb` (Debian/Ubuntu) dans les Releases GitHub.
2. Double-clic : Discover ou la Logithèque l'installe avec ses dépendances (libvirt, qemu, python3-libvirt, edk2/OVMF, swtpm…). En ligne de commande : `sudo dnf install ./kvm-studio-*.rpm` ou `sudo apt install ./kvm-studio_*.deb`.
3. Le paquet installe `/opt/kvm-studio` (code + frontend), le lanceur et l'icône, le service `kvmstudio-helper`, les règles polkit, le fichier NetworkManager de masquage et la définition de service pare-feu.
4. Mises à jour : nouveau paquet depuis les Releases ; plus tard, dépôts COPR (Fedora) et APT (Debian/Ubuntu) pour des mises à jour automatiques.
5. Désinstallation : `sudo dnf remove kvm-studio` ou `sudo apt remove kvm-studio` ; le script du paquet retire aussi les réseaux kvmnet et propose de garder les VMs.

**Assistant de premier lancement** (équivalent de l'assistant d'installation de Workstation) : Bienvenue et licence → Vérification (VT-x/AMD-V, module KVM, virtualisation imbriquée, service libvirt) → Ajout au groupe `libvirt` → Emplacements (VMs, bibliothèques ISO) → Mode d'interface → Création de kvmnet1 et kvmnet8 → Terminé. Il se relance depuis Aide.

Une doc INSTALL.md couvre aussi l'installation depuis le dépôt et le dépannage.

## 5. Interface : écrans et menus

L'interface reprend la disposition, les menus et les dialogues de Workstation 17 (d'après captures), avec des visuels 100 % originaux et des libellés en français.

**Disposition.**

- Barre de menus : Fichier, Édition, Affichage, VM, Onglets, Aide.
- Barre d'outils : alimentation (avec menu déroulant), envoi Ctrl+Alt+Suppr, snapshot / revenir / gestionnaire, afficher la bibliothèque, miniatures, plein écran, console.
- Bibliothèque à gauche : recherche avec filtre, arbre « Mon ordinateur » → dossiers → VMs, glisser-déposer entre dossiers.
- Zone centrale à onglets : Accueil + un onglet par VM ouverte.
- Barre d'état : périphériques (disque, réseau, CD, USB) avec activité, rappel du raccourci de libération.

**Écrans.**

| Écran | Contenu |
| --- | --- |
| Accueil | Tuiles : Créer une machine virtuelle, Ouvrir une machine virtuelle, Se connecter à un serveur (V2) |
| Résumé de VM | Actions (démarrer, paramètres), liste des périphériques, description, détails (état, dossier, IP via agent invité) |
| Console | Console intégrée à l'onglet, mise à l'échelle, plein écran |
| Paramètres de la VM | Onglets Matériel et Options, liste « Périphérique / Résumé » à gauche, détail à droite, boutons Ajouter… / Retirer |
| Assistant Nouvelle VM | Typique / Personnalisé, avec Installation simplifiée (section 6.3) |
| Gestionnaire de snapshots | Arbre, repère « Vous êtes ici », Prendre / Revenir / Supprimer / Cloner |
| Éditeur de réseaux virtuels | Section 6.8 |
| Préférences | Liste de sections à gauche, réglages à droite |
| Sélecteur d'ISO | Arbre des bibliothèques ISO, recherche, taille, OS détecté |
| Connexion (mode web partagé) | Mot de passe du compte invité, message en cas de blocage temporaire ; bandeau « Connecté en invité » ensuite |

**Menus.**

| Menu | Entrées |
| --- | --- |
| Fichier | Nouvelle machine virtuelle… (Ctrl+N), Ouvrir… (Ctrl+O : XML libvirt, OVA/OVF), Rechercher des machines virtuelles…, Configurer le démarrage auto des VMs…, Fermer l'onglet (Ctrl+W), Se connecter à un serveur… (V2), Exporter en OVF…, Quitter |
| Édition | Couper / Copier / Coller, Éditeur de réseaux virtuels…, Préférences… (Ctrl+P) |
| Affichage | Plein écran (Ctrl+Alt+Entrée), Vue console, Ajuster l'invité maintenant, Ajuster la fenêtre maintenant, Redimensionnement auto ›, Personnaliser › (bibliothèque, barre d'outils, barre d'état, miniatures) |
| VM | Alimentation ›, Périphériques amovibles ›, Pause (Ctrl+Maj+P), Envoyer Ctrl+Alt+Suppr, Capturer la saisie (Ctrl+G), Snapshot ›, Capture d'écran (Ctrl+Alt+Impr), Gérer › (cloner, renommer, supprimer du disque), Installer les outils invités…, Paramètres… (Ctrl+D) |
| Onglets | Liste des onglets ouverts, Aller à l'onglet Accueil, Onglet suivant (Ctrl+Tab), Onglet précédent (Ctrl+Maj+Tab) |
| Aide | Documentation, Raccourcis clavier, À propos (avec mention de non-affiliation), Signaler un bug |

Le sous-menu Alimentation contient : Démarrer, Arrêter l'invité, Redémarrer l'invité, Suspendre, Reprendre, Forcer l'arrêt, Réinitialiser.

**Paramètres de la VM, onglet Matériel.** Mémoire, Processeurs, Disques, CD/DVD, Cartes réseau, Contrôleur USB, Carte son, Affichage, Port série, TPM. Le panneau Mémoire reprend le curseur vertical de 4 Mo au maximum hôte, avec trois repères : minimum de l'OS invité, recommandé, maximum recommandé.

**Paramètres de la VM, onglet Options.**

| Option | Contenu |
| --- | --- |
| Général | Nom, OS invité + version, dossier de travail |
| Alimentation | Actions de démarrage/arrêt, comportement à la fermeture |
| Dossiers partagés | Partages virtiofs hôte → VM |
| Snapshots | Comportement à l'extinction (rien, revenir, demander) |
| AutoProtect | Snapshots planifiés avec rotation |
| Isolation de l'invité | Copier-coller et glisser-déposer autorisés ou non |
| Contrôle d'accès | Chiffrement des disques (LUKS qcow2) |
| Outils invités | État de l'agent, synchronisation de l'heure |
| Connexions VNC | Accès VNC externe avec port et mot de passe |
| Démarrage | Firmware, Secure Boot, ordre et menu de boot |
| Avancé | Éditeur XML brut, priorité |

**Préférences.** Espace de travail (emplacement des VMs, dossiers ISO, onglets mémorisés, VMs qui continuent à la fermeture, miniatures, captures d'écran), Interface (mode logiciel ou web, port, partage LAN, certificat, mot de passe du compte invité, personnes connectées), Saisie, Raccourcis, Affichage (thème, langue, mise à l'échelle), USB, Mémoire (réserve pour l'hôte), Périphériques.

**Raccourcis** identiques à ceux de Workstation listés ci-dessus, tous remappables (le navigateur capture certaines combinaisons en mode web).

## 6. Fonctionnalités détaillées

Chaque fonctionnalité porte un identifiant (F-xx) repris dans la priorisation.

### 6.1 Bibliothèque de VMs

- **F-01** Lister tous les domaines libvirt (actifs et inactifs), y compris ceux créés hors de KVM Studio.
- **F-02** Dossiers de bibliothèque imbriqués (ex. « Masters », « Labs »), stockés dans `<metadata>`.
- **F-03** Recherche, filtre (toutes / allumées), tri.
- **F-04** État en temps réel via les événements libvirt.
- **F-05** Rechercher des machines virtuelles : scanner un dossier pour retrouver des XML ou disques non inscrits.

### 6.2 Cycle de vie

- **F-10** Démarrer, arrêter l'invité (ACPI), forcer l'arrêt, redémarrer, réinitialiser.
- **F-11** Pause (gel en RAM) et Suspendre (état sauvegardé sur disque), comme Workstation.
- **F-12** Renommer, supprimer (désinscrire seulement ou supprimer aussi les disques).
- **F-13** Configurer le démarrage auto des VMs avec l'hôte, avec délai entre VMs.

### 6.3 Assistant Nouvelle VM

- **F-20** Typique : source d'installation → OS invité → nom et emplacement (dossier par défaut des Préférences) → disque → récapitulatif avec « Personnaliser le matériel ».
- **F-21** Personnalisé : firmware (BIOS/UEFI, Secure Boot), processeurs (sockets/cœurs/threads), mémoire, réseau, contrôleur et type de disque, disque (nouveau / existant / aucun).
- **F-22** Source : ISO via le sélecteur (F-30), « installer l'OS plus tard », ou disque existant.
- **F-23** Détection de l'OS depuis l'ISO (libosinfo), choix manuel en repli.
- **F-24** Profils d'OS : Windows 11 (UEFI + Secure Boot + TPM 2.0), Windows Server, Linux, firewall/BSD (pfSense, OPNsense, FortiGate VM, Stormshield EVA… : 3 NIC + console série par défaut), hyperviseur imbriqué (CPU host-passthrough).
- **F-25** Windows : 2e lecteur CD avec l'ISO virtio-win si elle est configurée.
- **F-26** Installation simplifiée (équivalent de l'Easy Install de Workstation) : l'assistant demande nom d'utilisateur, mot de passe, langue, clavier et, pour Windows, la clé produit (facultative). KVM Studio génère un fichier de réponse (autounattend.xml, kickstart, preseed ou autoinstall) sur une petite ISO à part, sans toucher à l'ISO d'origine. L'OS s'installe sans intervention, outils invités compris. Systèmes visés : Windows 10/11, Windows Server, Fedora/RHEL, Debian, Ubuntu.

### 6.4 Stockage et bibliothèques ISO

- **F-30** Sélecteur d'ISO arborescent sur plusieurs dossiers racine, sous-dossiers inclus, en lecture seule.
- **F-31** Recherche sur les noms, tri par nom/date/taille.
- **F-32** Cache des métadonnées (taille, date, OS détecté), rafraîchissement à la demande.
- **F-33** Vérification des droits de lecture par QEMU, bouton « Corriger » via le helper.
- **F-34** Changer ou éjecter l'ISO d'une VM allumée.
- **F-35** Emplacement par défaut des VMs modifiable ; une VM = un dossier contenant ses disques et sa NVRAM, comme Workstation.

### 6.5 Disques virtuels

- **F-40** Type de contrôleur au choix, avec recommandation selon l'OS : NVMe (si la version de libvirt le permet), SATA, SCSI (virtio-scsi), IDE, virtio-blk.
- **F-41** Créer un disque : taille, format qcow2 ou raw, case « Allouer tout l'espace maintenant » (préallocation), emplacement (dossier de la VM par défaut).
- **F-42** Utiliser un disque existant : qcow2, raw, VMDK, VDI, VHDX, avec proposition de conversion en qcow2 pour activer les snapshots.
- **F-43** Modes : normal, indépendant persistant (exclu des snapshots), indépendant non persistant (modifications perdues à l'extinction).
- **F-44** Utilitaires : Agrandir, Compacter (récupérer l'espace libre), Convertir, Informations (taille réelle/virtuelle, chaîne de backing), Monter sur l'hôte (V2, libguestfs).
- **F-45** Avancé : cache, mode d'E/S, TRIM/discard, numéro de série, limites d'IOPS.
- **F-46** Disque physique en passthrough (avancé, avec avertissement, propriétaire uniquement).

« Fractionner en plusieurs fichiers » n'a pas d'équivalent utile sous KVM et n'est pas repris.

### 6.6 Autre matériel virtuel

- **F-50** Processeurs : nombre, topologie, mode (host-passthrough, host-model, personnalisé), virtualisation imbriquée.
- **F-51** Mémoire avec curseur et repères (minimum invité, recommandé, maximum recommandé).
- **F-52** Lecteurs CD/DVD : plusieurs par VM, ISO ou vide.
- **F-53** Cartes réseau : plusieurs par VM, ajout en un clic, modèle (virtio, e1000e, rtl8139, vmxnet3), réseau kvmnet cible, MAC, carte connectée/déconnectée à chaud.
- **F-54** Affichage (virtio-gpu, qxl, vga), carte son, contrôleur USB, port série, TPM.
- **F-55** Firmware et démarrage : ordre de boot, menu de boot, Secure Boot.
- **F-56** Éditeur XML brut avec validation avant application (propriétaire uniquement).
- **F-57** USB passthrough (V2), PCI passthrough (plus tard), propriétaire uniquement.

### 6.7 Console et intégration invité

- **F-60** Console intégrée à l'onglet VM, mise à l'échelle, plein écran, Ajuster l'invité / la fenêtre.
- **F-61** Copier-coller de texte natif hôte ↔ VM via le canal `qemu-vdagent` et l'agent `spice-vdagent` de l'invité ; désactivable dans Options > Isolation. Fichiers et images non pris en charge.
- **F-62** Envoi de combinaisons (Ctrl+Alt+Suppr, Ctrl+Alt+F1…F12, Impr écran), Capturer la saisie (Ctrl+G).
- **F-63** Console série (xterm.js) pour firewalls et appliances.
- **F-64** Installer les outils invités en un clic sur une VM existante : KVM Studio monte l'ISO des outils si besoin (virtio-win pour Windows), puis tape lui-même la commande d'installation dans la console (injection clavier). L'utilisateur n'a qu'à valider l'élévation (UAC ou mot de passe sudo). Linux : spice-vdagent + qemu-guest-agent selon la distro de l'invité.
- **F-65** Dossiers partagés hôte → VM via virtiofs.
- **F-66** Capture d'écran de la VM (presse-papiers et/ou fichier).
- **F-67** Miniatures live des VMs allumées.

### 6.8 Réseaux virtuels

- **F-70** Éditeur de réseaux virtuels : tableau Nom / Type / Connexion externe / Connexion hôte / DHCP / Sous-réseau ; boutons Ajouter, Supprimer, Renommer ; panneau du réseau sélectionné (type, adaptateur hôte, DHCP et ses réglages, IP et masque) ; Restaurer les valeurs par défaut, Importer, Exporter.
- **F-71** Réseaux créés au premier lancement : kvmnet1 (Host-only, DHCP) et kvmnet8 (NAT, DHCP), sur des sous-réseaux qui ne chevauchent pas le LAN. kvmnet0 est réservé au Bridged (V2).
- **F-72** Host-only : réseau isolé, case « Connecter un adaptateur virtuel de l'hôte » (l'hôte a une IP sur ce réseau ou non), DHCP activable.
- **F-73** NAT : sortie via l'IP de l'hôte, DHCP, réglages NAT (passerelle, redirection de ports TCP/UDP) gérés dans une table nftables propre à KVM Studio.
- **F-74** Bridged transparent (V2) : mini-routeur transparent par proxy ARP + relais DHCP, Wi-Fi ou filaire, sans toucher à la connexion de l'utilisateur. À prototyper avant de s'engager (box qui refusent le relais DHCP, réseaux d'entreprise avec port security).
- **F-75** Bridged L2 complet (V2, option Ethernet uniquement) : vrai pont via NetworkManager.
- **F-76** Segments de lab rapides (LAN-1, LAN-2, DMZ…) = Host-only sans adaptateur hôte.
- **F-77** Poste propre : ponts nommés `kvmnetN`, cartes des VMs `ks-*`, déclarés non gérés dans NetworkManager → invisibles dans l'applet réseau.
- **F-78** Diagnostic réseau : routage IP, nftables, conflit de sous-réseau avec le LAN, présence de Docker ou d'un pare-feu qui bloque le transfert, avec correction proposée.
- **F-79** Vue topologie : quelles VMs et cartes sur quel kvmnet (V2).

### 6.9 Snapshots, clones, import

- **F-80** Prendre, revenir, supprimer un snapshot, avec nom et description.
- **F-81** Gestionnaire en arbre avec « Vous êtes ici ».
- **F-82** Snapshots internes qcow2 ; snapshots externes pour les VMs UEFI selon la version de libvirt.
- **F-83** AutoProtect : snapshots planifiés avec rotation.
- **F-84** Clone complet et clone lié.
- **F-85** Import OVA/OVF/VMDK : extraction, conversion qcow2, traduction du matériel OVF, rapport d'import.
- **F-86** Export en OVF.

### 6.10 Transverse

- **F-90** Interface FR/EN.
- **F-91** Thème clair/sombre/système.
- **F-92** Journal des tâches longues avec progression.
- **F-93** Erreurs libvirt traduites en langage clair, message brut dépliable.
- **F-94** Modes d'interface logiciel / web (section 3).
- **F-95** Paquets .rpm/.deb et assistant de premier lancement (section 4).

### 6.11 Mode web partagé et compte invité

- **F-100** Un compte invité unique, mot de passe défini par le propriétaire dans Préférences > Interface, utilisable par plusieurs personnes en même temps.
- **F-101** L'invité gère les VMs comme le propriétaire : créer, supprimer, modifier les paramètres, démarrer/arrêter, console, snapshots, clones.
- **F-102** L'invité ne touche pas à l'hôte : pas d'accès aux Préférences, à l'éditeur de réseaux, aux bibliothèques ISO ni au partage LAN ; pas d'éditeur XML brut ; pas de passthrough (disque physique, USB, PCI).
- **F-103** Confinement des chemins : un invité ne peut attacher que des disques du dossier des VMs et des ISO des bibliothèques déclarées. Vérifié côté backend, pas seulement dans l'interface.
- **F-104** Console partagée : plusieurs personnes sur la même VM voient le même écran et partagent clavier et souris ; indicateur « N personnes connectées ».
- **F-105** Sécurité de connexion : HTTPS auto-signé, mot de passe hashé, blocage temporaire après 5 échecs, sessions expirées après inactivité.
- **F-106** Ouverture et fermeture automatiques du port dans le pare-feu (firewalld ou ufw) quand le partage LAN est activé ou coupé.

## 7. Priorisation

Le MVP est l'outil perso de Romain sur Fedora : installé par le .rpm, il permet de monter un lab OPNsense à 3 NIC (NAT + 2 Host-only) depuis une ISO rangée dans un sous-dossier, avec copier-coller, en mode logiciel.

| Phase | Public | Fonctionnalités | Critère de sortie |
| --- | --- | --- | --- |
| Phase 0 : socle | Romain | Backend + frontend, config TOML, connexion libvirt, fenêtre pywebview, CI GitHub Actions, tests sur `test:///default` | La fenêtre KVM Studio liste les domaines de l'hôte |
| MVP | Romain, Fedora | F-01, F-03, F-04, F-10, F-12, F-20, F-22, F-24, F-30, F-31, F-33, F-34, F-35, F-40, F-41, F-52, F-53, F-60, F-61, F-62, F-64, F-70, F-71, F-72, F-73 (sans redirection de ports), F-76, F-77, F-90, F-93, F-94 (logiciel + web local), F-95 (.rpm + premier lancement) | Lab OPNsense 3 NIC + Windows 11 installés, outils invités en un clic, copier-coller OK, applet réseau propre |
| V1 | Amis, Fedora + Debian/Ubuntu | F-02, F-05, F-11, F-13, F-21, F-23, F-25, F-26 (Installation simplifiée), F-42 à F-45, F-50, F-51, F-54, F-55, F-63, F-65, F-73 (redirection de ports), F-78, F-80 à F-82, F-91, F-92, F-95 (.deb), F-100 à F-106 (partage LAN + compte invité) | Un ami installe le .deb ou le .rpm et monte son lab seul ; travail à plusieurs sur le LAN |
| V2 | Public | F-44 (montage hôte), F-46, F-56, F-57 (USB), F-66, F-67, F-74 et F-75 (Bridged), F-79, F-83 à F-86, dépôts COPR/APT, connexion à un serveur distant | Un ancien utilisateur de Workstation migre ses VMs sans retour arrière |
| Plus tard | Public | Autres distros (Arch, openSUSE), PCI passthrough, modèles de labs partageables | - |

Ordre conseillé dans le MVP : socle → liste et états → cycle de vie → kvmnet + masquage → sélecteur ISO → assistant → console + copier-coller + outils invités → multi-NIC → paquet .rpm.

## 8. Exigences non fonctionnelles et recette

| Exigence | Cible |
| --- | --- |
| Performance | Liste de 100 VMs affichée en moins de 1 s ; changement d'état visible en moins de 1 s |
| Bibliothèque ISO | 5 000 fichiers sur 3 racines parcourus sans bloquer l'UI |
| Poste propre | Après installation : aucune interface KVM Studio dans l'applet réseau ; après `dnf remove` / `apt remove` : aucun fichier, service, règle ou interface restant (hors VMs conservées) |
| Sécurité | Aucune commande shell construite depuis une saisie ; chemins confinés au dossier des VMs et aux bibliothèques ISO ; helper root à API minimale autorisée par polkit ; droits invité vérifiés côté backend ; HTTPS + mot de passe hashé en partage LAN |
| Robustesse | Reconnexion auto à libvirt ; aucune action destructive sans confirmation |
| Accessibilité | Menus, dialogues et arbre utilisables au clavier |
| Code | mypy strict, TypeScript strict, ruff, eslint, couverture backend ≥ 70 % |
| Docs | README (avec mention de non-affiliation), INSTALL, CONFIGURATION, TROUBLESHOOTING, CONTRIBUTING, CHANGELOG |

**Recette MVP (Fedora KDE Plasma 6).**

- [ ] Installation du .rpm par double-clic, assistant de premier lancement déroulé sans commande manuelle.
- [ ] kvmnet1 et kvmnet8 créés ; l'applet réseau de Plasma ne montre que le Wi-Fi et la carte filaire.
- [ ] Deux bibliothèques ISO configurées dans Préférences, navigation sur 3 niveaux de sous-dossiers.
- [ ] VM Windows 11 (UEFI, Secure Boot, TPM) installée ; « Installer les outils invités » en un clic ; copier-coller de texte dans les deux sens.
- [ ] OPNsense à 3 NIC (kvmnet8 + 2 segments Host-only), accès console.
- [ ] VM créée dans KVM Studio visible et démarrable dans virt-manager, et inversement.
- [ ] Changement d'ISO à chaud.
- [ ] `sudo dnf remove kvm-studio` : plus aucune trace hors VMs conservées.

**Recette V1 (Fedora, Debian, Ubuntu).**

- [ ] Même recette que le MVP avec le .deb sur Debian 13 et Ubuntu 26.04 LTS.
- [ ] Installation simplifiée d'un Windows 11 et d'une Ubuntu sans aucune intervention.
- [ ] Partage LAN activé : deux collègues se connectent en même temps avec le compte invité, créent et suppriment une VM, partagent une console.
- [ ] L'invité ne peut ni ouvrir les Préférences, ni attacher un fichier hors des emplacements autorisés (testé aussi par appel direct à l'API).
- [ ] Partage LAN coupé : le port est refermé dans le pare-feu.

## 9. Décisions et risques

**Décisions prises.**

- Nom KVM Studio ; aucun reverse engineering.
- Trajectoire perso → amis → public ; MVP Fedora, V1 Fedora + Debian/Ubuntu.
- Modes logiciel et web exclusifs ; partage LAN en V1 avec compte invité unique, HTTPS auto-signé.
- Invité : gestion complète des VMs, aucun accès aux réglages de l'hôte, chemins confinés.
- Copier-coller de texte uniquement, via qemu-vdagent ; outils invités en un clic (injection clavier) et Installation simplifiée (fichiers de réponse).
- Réseaux NAT et Host-only (kvmnet1, kvmnet8) ; Bridged repoussé en V2.
- Pas de Docker ; interfaces masquées dans NetworkManager.
- Licence GPL-3.0 ; code et commits en anglais, interface FR + EN.
- Ubuntu cible de la V1 : 26.04 LTS.
- Installation par paquets .rpm / .deb + assistant de premier lancement (pas de Flatpak ni de Snap, incompatibles avec le helper et libvirt système).

**Décisions ouvertes.**

- [ ] Vérifier la disponibilité de « KVM Studio » (GitHub, nom de domaine, dépôts de paquets).

**Risques.**

| Risque | Impact | Parade |
| --- | --- | --- |
| Périmètre trop large pour un projet mené par une seule personne | Jamais de version utilisable | MVP strict, phase suivante seulement après la recette de la précédente |
| Compte invité = accès libvirt ≈ accès root à l'hôte | Prise de contrôle du PC | Droits limités aux VMs, chemins confinés et vérifiés côté backend, pas de XML brut ni de passthrough |
| Injection clavier pour les outils invités | Commande mal tapée (disposition clavier AZERTY/QWERTY) | Détection de la disposition de l'invité, vérification via l'agent après installation |
| Fichiers de réponse spécifiques à chaque version d'OS | Installation simplifiée qui échoue | Modèles testés par version, repli sur l'installation manuelle |
| Helper root | Surface d'attaque | API minimale, entrées validées, polkit, revue obligatoire des PR qui le touchent |
| Qt WebEngine indisponible ou lourd | Mode logiciel dégradé | Repli GTK WebKit, sinon proposition du mode web |
| Droits ISO (utilisateur qemu, SELinux) | Installation d'OS impossible | Détection + bouton « Corriger » |
| Snapshots + UEFI selon versions de libvirt | Snapshots indisponibles | Détection de version, snapshots externes |
| Proximité avec Workstation | Risque de marque | Visuels originaux, mention de non-affiliation, aucun asset VMware |
