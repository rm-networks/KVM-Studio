# Virtual networks

The virtual network editor (Edit > Virtual Network Editor) shows every libvirt
network of the machine, including those created with virt-manager.

## Types

| Type | What libvirt does | Access |
| --- | --- | --- |
| Host-only | network without `<forward>` | between VMs, and with the host when the host card is connected |
| Host-only without host card | no address on the bridge | isolated lab segment (LAN-1, DMZ...) |
| NAT | `<forward mode='nat'/>` | outside access through the host address |
| Bridged | planned for V2 | |

The libvirt DHCP service needs an address on the bridge: ticking DHCP implies
the host virtual card. A NAT network always has this address.

Networks of another type (bridge, route, open...) are shown, started, stopped,
renamed and deleted here, but their settings are changed in virt-manager.

## Names

KVM Studio names its bridges `kvmnetN` (1 to 99). `kvmnet0` is reserved for
Bridged mode. The libvirt network name can differ from the bridge (for example
`LAN-1` on bridge `kvmnet4`). Renaming a network updates the VMs using it; it is
refused while a running VM is connected to it.

Default networks, created at first run or by "Restore Defaults":

- `kvmnet1`: Host-only with DHCP;
- `kvmnet8`: NAT with DHCP.

Their subnets are chosen so as not to overlap the local network or the other
libvirt networks (192.168.101.0/24 and 192.168.108.0/24 when free).

## Changes

Changing the DHCP range applies live. Changing the type or the subnet restarts
the network: it is refused while a running VM uses it.

## Hidden from the network applet

The package installs `/etc/NetworkManager/conf.d/90-kvm-studio.conf`, which
keeps the `kvmnet*` bridges, the `ks-*` VM cards and the `vnet*` cards libvirt
names itself (VMs created elsewhere) out of the desktop network applet.
`virbr*` and every other interface are left alone. It declares a `[device-kvm-studio]` section (`managed=0`) rather than
the `[keyfile] unmanaged-devices` key: another `conf.d` file setting that key
(for `virbr*`, for instance) would replace it, while `[device-*]` sections add
up. At installation, the package also releases the bridges and cards
NetworkManager had already taken ("connected (externally)") and deletes the
profiles left on these interfaces.

From the sources, it can be installed by hand:

```bash
sudo cp packaging/networkmanager/90-kvm-studio.conf /etc/NetworkManager/conf.d/
```

```bash
sudo systemctl reload NetworkManager
```

Check: the `kvmnet*`, `ks-*` and `vnet*` interfaces must show as "unmanaged".

```bash
nmcli device status
```

## Implementation and schedule

| Type | Implementation | Phase |
| --- | --- | --- |
| Host-only | network without `<forward>`; `<ip>` when the host card is connected; optional `<dhcp>` | MVP |
| NAT | `<forward mode='nat'/>` with DHCP | MVP |
| NAT port forwarding | nftables table `inet kvmstudio` managed by the helper; other tables are never changed | V1 |
| Transparent Bridged (proxy ARP and DHCP relay) | to prototype | V2 |
| L2 Bridged (NetworkManager bridge, Ethernet) | option | V2 |

VM cards are named `ks-<id>-<n>` (15 characters at most). The prefixes reserved
by libvirt (`vnet`, `macvtap`, `macvlan`) are never used.

With `qemu:///session`, the `kvmnet` networks are not available.

Docker sets the FORWARD chain to DROP, which cuts the outside access of NAT
networks. KVM Studio detects and reports it without changing the host
configuration.

Useful checks:

```bash
virsh -c qemu:///system net-list --all
```

```bash
ip -br link | grep -E 'kvmnet|ks-|vnet'
```

```bash
sudo nft list table inet kvmstudio
```
