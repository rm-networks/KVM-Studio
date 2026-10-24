# Feuille de route

Le développement avance phase par phase. Une phase commence quand la CI est
verte et que la recette de la précédente est validée. Les identifiants F-xx
renvoient au [cahier des charges](SPECIFICATIONS.md).

## Phase 0 : socle

Backend, frontend, configuration, connexion libvirt, fenêtre pywebview, CI.
Critère de sortie : la fenêtre liste les domaines.

## MVP (Fedora)

F-01, F-02 (dossiers synchronisés, section 6.1.1), F-03, F-04, F-10, F-12,
F-20, F-22, F-24, F-30, F-31, F-33, F-34, F-35, F-40, F-41, F-52, F-53, F-60,
F-61, F-62, F-64, F-70, F-71, F-72, F-73 (sans redirection), F-76, F-77, F-90,
F-93, F-94 (mode logiciel et web local), F-95 (.rpm et premier lancement).

Ordre : prototype du copier-coller UTF-8, liste et états, cycle de vie,
dossiers de bibliothèque, réseaux kvmnet et masquage, sélecteur d'ISO,
assistant, console avec copier-coller et outils invités, multi-NIC, paquet .rpm.

Critère de sortie : un lab OPNsense à 3 cartes réseau et une VM Windows 11,
copier-coller fonctionnel, applet réseau de l'hôte sans interfaces parasites.

## V1 (Fedora, Debian 13, Ubuntu 26.04 LTS)

Installation simplifiée, gestion complète des disques, console série,
virtiofs, snapshots, redirection de ports NAT, diagnostic réseau, paquet .deb,
partage sur le LAN avec compte invité (F-100 à F-106).

## V2 (diffusion publique)

Bridged, USB, miniatures, topologie, AutoProtect, clones, import et export
OVF, dépôts COPR et APT, serveur distant.
