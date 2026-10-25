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

## Addresses and DHCP

- **Host address.** The host's own address can be anywhere in the subnet (for
  instance `.254` instead of `.1`), neither the network nor the broadcast
  address. When it falls inside the DHCP range, the range is moved off it. With
  libvirt, this address is also the gateway and the DNS server of the VMs on a
  NAT network.
- **Gateway announced by DHCP** (DHCP Settings, host-only networks). libvirt
  announces none on a host-only network; the editor can announce the host
  address or another one, for instance a firewall VM that routes the segment.
  It is written as a libvirt dnsmasq option
  (`<dnsmasq:option value='dhcp-option=option:router,X'/>`), which virt-manager
  and virsh keep. A NAT network always announces the host address.
- KVM Studio reserves no DHCP address. Static hosts an administrator sets with
  `virsh net-update` (`<host mac=... ip=.../>`) are kept as they are.

## Changes

What libvirt 12 changes on a running network (`net-update`): the DHCP range. The type, the subnet, the host address and the announced
gateway need the network to restart, and libvirt does not plug the cards of
running VMs back into the bridge afterwards. When running VMs use the network,
the editor lists them and asks first: they are shut down (powered off after
60 s if confirmed again), the network restarts, then they start again.

## NAT port forwarding

NAT Settings > Port Forwarding, as in Workstation: Host port, Type (TCP or
UDP), VM IP address, VM port and Description, with Add, Remove and Properties.
The administrator writes every field; KVM Studio neither looks the VM address
up nor fixes it. The host address is 127.0.0.1 by default and can be any
address, 0.0.0.0 included. A host port something already listens on is only
mentioned.

The rules are a root operation of the helper (`set_port_forwards`,
administrator password every time). It checks the protocol (tcp or udp), the
ports (1 to 65535), the host address, and that the VM address lies in the
subnet of the libvirt network, which it reads from libvirt itself. It keeps the
rules in `/var/lib/kvm-studio/port-forwards.json` and writes the whole nftables
table `inet kvmstudio` again at each change; no other table, firewalld
included, is touched. A libvirt network hook
(`/etc/libvirt/hooks/network.d/50-kvm-studio`) writes it again when a network
starts, so the rules survive a restart (libvirt reads its hooks when its
network daemon starts), and `kvmstudio-forwards.service` writes it again after
nftables, firewalld or libvirt restart or reload (`systemctl restart nftables`
flushes every table). Deleting a network deletes its rules, and removing the
package deletes the table.

- From the host itself (127.0.0.1 or another of its addresses), connections go
  through the `output` chain. For 127.0.0.1, the network bridge gets
  `route_localnet`, and a rule drops anything a VM sends to 127.0.0.0/8 through
  it.
- From other machines (a host address other than 127.0.0.1, or 0.0.0.0), the
  `prerouting` chain forwards the connection, but libvirt 12's own rules
  (`ip libvirt_network`, chain `guest_input`) refuse new connections to a NAT
  network. KVM Studio does not change that table: opening a forwarded port to
  the LAN needs a rule of the administrator's.

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
