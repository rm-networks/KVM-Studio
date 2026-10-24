# Interface

La disposition reprend celle d'un logiciel de virtualisation de bureau
classique, avec un style propre au projet : rendu dense, thème clair ou sombre,
icônes Lucide.

## Fenêtre principale

- Menus : Fichier, Édition, Affichage, VM, Onglets, Aide.
- Barre d'outils sous les menus.
- Bibliothèque arborescente à gauche (dossiers et VMs).
- Onglets au centre : Accueil, puis un onglet par VM ouverte.
- Barre d'état en bas.

Le détail des entrées de menu figure dans la section 5 du
[cahier des charges](SPECIFICATIONS.md).

## Dialogues

- Paramètres de la VM (onglets Matériel et Options).
- Assistant Nouvelle VM (Typique, Personnalisé, Installation simplifiée).
- Gestionnaire de snapshots.
- Éditeur de réseaux virtuels.
- Préférences.
- Sélecteur d'ISO.
- Connexion (mode web partagé).
- Assistant de premier lancement.

Toute action destructive demande une confirmation. Les erreurs libvirt sont
affichées en clair, avec le message brut dépliable.

## Raccourcis

Les raccourcis suivent les conventions habituelles des logiciels de
virtualisation de bureau et sont remappables. En mode web, le navigateur
intercepte Ctrl+W, Ctrl+N et Ctrl+T : il faut alors leur attribuer d'autres
combinaisons. Le mode logiciel n'a pas cette limite.

## Langues

Français et anglais (i18next).
