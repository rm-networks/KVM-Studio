# Réseaux virtuels

L'éditeur de réseaux virtuels (Édition > Éditeur de réseaux virtuels) affiche
tous les réseaux libvirt de la machine, y compris ceux créés avec virt-manager.

## Types

| Type | Ce que fait libvirt | Accès |
| --- | --- | --- |
| Host-only | réseau sans `<forward>` | entre VMs, et avec l'hôte si la carte de l'hôte est connectée |
| Host-only sans carte hôte | aucune adresse sur le pont | segment de lab isolé (LAN-1, DMZ...) |
| NAT | `<forward mode='nat'/>` | sortie vers l'extérieur par l'adresse de l'hôte |
| Bridged | prévu en V2 | |

Le service DHCP de libvirt a besoin d'une adresse sur le pont : cocher DHCP
implique la carte virtuelle de l'hôte. Un réseau NAT a toujours cette adresse.

Les réseaux d'un autre type (bridge, route, open...) s'affichent, se démarrent,
s'arrêtent, se renomment et se suppriment ici, mais leurs réglages se modifient
dans virt-manager.

## Noms

KVM Studio nomme ses ponts `kvmnetN` (1 à 99). `kvmnet0` est réservé au mode
Bridged. Le nom du réseau libvirt peut différer du pont (par exemple `LAN-1`
sur le pont `kvmnet4`). Renommer un réseau met à jour les VMs qui l'utilisent ;
c'est refusé tant qu'une VM allumée y est connectée.

Réseaux par défaut, créés au premier lancement ou par « Restaurer les valeurs
par défaut » :

- `kvmnet1` : Host-only avec DHCP ;
- `kvmnet8` : NAT avec DHCP.

Leurs sous-réseaux sont choisis pour ne chevaucher ni le réseau local ni les
autres réseaux libvirt (192.168.101.0/24 et 192.168.108.0/24 quand c'est libre).

## Modifications

Changer la plage DHCP s'applique à chaud. Changer le type ou le sous-réseau
redémarre le réseau : c'est refusé tant qu'une VM allumée l'utilise.

## Masquage dans l'applet réseau

Le paquet installe `/etc/NetworkManager/conf.d/90-kvm-studio.conf`, qui rend
les ponts `kvmnet*` et les cartes des VMs `ks-*` invisibles dans l'applet réseau
du bureau. Depuis les sources, on peut l'installer à la main :

```bash
sudo cp packaging/networkmanager/90-kvm-studio.conf /etc/NetworkManager/conf.d/
```

```bash
sudo systemctl reload NetworkManager
```

Vérification : les interfaces `kvmnet*` doivent apparaître « unmanaged ».

```bash
nmcli device status
```
